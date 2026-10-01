from erp_bar.domain.mission import (
    MissionStatus,
)


ALLOWED_TRANSITIONS: dict[
    MissionStatus,
    set[MissionStatus],
] = {
    MissionStatus.NEW: {
        MissionStatus.PRODUCT_RESOLVED,
        MissionStatus.FAILED,
    },

    MissionStatus.PRODUCT_RESOLVED: {
        MissionStatus.INVENTORY_CHECKED,
        MissionStatus.FAILED,
    },

    MissionStatus.INVENTORY_CHECKED: {
        MissionStatus.STOCK_READY,
        MissionStatus.PROCUREMENT_REQUIRED,
        MissionStatus.FAILED,
    },

    MissionStatus.PROCUREMENT_REQUIRED: {
        MissionStatus.PROCUREMENT_SENT,
        MissionStatus.PROCUREMENT_FAILED,
        MissionStatus.FAILED,
    },

    MissionStatus.PROCUREMENT_SENT: {
        MissionStatus.GOODS_RECEIVED,
        MissionStatus.PROCUREMENT_FAILED,
        MissionStatus.FAILED,
    },

    MissionStatus.GOODS_RECEIVED: {
        MissionStatus.STOCK_READY,
        MissionStatus.PROCUREMENT_REQUIRED,
        MissionStatus.FAILED,
    },

    MissionStatus.PROCUREMENT_FAILED: {
        MissionStatus.FAILED,
    },

    MissionStatus.STOCK_READY: {
        MissionStatus.SALES_ORDER_CREATED,
        MissionStatus.FAILED,
    },

    MissionStatus.SALES_ORDER_CREATED: {
        MissionStatus.SALES_ORDER_CONFIRMED,
        MissionStatus.FAILED,
    },

    MissionStatus.SALES_ORDER_CONFIRMED: {
        MissionStatus.DELIVERY_IN_PROGRESS,
        MissionStatus.FAILED,
    },

    MissionStatus.DELIVERY_IN_PROGRESS: {
        MissionStatus.DELIVERED,
        MissionStatus.FAILED,
    },

    MissionStatus.DELIVERED: set(),

    MissionStatus.FAILED: set(),
}


def can_transition(
    current_status: MissionStatus,
    next_status: MissionStatus,
) -> bool:
    return (
        next_status
        in ALLOWED_TRANSITIONS[
            current_status
        ]
    )


def validate_transition(
    current_status: MissionStatus,
    next_status: MissionStatus,
) -> None:
    if not can_transition(
        current_status,
        next_status,
    ):
        raise ValueError(
            "Invalid mission transition: "
            f"{current_status} -> "
            f"{next_status}"
        )
