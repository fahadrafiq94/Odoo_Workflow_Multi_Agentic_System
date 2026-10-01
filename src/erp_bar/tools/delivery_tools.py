from erp_bar.runtime.events import observed_tool

from erp_bar.odoo.client import (
    get_odoo_bridge,
)
from erp_bar.tools.delivery_schemas import (
    AssignDeliveryInput,
    AssignDeliveryResult,
    CheckDeliveryAvailabilityInput,
    CheckDeliveryAvailabilityResult,
    DeliveryRecord,
    GetDeliveryInput,
    GetDeliveryResult,
    ValidateDeliveryInput,
    ValidateDeliveryResult,
)


def _delivery_record(
    data: dict,
) -> DeliveryRecord:
    return DeliveryRecord(
        picking_id=(
            data["picking_id"]
        ),
        name=data["name"],
        sales_order_id=(
            data["sales_order_id"]
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
        reserved_qty=(
            data.get(
                "reserved_qty",
                0,
            )
        ),
        delivered_qty=(
            data.get(
                "delivered_qty",
                0,
            )
        ),
    )


@observed_tool
def get_delivery(
    tool_input: GetDeliveryInput,
) -> GetDeliveryResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge
            .get_delivery_for_sales_order(
                tool_input.sales_order_id
            )
        )

        if data is None:
            return GetDeliveryResult(
                ok=False,
                error="DELIVERY_NOT_FOUND",
            )

        return GetDeliveryResult(
            ok=True,
            delivery=(
                _delivery_record(
                    data
                )
            ),
        )

    except Exception as exc:
        return GetDeliveryResult(
            ok=False,
            error=str(exc),
        )


@observed_tool
def check_delivery_availability(
    tool_input: (
        CheckDeliveryAvailabilityInput
    ),
) -> CheckDeliveryAvailabilityResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge
            .check_delivery_availability(
                tool_input.picking_id
            )
        )

        return (
            CheckDeliveryAvailabilityResult(
                ok=True,
                picking_id=(
                    data["picking_id"]
                ),
                required_qty=(
                    data["required_qty"]
                ),
                available_qty=(
                    data["available_qty"]
                ),
                can_fulfill=(
                    data["can_fulfill"]
                ),
            )
        )

    except Exception as exc:
        return (
            CheckDeliveryAvailabilityResult(
                ok=False,
                picking_id=(
                    tool_input.picking_id
                ),
                required_qty=0,
                available_qty=0,
                can_fulfill=False,
                error=str(exc),
            )
        )


@observed_tool
def assign_delivery(
    tool_input: AssignDeliveryInput,
) -> AssignDeliveryResult:
    try:
        bridge = get_odoo_bridge()

        data = bridge.assign_delivery(
            tool_input.picking_id
        )

        record = _delivery_record(
            data
        )

        if record.state not in {
            "assigned",
            "done",
        }:
            return AssignDeliveryResult(
                ok=False,
                delivery=record,
                error=(
                    "DELIVERY_NOT_ASSIGNED"
                ),
            )

        return AssignDeliveryResult(
            ok=True,
            delivery=record,
        )

    except Exception as exc:
        return AssignDeliveryResult(
            ok=False,
            error=str(exc),
        )


@observed_tool
def validate_delivery(
    tool_input: ValidateDeliveryInput,
) -> ValidateDeliveryResult:
    try:
        bridge = get_odoo_bridge()

        data = (
            bridge.validate_delivery(
                tool_input.picking_id
            )
        )

        record = _delivery_record(
            data
        )

        if record.state != "done":
            return ValidateDeliveryResult(
                ok=False,
                delivery=record,
                error="DELIVERY_NOT_DONE",
            )

        if record.delivered_qty < record.quantity:
            return ValidateDeliveryResult(
                ok=False,
                delivery=record,
                error="DELIVERY_QUANTITY_INCOMPLETE",
            )

        return ValidateDeliveryResult(
            ok=True,
            delivery=record,
        )

    except Exception as exc:
        return ValidateDeliveryResult(
            ok=False,
            error=str(exc),
        )
