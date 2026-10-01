from erp_bar.runtime.events import observed_tool

from erp_bar.odoo.client import (
    get_odoo_bridge,
)
from erp_bar.odoo.inventory_service import (
    get_warehouse_stock_snapshot,
)
from erp_bar.tools.inventory_schemas import (
    CreateProductInput,
    CreateProductResult,
    GetAvailableStockInput,
    GetAvailableStockResult,
    ProductRecord,
    SearchProductInput,
    SearchProductResult,
)


@observed_tool
def search_product(
    tool_input: SearchProductInput,
) -> SearchProductResult:
    try:
        bridge = get_odoo_bridge()

        product = bridge.search_product(
            tool_input.query
        )

        if product is None:
            return SearchProductResult(
                ok=False,
                query=tool_input.query,
                error="PRODUCT_NOT_FOUND",
            )

        return SearchProductResult(
            ok=True,
            query=tool_input.query,
            product=ProductRecord(
                product_id=(
                    product["product_id"]
                ),
                name=(
                    product["name"]
                ),
                sku=(
                    product.get("sku")
                ),
            ),
        )

    except Exception as exc:
        return SearchProductResult(
            ok=False,
            query=tool_input.query,
            error=str(exc),
        )


@observed_tool
def create_product(
    tool_input: CreateProductInput,
) -> CreateProductResult:
    try:
        bridge = get_odoo_bridge()

        product = bridge.create_product(
            name=tool_input.name,
            sku=tool_input.sku,
        )

        return CreateProductResult(
            ok=True,
            product=ProductRecord(
                product_id=(
                    product["product_id"]
                ),
                name=(
                    product["name"]
                ),
                sku=(
                    product.get("sku")
                ),
            ),
            created=bool(
                product.get(
                    "created",
                    False,
                )
            ),
        )

    except Exception as exc:
        return CreateProductResult(
            ok=False,
            created=False,
            error=str(exc),
        )


@observed_tool
def get_available_stock(
    tool_input: GetAvailableStockInput,
) -> GetAvailableStockResult:
    """
    Return stock that is actually available for
    fulfillment from the configured warehouse.

    This no longer uses global qty_available.

    available_qty is now based on:

        warehouse physical stock
        -
        warehouse reserved stock
    """

    try:
        snapshot = (
            get_warehouse_stock_snapshot(
                product_id=(
                    tool_input.product_id
                )
            )
        )

        available_qty = float(
            snapshot["available_qty"]
        )

        print()
        print(
            "[inventory_tool] Warehouse stock snapshot:"
        )

        print(
            {
                "product_id": (
                    snapshot["product_id"]
                ),
                "warehouse_id": (
                    snapshot["warehouse_id"]
                ),
                "stock_location": (
                    snapshot[
                        "stock_location_name"
                    ]
                ),
                "global_qty_available": (
                    snapshot[
                        "global_qty_available"
                    ]
                ),
                "global_free_qty": (
                    snapshot[
                        "global_free_qty"
                    ]
                ),
                "warehouse_physical_qty": (
                    snapshot[
                        "physical_qty"
                    ]
                ),
                "warehouse_reserved_qty": (
                    snapshot[
                        "reserved_qty"
                    ]
                ),
                "warehouse_available_qty": (
                    available_qty
                ),
            }
        )

        return GetAvailableStockResult(
            ok=True,
            product_id=(
                tool_input.product_id
            ),
            available_qty=(
                available_qty
            ),
        )

    except Exception as exc:
        return GetAvailableStockResult(
            ok=False,
            product_id=(
                tool_input.product_id
            ),
            available_qty=0,
            error=str(exc),
        )