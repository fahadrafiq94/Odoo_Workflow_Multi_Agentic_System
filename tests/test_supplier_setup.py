"""Test Purchase supplier setup with simulated ERP tools and configured Ollama.

No Odoo access. --mock-model also replaces Ollama with controlled replies.
For real Odoo verification use test_real_odoo_graph.py with a configured profile.
"""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock-model", action="store_true")
    args = parser.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if args.mock_model:
        stub = types.ModuleType("erp_bar.llm")
        def unexpected(*_args, **_kwargs):
            raise AssertionError("Unexpected model call")
        stub.invoke_llm = unexpected
        sys.modules.setdefault("erp_bar.llm", stub)

    from erp_bar.agents import purchase_agent as agent
    from erp_bar.domain.agent_context import AgentContext
    from erp_bar.domain.decisions import AgentCapability, DecisionType
    from erp_bar.domain.mission import OrderMission, RequestedItem, MissionStatus
    from erp_bar.domain.policies import BusinessPolicy
    from erp_bar.odoo.bridge import OdooBridge
    from erp_bar.tools.purchase_schemas import (
        GetProductVendorsResult, VendorRecord, SetupProductVendorResult,
        PurchaseOrderRecord, CreatePurchaseOrderResult, ConfirmPurchaseOrderResult, ReceivePurchaseResult,
    )
    profile = dict(supplier_key="demo_supplier", name="Demo Supplier", email="supplier@example.com", unit_price=2.5)
    mission = OrderMission(customer_request="5 Demo Lemonade", status=MissionStatus.PROCUREMENT_REQUIRED,
        requested_items=[RequestedItem(product_query="Demo Lemonade", product_id=15, requested_qty=5, shortage_qty=5)])
    context = AgentContext(mission=mission, requested_capability=AgentCapability.PROCURE_SHORTAGE,
        business_policy=BusinessPolicy(supplier_by_product={"Demo Lemonade": profile},
                                       auto_create_vendors=True, purchase_buffer_by_product={}))
    linked = False
    current_order = None

    def lookup(data):
        if data.product_id != 15 or data.required_qty != 5:
            raise AssertionError("Supplier lookup changed the verified request")
        return GetProductVendorsResult(ok=linked, product_id=15, required_qty=5,
            vendors=[VendorRecord(vendor_id=101, name="Demo Supplier")] if linked else [],
            error=None if linked else "NO_VENDOR_FOUND")

    def setup(data):
        nonlocal linked
        if data.mission_id != mission.mission_id or data.product_id != 15 or data.profile.model_dump() != profile:
            raise AssertionError("Supplier setup changed the configured profile or mission")
        linked = True
        return SetupProductVendorResult(ok=True, mission_id=mission.mission_id, product_id=15,
            vendor_id=101, supplierinfo_id=201, supplier_key="demo_supplier", vendor_created=True, link_created=True)

    def create(data):
        nonlocal current_order
        if not linked or data.vendor_id != 101 or data.quantity != 5 or data.product_id != 15:
            raise AssertionError("PO does not match verified supplier and shortage")
        current_order = PurchaseOrderRecord(purchase_order_id=22, name="P00022", mission_id=data.mission_id,
            vendor_id=data.vendor_id, product_id=data.product_id, quantity=data.quantity, state="draft", received_qty=0)
        return CreatePurchaseOrderResult(ok=True, purchase_order=current_order, created=True)

    def confirm(data):
        nonlocal current_order
        if current_order is None or data.purchase_order_id != current_order.purchase_order_id:
            raise AssertionError("Wrong PO confirmation")
        current_order = current_order.model_copy(update={"state": "purchase"})
        return ConfirmPurchaseOrderResult(ok=True, purchase_order=current_order)

    def receive(data):
        nonlocal current_order
        if current_order is None or current_order.state != "purchase" or data.purchase_order_id != current_order.purchase_order_id:
            raise AssertionError("Receipt requires the matching confirmed PO")
        current_order = current_order.model_copy(update={"received_qty": current_order.quantity})
        return ReceivePurchaseResult(ok=True, purchase_order=current_order, received_qty=current_order.received_qty)

    print("SUPPLIER SETUP TEST")
    print("Model:", "controlled replies" if args.mock_model else "configured Ollama")
    print("All ERP results are simulated. Odoo access is blocked. No supplier is contacted.")
    with ExitStack() as stack:
        init = stack.enter_context(patch.object(OdooBridge, "__init__", side_effect=AssertionError("Odoo access is blocked")))
        rpc = stack.enter_context(patch.object(OdooBridge, "execute", side_effect=AssertionError("Odoo access is blocked")))
        calls = {}
        for name, function in (("get_product_vendors", lookup), ("setup_product_vendor", setup),
                               ("create_purchase_order", create), ("confirm_purchase_order", confirm), ("receive_purchase", receive)):
            calls[name] = stack.enter_context(patch.object(agent, name, side_effect=function))
        if args.mock_model:
            actions = ["GET_PRODUCT_VENDORS", "SETUP_PRODUCT_VENDOR", "GET_PRODUCT_VENDORS",
                       "CREATE_PURCHASE_ORDER", "CONFIRM_PURCHASE_ORDER", "RECEIVE_PURCHASE", "PROCUREMENT_SUCCEEDED"]
            stack.enter_context(patch.object(agent, "invoke_llm", side_effect=[
                json.dumps(dict(action=action, arguments={"vendor_id":101,"quantity":5} if action=="CREATE_PURCHASE_ORDER" else {},
                                reason="Use verified supplier configuration and tool results.")) for action in actions]))
        decision = agent.run_purchase_agent(context)
        if decision.decision != DecisionType.PROCUREMENT_SUCCEEDED:
            raise AssertionError(f"Purchase did not complete: {decision.reason}")
        if calls["get_product_vendors"].call_count != 2:
            raise AssertionError("Expected lookup before setup and verification afterward")
        for name in ("setup_product_vendor", "create_purchase_order", "confirm_purchase_order", "receive_purchase"):
            calls[name].assert_called_once()
        init.assert_not_called()
        rpc.assert_not_called()
        if mission.purchase_order_ids != [22] or mission.purchase_quantity != 5 or decision.facts["received_qty"] != 5:
            raise AssertionError("Final PO/receipt does not match the request")
    print("SUPPLIER SETUP PASSED: configured setup, verified supplier link, one PO, full receipt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
