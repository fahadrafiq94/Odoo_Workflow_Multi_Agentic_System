"""Deliver one final Sales response when an active mission cannot complete."""
from functools import wraps

from erp_bar.agents.sales_agent import run_order_failure_agent
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.decisions import AgentDecision, AgentName, DecisionType
from erp_bar.domain.mission import MissionStatus
from erp_bar.runtime.events import observed_agent


@observed_agent(AgentName.SALES)
def finalize_failed_mission(state, reason=None):
    mission = state["mission"]
    if mission.status == MissionStatus.DELIVERED:
        return {"mission": mission}
    if reason:
        mission.errors.append(reason)
    if not mission.is_terminal():
        mission.transition_to(MissionStatus.FAILED)
    if mission.customer_response_prepared and mission.customer_message:
        return {"mission": mission}
    mission.current_owner = AgentName.SALES.value
    print(f"[sales_agent] Mission {mission.mission_id}: preparing final customer response")
    decision = run_order_failure_agent(AgentContext(
        mission=mission, requested_agent=AgentName.SALES,
        previous_decision=state.get("last_agent_decision"),
    ))
    mission.customer_message = decision.customer_message
    mission.customer_response_prepared = True
    mission.record_decision(decision)
    print("[sales_agent] Customer response:", mission.customer_message)
    return {"mission": mission, "last_agent_decision": decision}


def guard_agent_node(node, agent):
    """Catch runtime failures without retrying potentially completed ERP writes."""
    @wraps(node)
    def guarded(state):
        mission = state["mission"]
        # An already terminal mission must not execute another ERP/model action.
        if mission.is_terminal():
            return {"mission": mission}
        mission.current_owner = agent.value
        try:
            return node(state)
        except Exception as exc:
            reason = f"{agent.value} stopped: {type(exc).__name__}: {exc}"
            mission.errors.append(reason)
            if not mission.is_terminal():
                mission.transition_to(MissionStatus.FAILED)
            decision = AgentDecision(agent=agent, decision=DecisionType.MISSION_FAILED,
                                     reason=reason, facts={"runtime_failure": True})
            mission.record_decision(decision)
            print(f"[{agent.value}] Execution stopped; final customer response is required.")
            return {"mission": mission, "last_agent_decision": decision}
    return observed_agent(agent)(guarded)
