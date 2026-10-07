"""Test Sales demand interpretation through Ollama; no Odoo records are changed.

Place this file in the ERP_BAR project root and run:
    uv run python test_sales_agent.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from erp_bar.agents.sales_agent import run_sales_agent
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.decisions import AgentCapability, DecisionType
from erp_bar.domain.mission import OrderMission


def main() -> int:
    requests = [
        ("I want 5 units of Product X", False),
        ("I want some Product X", True),
        ("I need 5 of the blue one", True),
    ]
    passed_count = 0

    for request, expect_ambiguity in requests:
        mission = OrderMission(customer_request=request)
        context = AgentContext(
            mission=mission,
            requested_capability=AgentCapability.INTERPRET_DEMAND,
        )
        decision = run_sales_agent(context)

        if expect_ambiguity:
            passed = (
                decision.decision == DecisionType.MISSION_FAILED
                and decision.facts.get("is_ambiguous") is True
            )
        else:
            passed = (
                decision.decision == DecisionType.DEMAND_PARSED
                and decision.facts.get("requested_qty") == 5
                and str(decision.facts.get("product_query", "")).strip().casefold() == "product x"
                and decision.facts.get("is_ambiguous") is False
            )

        print(f"\nRequest: {request}")
        print(decision.model_dump_json(indent=2))
        print("Result:", "PASS" if passed else "FAIL")
        passed_count += int(passed)

    print(f"\nSales demand checks passed: {passed_count}/{len(requests)}")
    print("This test checks demand interpretation only, not sales-order creation or confirmation.")
    return 0 if passed_count == len(requests) else 1


if __name__ == "__main__":
    raise SystemExit(main())