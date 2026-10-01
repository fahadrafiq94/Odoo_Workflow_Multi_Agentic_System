from erp_bar.runtime.events import observed_tool

from erp_bar.odoo.client import (
    get_odoo_bridge,
)
from erp_bar.tools.purchase_schemas import (
    ConfirmPurchaseOrderInput,
    ConfirmPurchaseOrderResult,
    CreatePurchaseOrderInput,
    CreatePurchaseOrderResult,
    GetProductVendorsInput,
    GetProductVendorsResult,
    PurchaseOrderRecord,
    ReceivePurchaseInput,
    ReceivePurchaseResult,
    VendorRecord,
    SetupProductVendorInput,
    SetupProductVendorResult,
)


@observed_tool
def setup_product_vendor(tool_input: SetupProductVendorInput) -> SetupProductVendorResult:
    from erp_bar.odoo.vendor_setup import setup_product_vendor as execute_setup
    try:
        data = execute_setup(get_odoo_bridge(), tool_input.product_id, tool_input.profile)
        return SetupProductVendorResult(ok=True, mission_id=tool_input.mission_id,
                                        product_id=tool_input.product_id, **data)
    except Exception as exc:
        return SetupProductVendorResult(ok=False, mission_id=tool_input.mission_id,
                                        product_id=tool_input.product_id, error=str(exc))


def _purchase_record(
    data: dict,
) -> PurchaseOrderRecord:
    return PurchaseOrderRecord(
        purchase_order_id=(
            data["purchase_order_id"]
        ),
        name=data["name"],
        mission_id=(
            data["mission_id"]
        ),
        vendor_id=(
            data["vendor_id"]
        ),
        product_id=(
            data["product_id"]
        ),
        quantity=(
            data["quantity"]
        ),
        state=(
            data["state"]
        ),
        received_qty=(
            data["received_qty"]
        ),
    )


@observed_tool
def get_product_vendors(
    tool_input: GetProductVendorsInput,
) -> GetProductVendorsResult:
    try:
        bridge = get_odoo_bridge()

        raw_vendors = (
            bridge.get_product_vendors(
                tool_input.product_id
            )
        )

        vendors = [
            VendorRecord(
                vendor_id=(
                    vendor["vendor_id"]
                ),
                name=vendor["name"],
            )
            for vendor in raw_vendors
        ]

        if not vendors:
            return GetProductVendorsResult(
                ok=False,
                product_id=(
                    tool_input.product_id
                ),
                required_qty=(
                    tool_input.required_qty
                ),
                vendors=[],
                error="NO_VENDOR_FOUND",
            )

        return GetProductVendorsResult(
            ok=True,
            product_id=(
                tool_input.product_id
            ),
            required_qty=(
                tool_input.required_qty
            ),
            vendors=vendors,
        )

    except Exception as exc:
        return GetProductVendorsResult(
            ok=False,
            product_id=(
                tool_input.product_id
            ),
            required_qty=(
                tool_input.required_qty
            ),
            vendors=[],
            error=str(exc),
        )


@observed_tool
def create_purchase_order(
    tool_input: CreatePurchaseOrderInput,
) -> CreatePurchaseOrderResult:
    try:
        bridge = get_odoo_bridge()

        data, created = (
            bridge.create_purchase_order(
                mission_id=(
                    tool_input.mission_id
                ),
                vendor_id=(
                    tool_input.vendor_id
                ),
                product_id=(
                    tool_input.product_id
                ),
                quantity=(
                    tool_input.quantity
                ),
            )
        )

        return CreatePurchaseOrderResult(
            ok=True,
            purchase_order=(
                _purchase_record(
                    data
                )
            ),
            created=created,
        )

    except Exception as exc:
        return CreatePurchaseOrderResult(
            ok=False,
            created=False,
            error=str(exc),
        )


@observed_tool
def confirm_purchase_order(
    tool_input: ConfirmPurchaseOrderInput,
) -> ConfirmPurchaseOrderResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge.confirm_purchase_order(
                tool_input
                .purchase_order_id
            )
        )

        return ConfirmPurchaseOrderResult(
            ok=True,
            purchase_order=(
                _purchase_record(
                    data
                )
            ),
        )

    except Exception as exc:
        return ConfirmPurchaseOrderResult(
            ok=False,
            error=str(exc),
        )


@observed_tool
def receive_purchase(
    tool_input: ReceivePurchaseInput,
) -> ReceivePurchaseResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge.receive_purchase(
                tool_input
                .purchase_order_id
            )
        )

        record = _purchase_record(
            data
        )

        return ReceivePurchaseResult(
            ok=True,
            purchase_order=record,
            received_qty=(
                record.received_qty
            ),
        )

    except Exception as exc:
        return ReceivePurchaseResult(
            ok=False,
            received_qty=0,
            error=str(exc),
        )
