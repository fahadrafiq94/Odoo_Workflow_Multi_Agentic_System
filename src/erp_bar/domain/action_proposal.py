from typing import Any

from pydantic import BaseModel, Field

from erp_bar.domain.decisions import (
    AgentCapability,
    AgentName,
)


class SupervisorProposal(BaseModel):
    """
    Validated internal representation of a
    Supervisor delegation proposal.

    The LLM itself returns simple JSON.
    """

    next_agent: AgentName

    capability: AgentCapability

    objective: str = Field(
        min_length=1,
    )

    reason: str = Field(
        min_length=1,
    )


class SpecialistActionProposal(BaseModel):
    """
    A specialist agent's proposed next action.

    The LLM does NOT directly create this model.

    Flow:

        LLM JSON
            ↓
        Python parsing
            ↓
        SpecialistActionProposal
            ↓
        checkpoint
    """

    action: str = Field(
        min_length=1,
    )

    arguments: dict[str, Any] = Field(
        default_factory=dict,
    )

    reason: str = Field(
        min_length=1,
    )


class CheckpointResult(BaseModel):
    approved: bool

    reason: str = Field(
        min_length=1,
    )