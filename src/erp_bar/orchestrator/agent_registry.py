from erp_bar.domain.decisions import (
    AgentCapability,
    AgentName,
)


CAPABILITY_AGENT_MAP: dict[
    AgentCapability,
    AgentName,
] = {
    AgentCapability.REPORT_PROCUREMENT_FAILURE: AgentName.SALES,
    AgentCapability.INTERPRET_DEMAND: (
        AgentName.SALES
    ),

    AgentCapability.RESOLVE_PRODUCT: (
        AgentName.INVENTORY
    ),

    AgentCapability.CHECK_INVENTORY: (
        AgentName.INVENTORY
    ),

    AgentCapability.VERIFY_STOCK: (
        AgentName.INVENTORY
    ),

    AgentCapability.PROCURE_SHORTAGE: (
        AgentName.PURCHASE
    ),

    AgentCapability.CREATE_SALES_ORDER: (
        AgentName.SALES
    ),

    AgentCapability.FULFILL_DELIVERY: (
        AgentName.INVENTORY
    ),
}


def get_agent_for_capability(
    capability: AgentCapability,
) -> AgentName:
    try:
        return CAPABILITY_AGENT_MAP[
            capability
        ]

    except KeyError as exc:
        raise ValueError(
            "No agent registered for "
            f"capability: {capability}"
        ) from exc
