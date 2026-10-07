"""Run live fulfillment for a configured product or a customer product query.

Place in the ERP_BAR root. Examples:
    uv run python test_real_odoo_graph.py
    uv run python test_real_odoo_graph.py --quantity 5
    uv run python test_real_odoo_graph.py --product-query "Demo Lemonade" --quantity 5

This creates real Odoo orders and validates receipts/delivery. Each run creates
one new mission. Receipt validation uses the existing V1 supplier simulation.
"""

import argparse
from contextlib import closing
from math import isclose, isfinite
from pathlib import Path
import sys
import traceback

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

import os
from erp_bar.domain.mission import MissionStatus, OrderMission
from erp_bar.domain.policies import DEFAULT_BUSINESS_POLICY
from erp_bar.odoo.client import get_odoo_bridge


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def same_quantity(actual, expected):
    return isclose(float(actual), float(expected), rel_tol=1e-9, abs_tol=1e-9)


def check_progress(mission, product_id, product_query, quantity):
    if not mission.requested_items:
        return
    require(len(mission.requested_items) == 1, "The test expects exactly one requested product.")
    item = mission.requested_items[0]
    require(same_quantity(item.requested_qty, quantity), "An agent changed the requested quantity; stopping the test.")
    require(item.product_query.strip().casefold() == product_query.strip().casefold(),
            "Sales parsed a different product query; stopping before further agent actions.")
    require(product_id is None or item.product_id is None or item.product_id == product_id,
            "Inventory resolved a different product ID; stopping before further agent actions.")


def verify_product_query(bridge, product_id, product_query):
    records = bridge.execute("product.product", "read", [product_id],
                             fields=["name", "default_code", "barcode"])
    require(bool(records), "Resolved product could not be read from Odoo.")
    identities = [records[0].get(field) for field in ("name", "default_code", "barcode")]
    require(any(isinstance(value, str) and value.strip().casefold() == product_query.strip().casefold()
                for value in identities),
            "Resolved product does not exactly match the requested name, SKU or barcode. "
            "Use a unique product name or SKU for this test.")


def run_graph(graph, state, product_id, product_query, quantity, bridge=None):
    # Observe the existing graph; the test does not decide which agent runs next.
    with closing(graph.stream(
        state,
        config={"recursion_limit": DEFAULT_BUSINESS_POLICY.max_graph_steps},
        stream_mode="updates",
    )) as updates:
        for event in updates:
            for node_name, update in event.items():
                if not isinstance(update, dict):
                    continue
                state.update(update)
                mission = state["mission"]
                check_progress(mission, product_id, product_query, quantity)
                if product_id is None and mission.requested_items and mission.requested_items[0].product_id is not None:
                    require(bridge is not None, "Odoo verification is required for a newly resolved product.")
                    product_id = mission.requested_items[0].product_id
                    verify_product_query(bridge, product_id, product_query)
                print(f"[graph] {node_name} completed; mission status: {mission.status.value}")
    return product_id


def verify_odoo_result(bridge, mission, product_id, quantity):
    require(mission.status == MissionStatus.DELIVERED, "Mission did not reach DELIVERED.")
    require(mission.sales_order_id is not None, "No verified sales order ID was recorded.")
    require(mission.delivery_picking_id is not None, "No verified delivery ID was recorded.")

    sales_ids = bridge.execute("sale.order", "search", [
        ["client_order_ref", "=", mission.mission_id], ["state", "!=", "cancel"],
    ])
    require(sales_ids == [mission.sales_order_id], "Expected exactly one active sales order for this mission.")
    order = bridge.get_sales_order(mission.sales_order_id)
    require(order["state"] == "sale", "Odoo has not confirmed the sales order.")
    require(order["mission_id"] == mission.mission_id and order["customer_id"] == mission.customer_id,
            "Sales order mission/customer does not match the test.")
    require(order["product_id"] == product_id and same_quantity(order["quantity"], quantity),
            "Sales order product/quantity does not match the test.")

    delivery = bridge._read_delivery(mission.delivery_picking_id)
    require(delivery is not None and delivery["state"] == "done", "Odoo delivery is not done.")
    require(delivery["sales_order_id"] == mission.sales_order_id and delivery["product_id"] == product_id,
            "Delivery is for a different sales order or product.")
    require(same_quantity(delivery["delivered_qty"], quantity), "Odoo has not delivered the full requested quantity.")

    purchase_ids = bridge.execute("purchase.order", "search", [
        ["origin", "=", mission.mission_id], ["state", "!=", "cancel"],
    ])
    require(set(purchase_ids) == set(mission.purchase_order_ids), "Odoo purchase orders do not match recorded mission IDs.")
    procurement_requests = [
        entry for entry in mission.decision_log
        if entry.get("decision") == "REQUEST_PROCUREMENT"
    ]
    if not procurement_requests:
        require(not purchase_ids, "A purchase order was created without a verified shortage.")
    else:
        require(len(procurement_requests) == 1 and len(purchase_ids) == 1,
                "This test expects one purchase order for one verified shortage.")
        shortage = procurement_requests[0]["facts"]["shortage_qty"]
        po = bridge._read_purchase_order(purchase_ids[0])
        require(po is not None and po["state"] in {"purchase", "done"}, "Purchase order is not confirmed.")
        require(po["mission_id"] == mission.mission_id and po["product_id"] == product_id
                and po["vendor_id"] == mission.supplier_id, "Purchase order does not match this mission.")
        planned = mission.purchase_quantity
        allowance = DEFAULT_BUSINESS_POLICY.purchase_buffer_by_product.get(product_id, 0.0)
        require(planned is not None and isfinite(planned) and shortage <= planned <= shortage + allowance,
                "Chosen purchase quantity must cover the verified shortage within the configured buffer allowance.")
        require(same_quantity(po["quantity"], planned) and same_quantity(po["received_qty"], planned),
                "Purchase order/receipt quantity does not match the chosen quantity for the verified shortage plus buffer.")
        print(f"Purchase allocation: shortage {shortage}, extra stock {planned - shortage}, total {planned}")
        print(f"Verified purchase: {po['name']} (ID {po['purchase_order_id']}), received {po['received_qty']}")

    sales_record = bridge.execute("sale.order", "read", [mission.sales_order_id], fields=["invoice_ids"])
    require(bool(sales_record) and not sales_record[0].get("invoice_ids"), "V1 must stop before invoicing.")
    print(f"Verified sales order: {order['name']} (ID {mission.sales_order_id}), state {order['state']}")
    print(f"Verified delivery: {delivery['name']} (ID {mission.delivery_picking_id}), delivered {delivery['delivered_qty']}")


def print_summary(mission):
    print("\nFINAL MISSION")
    print("Mission ID:", mission.mission_id)
    print("Status:", mission.status.value)
    print("Sales order ID:", mission.sales_order_id)
    print("Purchase order IDs:", mission.purchase_order_ids)
    print("Delivery ID:", mission.delivery_picking_id)
    if mission.customer_message:
        print("Customer response:", mission.customer_message)
    for error in mission.errors:
        print("Mission error:", error)


def report_supplier_contacts(bridge, product_id, product_query):
    """Read-only diagnostic: show actual contacts, not the supplierinfo row."""
    if product_id is None:
        return
    vendors = bridge.get_product_vendors(product_id)
    ids = sorted({vendor["vendor_id"] for vendor in vendors})
    if not ids:
        return
    partners = bridge.execute("res.partner", "read", ids, fields=["name", "email", "ref"])
    profile = DEFAULT_BUSINESS_POLICY.supplier_by_product.get(product_query.strip().casefold())
    for partner in partners:
        print(f"Supplier contact ID {partner['id']}: {partner['name']} | email: {partner.get('email') or '(empty)'}")
        if profile and partner.get("ref") == "ERP_BAR_SUPPLIER:" + profile.supplier_key:
            if str(partner.get("email") or "").strip().lower() != profile.email:
                print("SUPPLIER EMAIL MISMATCH: this contact differs from the configured profile.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quantity", type=float, default=1.0, help="Customer quantity; default 1")
    parser.add_argument("--product-query", help="Requested name or SKU, including a missing product; overrides ODOO_PRODUCT_TEMPLATE_ID")
    args = parser.parse_args(argv)
    if not isfinite(args.quantity) or args.quantity <= 0:
        parser.error("--quantity must be finite and positive")
    if args.product_query is not None and not args.product_query.strip():
        parser.error("--product-query must not be empty")

    state = None
    try:
        bridge = get_odoo_bridge()
        config = bridge.validate_runtime_configuration()
        if args.product_query is not None:
            product_query = args.product_query.strip()
            product = bridge.search_product(product_query)
            product_id = product["product_id"] if product else None
            template_id = product.get("product_template_id") if product else None
            if product_id is not None:
                verify_product_query(bridge, product_id, product_query)
        else:
            template_id = int(os.environ["ODOO_PRODUCT_TEMPLATE_ID"])
            product_id = bridge.get_variant_id(template_id)
            product = bridge._read_product(product_id)
            require(product is not None, "Configured product could not be read.")
            # Prefer an exact SKU. Read the raw name to avoid display-name prefixes.
            raw_product = bridge.execute("product.product", "read", [product_id], fields=["name"])
            require(bool(raw_product), "Configured product name could not be read.")
            product_query = product.get("sku") or raw_product[0]["name"]
            resolved = bridge.search_product(product_query)
            require(resolved is not None and resolved["product_id"] == product_id,
                    "Product query is ambiguous or resolves to a different ID. Give the configured product a unique SKU.")
        available = bridge.get_available_stock(product_id) if product_id is not None else 0.0
        vendors = bridge.get_product_vendors(product_id) if product_id is not None else []

        print("LIVE ERP_BAR FULFILLMENT TEST")
        print("Product query:", product_query, "| template ID:", template_id, "| variant ID:", product_id)
        if product_id is None:
            print("Product not found in preflight. Inventory will resolve it and may create it under the business policy.")
        print("Customer:", config["customer_id"], "| Warehouse:", config["warehouse_id"])
        print("Warehouse available:", available, "| Requested:", args.quantity)
        print("Maximum extra purchase stock:", DEFAULT_BUSINESS_POLICY.purchase_buffer_by_product.get(product_id, 0.0))
        print("Configured suppliers:", [(v["vendor_id"], v["name"]) for v in vendors])
        print("Graph node limit:", DEFAULT_BUSINESS_POLICY.max_graph_steps)
        print("Minimum sales markup:", DEFAULT_BUSINESS_POLICY.minimum_sales_markup * 100, "% on purchase cost")
        profile = DEFAULT_BUSINESS_POLICY.supplier_by_product.get(product_query.strip().casefold())
        print("Matching supplier setup profile:", profile.name if profile else "None")
        print("Creation policy: products =", DEFAULT_BUSINESS_POLICY.auto_create_products,
              "| suppliers =", DEFAULT_BUSINESS_POLICY.auto_create_vendors)
        print("This run writes Odoo orders and validates receipts/delivery. Every run starts a new mission.")

        mission = OrderMission(customer_id=config["customer_id"], customer_request=f"I want {args.quantity:g} units of {product_query}")
        state = {"mission": mission, "supervisor_decision": None, "last_agent_decision": None}
        print("Mission ID:", mission.mission_id)
        from erp_bar.orchestrator.graph import build_graph
        product_id = run_graph(build_graph(), state, product_id, product_query, args.quantity, bridge=bridge)
        mission = state["mission"]
        print_summary(mission)
        report_supplier_contacts(bridge, product_id, product_query)
        if mission.status != MissionStatus.DELIVERED:
            print("FULL FLOW DID NOT COMPLETE. Review the agent's last tool result and reason above.")
            return 1
        require(product_id is not None, "No verified product ID was recorded.")
        verify_odoo_result(bridge, mission, product_id, args.quantity)
        final_available = bridge.get_available_stock(product_id)
        expected_available = available + (mission.purchase_quantity or 0.0) - args.quantity
        print("Warehouse available after delivery:", final_available)
        print("Expected available for this isolated test:", expected_available)
        require(same_quantity(final_available, expected_available),
                "Final stock balance differs from this isolated test's expectation. Check other stock movements or reservations.")
        print("FULL FLOW PASSED: one confirmed sales order, full delivery, no invoice.")
        return 0
    except Exception as exc:
        if state is not None:
            from erp_bar.orchestrator.failure_handling import finalize_failed_mission
            state.update(finalize_failed_mission(state, reason=f"Mission runner stopped: {type(exc).__name__}: {exc}"))
            print_summary(state["mission"])
        traceback.print_exc()
        if state is not None and state["mission"].requested_items:
            try:
                report_supplier_contacts(bridge, state["mission"].requested_items[0].product_id, product_query)
            except Exception as diagnostic_error:
                print("Supplier contact readback unavailable:", diagnostic_error)
        print("FULL FLOW TEST FAILED. The traceback above identifies the failing operation.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
