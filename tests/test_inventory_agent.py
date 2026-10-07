from erp_bar.agents.inventory_agent import (
    run_inventory_agent,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
)
from erp_bar.domain.mission import (
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
                requested_qty=5,
            )
        ],
    )

    context = AgentContext(
        mission=mission,
        requested_capability=(
            AgentCapability
            .CHECK_INVENTORY
        ),
    )

    decision = run_inventory_agent(
        context
    )

    print()
    print("=" * 60)
    print("INVENTORY DECISION")
    print("=" * 60)

    print(decision)


if __name__ == "__main__":
    main()