"""Offline regression test for final Sales responses. No Odoo or Ollama access.

Run from the project root: uv run python test_order_failure.py
"""
import io
import importlib.util
import json
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
if __name__ == "__main__":
    stub = types.ModuleType("erp_bar.llm")
    def unavailable(*args, **kwargs):
        raise AssertionError("Live model calls are blocked in this test.")
    stub.invoke_llm = unavailable
    sys.modules["erp_bar.llm"] = stub

from erp_bar.agents import inventory_agent, sales_agent
from erp_bar.domain.decisions import AgentCapability, AgentDecision, AgentName, DecisionType, SupervisorDecision
from erp_bar.domain.mission import MissionStatus, OrderMission, RequestedItem
from erp_bar.domain.policies import DEFAULT_BUSINESS_POLICY
from erp_bar.odoo.bridge import OdooBridge
from erp_bar.orchestrator import nodes
from erp_bar.orchestrator.failure_handling import finalize_failed_mission
from erp_bar.orchestrator.graph import build_graph
from erp_bar.tools.inventory_schemas import SearchProductResult
from erp_bar.tools.sales_schemas import PrepareFailureResponseResult


class OrderFailureTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.odoo_init = self.stack.enter_context(patch.object(OdooBridge, "__init__", side_effect=AssertionError("Odoo blocked")))
        self.rpc = self.stack.enter_context(patch.object(OdooBridge, "execute", side_effect=AssertionError("Odoo blocked")))
        self.sales_model = self.stack.enter_context(patch.object(sales_agent, "invoke_llm", side_effect=AssertionError("Model blocked")))

    def tearDown(self):
        self.odoo_init.assert_not_called()
        self.rpc.assert_not_called()
        self.sales_model.assert_not_called()

    def mission(self, status=MissionStatus.NEW):
        return OrderMission(customer_id=10, customer_request="I want 1 Lemonade", status=status,
                            requested_items=[RequestedItem(product_query="Lemonade", requested_qty=1)])

    def run_graph(self, mission, capability, agent, *, decision=None, error=None):
        supervisor = SupervisorDecision(reason="Use the verified mission state.", requested_capability=capability)
        state = {"mission": mission, "last_agent_decision": None, "supervisor_decision": None}
        with patch.object(nodes, "decide_next_agent", return_value=supervisor), patch.object(
            nodes, agent, **({"side_effect": error} if error else {"return_value": decision})
        ):
            visited = []
            for event in build_graph().stream(state, stream_mode="updates", config={"recursion_limit": 10}):
                for name, update in event.items():
                    visited.append(name)
                    state.update(update)
        self.assertEqual(mission.status, MissionStatus.FAILED)
        self.assertTrue(mission.customer_response_prepared)
        self.assertTrue(mission.customer_message)
        self.assertEqual(visited[-1], "sales_failure_response")
        self.assertEqual(state["last_agent_decision"].agent, AgentName.SALES)
        return state

    def test_sales_failure_gets_final_response_without_exposing_internal_error(self):
        mission = self.mission(MissionStatus.STOCK_READY)
        failure = AgentDecision(agent=AgentName.SALES, decision=DecisionType.MISSION_FAILED,
                                reason="RPC secret endpoint detail", customer_message="Unverified model text")
        self.run_graph(mission, AgentCapability.CREATE_SALES_ORDER, "run_sales_agent", decision=failure)
        self.assertIn("1 unit of Lemonade", mission.customer_message)
        self.assertIn(mission.mission_id, mission.customer_message)
        self.assertNotIn("secret", mission.customer_message)
        self.assertNotIn("Unverified", mission.customer_message)

    def test_inventory_exception_gets_sales_response(self):
        self.run_graph(self.mission(), AgentCapability.CHECK_INVENTORY, "run_inventory_agent", error=RuntimeError("connection failed"))

    def test_delivery_failure_preserves_confirmed_order_and_purchase(self):
        mission = self.mission(MissionStatus.SALES_ORDER_CONFIRMED)
        mission.sales_order_id, mission.purchase_order_ids = 77, [27]
        self.run_graph(mission, AgentCapability.FULFILL_DELIVERY, "run_inventory_agent", error=RuntimeError("receipt state uncertain"))
        self.assertIn("was confirmed, but we could not verify delivery", mission.customer_message)
        self.assertEqual(mission.sales_order_id, 77)
        self.assertEqual(mission.purchase_order_ids, [27])
        self.assertNotIn("cancel", mission.customer_message)

    def test_ambiguous_request_does_not_invent_product_or_quantity(self):
        mission = OrderMission(customer_request="I want that")
        failure = AgentDecision(agent=AgentName.SALES, decision=DecisionType.MISSION_FAILED,
                                reason="Ambiguous request", facts={"is_ambiguous": True})
        self.run_graph(mission, AgentCapability.INTERPRET_DEMAND, "run_sales_agent", decision=failure)
        self.assertIn("which product", mission.customer_message)
        self.assertNotIn("Lemonade", mission.customer_message)

    def test_supervisor_failure_still_gets_sales_response(self):
        mission = self.mission()
        with patch.object(nodes, "decide_next_agent", side_effect=RuntimeError("Ollama offline")):
            result = build_graph().invoke({"mission": mission})
        self.assertTrue(mission.customer_response_prepared)
        self.assertEqual(result["last_agent_decision"].agent, AgentName.SALES)

    def test_creation_is_disabled_even_when_inventory_proposes_it(self):
        self.assertFalse(DEFAULT_BUSINESS_POLICY.auto_create_products)
        self.assertFalse(DEFAULT_BUSINESS_POLICY.auto_create_vendors)
        mission = self.mission()
        supervisor = SupervisorDecision(reason="Resolve product", requested_capability=AgentCapability.CHECK_INVENTORY)
        responses = [json.dumps(dict(action=action, arguments=arguments, reason="Use the product lookup result."))
                     for action, arguments in [("SEARCH_PRODUCT", {"query":"Lemonade"}),
                                               ("CREATE_PRODUCT", {"name":"Lemonade"}), ("FAIL", {})]]
        with patch.object(nodes, "decide_next_agent", return_value=supervisor), patch.object(
            inventory_agent, "invoke_llm", side_effect=responses
        ), patch.object(inventory_agent, "search_product", return_value=SearchProductResult(
            ok=False, query="Lemonade", error="PRODUCT_NOT_FOUND"
        )), patch.object(inventory_agent, "create_product") as create:
            build_graph().invoke({"mission": mission})
        create.assert_not_called()
        self.assertTrue(mission.customer_response_prepared)
        self.assertIn("not available in our product catalog", mission.customer_message)

    def test_wrong_response_or_tool_failure_uses_safe_fallback(self):
        for outcome in [RuntimeError("internal token"), PrepareFailureResponseResult(ok=True, mission_id="WRONG", customer_message="Wrong customer's order")]:
            with self.subTest(outcome=type(outcome).__name__):
                mission = self.mission()
                kwargs = {"side_effect":outcome} if isinstance(outcome, Exception) else {"return_value":outcome}
                with patch.object(sales_agent, "prepare_failure_response", **kwargs):
                    finalize_failed_mission({"mission":mission}, "Execution interrupted")
                self.assertTrue(mission.customer_response_prepared)
                self.assertIn("could not verify completion", mission.customer_message)
                self.assertNotIn("Wrong customer", mission.customer_message)
                self.assertNotIn("token", mission.customer_message)

    def test_final_response_is_idempotent_after_serialization(self):
        mission = self.mission()
        finalize_failed_mission({"mission":mission}, "Execution interrupted")
        restored = OrderMission.model_validate_json(mission.model_dump_json())
        previous_count = len(restored.decision_log)
        with patch.object(sales_agent, "prepare_failure_response") as tool:
            finalize_failed_mission({"mission":restored})
        tool.assert_not_called()
        self.assertEqual(len(restored.decision_log), previous_count)
        self.assertEqual(restored.customer_message, mission.customer_message)

    def test_delivered_mission_is_never_relabelled_as_failed(self):
        mission = self.mission(MissionStatus.DELIVERED)
        with patch.object(nodes, "decide_next_agent") as supervisor:
            build_graph().invoke({"mission":mission})
            finalize_failed_mission({"mission":mission}, "Post-run diagnostic failed")
        supervisor.assert_not_called()
        self.assertEqual(mission.status, MissionStatus.DELIVERED)
        self.assertIsNone(mission.customer_message)

    def test_live_runner_recursion_error_still_prepares_final_response(self):
        from langgraph.errors import GraphRecursionError
        spec = importlib.util.spec_from_file_location("order_failure_live_runner", Path(__file__).with_name("test_real_odoo_graph.py"))
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        bridge = Mock()
        bridge.validate_runtime_configuration.return_value = {"customer_id":10,"warehouse_id":1}
        bridge.search_product.return_value = {"product_id":15,"product_template_id":15}
        bridge.execute.return_value = [{"name":"Lemonade"}]
        bridge.get_available_stock.return_value = 1
        bridge.get_product_vendors.return_value = []
        observed = []
        def interrupted(graph, state, *args, **kwargs):
            observed.append(state["mission"])
            raise GraphRecursionError("Graph node limit reached")
        from contextlib import redirect_stderr
        with patch.object(runner, "get_odoo_bridge", return_value=bridge), patch.object(
            runner, "run_graph", side_effect=interrupted
        ), redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(["--product-query","Lemonade","--quantity","1"]), 1)
        self.assertTrue(observed[0].customer_response_prepared)
        self.assertEqual(observed[0].status, MissionStatus.FAILED)


if __name__ == "__main__":
    print("FINAL SALES RESPONSE TEST — simulated failures; Odoo and Ollama are blocked.")
    unittest.main(verbosity=2)
