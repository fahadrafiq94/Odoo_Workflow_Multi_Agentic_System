from erp_bar.agents.purchase_agent import (
    run_purchase_agent,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
)
from erp_bar.domain.mission import (
    MissionStatus,
    OrderMission,
    RequestedItem,
)


def main():
    mission = OrderMission(
        customer_id=17,
        customer_request=(
            "I want 5 units of Product X"
        ),
        requested_items=[
            RequestedItem(
                product_query=(
                    "Product X"
                ),
                product_id=42,
                requested_qty=5,
                available_qty=2,
                shortage_qty=3,
            )
        ],
        status=(
            MissionStatus
            .PROCUREMENT_REQUIRED
        ),
    )

    context = AgentContext(
        mission=mission,
        requested_capability=(
            AgentCapability
            .PROCURE_SHORTAGE
        ),
    )

    decision = run_purchase_agent(
        context
    )

    print()
    print("=" * 60)
    print("PURCHASE DECISION")
    print("=" * 60)

    print(decision)


if __name__ == "__main__":
    main()