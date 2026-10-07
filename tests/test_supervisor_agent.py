from erp_bar.agents.supervisor_agent import decide_next_agent
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.mission import OrderMission


def main():
    mission = OrderMission(
        customer_id=17,
        customer_request="I want 5 units of Product X",
    )
    decision = decide_next_agent(AgentContext(mission=mission))
    print(decision)


if __name__ == "__main__":
    main()
