"""Inventory decisions tested with controlled model replies and Python tools."""

import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from erp_bar.agents import inventory_agent as agent
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.decisions import AgentCapability, DecisionType, SupervisorDecision
from erp_bar.domain.mission import MissionStatus, OrderMission, RequestedItem
from erp_bar.domain.policies import BusinessPolicy
from erp_bar.orchestrator.nodes import inventory_agent_node
from erp_bar.tools.inventory_schemas import (
    CreateProductResult,
    GetAvailableStockResult,
    ProductRecord,
    SearchProductResult,
)


def proposal(action, **arguments):
    return json.dumps({"action": action, "arguments": arguments, "reason": f"Business choice: {action}."})


def context(*, product_id=None, status=MissionStatus.NEW, create=True, steps=10,
            capability=AgentCapability.CHECK_INVENTORY, available=0):
    return AgentContext(
        mission=OrderMission(
            mission_id="MISSION-INVENTORY-TEST",
            customer_request="I want 5 Lemonade",
            requested_items=[RequestedItem(product_query="Lemonade", requested_qty=5, product_id=product_id, available_qty=available)],
            status=status,
        ),
        requested_capability=capability,
        business_policy=BusinessPolicy(auto_create_products=create, max_agent_steps_per_mission=steps),
    )


PRODUCT = ProductRecord(product_id=15, name="Lemonade")
FOUND = SearchProductResult(ok=True, query="Lemonade", product=PRODUCT)
MISSING = SearchProductResult(ok=False, query="Lemonade", error="PRODUCT_NOT_FOUND")


class InventoryLoopTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.llm = self.stack.enter_context(patch.object(agent, "invoke_llm"))
        self.search = self.stack.enter_context(patch.object(agent, "search_product", return_value=FOUND))
        self.create = self.stack.enter_context(patch.object(agent, "create_product", return_value=CreateProductResult(ok=True, product=PRODUCT, created=True)))
        self.stock = self.stack.enter_context(patch.object(agent, "get_available_stock", return_value=GetAvailableStockResult(ok=True, product_id=15, available_qty=5)))

    def test_thinking_wrappers_do_not_block_product_search(self):
        result = self.run_steps(context(),
            '<think>Resolve the product first.</think>' + proposal('SEARCH_PRODUCT') + '<think>Done.</think>',
            proposal('GET_AVAILABLE_STOCK'), proposal('STOCK_READY'))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.search.assert_called_once()
        self.stock.assert_called_once()
        self.assertEqual(self.llm.call_count, 3)

    def test_extra_data_cannot_execute_a_search_until_response_is_revised(self):
        result = self.run_steps(context(),
            proposal('SEARCH_PRODUCT') + '\nAnother JSON object must not run.',
            proposal('SEARCH_PRODUCT'), proposal('GET_AVAILABLE_STOCK'), proposal('STOCK_READY'))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.search.assert_called_once()
        feedback = json.loads(self.llm.call_args_list[1].args[1])['latest_feedback']
        self.assertIn('exactly one JSON object', feedback)

    def run_steps(self, ctx, *steps):
        self.llm.side_effect = steps
        return agent.run_inventory_agent(ctx)

    def test_agent_reads_results_and_selects_stock_ready(self):
        ctx = context()
        result = self.run_steps(ctx, proposal("SEARCH_PRODUCT", query="Lemonade"), proposal("GET_AVAILABLE_STOCK", product_id=15), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.assertEqual(result.facts["shortage_qty"], 0)
        self.assertEqual(self.llm.call_count, 3)
        self.search.assert_called_once()
        self.stock.assert_called_once()
        self.create.assert_not_called()
        second_prompt = json.loads(self.llm.call_args_list[1].args[1])
        self.assertEqual(second_prompt["verified_facts"]["product_id"], 15)
        self.assertIsNone(second_prompt["verified_facts"]["available_qty"])
        self.assertEqual([entry["action"] for entry in second_prompt["allowed_actions"]], ["GET_AVAILABLE_STOCK"])
        self.assertEqual(len(ctx.mission.decision_log), 3)

    def test_shortage_is_calculated_from_the_tool_and_rejects_false_readiness(self):
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=2)
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"), proposal("REQUEST_PROCUREMENT"))
        self.assertEqual(result.decision, DecisionType.REQUEST_PROCUREMENT)
        self.assertEqual(result.facts["shortage_qty"], 3)
        prompt = json.loads(self.llm.call_args_list[-1].args[1])
        self.assertFalse(prompt["recent_action_outcomes"][-1]["approved"])
        self.assertIn("below", prompt["latest_feedback"])

    def test_cannot_claim_stock_before_any_read(self):
        result = self.run_steps(context(product_id=15), proposal("STOCK_READY"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.stock.assert_called_once()
        self.assertFalse(json.loads(self.llm.call_args_list[1].args[1])["recent_action_outcomes"][0]["approved"])

    def test_missing_product_creation_passes_mission_id_and_requires_new_stock_read(self):
        self.search.return_value = MISSING
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=0)
        result = self.run_steps(context(), proposal("SEARCH_PRODUCT"), proposal("CREATE_PRODUCT", name="Lemonade"), proposal("STOCK_READY"), proposal("GET_AVAILABLE_STOCK"), proposal("REQUEST_PROCUREMENT"))
        self.assertEqual(result.decision, DecisionType.REQUEST_PROCUREMENT)
        self.assertEqual(result.facts["shortage_qty"], 5)
        self.create.assert_called_once()
        self.assertEqual(self.create.call_args.args[0].mission_id, "MISSION-INVENTORY-TEST")
        self.assertEqual(self.create.call_args.args[0].name, "Lemonade")

    def test_creation_requires_a_missing_product_result(self):
        result = self.run_steps(context(), proposal("CREATE_PRODUCT"), proposal("SEARCH_PRODUCT"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.create.assert_not_called()

    def test_creation_policy_is_enforced_and_failure_terminates_the_existing_node(self):
        self.search.return_value = MISSING
        ctx = context(create=False)
        self.llm.side_effect = [proposal("SEARCH_PRODUCT"), proposal("CREATE_PRODUCT"), proposal("FAIL")]
        # The normal graph uses DEFAULT_BUSINESS_POLICY to build its context.
        with patch("erp_bar.orchestrator.nodes.AgentContext", return_value=ctx):
            state = inventory_agent_node({"mission": ctx.mission, "supervisor_decision": SupervisorDecision(reason="Check inventory", requested_capability=AgentCapability.CHECK_INVENTORY)})
        self.assertEqual(state["mission"].status, MissionStatus.FAILED)
        self.create.assert_not_called()
        self.stock.assert_not_called()

    def test_agent_can_decline_creation_of_a_missing_product(self):
        self.search.return_value = MISSING
        result = self.run_steps(context(), proposal("SEARCH_PRODUCT"), proposal("FAIL"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.create.assert_not_called()

    def test_invented_product_id_is_rejected_before_tool_execution(self):
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK", product_id=99), proposal("GET_AVAILABLE_STOCK", product_id=15), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.stock.assert_called_once()
        self.assertEqual(self.stock.call_args.args[0].product_id, 15)

    def test_forged_fact_fields_are_rejected(self):
        forged = json.dumps({"action": "STOCK_READY", "arguments": {}, "reason": "Done", "facts": {"available_qty": 100}})
        result = self.run_steps(context(product_id=15), forged, proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.facts["available_qty"], 5)
        self.assertFalse(json.loads(self.llm.call_args_list[1].args[1])["recent_action_outcomes"][0]["approved"])

    def test_context_supports_recovery_from_bad_handoff_arguments_and_duplicate_creation(self):
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=0)
        ctx = context()
        prompts = []
        def respond(system, prompt):
            data = json.loads(prompt)
            prompts.append(data)
            if len(prompts) == 3:
                return proposal("REQUEST_PROCUREMENT", product_id=15, requested_qty=5.0)
            if len(prompts) == 4:
                return proposal("CREATE_PRODUCT", name="Lemonade")
            if len(prompts) == 5:
                return proposal("REQUEST_PROCUREMENT") + "\n{}"
            self.assertEqual(len(data["allowed_actions"]), 1)
            return json.dumps(data["allowed_actions"][0])
        self.llm.side_effect = respond
        result = agent.run_inventory_agent(ctx)
        self.assertEqual(result.decision, DecisionType.REQUEST_PROCUREMENT)
        self.assertEqual(result.facts["shortage_qty"], 5)
        self.assertIn("Allowed arguments for REQUEST_PROCUREMENT: {}", prompts[3]["latest_feedback"])
        self.assertIn("already exists", prompts[4]["latest_feedback"])
        self.assertIn("Invalid proposal", prompts[5]["latest_feedback"])
        for data in prompts[2:]:
            self.assertEqual([entry["action"] for entry in data["allowed_actions"]], ["REQUEST_PROCUREMENT"])
            self.assertEqual(data["allowed_actions"][0]["arguments"], {})
            self.assertIn("product exists", data["product_status"])
            self.assertEqual(data["verified_facts"]["available_qty"], 0)
        self.assertTrue(all(len(data["recent_action_outcomes"]) <= 3 for data in prompts))
        self.assertTrue(all("arguments" not in entry and "reason" not in entry and "tool_result" not in entry
                            for data in prompts for entry in data["recent_action_outcomes"]))
        self.assertEqual(len(ctx.mission.decision_log), 6)
        self.assertEqual(ctx.mission.decision_log[2]["arguments"], {"product_id":15, "requested_qty":5.0})
        self.search.assert_called_once()
        self.stock.assert_called_once()
        self.create.assert_not_called()

    def test_context_offers_creation_only_when_policy_allows_and_never_after_uncertain_write(self):
        for permitted in (True, False):
            with self.subTest(create=permitted):
                self.search.return_value = MISSING
                self.run_steps(context(create=permitted), proposal("SEARCH_PRODUCT"), proposal("FAIL"))
                data = json.loads(self.llm.call_args.args[1])
                allowed = {entry["action"] for entry in data["allowed_actions"]}
                self.assertEqual("CREATE_PRODUCT" in allowed, permitted)
                self.assertIn("FAIL", allowed)
                self.assertNotIn("GET_AVAILABLE_STOCK", allowed)
        self.search.side_effect = [MISSING, FOUND]
        self.create.return_value = CreateProductResult(ok=False, error="Response lost")
        self.run_steps(context(), proposal("SEARCH_PRODUCT"), proposal("CREATE_PRODUCT"), proposal("SEARCH_PRODUCT"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        data = json.loads(self.llm.call_args_list[-3].args[1])
        allowed = {entry["action"] for entry in data["allowed_actions"]}
        self.assertIn("SEARCH_PRODUCT", allowed)
        self.assertNotIn("CREATE_PRODUCT", allowed)
        self.create.assert_called_once()

    def test_context_distinguishes_failed_stock_read_from_verified_zero(self):
        self.stock.return_value = GetAvailableStockResult(ok=False, product_id=15, error="RPC unavailable")
        self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("FAIL"))
        data = json.loads(self.llm.call_args.args[1])
        allowed = {entry["action"] for entry in data["allowed_actions"]}
        self.assertIsNone(data["verified_facts"]["available_qty"])
        self.assertIn("GET_AVAILABLE_STOCK", allowed)
        self.assertIn("FAIL", allowed)
        self.assertNotIn("REQUEST_PROCUREMENT", allowed)
        self.assertNotIn("STOCK_READY", allowed)

    def test_malformed_proposal_feedback_allows_replanning(self):
        result = self.run_steps(context(product_id=15), "not JSON", "```json\n" + proposal("GET_AVAILABLE_STOCK") + "\n```", proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.stock.assert_called_once()

    def test_read_failure_can_be_retried_by_the_agent(self):
        self.stock.side_effect = [GetAvailableStockResult(ok=False, product_id=15, error="Temporary read failure"), GetAvailableStockResult(ok=True, product_id=15, available_qty=5)]
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.assertEqual(self.stock.call_count, 2)
        prompt = json.loads(self.llm.call_args_list[1].args[1])
        self.assertEqual(prompt["verified_facts"]["last_error"], "Temporary read failure")
        self.assertIsNone(prompt["verified_facts"]["available_qty"])

    def test_read_failure_does_not_authorize_product_creation(self):
        self.search.return_value = SearchProductResult(ok=False, query="Lemonade", error="Odoo unavailable")
        result = self.run_steps(context(), proposal("SEARCH_PRODUCT"), proposal("CREATE_PRODUCT"), proposal("FAIL"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.create.assert_not_called()

    def test_uncertain_create_is_verified_by_search_instead_of_repeated_write(self):
        self.search.side_effect = [MISSING, FOUND]
        self.create.return_value = CreateProductResult(ok=False, error="Connection lost after create")
        result = self.run_steps(context(), proposal("SEARCH_PRODUCT"), proposal("CREATE_PRODUCT"), proposal("CREATE_PRODUCT"), proposal("SEARCH_PRODUCT"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.create.assert_called_once()
        self.assertEqual(self.search.call_count, 2)

    def test_tool_exception_is_returned_to_the_agent(self):
        self.stock.side_effect = RuntimeError("RPC unavailable")
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("FAIL"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.assertEqual(result.facts["last_error"], "RPC unavailable")

    def test_stock_verification_after_receipt_does_not_reuse_old_quantities(self):
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=2)
        ctx = context(product_id=15, status=MissionStatus.GOODS_RECEIVED, capability=AgentCapability.VERIFY_STOCK, available=100)
        result = self.run_steps(ctx, proposal("STOCK_READY"), proposal("GET_AVAILABLE_STOCK"), proposal("REQUEST_PROCUREMENT"))
        self.assertEqual(result.decision, DecisionType.REQUEST_PROCUREMENT)
        self.assertEqual(result.facts["available_qty"], 2)
        self.assertIsNone(json.loads(self.llm.call_args_list[0].args[1])["verified_facts"]["available_qty"])
        self.search.assert_not_called()

    def test_reading_stock_for_the_wrong_product_cannot_prove_readiness(self):
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=99, available_qty=100)
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("FAIL"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.assertIsNone(result.facts["available_qty"])

    def test_nonfinite_stock_is_not_accepted_as_available(self):
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=float("inf"))
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("FAIL"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.assertIsNone(result.facts["available_qty"])

    def test_successful_reads_are_not_repeated_without_a_state_change(self):
        result = self.run_steps(context(product_id=15), proposal("GET_AVAILABLE_STOCK"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY"))
        self.assertEqual(result.decision, DecisionType.STOCK_READY)
        self.stock.assert_called_once()

    def test_action_limit_includes_rejected_proposals(self):
        result = self.run_steps(context(steps=2), proposal("DELETE_PRODUCT"), proposal("DELETE_PRODUCT"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.assertIn("limit reached (2)", result.reason)
        self.assertEqual(self.llm.call_count, 2)
        self.search.assert_not_called()
        self.create.assert_not_called()
        self.stock.assert_not_called()

    def test_model_failure_is_a_structured_failure(self):
        result = self.run_steps(context(), ConnectionError("Ollama unavailable"))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.assertIn("Ollama unavailable", result.reason)
        self.search.assert_not_called()

    def test_terminal_mission_does_not_invoke_model_or_tools(self):
        result = agent.run_inventory_agent(context(status=MissionStatus.DELIVERED))
        self.assertEqual(result.decision, DecisionType.MISSION_FAILED)
        self.llm.assert_not_called()
        self.search.assert_not_called()

    def test_existing_node_applies_stock_ready_result(self):
        ctx = context()
        self.llm.side_effect = [proposal("SEARCH_PRODUCT"), proposal("GET_AVAILABLE_STOCK"), proposal("STOCK_READY")]
        result = inventory_agent_node({"mission": ctx.mission, "supervisor_decision": SupervisorDecision(reason="Check stock", requested_capability=AgentCapability.CHECK_INVENTORY)})
        self.assertEqual(result["mission"].status, MissionStatus.STOCK_READY)
        self.assertEqual(result["mission"].requested_items[0].product_id, 15)
        self.assertEqual(result["mission"].requested_items[0].available_qty, 5)

    def test_existing_node_hands_off_a_verified_shortage(self):
        ctx = context()
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=2)
        self.llm.side_effect = [proposal("SEARCH_PRODUCT"), proposal("GET_AVAILABLE_STOCK"), proposal("REQUEST_PROCUREMENT")]
        result = inventory_agent_node({"mission": ctx.mission, "supervisor_decision": SupervisorDecision(reason="Check stock", requested_capability=AgentCapability.CHECK_INVENTORY)})
        self.assertEqual(result["mission"].status, MissionStatus.PROCUREMENT_REQUIRED)
        self.assertEqual(result["mission"].requested_items[0].shortage_qty, 3)

    def test_existing_delivery_entry_point_still_uses_delivery_skill(self):
        ctx = context(capability=AgentCapability.FULFILL_DELIVERY)
        ctx.mission.sales_order_id = 201
        with patch.object(agent, "fulfill_delivery", return_value={"ok": True, "picking_id": 101, "delivered_qty": 5}) as tool:
            result = agent.run_inventory_agent(ctx)
        self.assertEqual(result.decision, DecisionType.DELIVERY_COMPLETED)
        tool.assert_called_once_with(sales_order_id=201)
        self.llm.assert_not_called()

    def test_repeated_shortage_result_preserves_status_without_self_transition(self):
        ctx = context(product_id=15, status=MissionStatus.PROCUREMENT_REQUIRED)
        ctx.mission.requested_items[0].shortage_qty = 5
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=0)
        self.llm.side_effect = [proposal("GET_AVAILABLE_STOCK"), proposal("REQUEST_PROCUREMENT")]
        result = inventory_agent_node({
            "mission": ctx.mission,
            "supervisor_decision": SupervisorDecision(reason="Recheck stock", requested_capability=AgentCapability.VERIFY_STOCK),
        })
        self.assertEqual(result["mission"].status, MissionStatus.PROCUREMENT_REQUIRED)
        self.assertEqual(result["mission"].requested_items[0].shortage_qty, 5)
        self.assertEqual(result["last_agent_decision"].decision, DecisionType.REQUEST_PROCUREMENT)

    def test_shortage_after_receipt_still_transitions_to_procurement_required(self):
        ctx = context(product_id=15, status=MissionStatus.GOODS_RECEIVED)
        self.stock.return_value = GetAvailableStockResult(ok=True, product_id=15, available_qty=2)
        self.llm.side_effect = [proposal("GET_AVAILABLE_STOCK"), proposal("REQUEST_PROCUREMENT")]
        result = inventory_agent_node({
            "mission": ctx.mission,
            "supervisor_decision": SupervisorDecision(reason="Verify receipt", requested_capability=AgentCapability.VERIFY_STOCK),
        })
        self.assertEqual(result["mission"].status, MissionStatus.PROCUREMENT_REQUIRED)
        self.assertEqual(result["mission"].requested_items[0].shortage_qty, 3)


if __name__ == "__main__":
    unittest.main()
