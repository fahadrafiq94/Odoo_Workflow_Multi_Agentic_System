"""Exercise Purchase -> Supervisor -> Sales when no supplier is found.

Default: use configured Ollama with a simulated supplier lookup, no Odoo access.
--mock-model: also use controlled model replies, for an offline wiring check.
Place this file in the ERP_BAR root.
"""
import argparse
from contextlib import ExitStack, closing
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
    if args.mock_model:
        # Keep the offline runner independent of Ollama configuration/transport.
        stub = types.ModuleType("erp_bar.llm")
        def unexpected_model_call(*_args, **_kwargs):
            raise AssertionError("Unexpected model call in the offline test.")
        stub.invoke_llm = unexpected_model_call
        sys.modules.setdefault("erp_bar.llm", stub)

    from erp_bar.agents import purchase_agent, supervisor_agent
    from erp_bar.domain.mission import MissionStatus, OrderMission, RequestedItem
    from erp_bar.domain.policies import DEFAULT_BUSINESS_POLICY
    from erp_bar.odoo.bridge import OdooBridge
    from erp_bar.orchestrator.graph import build_graph
    from erp_bar.tools.purchase_schemas import GetProductVendorsResult

    # IDs are test data; no real product, supplier or customer is accessed.
    mission = OrderMission(
        customer_id=10, customer_request="I want 5 units of Demo Lemonade",
        status=MissionStatus.PROCUREMENT_REQUIRED,
        requested_items=[RequestedItem(product_query="Demo Lemonade", product_id=15,
                                       requested_qty=5, available_qty=0, shortage_qty=5)],
    )
    state = {"mission": mission, "supervisor_decision": None, "last_agent_decision": None}
    visited = []
    statuses = []
    print("PROCUREMENT FAILURE HANDOFF TEST")
    print("Model:", "controlled replies" if args.mock_model else "configured Ollama")
    print("Supplier lookup is simulated. Odoo access is blocked. No message is sent externally.")

    def delegate(owner, capability):
        return json.dumps(dict(next_agent=owner, capability=capability,
                               objective="Handle the verified procurement outcome.",
                               reason="Use the current mission evidence."))

    with ExitStack() as stack:
        # This test deliberately has no approved supplier-setup profile.
        stack.enter_context(patch.dict(DEFAULT_BUSINESS_POLICY.supplier_by_product, {}, clear=True))
        blocked_init = stack.enter_context(patch.object(OdooBridge, "__init__", side_effect=AssertionError("Odoo access is blocked in this test.")))
        blocked_rpc = stack.enter_context(patch.object(OdooBridge, "execute", side_effect=AssertionError("Odoo access is blocked in this test.")))
        lookup = stack.enter_context(patch.object(purchase_agent, "get_product_vendors", return_value=GetProductVendorsResult(
            ok=False, product_id=15, required_qty=5, vendors=[], error="NO_VENDOR_FOUND")))
        if args.mock_model:
            stack.enter_context(patch.object(supervisor_agent, "invoke_llm", side_effect=[
                delegate("purchase_agent", "PROCURE_SHORTAGE"),
                delegate("sales_agent", "REPORT_PROCUREMENT_FAILURE"),
            ]))
            stack.enter_context(patch.object(purchase_agent, "invoke_llm", side_effect=[
                json.dumps(dict(action=action, arguments={}, reason="Use verified supplier evidence."))
                for action in ("GET_PRODUCT_VENDORS", "PROCUREMENT_FAILED")
            ]))
        with closing(build_graph().stream(state, config={"recursion_limit": 12}, stream_mode="updates")) as updates:
            for event in updates:
                for node, update in event.items():
                    state.update(update)
                    visited.append(node)
                    statuses.append(state["mission"].status)
                    print(f"[graph] {node}: {state['mission'].status.value}")
        result = state["mission"]
        expected = "We could not complete your order for 5 units of Demo Lemonade. No configured supplier was found for this product."
        checks = [
            (visited == ["supervisor", "purchase_agent", "supervisor", "sales_agent"], "Incorrect agent handoff."),
            (MissionStatus.PROCUREMENT_FAILED in statuses, "Missing intermediate procurement-failure state."),
            (result.status == MissionStatus.FAILED, "Mission must end FAILED."),
            (result.customer_message == expected, "Missing or incorrect customer response."),
            (not result.purchase_order_ids and result.sales_order_id is None and result.delivery_picking_id is None, "Unexpected ERP records."),
            (result.procurement_failure_code == "NO_VENDOR_FOUND" and bool(result.procurement_failure_reason), "Failure evidence was not preserved."),
        ]
        for ok, error in checks:
            if not ok:
                raise AssertionError(error)
        lookup.assert_called_once()
        blocked_init.assert_not_called()
        blocked_rpc.assert_not_called()
    print("Customer response:", result.customer_message)
    print("FAILURE HANDOFF PASSED: customer response prepared, mission FAILED, no Odoo operations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
