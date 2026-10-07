from erp_bar.agents.inventory_agent import (
    run_delivery_agent,
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
from erp_bar.tools.mock_odoo import (
    mock_odoo,
)


def main():
    # First create and confirm a mock SO so
    # the mock Odoo backend generates delivery.

    sales_order, _ = (
        mock_odoo.create_sales_order(
            mission_id=(
                "MISSION-DELIVERY-TEST"
            ),
            customer_id=17,
            product_id=43,
            quantity=5,
        )
    )

    mock_odoo.confirm_sales_order(
        sales_order.sales_order_id
    )

    mission = OrderMission(
        mission_id=(
            "MISSION-DELIVERY-TEST"
        ),
        customer_id=17,
        customer_request=(
            "I want 5 units of Product Y"
        ),
        requested_items=[
            RequestedItem(
                product_query="Product Y",
                product_id=43,
                requested_qty=5,
                available_qty=10,
                shortage_qty=0,
            )
        ],
        sales_order_id=(
            sales_order.sales_order_id
        ),
        status=(
            MissionStatus
            .SALES_ORDER_CONFIRMED
        ),
    )

    context = AgentContext(
        mission=mission,
        requested_capability=(
            AgentCapability
            .FULFILL_DELIVERY
        ),
    )

    decision = run_delivery_agent(
        context
    )

    print()
    print("=" * 60)
    print("DELIVERY DECISION")
    print("=" * 60)

    print(decision)

    print()
    print("REMAINING STOCK")
    print("=" * 60)

    print(
        mock_odoo.get_available_stock(
            43
        )
    )


if __name__ == "__main__":
    main()