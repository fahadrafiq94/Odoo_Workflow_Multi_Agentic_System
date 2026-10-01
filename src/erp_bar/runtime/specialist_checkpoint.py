from typing import Any
from math import isfinite
from erp_bar.domain.supplier_profile import product_query_key

from erp_bar.domain.action_proposal import (
    CheckpointResult,
    SpecialistActionProposal,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
)


# ==========================================================
# ACTION OWNERSHIP
# ==========================================================

INVENTORY_ACTIONS = {
    "SEARCH_PRODUCT",
    "CREATE_PRODUCT",
    "GET_AVAILABLE_STOCK",
    "STOCK_READY",
    "REQUEST_PROCUREMENT",
    "GET_DELIVERY",
    "CHECK_DELIVERY_AVAILABILITY",
    "ASSIGN_DELIVERY",
    "VALIDATE_DELIVERY",
    "DELIVERY_COMPLETED",
    "FAIL",
}


PURCHASE_ACTIONS = {
    "SETUP_PRODUCT_VENDOR",
    "GET_PRODUCT_VENDORS",
    "CREATE_PURCHASE_ORDER",
    "CONFIRM_PURCHASE_ORDER",
    "RECEIVE_PURCHASE",
    "PROCUREMENT_SUCCEEDED",
    "PROCUREMENT_FAILED",
}


SALES_ORDER_ACTIONS = {
    "GET_AVAILABLE_STOCK",
    "GET_SALES_ORDER",
    "CREATE_SALES_ORDER",
    "CONFIRM_SALES_ORDER",
    "SALES_ORDER_CONFIRMED",
    "FAIL",
}


def _approved(
    reason: str,
) -> CheckpointResult:
    return CheckpointResult(
        approved=True,
        reason=reason,
    )


def _rejected(
    reason: str,
) -> CheckpointResult:
    return CheckpointResult(
        approved=False,
        reason=reason,
    )


# ==========================================================
# INVENTORY CHECKPOINT
# ==========================================================


def validate_inventory_proposal(
    context: AgentContext,
    proposal: SpecialistActionProposal,
    facts: dict[str, Any],
) -> CheckpointResult:
    action = proposal.action

    capability = (
        context.requested_capability
    )

    if action not in INVENTORY_ACTIONS:
        return _rejected(
            f"{action} is not an Inventory "
            "Agent capability."
        )

    # ======================================================
    # DELIVERY DOMAIN
    # ======================================================

    if (
        capability
        == AgentCapability.FULFILL_DELIVERY
    ):
        return _validate_delivery_proposal(
            proposal=proposal,
            facts=facts,
        )

    # Prevent warehouse delivery actions during
    # inventory-resolution work.

    if action in {
        "GET_DELIVERY",
        "CHECK_DELIVERY_AVAILABILITY",
        "ASSIGN_DELIVERY",
        "VALIDATE_DELIVERY",
        "DELIVERY_COMPLETED",
    }:
        return _rejected(
            "Delivery actions are not valid for "
            "the current Inventory objective."
        )

    product_query = facts.get(
        "product_query"
    )

    product_id = facts.get(
        "product_id"
    )

    available_qty = facts.get(
        "available_qty"
    )

    shortage_qty = facts.get(
        "shortage_qty"
    )

    requested_qty = facts.get(
        "requested_qty"
    )

    product_not_found = facts.get(
        "product_not_found",
        False,
    )

    # Arguments may repeat verified values, but cannot replace them.
    # Omitted values are supplied by the runtime from these same facts.
    allowed_arguments = {
        "SEARCH_PRODUCT": {"query": product_query},
        "CREATE_PRODUCT": {"name": product_query},
        "GET_AVAILABLE_STOCK": {"product_id": product_id},
    }.get(action, {})
    for key, value in proposal.arguments.items():
        if (
            key not in allowed_arguments
            or type(value) is not type(allowed_arguments[key])
            or value != allowed_arguments[key]
        ):
            return _rejected(
                f"Argument {key!r} must match the verified mission facts. "
                f"Allowed arguments for {action}: {allowed_arguments}."
            )

    # ======================================================
    # SEARCH PRODUCT
    # ======================================================

    if action == "SEARCH_PRODUCT":
        if not product_query:
            return _rejected(
                "SEARCH_PRODUCT requires a "
                "customer product query."
            )

        if product_id is not None:
            return _rejected(
                "The product is already resolved. "
                "Searching for it again would be "
                "redundant."
            )

        if product_not_found:
            return _rejected(
                "The product search already returned PRODUCT_NOT_FOUND. "
                "Decide whether to create the product or fail."
            )

        return _approved(
            "Product identity is not yet verified."
        )

    # ======================================================
    # CREATE PRODUCT
    # ======================================================

    if action == "CREATE_PRODUCT":
        if product_id is not None:
            return _rejected(
                "The product already exists."
            )

        if facts.get("product_creation_attempted"):
            return _rejected(
                "Product creation was already attempted. Do not repeat "
                "the write; search to verify its result or fail."
            )

        if not product_not_found:
            return _rejected(
                "Product creation requires a "
                "verified PRODUCT_NOT_FOUND result."
            )

        if (
            not context
            .business_policy
            .auto_create_products
        ):
            return _rejected(
                "Business policy does not permit "
                "automatic product creation."
            )

        return _approved(
            "The requested product was not found "
            "and automatic product creation is "
            "permitted."
        )

    # ======================================================
    # STOCK
    # ======================================================

    if action == "GET_AVAILABLE_STOCK":
        if product_id is None:
            return _rejected(
                "Stock cannot be queried until "
                "product_id is verified."
            )

        if available_qty is not None:
            return _rejected(
                "Stock was already read during this inventory task. "
                "Use the result to report readiness or request procurement."
            )

        return _approved(
            "The product is verified and Odoo "
            "stock may be inspected."
        )

    # ======================================================
    # STOCK READY
    # ======================================================

    if action == "STOCK_READY":
        if product_id is None:
            return _rejected(
                "STOCK_READY requires a verified "
                "product."
            )

        if available_qty is None:
            return _rejected(
                "STOCK_READY requires fresh "
                "inventory information."
            )

        if requested_qty is None:
            return _rejected(
                "Requested quantity is unknown."
            )

        if (
            float(available_qty)
            < float(requested_qty)
        ):
            return _rejected(
                "Available inventory is below the "
                "requested quantity."
            )

        if (
            shortage_qty is not None
            and float(shortage_qty) > 0
        ):
            return _rejected(
                "STOCK_READY conflicts with the "
                "verified positive shortage."
            )

        return _approved(
            "Verified Odoo stock can fulfill the "
            "requested quantity."
        )

    # ======================================================
    # REQUEST PROCUREMENT
    # ======================================================

    if action == "REQUEST_PROCUREMENT":
        if product_id is None:
            return _rejected(
                "Procurement cannot be requested "
                "without a verified product."
            )

        if available_qty is None or requested_qty is None:
            return _rejected(
                "Procurement requires fresh stock and a requested quantity."
            )

        if shortage_qty is None:
            return _rejected(
                "Procurement requires a verified "
                "shortage."
            )

        if float(shortage_qty) <= 0:
            return _rejected(
                "There is no positive stock "
                "shortage to procure."
            )

        if float(shortage_qty) != max(
            float(requested_qty) - float(available_qty), 0.0
        ):
            return _rejected(
                "The shortage must match requested quantity minus verified stock."
            )

        return _approved(
            "A verified stock shortage exists."
        )

    # ======================================================
    # FAIL
    # ======================================================

    if action == "FAIL":
        error = facts.get(
            "last_error"
        )

        if error or product_not_found:
            return _approved(
                "The Inventory Agent has a verified error or a missing "
                "product that cannot safely be created."
            )

        return _rejected(
            "FAIL requires a verified blocking "
            "condition."
        )

    return _rejected(
        f"Action {action} is not valid for the "
        "current Inventory objective."
    )


# ==========================================================
# DELIVERY CHECKPOINT
# ==========================================================


def _validate_delivery_proposal(
    proposal: SpecialistActionProposal,
    facts: dict[str, Any],
) -> CheckpointResult:
    action = proposal.action

    sales_order_id = facts.get(
        "sales_order_id"
    )

    picking_id = facts.get(
        "picking_id"
    )

    delivery_state = facts.get(
        "delivery_state"
    )

    can_fulfill = facts.get(
        "can_fulfill"
    )

    availability_checked = facts.get(
        "availability_checked",
        False,
    )

    # ======================================================
    # GET DELIVERY
    # ======================================================

    if action == "GET_DELIVERY":
        if sales_order_id is None:
            return _rejected(
                "GET_DELIVERY requires a verified "
                "sales_order_id."
            )

        if picking_id is not None:
            return _rejected(
                "Delivery picking is already "
                "resolved."
            )

        return _approved(
            "The confirmed Sales Order exists but "
            "its warehouse picking is not yet "
            "resolved."
        )

    # ======================================================
    # CHECK AVAILABILITY
    # ======================================================

    if (
        action
        == "CHECK_DELIVERY_AVAILABILITY"
    ):
        if picking_id is None:
            return _rejected(
                "Delivery availability cannot be "
                "checked before resolving the "
                "picking."
            )

        if delivery_state == "done":
            return _rejected(
                "Delivery is already completed."
            )

        return _approved(
            "The delivery picking exists and its "
            "fulfillment availability may be "
            "verified."
        )

    # ======================================================
    # ASSIGN
    # ======================================================

    if action == "ASSIGN_DELIVERY":
        if picking_id is None:
            return _rejected(
                "ASSIGN_DELIVERY requires a "
                "verified picking."
            )

        if not availability_checked:
            return _rejected(
                "Delivery stock availability must "
                "be checked first."
            )

        if can_fulfill is not True:
            return _rejected(
                "Delivery cannot be reserved "
                "because inventory cannot fulfill "
                "the requested quantity."
            )

        if delivery_state == "done":
            return _rejected(
                "Delivery is already completed."
            )

        if delivery_state == "assigned":
            return _rejected(
                "Delivery is already assigned."
            )

        return _approved(
            "Availability is verified and the "
            "delivery may be reserved."
        )

    # ======================================================
    # VALIDATE DELIVERY
    # ======================================================

    if action == "VALIDATE_DELIVERY":
        if picking_id is None:
            return _rejected(
                "VALIDATE_DELIVERY requires a "
                "verified picking."
            )

        if delivery_state == "done":
            return _rejected(
                "Delivery is already completed."
            )

        if delivery_state != "assigned":
            return _rejected(
                "Delivery must be assigned before "
                "validation."
            )

        return _approved(
            "The delivery is reserved and may now "
            "be validated."
        )

    # ======================================================
    # COMPLETE
    # ======================================================

    if action == "DELIVERY_COMPLETED":
        if picking_id is None:
            return _rejected(
                "Delivery completion requires a "
                "verified picking."
            )

        if delivery_state != "done":
            return _rejected(
                "Odoo has not verified the "
                "delivery as done."
            )

        return _approved(
            "Odoo confirms that the delivery "
            "picking is done."
        )

    if action == "FAIL":
        if facts.get("last_error"):
            return _approved(
                "A verified warehouse failure "
                "prevents fulfillment."
            )

        if (
            availability_checked
            and can_fulfill is False
        ):
            return _approved(
                "Delivery availability was "
                "verified as insufficient."
            )

        return _rejected(
            "FAIL requires a verified delivery "
            "failure."
        )

    return _rejected(
        f"{action} is not valid for the current "
        "delivery objective."
    )


# ==========================================================
# PURCHASE CHECKPOINT
# ==========================================================


def validate_purchase_proposal(
    context: AgentContext,
    proposal: SpecialistActionProposal,
    facts: dict[str, Any],
) -> CheckpointResult:
    action = proposal.action

    if action not in PURCHASE_ACTIONS:
        return _rejected(
            f"{action} is not a Purchase Agent "
            "capability."
        )

    product_id = facts.get(
        "product_id"
    )

    shortage_qty = facts.get(
        "shortage_qty"
    )

    vendors = facts.get(
        "vendors"
    )

    selected_vendor_id = (
        facts.get(
            "selected_vendor_id"
        )
    )

    purchase_order_id = facts.get(
        "purchase_order_id"
    )

    po_state = facts.get(
        "po_state"
    )

    received_qty = facts.get(
        "received_qty",
        0,
    )

    purchase_qty = facts.get("purchase_qty")
    max_buffer = context.business_policy.purchase_buffer_by_product.get(product_id, 0.0)

    expected = {
        "GET_PRODUCT_VENDORS": {"product_id": product_id, "required_qty": shortage_qty},
        "CREATE_PURCHASE_ORDER": {"product_id": product_id, "quantity": shortage_qty},
        "CONFIRM_PURCHASE_ORDER": {"purchase_order_id": purchase_order_id},
        "RECEIVE_PURCHASE": {"purchase_order_id": purchase_order_id},
    }.get(action, {})
    for key, value in proposal.arguments.items():
        if action == "CREATE_PURCHASE_ORDER" and key in {"vendor_id", "quantity"}:
            continue
        if (
            key not in expected
            or isinstance(value, bool)
            or value != expected[key]
            or (key.endswith("_id") and type(value) is not int)
        ):
            return _rejected(f"Argument {key!r} must match verified facts: {expected}.")

    if facts.get("unsafe_result") and action != "PROCUREMENT_FAILED":
        return _rejected("An inconsistent Odoo result must be resolved before further actions. Report failure.")

    if action in {"SETUP_PRODUCT_VENDOR", "CREATE_PURCHASE_ORDER", "CONFIRM_PURCHASE_ORDER", "RECEIVE_PURCHASE"}:
        attempts = facts.get("tool_attempts", {}).get(action, 0)
        if attempts >= context.business_policy.max_procurement_attempts:
            return _rejected("The retry limit for this purchase action has been reached. Report failure.")

    if action == "SETUP_PRODUCT_VENDOR":
        if not context.business_policy.auto_create_vendors:
            return _rejected("Business policy does not permit supplier creation/linking.")
        if vendors != [] or facts.get("last_error") != "NO_VENDOR_FOUND":
            return _rejected("Supplier setup requires a verified NO_VENDOR_FOUND lookup. Read suppliers first.")
        if purchase_order_id is not None or selected_vendor_id is not None or purchase_qty is not None:
            return _rejected("Supplier setup cannot change an existing purchase plan.")
        if not context.mission.requested_items or context.mission.requested_items[0].product_id != product_id:
            return _rejected("Supplier setup requires the mission's verified product.")
        profile = context.mission.supplier_setup_profile or context.business_policy.supplier_by_product.get(
            product_query_key(context.mission.requested_items[0].product_query))
        if profile is None:
            return _rejected("No operator-supplied profile exists for this exact product query. Do not invent supplier details.")
        if context.mission.supplier_setup_profile is not None and context.mission.supplier_setup_product_id != product_id:
            return _rejected("Locked supplier setup belongs to a different product.")
        return _approved("No linked supplier exists; configured supplier details may be used to create/reuse the supplier and link this product.")

    # ======================================================
    # VENDORS
    # ======================================================

    if action == "GET_PRODUCT_VENDORS":
        if product_id is None:
            return _rejected(
                "Vendor lookup requires a verified "
                "product."
            )

        if (
            shortage_qty is None
            or float(shortage_qty) <= 0
        ):
            return _rejected(
                "Vendor lookup requires a "
                "positive verified shortage."
            )

        if vendors is not None:
            return _rejected(
                "Vendor lookup has already been "
                "performed."
            )

        return _approved(
            "Procurement requires supplier "
            "information."
        )

    # ======================================================
    # CREATE PO
    # ======================================================

    if action == "CREATE_PURCHASE_ORDER":
        if shortage_qty is None or not isfinite(shortage_qty) or shortage_qty <= 0:
            return _rejected("PO creation requires a finite positive verified shortage.")
        if max_buffer > 0 and purchase_qty is None and "quantity" not in proposal.arguments:
            return _rejected("Choose an explicit total quantity: verified shortage plus your chosen extra stock, within the configured buffer allowance.")
        quantity = proposal.arguments.get("quantity", purchase_qty if purchase_qty is not None else shortage_qty)
        if (isinstance(quantity, bool) or not isinstance(quantity, (int, float))
                or not isfinite(quantity)):
            return _rejected("Purchase quantity must be a finite number.")
        if quantity < shortage_qty or quantity > shortage_qty + max_buffer:
            return _rejected(f"Purchase quantity must be between shortage {shortage_qty} and maximum {shortage_qty + max_buffer} (extra allowance {max_buffer}).")
        if purchase_qty is not None and quantity != purchase_qty:
            return _rejected(f"PO creation was already attempted. Retry the locked purchase quantity {purchase_qty}; do not change it.")
        if not vendors:
            return _rejected(
                "A purchase order cannot be "
                "created before verified vendors "
                "are available."
            )

        proposed_vendor = (
            proposal.arguments.get(
                "vendor_id"
            )
        )

        if type(proposed_vendor) is not int:
            return _rejected(
                "The Purchase Agent must select "
                "one verified vendor."
            )

        verified_vendor_ids = {
            int(vendor["vendor_id"])
            for vendor in vendors
        }

        if (
            proposed_vendor
            not in verified_vendor_ids
        ):
            return _rejected(
                "The proposed vendor_id was not "
                "returned by Odoo vendor lookup."
            )

        if selected_vendor_id is not None and proposed_vendor != selected_vendor_id:
            return _rejected(
                "A purchase write was already attempted for another vendor. "
                "Retry with the same vendor and mission key or report failure."
            )

        if purchase_order_id is not None:
            return _rejected(
                "A purchase order already exists "
                "for this procurement objective."
            )

        return _approved(
            f"Verified supplier selected; purchase {quantity} = shortage "
            f"{shortage_qty} + extra {quantity - shortage_qty}, within allowance {max_buffer}."
        )

    # ======================================================
    # CONFIRM PO
    # ======================================================

    if action == "CONFIRM_PURCHASE_ORDER":
        if purchase_order_id is None:
            return _rejected(
                "Purchase-order confirmation "
                "requires an existing PO."
            )

        if po_state not in {
            "draft",
            "sent",
            "to approve",
        }:
            return _rejected(
                f"PO state {po_state!r} does not "
                "require confirmation."
            )

        return _approved(
            "The verified PO is awaiting "
            "confirmation."
        )

    # ======================================================
    # RECEIVE
    # ======================================================

    if action == "RECEIVE_PURCHASE":
        if purchase_order_id is None:
            return _rejected(
                "Receipt requires an existing PO."
            )

        if po_state not in {
            "purchase",
            "done",
        }:
            return _rejected(
                "Goods may only be received from "
                "a confirmed purchase order."
            )

        if (
            purchase_qty is not None
            and float(received_qty)
            >= float(purchase_qty)
        ):
            return _rejected(
                "The required quantity is already "
                "received."
            )

        return _approved(
            "The PO is confirmed and goods still "
            "need to be received."
        )

    # ======================================================
    # SUCCESS
    # ======================================================

    if action == "PROCUREMENT_SUCCEEDED":
        if facts.get("last_error") or po_state not in {"purchase", "done"}:
            return _rejected("Success requires a confirmed PO and a successful verified receipt result.")

        if purchase_order_id is None:
            return _rejected(
                "Procurement success requires an "
                "actual purchase order."
            )

        if purchase_qty is None:
            return _rejected("Chosen purchase quantity is missing.")

        if (
            float(received_qty)
            < float(purchase_qty)
        ):
            return _rejected(
                "Odoo has not verified receipt of "
                "the full chosen purchase quantity, including buffer."
            )

        return _approved(
            "Odoo confirms that the required "
            "procurement quantity was received."
        )

    # ======================================================
    # FAILURE
    # ======================================================

    if action == "PROCUREMENT_FAILED":
        if vendors == []:
            return _approved(
                "Odoo vendor lookup returned no "
                "configured supplier."
            )

        if facts.get("last_error"):
            return _approved(
                "A verified procurement error "
                "prevents completion."
            )

        return _rejected(
            "PROCUREMENT_FAILED requires a "
            "verified blocking procurement "
            "condition."
        )

    return _rejected(
        f"{action} is not valid for the current "
        "Purchase objective."
    )


# ==========================================================
# SALES CHECKPOINT
# ==========================================================


def validate_sales_proposal(
    context: AgentContext,
    proposal: SpecialistActionProposal,
    facts: dict[str, Any],
) -> CheckpointResult:
    action = proposal.action

    if action not in SALES_ORDER_ACTIONS:
        return _rejected(
            f"{action} is not a Sales Agent "
            "order-processing capability."
        )

    customer_id = facts.get(
        "customer_id"
    )

    product_id = facts.get(
        "product_id"
    )

    requested_qty = facts.get(
        "requested_qty"
    )

    shortage_qty = facts.get(
        "shortage_qty"
    )

    sales_order_id = facts.get(
        "sales_order_id"
    )

    sales_order_state = facts.get(
        "sales_order_state"
    )

    expected = {
        "GET_AVAILABLE_STOCK": {"product_id": product_id},
        "GET_SALES_ORDER": {"sales_order_id": sales_order_id},
        "CREATE_SALES_ORDER": {"customer_id": customer_id, "product_id": product_id, "quantity": requested_qty},
        "CONFIRM_SALES_ORDER": {"sales_order_id": sales_order_id},
    }.get(action, {})
    for key, value in proposal.arguments.items():
        if (
            key not in expected
            or isinstance(value, bool)
            or value != expected[key]
            or (key.endswith("_id") and type(value) is not int)
        ):
            return _rejected(f"Argument {key!r} must match verified facts: {expected}.")

    if facts.get("unsafe_result") and action != "FAIL":
        return _rejected("An inconsistent tool result blocks further sales actions. Report failure.")

    if action == "GET_AVAILABLE_STOCK":
        if product_id is None:
            return _rejected("Stock checking requires a verified product.")
        if sales_order_id is not None and sales_order_state is None:
            return _rejected("Read the known sales order first; it may already be confirmed.")
        if sales_order_state == "sale":
            return _rejected("The order is already confirmed; its own reservations are not free stock.")
        return _approved("Read current warehouse stock before committing the order.")

    if action in {"CREATE_SALES_ORDER", "CONFIRM_SALES_ORDER"}:
        available = facts.get("available_qty")
        if (
            available is None or requested_qty is None
            or float(available) < float(requested_qty)
            or shortage_qty is None or float(shortage_qty) > 0
        ):
            return _rejected("Sales writes require a fresh stock check covering the full requested quantity.")

    # ======================================================
    # GET EXISTING SO
    # ======================================================

    if action == "GET_SALES_ORDER":
        if sales_order_id is None:
            return _rejected(
                "There is no known sales_order_id "
                "to retrieve."
            )

        return _approved(
            "A known Sales Order may be refreshed "
            "from Odoo."
        )

    # ======================================================
    # CREATE
    # ======================================================

    if action == "CREATE_SALES_ORDER":
        if customer_id is None:
            return _rejected(
                "Sales order creation requires a "
                "verified customer."
            )

        if product_id is None:
            return _rejected(
                "Sales order creation requires a "
                "verified product."
            )

        if (
            requested_qty is None
            or float(requested_qty) <= 0
        ):
            return _rejected(
                "Requested sales quantity is "
                "invalid."
            )

        if (
            shortage_qty is not None
            and float(shortage_qty) > 0
        ):
            return _rejected(
                "A customer Sales Order cannot be "
                "created while a verified stock "
                "shortage remains."
            )

        if sales_order_id is not None:
            return _rejected(
                "A Sales Order already exists."
            )

        return _approved(
            "Customer, product and fulfillment "
            "quantity are verified."
        )

    # ======================================================
    # CONFIRM
    # ======================================================

    if action == "CONFIRM_SALES_ORDER":
        if sales_order_id is None:
            return _rejected(
                "Sales confirmation requires an "
                "existing Sales Order."
            )

        if sales_order_state not in {
            "draft",
            "sent",
        }:
            return _rejected(
                f"Sales Order state "
                f"{sales_order_state!r} does not "
                "require confirmation."
            )

        return _approved(
            "The Sales Order exists and is "
            "awaiting confirmation."
        )

    # ======================================================
    # SUCCESS
    # ======================================================

    if action == "SALES_ORDER_CONFIRMED":
        if facts.get("last_error"):
            return _rejected("Refresh the order to verify its state after the tool error.")

        if sales_order_id is None:
            return _rejected(
                "Sales completion requires an "
                "existing Sales Order."
            )

        if sales_order_state != "sale":
            return _rejected(
                "Odoo has not verified the Sales "
                "Order as confirmed."
            )

        return _approved(
            "Odoo confirms that the customer "
            "Sales Order is in sale state."
        )

    if action == "FAIL":
        if facts.get("last_error"):
            return _approved(
                "A verified Sales Order failure "
                "prevents completion."
            )

        return _rejected(
            "FAIL requires a verified blocking "
            "Sales error."
        )

    return _rejected(
        f"{action} is not valid for the current "
        "Sales objective."
    )
