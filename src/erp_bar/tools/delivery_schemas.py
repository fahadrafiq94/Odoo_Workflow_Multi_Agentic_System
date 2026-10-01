from typing import Literal

from pydantic import BaseModel, Field


class DeliveryRecord(BaseModel):
    picking_id: int = Field(
        gt=0
    )

    name: str = Field(
        min_length=1
    )

    sales_order_id: int = Field(
        gt=0
    )

    customer_id: int = Field(
        gt=0
    )

    product_id: int = Field(
        gt=0
    )

    quantity: float = Field(
        gt=0
    )

    state: str = Field(
        min_length=1
    )

    reserved_qty: float = Field(
        default=0,
        ge=0,
    )

    delivered_qty: float = Field(
        default=0,
        ge=0,
    )


class GetDeliveryInput(BaseModel):
    sales_order_id: int = Field(
        gt=0
    )


class GetDeliveryResult(BaseModel):
    ok: bool

    action: Literal[
        "get_delivery"
    ] = "get_delivery"

    delivery: DeliveryRecord | None = None

    error: str | None = None


class CheckDeliveryAvailabilityInput(
    BaseModel
):
    picking_id: int = Field(
        gt=0
    )


class CheckDeliveryAvailabilityResult(
    BaseModel
):
    ok: bool

    action: Literal[
        "check_delivery_availability"
    ] = "check_delivery_availability"

    picking_id: int = Field(
        gt=0
    )

    required_qty: float = Field(
        ge=0
    )

    available_qty: float = Field(
        ge=0
    )

    can_fulfill: bool

    error: str | None = None


class AssignDeliveryInput(BaseModel):
    picking_id: int = Field(
        gt=0
    )


class AssignDeliveryResult(BaseModel):
    ok: bool

    action: Literal[
        "assign_delivery"
    ] = "assign_delivery"

    delivery: DeliveryRecord | None = None

    error: str | None = None


class ValidateDeliveryInput(BaseModel):
    picking_id: int = Field(
        gt=0
    )


class ValidateDeliveryResult(BaseModel):
    ok: bool

    action: Literal[
        "validate_delivery"
    ] = "validate_delivery"

    delivery: DeliveryRecord | None = None

    error: str | None = None