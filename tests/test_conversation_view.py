"""Offline conversation event checks: uv run python test_conversation_view.py."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from erp_bar.agents import supervisor_agent as supervisor
from erp_bar.domain.agent_context import AgentContext
from erp_bar.domain.mission import OrderMission
from erp_bar.runtime.events import event_sink, observed_agent


class ConversationEvents(unittest.TestCase):
    def test_only_approved_instruction_is_published_and_secrets_are_removed(self):
        context = AgentContext(mission=OrderMission(customer_id=10, customer_request="One Lemonade"))
        replies = [json.dumps(dict(next_agent=agent, capability=capability,
                                  objective="Handle the request with test-private-token.",
                                  reason="Use the verified mission state."))
                   for agent, capability in [("inventory_agent", "CHECK_INVENTORY"),
                                              ("sales_agent", "INTERPRET_DEMAND")]]
        captured = []
        with patch.object(supervisor, "invoke_llm", side_effect=replies), \
             patch.dict("os.environ", {"TEST_API_KEY":"test-private-token"}), event_sink(captured.append):
            decision = supervisor.decide_next_agent(context)
        instructions = [e for e in captured if e["kind"] == "instruction"]
        self.assertEqual(len(instructions), 1)
        self.assertEqual(instructions[0]["target"], "sales_agent")
        self.assertEqual(instructions[0]["action"], str(decision.requested_capability))
        self.assertTrue(instructions[0]["validated"])
        self.assertNotIn("test-private-token", json.dumps(captured))
        self.assertLess(next(i for i,e in enumerate(captured) if e["kind"] == "checkpoint_rejected"),
                        next(i for i,e in enumerate(captured) if e["kind"] == "instruction"))

    def test_failed_task_returns_failure_decision_not_success_dialogue(self):
        mission = SimpleNamespace(status="PROCUREMENT_FAILED", sales_order_id=None,
                                  purchase_order_ids=[27], delivery_picking_id=None,
                                  customer_message=None, is_terminal=lambda:False)
        decision = SimpleNamespace(decision="PROCUREMENT_FAILED", reason="private error", facts={})
        @observed_agent("purchase_agent")
        def agent(state):
            return {"mission":mission,"last_agent_decision":decision}
        captured=[]
        with event_sink(captured.append):
            agent({})
        reply=next(e for e in captured if e["kind"]=="agent_end")
        self.assertEqual(reply["decision"], "PROCUREMENT_FAILED")
        self.assertIn("could not be completed",reply["message"])
        self.assertEqual(reply["purchase_order_ids"],[27])
        self.assertNotIn("private error",json.dumps(captured))


if __name__ == "__main__":
    unittest.main(verbosity=2)
