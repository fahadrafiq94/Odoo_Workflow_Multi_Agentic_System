from erp_bar.runtime.events import observed_tool

from erp_bar.odoo.client import (
    get_odoo_bridge,
)
from erp_bar.tools.sales_schemas import (
    ConfirmSalesOrderInput,
    ConfirmSalesOrderResult,
    CreateSalesOrderInput,
    CreateSalesOrderResult,
    GetSalesOrderInput,
    GetSalesOrderResult,
    SalesOrderRecord,
    PrepareFailureResponseInput,
    PrepareFailureResponseResult,
)


@observed_tool
def prepare_failure_response(tool_input: PrepareFailureResponseInput) -> PrepareFailureResponseResult:
    """Prepare text for the caller/UI. This does not send a message or change ERP records."""
    product = " ".join((tool_input.product_query or "").split())
    description = "your order"
    if product and tool_input.requested_qty is not None:
        unit = "unit" if tool_input.requested_qty == 1 else "units"
        description += f" for {tool_input.requested_qty:g} {unit} of {product}"
    message = f"We could not complete {description}."
    if tool_input.failure_code == "NO_VENDOR_FOUND":
        message += " No configured supplier was found for this product."
    elif tool_input.failure_code == "PROCUREMENT_FAILED":
        message += " Procurement could not be completed."
    elif tool_input.failure_code == "PRODUCT_NOT_FOUND":
        message += " The requested product is not available in our product catalog."
    elif tool_input.failure_code == "DEMAND_UNCLEAR":
        message = "We could not understand your request. Please tell us which product you want and how many units."
    elif tool_input.failure_code == "DELIVERY_NOT_VERIFIED":
        message = f"{description[0].upper() + description[1:]} was confirmed, but we could not verify delivery."
    if tool_input.failure_code not in {"NO_VENDOR_FOUND", "PROCUREMENT_FAILED", "DEMAND_UNCLEAR"}:
        message += f" Please ask a staff member to check before trying again. Reference: {tool_input.mission_id}."
    # Never copy internal RPC errors or promise cancellation, refunds or dates.
    return PrepareFailureResponseResult(ok=True, mission_id=tool_input.mission_id, customer_message=message)


def _sales_record(
    data: dict,
) -> SalesOrderRecord:
    return SalesOrderRecord(
        unit_price=data.get("unit_price"),
        net_unit_price=data.get("net_unit_price"),
        sales_order_id=(
            data["sales_order_id"]
        ),
        name=data["name"],
        mission_id=(
            data["mission_id"]
        ),
        customer_id=(
            data["customer_id"]
        ),
        product_id=(
            data["product_id"]
        ),
        quantity=(
            data["quantity"]
        ),
        state=data["state"],
    )


@observed_tool
def create_sales_order(
    tool_input: CreateSalesOrderInput,
) -> CreateSalesOrderResult:
    try:
        bridge = get_odoo_bridge()

        data, created = (
            bridge.create_sales_order(
                mission_id=(
                    tool_input.mission_id
                ),
                customer_id=(
                    tool_input.customer_id
                ),
                product_id=(
                    tool_input.product_id
                ),
                quantity=(
                    tool_input.quantity
                ),
            )
        )

        return CreateSalesOrderResult(
            ok=True,
            sales_order=(
                _sales_record(
                    data
                )
            ),
            created=created,
        )

    except Exception as exc:
        return CreateSalesOrderResult(
            ok=False,
            created=False,
            error=str(exc),
        )


@observed_tool
def get_sales_order(
    tool_input: GetSalesOrderInput,
) -> GetSalesOrderResult:
    try:
        bridge = get_odoo_bridge()

        data = bridge.get_sales_order(
            tool_input.sales_order_id
        )

        return GetSalesOrderResult(
            ok=True,
            sales_order=(
                _sales_record(
                    data
                )
            ),
        )

    except Exception as exc:
        return GetSalesOrderResult(
            ok=False,
            error=str(exc),
        )


@observed_tool
def confirm_sales_order(
    tool_input: ConfirmSalesOrderInput,
) -> ConfirmSalesOrderResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge.confirm_sales_order(
                tool_input
                .sales_order_id
            )
        )

        record = _sales_record(
            data
        )

        if record.state != "sale":
            return ConfirmSalesOrderResult(
                ok=False,
                sales_order=record,
                error=(
                    "SALES_ORDER_NOT_CONFIRMED"
                ),
            )

        return ConfirmSalesOrderResult(
            ok=True,
            sales_order=record,
        )

    except Exception as exc:
        return ConfirmSalesOrderResult(
            ok=False,
            error=str(exc),
        )
