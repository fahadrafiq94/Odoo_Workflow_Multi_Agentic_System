from enum import StrEnum
from typing import Any

from pydantic import (
    BaseModel,
    Field,
)


class AgentName(StrEnum):
    SUPERVISOR = "supervisor"
    SALES = "sales_agent"
    INVENTORY = "inventory_agent"
    PURCHASE = "purchase_agent"


class DecisionType(StrEnum):
    DELEGATE = "DELEGATE"

    DEMAND_PARSED = "DEMAND_PARSED"

    PRODUCT_RESOLVED = "PRODUCT_RESOLVED"

    PRODUCT_CREATION_REQUIRED = (
        "PRODUCT_CREATION_REQUIRED"
    )

    STOCK_READY = "STOCK_READY"

    REQUEST_PROCUREMENT = (
        "REQUEST_PROCUREMENT"
    )

    PROCUREMENT_SUCCEEDED = (
        "PROCUREMENT_SUCCEEDED"
    )

    PROCUREMENT_FAILED = (
        "PROCUREMENT_FAILED"
    )

    CREATE_SALES_ORDER = (
        "CREATE_SALES_ORDER"
    )

    SALES_ORDER_CREATED = (
        "SALES_ORDER_CREATED"
    )

    SALES_ORDER_CONFIRMED = (
        "SALES_ORDER_CONFIRMED"
    )

    START_DELIVERY = "START_DELIVERY"

    DELIVERY_COMPLETED = (
        "DELIVERY_COMPLETED"
    )

    MISSION_COMPLETED = (
        "MISSION_COMPLETED"
    )

    MISSION_FAILED = "MISSION_FAILED"


class AgentCapability(StrEnum):
    REPORT_PROCUREMENT_FAILURE = "REPORT_PROCUREMENT_FAILURE"

    INTERPRET_DEMAND = (
        "INTERPRET_DEMAND"
    )

    RESOLVE_PRODUCT = (
        "RESOLVE_PRODUCT"
    )

    CHECK_INVENTORY = (
        "CHECK_INVENTORY"
    )

    VERIFY_STOCK = (
        "VERIFY_STOCK"
    )

    PROCURE_SHORTAGE = (
        "PROCURE_SHORTAGE"
    )

    CREATE_SALES_ORDER = (
        "CREATE_SALES_ORDER"
    )

    FULFILL_DELIVERY = (
        "FULFILL_DELIVERY"
    )


class AgentHandoff(BaseModel):
    next_agent: AgentName

    capability: AgentCapability

    reason: str = Field(
        min_length=1
    )


class AgentDecision(BaseModel):
    """
    Internal validated agent decision.

    The LLM does not construct this Pydantic model
    directly.

    Python interprets/validates the LLM choice and
    constructs this object.
    """

    agent: AgentName

    decision: DecisionType

    reason: str = Field(
        min_length=1
    )

    facts: dict[str, Any] = Field(
        default_factory=dict
    )

    handoff: AgentHandoff | None = None

    customer_message: str | None = None


class SupervisorDecision(BaseModel):
    """
    Internal validated Supervisor decision.
    """

    decision: DecisionType = (
        DecisionType.DELEGATE
    )

    reason: str = Field(
        min_length=1
    )

    requested_capability: AgentCapability

    customer_message: str | None = None
