from typing import Any

from erp_bar.odoo.client import get_odoo_bridge


def get_warehouse_stock_snapshot(
    product_id: int,
    warehouse_id: int | None = None,
    *,
    bridge=None,
) -> dict[str, Any]:
    """
    Return warehouse-specific stock information for
    one product.

    IMPORTANT:

    This deliberately does NOT use global
    product.product.qty_available as the fulfillment
    quantity.

    Instead we inspect stock.quant records inside the
    configured warehouse's main stock location.

    available_qty =
        physical_qty - reserved_qty

    This is much closer to what Odoo can actually
    reserve for an outgoing delivery.
    """

    if bridge is None:
        bridge = get_odoo_bridge()

    resolved_warehouse_id = (
        warehouse_id
        if warehouse_id is not None
        else bridge.warehouse_id
    )

    # ==========================================================
    # VERIFY PRODUCT
    # ==========================================================

    product_data = bridge.execute(
        "product.product",
        "read",
        [product_id],
        fields=[
            "display_name",
            "qty_available",
            "free_qty",
        ],
    )

    if not product_data:
        raise ValueError(
            f"Product #{product_id} does not exist."
        )

    product = product_data[0]

    # ==========================================================
    # RESOLVE WAREHOUSE STOCK LOCATION
    # ==========================================================

    warehouse_data = bridge.execute(
        "stock.warehouse",
        "read",
        [resolved_warehouse_id],
        fields=[
            "name",
            "code",
            "lot_stock_id",
        ],
    )

    if not warehouse_data:
        raise ValueError(
            f"Warehouse #{resolved_warehouse_id} "
            "does not exist."
        )

    warehouse = warehouse_data[0]

    lot_stock = warehouse.get(
        "lot_stock_id"
    )

    if not lot_stock:
        raise ValueError(
            f"Warehouse #{resolved_warehouse_id} "
            "does not have a main stock location."
        )

    stock_location_id = int(
        lot_stock[0]
    )

    stock_location_name = str(
        lot_stock[1]
    )

    # ==========================================================
    # READ WAREHOUSE QUANTS
    # ==========================================================
    #
    # child_of includes the warehouse's stock location and
    # internal child locations beneath it.
    #
    # We explicitly limit this to internal locations.
    # ==========================================================

    quants = bridge.execute(
        "stock.quant",
        "search_read",
        [
            [
                "product_id",
                "=",
                product_id,
            ],
            [
                "location_id",
                "child_of",
                stock_location_id,
            ],
            [
                "location_id.usage",
                "=",
                "internal",
            ],
        ],
        fields=[
            "location_id",
            "quantity",
            "reserved_quantity",
        ],
    )

    physical_qty = 0.0
    reserved_qty = 0.0

    location_details = []

    for quant in quants:
        quantity = float(
            quant.get(
                "quantity",
                0,
            )
            or 0
        )

        reserved = float(
            quant.get(
                "reserved_quantity",
                0,
            )
            or 0
        )

        physical_qty += quantity
        reserved_qty += reserved

        location = quant.get(
            "location_id"
        )

        location_details.append(
            {
                "location_id": (
                    int(location[0])
                    if location
                    else None
                ),
                "location_name": (
                    str(location[1])
                    if location
                    else None
                ),
                "quantity": quantity,
                "reserved_quantity": reserved,
                "free_quantity": max(
                    quantity - reserved,
                    0.0,
                ),
            }
        )

    # ==========================================================
    # FULFILLMENT AVAILABILITY
    # ==========================================================

    available_qty = max(
        physical_qty - reserved_qty,
        0.0,
    )

    return {
        "product_id": product_id,
        "product_name": (
            product.get(
                "display_name"
            )
        ),

        # Global values are returned for diagnostics only.
        # They are NOT used for fulfillment decisions.
        "global_qty_available": float(
            product.get(
                "qty_available",
                0,
            )
            or 0
        ),
        "global_free_qty": float(
            product.get(
                "free_qty",
                0,
            )
            or 0
        ),

        "warehouse_id": (
            resolved_warehouse_id
        ),
        "warehouse_name": (
            warehouse.get("name")
        ),
        "warehouse_code": (
            warehouse.get("code")
        ),

        "stock_location_id": (
            stock_location_id
        ),
        "stock_location_name": (
            stock_location_name
        ),

        "physical_qty": (
            physical_qty
        ),
        "reserved_qty": (
            reserved_qty
        ),

        # THIS is what ERP_BAR should use.
        "available_qty": (
            available_qty
        ),

        "locations": (
            location_details
        ),
    }

def get_product_reservations(
    product_id: int,
    warehouse_id: int | None = None,
) -> list[dict]:
    bridge = get_odoo_bridge()

    resolved_warehouse_id = (
        warehouse_id
        if warehouse_id is not None
        else bridge.warehouse_id
    )

    warehouse_data = bridge.execute(
        "stock.warehouse",
        "read",
        [resolved_warehouse_id],
        fields=[
            "lot_stock_id",
        ],
    )

    if not warehouse_data:
        raise ValueError(
            f"Warehouse #{resolved_warehouse_id} not found."
        )

    lot_stock = (
        warehouse_data[0]
        ["lot_stock_id"]
    )

    stock_location_id = int(
        lot_stock[0]
    )

    move_lines = bridge.execute(
        "stock.move.line",
        "search_read",
        [
            [
                "product_id",
                "=",
                product_id,
            ],
            [
                "location_id",
                "child_of",
                stock_location_id,
            ],
            [
                "state",
                "not in",
                [
                    "done",
                    "cancel",
                ],
            ],
        ],
        fields=[
            "picking_id",
            "move_id",
            "location_id",
            "location_dest_id",
            "quantity",
            "state",
        ],
    )

    results = []

    for line in move_lines:
        picking = line.get(
            "picking_id"
        )

        picking_info = None

        if picking:
            picking_data = bridge.execute(
                "stock.picking",
                "read",
                [picking[0]],
                fields=[
                    "name",
                    "state",
                    "origin",
                    "sale_id",
                ],
            )

            if picking_data:
                picking_info = (
                    picking_data[0]
                )

        results.append(
            {
                "move_line_id": (
                    line["id"]
                ),
                "quantity": (
                    line.get(
                        "quantity",
                        0,
                    )
                ),
                "location_id": (
                    line.get(
                        "location_id"
                    )
                ),
                "picking": (
                    picking_info
                ),
            }
        )

    return results
