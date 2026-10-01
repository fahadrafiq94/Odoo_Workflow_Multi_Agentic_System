from typing import Literal

from pydantic import BaseModel, Field
from erp_bar.domain.supplier_profile import SupplierProfile


class SetupProductVendorInput(BaseModel):
    mission_id: str = Field(min_length=1)
    product_id: int = Field(gt=0)
    profile: SupplierProfile


class SetupProductVendorResult(BaseModel):
    ok: bool
    action: Literal["setup_product_vendor"] = "setup_product_vendor"
    mission_id: str = Field(min_length=1)
    product_id: int = Field(gt=0)
    vendor_id: int | None = Field(default=None, gt=0)
    supplierinfo_id: int | None = Field(default=None, gt=0)
    supplier_key: str | None = None
    vendor_created: bool = False
    link_created: bool = False
    error: str | None = None


class VendorRecord(BaseModel):
    vendor_id: int = Field(gt=0)

    name: str = Field(
        min_length=1
    )


class GetProductVendorsInput(BaseModel):
    product_id: int = Field(
        gt=0
    )

    required_qty: float = Field(
        gt=0
    )


class GetProductVendorsResult(BaseModel):
    ok: bool

    action: Literal[
        "get_product_vendors"
    ] = "get_product_vendors"

    product_id: int = Field(
        gt=0
    )

    required_qty: float = Field(
        gt=0
    )

    vendors: list[
        VendorRecord
    ] = Field(
        default_factory=list
    )

    error: str | None = None


class PurchaseOrderRecord(BaseModel):
    purchase_order_id: int = Field(
        gt=0
    )

    name: str = Field(
        min_length=1
    )

    mission_id: str = Field(
        min_length=1
    )

    vendor_id: int = Field(
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

    received_qty: float = Field(
        default=0,
        ge=0,
    )


class CreatePurchaseOrderInput(
    BaseModel
):
    mission_id: str = Field(
        min_length=1
    )

    vendor_id: int = Field(
        gt=0
    )

    product_id: int = Field(
        gt=0
    )

    quantity: float = Field(
        gt=0
    )


class CreatePurchaseOrderResult(
    BaseModel
):
    ok: bool

    action: Literal[
        "create_purchase_order"
    ] = "create_purchase_order"

    purchase_order: (
        PurchaseOrderRecord | None
    ) = None

    created: bool = False

    error: str | None = None


class ConfirmPurchaseOrderInput(
    BaseModel
):
    purchase_order_id: int = Field(
        gt=0
    )


class ConfirmPurchaseOrderResult(
    BaseModel
):
    ok: bool

    action: Literal[
        "confirm_purchase_order"
    ] = "confirm_purchase_order"

    purchase_order: (
        PurchaseOrderRecord | None
    ) = None

    error: str | None = None


class ReceivePurchaseInput(
    BaseModel
):
    purchase_order_id: int = Field(
        gt=0
    )


class ReceivePurchaseResult(
    BaseModel
):
    ok: bool

    action: Literal[
        "receive_purchase"
    ] = "receive_purchase"

    purchase_order: (
        PurchaseOrderRecord | None
    ) = None

    received_qty: float = Field(
        default=0,
        ge=0,
    )

    error: str | None = None
