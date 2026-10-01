from typing import Literal

from pydantic import (
    BaseModel,
    Field,
)


class ProductRecord(BaseModel):
    product_id: int = Field(
        gt=0
    )

    name: str = Field(
        min_length=1
    )

    sku: str | None = None


class SearchProductInput(BaseModel):
    query: str = Field(
        min_length=1
    )


class SearchProductResult(BaseModel):
    ok: bool

    action: Literal[
        "search_product"
    ] = "search_product"

    query: str

    product: ProductRecord | None = None

    error: str | None = None


class CreateProductInput(BaseModel):
    mission_id: str = Field(
        min_length=1
    )

    name: str = Field(
        min_length=1
    )

    sku: str | None = None


class CreateProductResult(BaseModel):
    ok: bool

    action: Literal[
        "create_product"
    ] = "create_product"

    product: ProductRecord | None = None

    created: bool = False

    error: str | None = None


class GetAvailableStockInput(BaseModel):
    product_id: int = Field(
        gt=0
    )


class GetAvailableStockResult(BaseModel):
    ok: bool

    action: Literal[
        "get_available_stock"
    ] = "get_available_stock"

    product_id: int = Field(
        gt=0
    )

    available_qty: float = Field(
        default=0,
        ge=0,
    )

    error: str | None = None