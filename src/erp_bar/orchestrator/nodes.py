from erp_bar.agents.inventory_agent import (
    run_inventory_agent,
)
from erp_bar.agents.purchase_agent import (
    run_purchase_agent,
)
from erp_bar.agents.sales_agent import (
    run_sales_agent,
)
from erp_bar.agents.supervisor_agent import (
    decide_next_agent,
)
from erp_bar.domain.agent_context import (
    AgentContext,
)
from erp_bar.domain.decisions import (
    AgentCapability,
    DecisionType,
)
from erp_bar.domain.mission import (
    MissionStatus,
    RequestedItem,
)
from erp_bar.orchestrator.agent_registry import (
    get_agent_for_capability,
)
from erp_bar.orchestrator.graph_state import (
    ERPBarGraphState,
)


PHASE_6_IMPLEMENTED_CAPABILITIES = {
    AgentCapability.REPORT_PROCUREMENT_FAILURE,
    AgentCapability.INTERPRET_DEMAND,
    AgentCapability.RESOLVE_PRODUCT,
    AgentCapability.CHECK_INVENTORY,
    AgentCapability.VERIFY_STOCK,
    AgentCapability.PROCURE_SHORTAGE,
    AgentCapability.CREATE_SALES_ORDER,
    AgentCapability.FULFILL_DELIVERY,
}


# ==========================================================
# SUPERVISOR
# ==========================================================


def supervisor_node(
    state: ERPBarGraphState,
) -> dict:
    mission = state["mission"]

    print(
        "\n[supervisor] Mission",
        mission.mission_id,
    )

    context = AgentContext(
        mission=mission,
        previous_decision=state.get(
            "last_agent_decision"
        ),
    )

    decision = decide_next_agent(
        context
    )

    selected_agent = (
        get_agent_for_capability(
            decision.requested_capability
        )
    )

    print(
        "[supervisor] Capability:",
        decision.requested_capability,
    )

    print(
        "[supervisor] Selected agent:",
        selected_agent,
    )

    mission.record_decision(
        decision
    )

    return {
        "mission": mission,
        "supervisor_decision": decision,
    }


# ==========================================================
# SALES
# ==========================================================


def sales_agent_node(
    state: ERPBarGraphState,
) -> dict:
    mission = state["mission"]

    supervisor_decision = (
        state[
            "supervisor_decision"
        ]
    )

    capability = (
        supervisor_decision
        .requested_capability
    )

    print(
        "\n[sales_agent] Mission",
        mission.mission_id,
    )

    print(
        "[sales_agent] Capability:",
        capability,
    )

    context = AgentContext(
        mission=mission,
        requested_capability=capability,
        previous_decision=state.get(
            "last_agent_decision"
        ),
    )

    decision = run_sales_agent(
        context
    )

    if decision.customer_message and decision.facts.get("failure_response_prepared") is True:
        mission.customer_message = decision.customer_message
        mission.customer_response_prepared = True
        print("[sales_agent] Customer response:", mission.customer_message)

    mission.record_decision(
        decision
    )

    if (
        decision.decision
        == DecisionType.MISSION_FAILED
    ):
        mission.errors.append(
            decision.reason
        )

        if not mission.is_terminal():
            mission.transition_to(
                MissionStatus.FAILED
            )

        print(
            "[sales_agent] Failed:",
            decision.reason,
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    if (
        decision.decision
        == DecisionType.DEMAND_PARSED
    ):
        mission.requested_items = [
            RequestedItem(
                product_query=(
                    decision.facts[
                        "product_query"
                    ]
                ),
                requested_qty=(
                    decision.facts[
                        "requested_qty"
                    ]
                ),
            )
        ]

        print(
            "[sales_agent] Parsed:",
            decision.facts[
                "requested_qty"
            ],
            "x",
            decision.facts[
                "product_query"
            ],
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    if (
        decision.decision
        == DecisionType
        .SALES_ORDER_CONFIRMED
    ):
        sales_order_id = (
            decision.facts.get(
                "sales_order_id"
            )
        )

        if sales_order_id is None:
            mission.errors.append(
                "Sales order confirmation "
                "did not return an order ID."
            )

            mission.transition_to(
                MissionStatus.FAILED
            )

            return {
                "mission": mission,
                "last_agent_decision": decision,
            }

        mission.sales_order_id = int(
            sales_order_id
        )

        if (
            mission.status
            == MissionStatus.STOCK_READY
        ):
            mission.transition_to(
                MissionStatus
                .SALES_ORDER_CREATED
            )

        if (
            mission.status
            == MissionStatus
            .SALES_ORDER_CREATED
        ):
            mission.transition_to(
                MissionStatus
                .SALES_ORDER_CONFIRMED
            )

        print(
            "[sales_agent] Sales order:",
            mission.sales_order_id,
        )

        print(
            "[sales_agent] Decision:",
            decision.decision,
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    mission.errors.append(
        "Unexpected Sales Agent decision: "
        f"{decision.decision}"
    )

    if not mission.is_terminal():
        mission.transition_to(
            MissionStatus.FAILED
        )

    return {
        "mission": mission,
        "last_agent_decision": decision,
    }


# ==========================================================
# INVENTORY / DELIVERY
# ==========================================================


def inventory_agent_node(
    state: ERPBarGraphState,
) -> dict:
    mission = state["mission"]

    supervisor_decision = (
        state[
            "supervisor_decision"
        ]
    )

    capability = (
        supervisor_decision
        .requested_capability
    )

    print(
        "\n[inventory_agent] Mission",
        mission.mission_id,
    )

    print(
        "[inventory_agent] Capability:",
        capability,
    )

    context = AgentContext(
        mission=mission,
        requested_capability=capability,
        previous_decision=state.get(
            "last_agent_decision"
        ),
    )

    decision = run_inventory_agent(
        context
    )

    mission.record_decision(
        decision
    )

    # ==================================================
    # FAILURE
    # ==================================================

    if (
        decision.decision
        == DecisionType.MISSION_FAILED
    ):
        mission.errors.append(
            decision.reason
        )

        if not mission.is_terminal():
            mission.transition_to(
                MissionStatus.FAILED
            )

        print(
            "[inventory_agent] Failed:",
            decision.reason,
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    # ==================================================
    # DELIVERY COMPLETED
    # ==================================================

    if (
        decision.decision
        == DecisionType
        .DELIVERY_COMPLETED
    ):
        picking_id = (
            decision.facts.get(
                "picking_id"
            )
        )

        if picking_id is None:
            mission.errors.append(
                "Delivery completed without "
                "verified picking_id."
            )

            mission.transition_to(
                MissionStatus.FAILED
            )

            return {
                "mission": mission,
                "last_agent_decision": decision,
            }

        mission.delivery_picking_id = int(
            picking_id
        )

        if (
            mission.status
            == MissionStatus
            .SALES_ORDER_CONFIRMED
        ):
            mission.transition_to(
                MissionStatus
                .DELIVERY_IN_PROGRESS
            )

        if (
            mission.status
            == MissionStatus
            .DELIVERY_IN_PROGRESS
        ):
            mission.transition_to(
                MissionStatus.DELIVERED
            )

        print(
            "[inventory_agent] Delivery:",
            mission.delivery_picking_id,
        )

        print(
            "[inventory_agent] Decision:",
            decision.decision,
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    # ==================================================
    # INVENTORY RESULT
    # ==================================================

    if not mission.requested_items:
        mission.errors.append(
            "Inventory result received without "
            "requested item."
        )

        mission.transition_to(
            MissionStatus.FAILED
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    item = (
        mission.requested_items[0]
    )

    product_id = (
        decision.facts.get(
            "product_id"
        )
    )

    available_qty = (
        decision.facts.get(
            "available_qty"
        )
    )

    shortage_qty = (
        decision.facts.get(
            "shortage_qty"
        )
    )

    if product_id is not None:
        item.product_id = int(
            product_id
        )

        if (
            mission.status
            == MissionStatus.NEW
        ):
            mission.transition_to(
                MissionStatus
                .PRODUCT_RESOLVED
            )

    if available_qty is not None:
        item.available_qty = float(
            available_qty
        )

        item.shortage_qty = float(
            shortage_qty or 0
        )

        if (
            mission.status
            == MissionStatus
            .PRODUCT_RESOLVED
        ):
            mission.transition_to(
                MissionStatus
                .INVENTORY_CHECKED
            )

    if (
        decision.decision
        == DecisionType.STOCK_READY
    ):
        if (
            mission.status
            == MissionStatus
            .INVENTORY_CHECKED
        ):
            mission.transition_to(
                MissionStatus.STOCK_READY
            )

        elif (
            mission.status
            == MissionStatus
            .GOODS_RECEIVED
        ):
            mission.transition_to(
                MissionStatus.STOCK_READY
            )

    elif (
        decision.decision
        == DecisionType
        .REQUEST_PROCUREMENT
    ):
        # A repeated shortage result updates the facts above but does not
        # represent a new state transition. Keep other transitions validated.
        if mission.status != MissionStatus.PROCUREMENT_REQUIRED:
            mission.transition_to(
                MissionStatus.PROCUREMENT_REQUIRED
            )

    print(
        "[inventory_agent] Decision:",
        decision.decision,
    )

    print(
        "[inventory_agent] Facts:",
        decision.facts,
    )

    return {
        "mission": mission,
        "last_agent_decision": decision,
    }


# ==========================================================
# PURCHASE
# ==========================================================


def purchase_agent_node(
    state: ERPBarGraphState,
) -> dict:
    mission = state["mission"]

    supervisor_decision = (
        state[
            "supervisor_decision"
        ]
    )

    print(
        "\n[purchase_agent] Mission",
        mission.mission_id,
    )

    context = AgentContext(
        mission=mission,
        requested_capability=(
            supervisor_decision
            .requested_capability
        ),
        previous_decision=state.get(
            "last_agent_decision"
        ),
    )

    decision = run_purchase_agent(
        context
    )

    mission.record_decision(
        decision
    )

    if (
        decision.decision
        == DecisionType
        .PROCUREMENT_FAILED
    ):
        mission.errors.append(
            decision.reason
        )

        if mission.status in {MissionStatus.PROCUREMENT_REQUIRED, MissionStatus.PROCUREMENT_SENT} and len(mission.requested_items) == 1:
            mission.procurement_failure_reason = decision.reason
            mission.procurement_failure_code = (
                "NO_VENDOR_FOUND"
                if decision.facts.get("vendors") == [] and decision.facts.get("last_error") == "NO_VENDOR_FOUND"
                else "PROCUREMENT_FAILED"
            )
            mission.transition_to(MissionStatus.PROCUREMENT_FAILED)
        elif not mission.is_terminal():
            mission.transition_to(
                MissionStatus.FAILED
            )

        print(
            "[purchase_agent] Failed:",
            decision.reason,
        )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    if (
        decision.decision
        != DecisionType
        .PROCUREMENT_SUCCEEDED
    ):
        mission.errors.append(
            "Unexpected Purchase Agent "
            f"decision: {decision.decision}"
        )

        if not mission.is_terminal():
            mission.transition_to(
                MissionStatus.FAILED
            )

        return {
            "mission": mission,
            "last_agent_decision": decision,
        }

    vendor_id = (
        decision.facts.get(
            "vendor_id"
        )
    )

    purchase_order_id = (
        decision.facts.get(
            "purchase_order_id"
        )
    )

    if vendor_id is not None:
        mission.supplier_id = int(
            vendor_id
        )

    if (
        purchase_order_id is not None
        and int(purchase_order_id)
        not in mission.purchase_order_ids
    ):
        mission.purchase_order_ids.append(
            int(purchase_order_id)
        )

    if (
        mission.status
        == MissionStatus
        .PROCUREMENT_REQUIRED
    ):
        mission.transition_to(
            MissionStatus
            .PROCUREMENT_SENT
        )

    if (
        mission.status
        == MissionStatus
        .PROCUREMENT_SENT
    ):
        mission.transition_to(
            MissionStatus
            .GOODS_RECEIVED
        )

    print(
        "[purchase_agent] Decision:",
        decision.decision,
    )

    print(
        "[purchase_agent] Facts:",
        decision.facts,
    )

    return {
        "mission": mission,
        "last_agent_decision": decision,
    }


# ==========================================================
# ROUTING
# ==========================================================


def route_supervisor(
    state: ERPBarGraphState,
) -> str:
    mission = state["mission"]
    if mission.status == MissionStatus.FAILED:
        return "phase_end" if mission.customer_response_prepared else "sales_failure_response"
    if mission.status == MissionStatus.DELIVERED:
        return "phase_end"
    decision = (
        state[
            "supervisor_decision"
        ]
    )

    capability = (
        decision
        .requested_capability
    )

    if (
        capability
        not in PHASE_6_IMPLEMENTED_CAPABILITIES
    ):
        return "phase_end"

    agent = (
        get_agent_for_capability(
            capability
        )
    )

    return agent.value


def route_after_specialist(
    state: ERPBarGraphState,
) -> str:
    mission = state["mission"]

    if mission.status == MissionStatus.FAILED and not mission.customer_response_prepared:
        return "sales_failure_response"
    if mission.is_terminal():
        return "end"

    return "supervisor"
