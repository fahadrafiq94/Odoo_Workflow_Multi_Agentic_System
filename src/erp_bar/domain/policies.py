import json
import os
from math import isfinite

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator
from erp_bar.domain.supplier_profile import SupplierProfile, product_query_key


load_dotenv()


def _purchase_buffers():
    try:
        return json.loads(os.getenv("ERP_BAR_PURCHASE_BUFFER_BY_PRODUCT", "{}"))
    except (ValueError, TypeError) as exc:
        raise ValueError("ERP_BAR_PURCHASE_BUFFER_BY_PRODUCT must be a JSON object mapping product variant IDs to extra quantities.") from exc


def _supplier_profiles():
    try:
        return json.loads(os.getenv("ERP_BAR_SUPPLIER_BY_PRODUCT", "{}"))
    except (ValueError, TypeError) as exc:
        raise ValueError("ERP_BAR_SUPPLIER_BY_PRODUCT must be a JSON object mapping exact product queries to supplier profiles.") from exc


class BusinessPolicy(BaseModel):
    supplier_by_product: dict[str, SupplierProfile] = Field(default_factory=_supplier_profiles, validate_default=True)

    @field_validator("supplier_by_product", mode="before")
    @classmethod
    def validate_suppliers(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Supplier profiles must be an object keyed by exact product name or SKU.")
        result, identities, emails = {}, {}, {}
        for query, raw in value.items():
            if not isinstance(query, str) or not query.strip():
                raise ValueError("Supplier product queries must be nonempty strings.")
            key = product_query_key(query)
            if key in result:
                raise ValueError("Duplicate product query in supplier configuration.")
            profile = SupplierProfile.model_validate(raw)
            identity = (profile.name.casefold(), profile.email)
            if profile.supplier_key in identities and identities[profile.supplier_key] != identity:
                raise ValueError("A supplier_key cannot identify different suppliers.")
            if profile.email in emails and emails[profile.email] != profile.supplier_key:
                raise ValueError("A supplier email cannot use multiple supplier keys.")
            identities[profile.supplier_key] = identity
            emails[profile.email] = profile.supplier_key
            result[key] = profile
        return result

    # Maximum extra units per purchase, keyed by Odoo product.product ID.
    # Missing products retain exact-shortage purchasing.
    purchase_buffer_by_product: dict[int, float] = Field(
        default_factory=_purchase_buffers, validate_default=True,
    )

    @field_validator("purchase_buffer_by_product", mode="before")
    @classmethod
    def validate_purchase_buffers(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Purchase buffers must map product variant IDs to quantities.")
        result = {}
        for key, quantity in value.items():
            if isinstance(key, bool) or not isinstance(key, (str, int)):
                raise ValueError("Purchase buffer product IDs must be positive integers.")
            try:
                product_id = int(key)
            except (TypeError, ValueError) as exc:
                raise ValueError("Purchase buffer product IDs must be positive integers.") from exc
            if product_id <= 0 or str(product_id) != str(key):
                raise ValueError("Purchase buffer product IDs must be positive integers.")
            if isinstance(quantity, bool) or not isinstance(quantity, (int, float)):
                raise ValueError("Purchase buffers must be finite nonnegative numbers.")
            if not isfinite(quantity) or quantity < 0:
                raise ValueError("Purchase buffers must be finite nonnegative numbers.")
            result[product_id] = float(quantity)
        return result

    auto_create_products: bool = False

    auto_create_vendors: bool = False

    allow_partial_fulfillment: bool = False

    allow_backorders: bool = False

    max_procurement_attempts: int = 3

    max_agent_steps_per_mission: int = 30

    # Graph node executions include supervisor visits as well as specialists.
    max_graph_steps: int = Field(default=40, ge=1, le=200)

    # Markup on tax-exclusive purchase cost, not gross profit margin.
    minimum_sales_markup: float = Field(default=0.40, ge=0.40, allow_inf_nan=False)

    require_stock_verification_after_receipt: bool = True

    require_full_quantity_before_sales_confirmation: bool = True

    stop_after_delivery: bool = True


DEFAULT_BUSINESS_POLICY = (
    BusinessPolicy()
)
