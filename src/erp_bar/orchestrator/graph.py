from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from erp_bar.orchestrator.graph_state import (
    ERPBarGraphState,
)
from erp_bar.domain.decisions import AgentName
from erp_bar.orchestrator.failure_handling import finalize_failed_mission, guard_agent_node
from erp_bar.orchestrator.nodes import (
    inventory_agent_node,
    purchase_agent_node,
    route_after_specialist,
    route_supervisor,
    sales_agent_node,
    supervisor_node,
)


def build_graph():
    builder = StateGraph(
        ERPBarGraphState
    )

    builder.add_node(
        "supervisor",
        guard_agent_node(supervisor_node, AgentName.SUPERVISOR),
    )

    builder.add_node(
        "sales_agent",
        guard_agent_node(sales_agent_node, AgentName.SALES),
    )

    builder.add_node(
        "inventory_agent",
        guard_agent_node(inventory_agent_node, AgentName.INVENTORY),
    )

    builder.add_node(
        "purchase_agent",
        guard_agent_node(purchase_agent_node, AgentName.PURCHASE),
    )

    builder.add_node("sales_failure_response", finalize_failed_mission)
    builder.add_edge("sales_failure_response", END)

    builder.add_edge(
        START,
        "supervisor",
    )

    builder.add_conditional_edges(
        "supervisor",
        route_supervisor,
        {
            "sales_agent": (
                "sales_agent"
            ),

            "inventory_agent": (
                "inventory_agent"
            ),

            "purchase_agent": (
                "purchase_agent"
            ),

            "phase_end": END,
            "sales_failure_response": "sales_failure_response",
        },
    )

    builder.add_conditional_edges(
        "sales_agent",
        route_after_specialist,
        {
            "supervisor": (
                "supervisor"
            ),
            "end": END,
            "sales_failure_response": "sales_failure_response",
        },
    )

    builder.add_conditional_edges(
        "inventory_agent",
        route_after_specialist,
        {
            "supervisor": (
                "supervisor"
            ),
            "end": END,
            "sales_failure_response": "sales_failure_response",
        },
    )

    builder.add_conditional_edges(
        "purchase_agent",
        route_after_specialist,
        {
            "supervisor": (
                "supervisor"
            ),
            "end": END,
            "sales_failure_response": "sales_failure_response",
        },
    )

    return builder.compile()
