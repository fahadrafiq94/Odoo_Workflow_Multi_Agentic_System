from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class PrepareFailureResponseInput(BaseModel):
    mission_id: str = Field(min_length=1)
    product_query: str | None = Field(default=None, min_length=1)
    requested_qty: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    failure_code: Literal["NO_VENDOR_FOUND", "PROCUREMENT_FAILED", "PRODUCT_NOT_FOUND",
                          "DEMAND_UNCLEAR", "ORDER_NOT_COMPLETED", "DELIVERY_NOT_VERIFIED"]


class PrepareFailureResponseResult(BaseModel):
    ok: bool
    action: Literal["prepare_failure_response"] = "prepare_failure_response"
    mission_id: str = Field(min_length=1)
    customer_message: str | None = Field(default=None, min_length=1)
    error: str | None = None


class SalesOrderRecord(BaseModel):
    unit_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    net_unit_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)

    sales_order_id: int = Field(
        gt=0
    )

    name: str = Field(
        min_length=1
    )

    mission_id: str = Field(
        min_length=1
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


class CreateSalesOrderInput(BaseModel):
    mission_id: str = Field(
        min_length=1
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


class CreateSalesOrderResult(BaseModel):
    ok: bool

    action: Literal[
        "create_sales_order"
    ] = "create_sales_order"

    sales_order: (
        SalesOrderRecord | None
    ) = None

    created: bool = False

    error: str | None = None


class GetSalesOrderInput(BaseModel):
    sales_order_id: int = Field(
        gt=0
    )


class GetSalesOrderResult(BaseModel):
    ok: bool

    action: Literal[
        "get_sales_order"
    ] = "get_sales_order"

    sales_order: (
        SalesOrderRecord | None
    ) = None

    error: str | None = None


class ConfirmSalesOrderInput(BaseModel):
    sales_order_id: int = Field(
        gt=0
    )


class ConfirmSalesOrderResult(BaseModel):
    ok: bool

    action: Literal[
        "confirm_sales_order"
    ] = "confirm_sales_order"

    sales_order: (
        SalesOrderRecord | None
    ) = None

    error: str | None = None
