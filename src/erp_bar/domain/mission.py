from datetime import (
    datetime,
    timezone,
)
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    Field,
)
from erp_bar.domain.supplier_profile import SupplierProfile


class MissionStatus(StrEnum):
    NEW = "NEW"

    PRODUCT_RESOLVED = (
        "PRODUCT_RESOLVED"
    )

    INVENTORY_CHECKED = (
        "INVENTORY_CHECKED"
    )

    STOCK_READY = "STOCK_READY"

    PROCUREMENT_REQUIRED = (
        "PROCUREMENT_REQUIRED"
    )

    PROCUREMENT_SENT = (
        "PROCUREMENT_SENT"
    )

    # Nonterminal: Sales still needs to prepare the customer response.
    PROCUREMENT_FAILED = "PROCUREMENT_FAILED"

    GOODS_RECEIVED = (
        "GOODS_RECEIVED"
    )

    SALES_ORDER_CREATED = (
        "SALES_ORDER_CREATED"
    )

    SALES_ORDER_CONFIRMED = (
        "SALES_ORDER_CONFIRMED"
    )

    DELIVERY_IN_PROGRESS = (
        "DELIVERY_IN_PROGRESS"
    )

    DELIVERED = "DELIVERED"

    FAILED = "FAILED"


class RequestedItem(BaseModel):
    product_query: str = Field(
        min_length=1
    )

    product_id: int | None = None

    requested_qty: float = Field(
        gt=0
    )

    available_qty: float = Field(
        default=0,
        ge=0,
    )

    shortage_qty: float = Field(
        default=0,
        ge=0,
    )

    def calculate_shortage(
        self,
    ) -> float:
        self.shortage_qty = max(
            self.requested_qty
            - self.available_qty,
            0,
        )

        return self.shortage_qty


class OrderMission(BaseModel):
    mission_id: str = Field(
        default_factory=lambda: (
            "MISSION-"
            f"{uuid4().hex[:12].upper()}"
        )
    )

    customer_id: int | None = None

    customer_request: str = Field(
        min_length=1
    )

    requested_items: list[
        RequestedItem
    ] = Field(
        default_factory=list
    )

    status: MissionStatus = (
        MissionStatus.NEW
    )

    supplier_id: int | None = None

    # Preserve setup inputs across uncertain writes and mission serialization.
    supplier_setup_profile: SupplierProfile | None = None
    supplier_setup_product_id: int | None = Field(default=None, gt=0)

    purchase_order_ids: list[int] = Field(
        default_factory=list
    )

    # Locked before the first PO write, including a write with a lost response.
    purchase_quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    sales_order_id: int | None = None

    delivery_picking_id: int | None = None

    procurement_failure_reason: str | None = Field(default=None, min_length=1)
    procurement_failure_code: Literal["NO_VENDOR_FOUND", "PROCUREMENT_FAILED"] | None = None
    customer_message: str | None = Field(default=None, min_length=1)
    customer_response_prepared: bool = False
    failure_stage: MissionStatus | None = None

    current_owner: str | None = None

    retry_count: int = 0

    created_at: datetime = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc)
        )
    )

    updated_at: datetime = Field(
        default_factory=lambda: (
            datetime.now(timezone.utc)
        )
    )

    decision_log: list[
        dict[str, Any]
    ] = Field(
        default_factory=list
    )

    errors: list[str] = Field(
        default_factory=list
    )

    def is_terminal(
        self,
    ) -> bool:
        return self.status in {
            MissionStatus.DELIVERED,
            MissionStatus.FAILED,
        }

    def transition_to(
        self,
        next_status: MissionStatus,
    ) -> None:
        from erp_bar.orchestrator.state_machine import (
            validate_transition,
        )

        validate_transition(
            self.status,
            next_status,
        )

        if next_status == MissionStatus.FAILED and self.failure_stage is None:
            self.failure_stage = self.status
        self.status = next_status

        self.updated_at = datetime.now(
            timezone.utc
        )

    def record_decision(
        self,
        decision,
    ) -> None:
        self.decision_log.append(
            decision.model_dump(
                mode="json"
            )
        )

        self.updated_at = datetime.now(
            timezone.utc
        )
