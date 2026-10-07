# ERP_BAR conversation view update

Apply this over the previously installed agent-view version of ERP_BAR.
This archive contains only the replacement files and a new offline test.

## Install

1. Stop the running dashboard with Ctrl+C.
2. Extract this ZIP into your existing ERP_BAR folder. Merge `src` and replace
   the matching files; do not create an extra ERP_BAR subfolder.
3. Start the preview from your project folder:

   ```powershell
   uv run python run_agent_view.py --demo
   ```

4. Open http://127.0.0.1:8765 and hard-refresh with Ctrl+F5.
5. To connect the existing workflow to Odoo and Ollama, restart with:

   ```powershell
   uv run python run_agent_view.py --live
   ```

The live mode uses your existing configuration and creates real Odoo orders,
receipts, and deliveries when you start a mission. Demo mode is simulated.
There are no new dependencies.

## What changed

- The supervisor's approved instruction, assigned agent, and reason appear above
  the team. The last instruction remains visible when a mission finishes.
- The conversation distinguishes instructions, model decision summaries,
  tool execution, tool results, and specialist replies.
- A typing indicator appears while a model call is in progress. Decision
  summaries appear when the model returns. These are explicit structured
  explanations, not a stream of the model's private internal reasoning.
- All four agents have a latest-summary card. Click an agent to inspect its
  current activity. Active cards and route animations follow workflow events.
- Failed tasks show a failure reply instead of a completion claim.
- Follow/Resume, filters, reconnect/replay, and responsive layouts remain available.

Live instructions are emitted only after supervisor checkpoint approval.
Actual tool results and specialist decisions supply the conversation; the UI
adds labels but does not call a model to invent dialogue or choose ERP actions.
Long summaries retain the existing event text limit (600 characters).

## Files

Replace:
- src/erp_bar/agent_view/static/index.html
- src/erp_bar/agent_view/static/style.css
- src/erp_bar/agent_view/static/app.js
- src/erp_bar/agent_view/server.py
- src/erp_bar/runtime/events.py
- src/erp_bar/agents/supervisor_agent.py
- test_agent_view.py

Add:
- test_conversation_view.py

## Checks

```powershell
uv run python test_agent_view.py
uv run python test_conversation_view.py
```

Validation during development: 27 focused offline tests passed, covering the
supervisor context, dashboard events/server, approved-only instructions, and
failure replies. Browser checks covered a complete simulated mission,
refresh/replay, thinking indicators, six instruction/reply pairs, filters,
failure presentation, HTML escaping, and desktop/mobile layouts.
Live Odoo/Ollama execution was not available in the development environment.

This patch changes presentation and event observation. Business policies,
agent decision prompts, tool execution, and pricing rules remain as before.
Smile detection and the Odoo window display remain later integration steps.
