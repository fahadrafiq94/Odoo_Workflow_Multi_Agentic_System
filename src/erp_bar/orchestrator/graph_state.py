from typing import TypedDict

from erp_bar.domain.decisions import (
    AgentDecision,
    SupervisorDecision,
)
from erp_bar.domain.mission import (
    OrderMission,
)


class ERPBarGraphState(
    TypedDict,
    total=False,
):
    mission: OrderMission

    supervisor_decision: (
        SupervisorDecision | None
    )

    last_agent_decision: (
        AgentDecision | None
    )