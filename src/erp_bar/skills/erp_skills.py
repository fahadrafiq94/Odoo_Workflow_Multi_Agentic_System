from typing import Any

from erp_bar.tools.delivery_schemas import (
    AssignDeliveryInput,
    CheckDeliveryAvailabilityInput,
    GetDeliveryInput,
    ValidateDeliveryInput,
)
from erp_bar.tools.delivery_tools import (
    assign_delivery,
    check_delivery_availability,
    get_delivery,
    validate_delivery,
)
from erp_bar.tools.inventory_schemas import (
    CreateProductInput,
    GetAvailableStockInput,
    SearchProductInput,
)
from erp_bar.tools.inventory_tools import (
    create_product,
    get_available_stock,
    search_product,
)
from erp_bar.tools.purchase_schemas import (
    ConfirmPurchaseOrderInput,
    CreatePurchaseOrderInput,
    GetProductVendorsInput,
    ReceivePurchaseInput,
)
from erp_bar.tools.purchase_tools import (
    confirm_purchase_order,
    create_purchase_order,
    get_product_vendors,
    receive_purchase,
)
from erp_bar.tools.sales_schemas import (
    ConfirmSalesOrderInput,
    CreateSalesOrderInput,
)
from erp_bar.tools.sales_tools import (
    confirm_sales_order,
    create_sales_order,
)


# ==========================================================
# INVENTORY
# ==========================================================


def assess_inventory(
    product_query: str,
    requested_qty: float,
    product_id: int | None = None,
) -> dict[str, Any]:
    """
    Resolve the requested product if necessary and
    obtain the current Odoo stock position.

    No LLM reasoning occurs here.

    This skill only establishes verified ERP facts.
    """

    facts: dict[str, Any] = {
        "product_query": product_query,
        "requested_qty": float(
            requested_qty
        ),
    }

    resolved_product_id = product_id

    # ------------------------------------------------------
    # PRODUCT RESOLUTION
    # ------------------------------------------------------

    if resolved_product_id is None:
        search_result = search_product(
            SearchProductInput(
                query=product_query,
            )
        )

        if not search_result.ok:
            if (
                search_result.error
                == "PRODUCT_NOT_FOUND"
            ):
                return {
                    **facts,
                    "outcome": (
                        "PRODUCT_NOT_FOUND"
                    ),
                    "product_found": False,
                    "product_id": None,
                    "error": None,
                }

            return {
                **facts,
                "outcome": "FAILED",
                "product_found": False,
                "product_id": None,
                "error": search_result.error,
            }

        if search_result.product is None:
            return {
                **facts,
                "outcome": "FAILED",
                "product_found": False,
                "product_id": None,
                "error": (
                    "Product search succeeded "
                    "without returning a product."
                ),
            }

        product = search_result.product

        resolved_product_id = (
            product.product_id
        )

        facts.update(
            {
                "product_id": (
                    product.product_id
                ),
                "product_name": (
                    product.name
                ),
                "product_sku": (
                    product.sku
                ),
                "product_found": True,
            }
        )

    else:
        facts.update(
            {
                "product_id": (
                    resolved_product_id
                ),
                "product_found": True,
            }
        )

    # ------------------------------------------------------
    # STOCK
    # ------------------------------------------------------

    stock_result = get_available_stock(
        GetAvailableStockInput(
            product_id=(
                resolved_product_id
            ),
        )
    )

    if not stock_result.ok:
        return {
            **facts,
            "outcome": "FAILED",
            "available_qty": None,
            "shortage_qty": None,
            "error": stock_result.error,
        }

    available_qty = float(
        stock_result.available_qty
    )

    shortage_qty = max(
        float(requested_qty)
        - available_qty,
        0.0,
    )

    outcome = (
        "STOCK_READY"
        if shortage_qty <= 0
        else "SHORTAGE"
    )

    return {
        **facts,
        "available_qty": (
            available_qty
        ),
        "shortage_qty": (
            shortage_qty
        ),
        "outcome": outcome,
        "error": None,
    }


def verify_inventory(
    product_id: int,
    requested_qty: float,
    product_query: str,
) -> dict[str, Any]:
    """
    Obtain a fresh Odoo inventory snapshot.

    Used especially after procurement.
    """

    return assess_inventory(
        product_query=product_query,
        requested_qty=requested_qty,
        product_id=product_id,
    )


def create_missing_product(
    product_name: str,
) -> dict[str, Any]:
    """
    Deterministically create a missing Odoo product.

    The decision to call this skill belongs to the
    Inventory Agent / policy layer.
    """

    result = create_product(
        CreateProductInput(
            name=product_name,
            sku=None,
        )
    )

    if (
        not result.ok
        or result.product is None
    ):
        return {
            "ok": False,
            "product_id": None,
            "error": result.error,
        }

    return {
        "ok": True,
        "product_id": (
            result.product.product_id
        ),
        "product_name": (
            result.product.name
        ),
        "product_sku": (
            result.product.sku
        ),
        "created": (
            result.created
        ),
        "error": None,
    }


# ==========================================================
# PROCUREMENT
# ==========================================================


def get_procurement_options(
    product_id: int,
    shortage_qty: float,
) -> dict[str, Any]:
    """
    Read verified supplier options from Odoo.

    This is read-only.
    """

    result = get_product_vendors(
        GetProductVendorsInput(
            product_id=product_id,
            required_qty=shortage_qty,
        )
    )

    if not result.ok:
        if result.error == "NO_VENDOR_FOUND":
            return {
                "ok": True,
                "vendors": [],
                "error": None,
            }

        return {
            "ok": False,
            "vendors": [],
            "error": result.error,
        }

    return {
        "ok": True,
        "vendors": [
            vendor.model_dump()
            for vendor
            in result.vendors
        ],
        "error": None,
    }


def execute_procurement(
    mission_id: str,
    vendor_id: int,
    product_id: int,
    shortage_qty: float,
) -> dict[str, Any]:
    """
    Execute one approved procurement strategy.

    Deterministic mechanics:

        create/reuse PO
        confirm PO
        receive goods
        verify received quantity

    The Purchase Agent chooses the supplier strategy.
    """

    # ------------------------------------------------------
    # CREATE / REUSE PO
    # ------------------------------------------------------

    create_result = (
        create_purchase_order(
            CreatePurchaseOrderInput(
                mission_id=mission_id,
                vendor_id=vendor_id,
                product_id=product_id,
                quantity=shortage_qty,
            )
        )
    )

    if (
        not create_result.ok
        or create_result.purchase_order
        is None
    ):
        return {
            "ok": False,
            "stage": (
                "CREATE_PURCHASE_ORDER"
            ),
            "vendor_id": vendor_id,
            "product_id": product_id,
            "shortage_qty": (
                shortage_qty
            ),
            "error": (
                create_result.error
            ),
        }

    po = create_result.purchase_order

    # ------------------------------------------------------
    # CONFIRM
    # ------------------------------------------------------

    if po.state in {
        "draft",
        "sent",
        "to approve",
    }:
        confirm_result = (
            confirm_purchase_order(
                ConfirmPurchaseOrderInput(
                    purchase_order_id=(
                        po.purchase_order_id
                    )
                )
            )
        )

        if (
            not confirm_result.ok
            or confirm_result.purchase_order
            is None
        ):
            return {
                "ok": False,
                "stage": (
                    "CONFIRM_PURCHASE_ORDER"
                ),
                "purchase_order_id": (
                    po.purchase_order_id
                ),
                "vendor_id": vendor_id,
                "product_id": product_id,
                "shortage_qty": (
                    shortage_qty
                ),
                "error": (
                    confirm_result.error
                ),
            }

        po = confirm_result.purchase_order

    # ------------------------------------------------------
    # RECEIVE
    # ------------------------------------------------------

    if (
        float(po.received_qty)
        < float(shortage_qty)
    ):
        receipt_result = receive_purchase(
            ReceivePurchaseInput(
                purchase_order_id=(
                    po.purchase_order_id
                )
            )
        )

        if not receipt_result.ok:
            return {
                "ok": False,
                "stage": (
                    "RECEIVE_PURCHASE"
                ),
                "purchase_order_id": (
                    po.purchase_order_id
                ),
                "vendor_id": vendor_id,
                "product_id": product_id,
                "shortage_qty": (
                    shortage_qty
                ),
                "error": (
                    receipt_result.error
                ),
            }

        if (
            receipt_result.purchase_order
            is not None
        ):
            po = (
                receipt_result
                .purchase_order
            )

    # ------------------------------------------------------
    # VERIFY
    # ------------------------------------------------------

    received_qty = float(
        po.received_qty
    )

    success = (
        received_qty
        >= float(shortage_qty)
    )

    return {
        "ok": success,
        "stage": "COMPLETE",
        "purchase_order_id": (
            po.purchase_order_id
        ),
        "purchase_order_name": (
            po.name
        ),
        "purchase_order_state": (
            po.state
        ),
        "vendor_id": (
            po.vendor_id
        ),
        "product_id": (
            po.product_id
        ),
        "ordered_qty": (
            po.quantity
        ),
        "received_qty": (
            received_qty
        ),
        "shortage_qty": (
            shortage_qty
        ),
        "error": (
            None
            if success
            else (
                "Received quantity is below "
                "the required shortage."
            )
        ),
    }


# ==========================================================
# SALES ORDER
# ==========================================================


def place_sales_order(
    mission_id: str,
    customer_id: int,
    product_id: int,
    quantity: float,
) -> dict[str, Any]:
    """
    Deterministically create/reuse and confirm the
    customer Sales Order.

    The business decision to place the order has
    already been made before this skill executes.
    """

    create_result = create_sales_order(
        CreateSalesOrderInput(
            mission_id=mission_id,
            customer_id=customer_id,
            product_id=product_id,
            quantity=quantity,
        )
    )

    if (
        not create_result.ok
        or create_result.sales_order
        is None
    ):
        return {
            "ok": False,
            "stage": (
                "CREATE_SALES_ORDER"
            ),
            "error": (
                create_result.error
            ),
        }

    order = create_result.sales_order

    if order.state in {
        "draft",
        "sent",
    }:
        confirm_result = (
            confirm_sales_order(
                ConfirmSalesOrderInput(
                    sales_order_id=(
                        order.sales_order_id
                    )
                )
            )
        )

        if (
            not confirm_result.ok
            or confirm_result.sales_order
            is None
        ):
            return {
                "ok": False,
                "stage": (
                    "CONFIRM_SALES_ORDER"
                ),
                "sales_order_id": (
                    order.sales_order_id
                ),
                "error": (
                    confirm_result.error
                ),
            }

        order = (
            confirm_result
            .sales_order
        )

    success = (
        order.state == "sale"
    )

    return {
        "ok": success,
        "stage": "COMPLETE",
        "sales_order_id": (
            order.sales_order_id
        ),
        "sales_order_name": (
            order.name
        ),
        "sales_order_state": (
            order.state
        ),
        "customer_id": (
            order.customer_id
        ),
        "product_id": (
            order.product_id
        ),
        "quantity": (
            order.quantity
        ),
        "error": (
            None
            if success
            else (
                "Sales Order did not reach "
                "confirmed sale state."
            )
        ),
    }


# ==========================================================
# DELIVERY
# ==========================================================


def fulfill_delivery(
    sales_order_id: int,
) -> dict[str, Any]:
    """
    Deterministically execute the normal delivery
    mechanics:

        locate picking
        check availability
        reserve
        validate
        verify done

    Exceptional results are returned to the agent
    rather than guessed around.
    """

    # ------------------------------------------------------
    # FIND PICKING
    # ------------------------------------------------------

    delivery_result = get_delivery(
        GetDeliveryInput(
            sales_order_id=(
                sales_order_id
            )
        )
    )

    if (
        not delivery_result.ok
        or delivery_result.delivery
        is None
    ):
        return {
            "ok": False,
            "stage": "GET_DELIVERY",
            "sales_order_id": (
                sales_order_id
            ),
            "error": (
                delivery_result.error
            ),
        }

    delivery = (
        delivery_result.delivery
    )

    # A completed picking is successful only for the full quantity.

    if delivery.state == "done":
        success = delivery.delivered_qty >= delivery.quantity
        return {
            "ok": success,
            "stage": "COMPLETE",
            "picking_id": (
                delivery.picking_id
            ),
            "picking_name": (
                delivery.name
            ),
            "sales_order_id": (
                delivery.sales_order_id
            ),
            "state": (
                delivery.state
            ),
            "delivered_qty": (
                delivery.delivered_qty
            ),
            "error": (
                None
                if success
                else "Delivery completed with less than the required quantity."
            ),
        }

    # ------------------------------------------------------
    # AVAILABILITY
    # ------------------------------------------------------

    availability = (
        check_delivery_availability(
            CheckDeliveryAvailabilityInput(
                picking_id=(
                    delivery.picking_id
                )
            )
        )
    )

    if not availability.ok:
        return {
            "ok": False,
            "stage": (
                "CHECK_AVAILABILITY"
            ),
            "picking_id": (
                delivery.picking_id
            ),
            "error": (
                availability.error
            ),
        }

    if not availability.can_fulfill:
        return {
            "ok": False,
            "stage": (
                "INSUFFICIENT_DELIVERY_STOCK"
            ),
            "picking_id": (
                delivery.picking_id
            ),
            "required_qty": (
                availability.required_qty
            ),
            "available_qty": (
                availability.available_qty
            ),
            "error": (
                "Odoo cannot currently reserve "
                "the required delivery quantity."
            ),
        }

    # ------------------------------------------------------
    # RESERVE
    # ------------------------------------------------------

    if delivery.state != "assigned":
        assign_result = assign_delivery(
            AssignDeliveryInput(
                picking_id=(
                    delivery.picking_id
                )
            )
        )

        if (
            not assign_result.ok
            or assign_result.delivery
            is None
        ):
            return {
                "ok": False,
                "stage": (
                    "ASSIGN_DELIVERY"
                ),
                "picking_id": (
                    delivery.picking_id
                ),
                "error": (
                    assign_result.error
                ),
            }

        delivery = (
            assign_result.delivery
        )

    # ------------------------------------------------------
    # VALIDATE
    # ------------------------------------------------------

    validate_result = validate_delivery(
        ValidateDeliveryInput(
            picking_id=(
                delivery.picking_id
            )
        )
    )

    if (
        not validate_result.ok
        or validate_result.delivery
        is None
    ):
        return {
            "ok": False,
            "stage": (
                "VALIDATE_DELIVERY"
            ),
            "picking_id": (
                delivery.picking_id
            ),
            "error": (
                validate_result.error
            ),
        }

    delivery = (
        validate_result.delivery
    )

    success = (
        delivery.state == "done"
        and delivery.delivered_qty >= delivery.quantity
    )

    return {
        "ok": success,
        "stage": "COMPLETE",
        "picking_id": (
            delivery.picking_id
        ),
        "picking_name": (
            delivery.name
        ),
        "sales_order_id": (
            delivery.sales_order_id
        ),
        "state": (
            delivery.state
        ),
        "required_qty": (
            delivery.quantity
        ),
        "delivered_qty": (
            delivery.delivered_qty
        ),
        "error": (
            None
            if success
            else (
                "Delivery did not reach done state "
                "with the full required quantity."
            )
        ),
    }
