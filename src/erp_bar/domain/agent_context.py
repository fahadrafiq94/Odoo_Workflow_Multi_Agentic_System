from typing import Any

from pydantic import (
    BaseModel,
    Field,
)

from erp_bar.domain.decisions import (
    AgentCapability,
    AgentDecision,
    AgentName,
)
from erp_bar.domain.mission import (
    OrderMission,
)
from erp_bar.domain.policies import (
    BusinessPolicy,
    DEFAULT_BUSINESS_POLICY,
)


class AgentContext(BaseModel):
    mission: OrderMission

    requested_agent: (
        AgentName | None
    ) = None

    requested_capability: (
        AgentCapability | None
    ) = None

    previous_decision: (
        AgentDecision | None
    ) = None

    verified_facts: dict[
        str,
        Any,
    ] = Field(
        default_factory=dict
    )

    business_policy: BusinessPolicy = Field(
        default_factory=lambda: (
            DEFAULT_BUSINESS_POLICY.model_copy(
                deep=True
            )
        )
    )