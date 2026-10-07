from erp_bar.domain.mission import (
    OrderMission,
)
from erp_bar.orchestrator.graph import (
    build_graph,
)


def main():
    mission = OrderMission(
        customer_id=17,
        customer_request=(
            "I want 5 units of Product X"
        ),
    )

    graph = build_graph()

    result = graph.invoke(
        {
            "mission": mission,
            "supervisor_decision": None,
            "last_agent_decision": None,
        }
    )

    final_mission = (
        result["mission"]
    )

    print()
    print("=" * 60)
    print("FINAL MISSION")
    print("=" * 60)

    print(
        "Mission ID:",
        final_mission.mission_id,
    )

    print(
        "Status:",
        final_mission.status,
    )

    print()
    print("REQUESTED ITEMS")
    print("-" * 60)

    if not (
        final_mission.requested_items
    ):
        print(
            "No requested items."
        )

    for item in (
        final_mission
        .requested_items
    ):
        print(item)

    print()
    print("LAST AGENT DECISION")
    print("-" * 60)

    print(
        result.get(
            "last_agent_decision"
        )
    )

    print()
    print("SUPERVISOR DECISION")
    print("-" * 60)

    print(
        result.get(
            "supervisor_decision"
        )
    )

    print()
    print("DECISION LOG")
    print("-" * 60)

    for decision in (
        final_mission
        .decision_log
    ):
        print(decision)

    print()
    print("ERRORS")
    print("-" * 60)

    print(
        final_mission.errors
    )


if __name__ == "__main__":
    main()