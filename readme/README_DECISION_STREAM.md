# Streaming agent decision summaries

Apply this incremental update to your existing ERP_BAR project, including the latest dashboard and second-screen update.

1. Stop the main dashboard after its current mission finishes.
2. Extract this ZIP into the ERP_BAR project root. Merge `src` and replace the included files. Keep your existing `.env`.
3. Restart with your usual command. For a safe visual demo:

   `uv run python run_agent_view.py --demo`

   For your configured real workflow:

   `uv run python run_agent_view.py --live`

   Keep your existing companion flags if using the second computer.
4. Refresh the dashboard. No new dependencies or customer-screen changes are needed.

## What appears

Supervisor, Sales, Inventory and Purchase now stream their brief public decision summary into the selected-agent panel, agent summary card and one growing chat bubble per model call. The next proposal follows, then the existing checkpoint and tool events. Click another agent to inspect its latest summary. The Decisions filter includes streamed explanations.

Live mode reads text chunks from the same Ollama call that produces the existing JSON proposal. The prompt asks for the existing `reason` field first and a short explanation of the relevant verified fact and proposed next step. The original complete reply still goes through existing Python validation. No tool runs from a partial summary, and a stream failure does not trigger an extra model call or retry.

These are model-authored public explanations, not a raw internal thinking transcript. Hidden reasoning fields and `<think>` blocks are excluded. A model may finish internal processing before it begins its public explanation; the dashboard shows a preparing state while waiting. If the model ignores the requested key order, the explanation appears when its reason field arrives. Invalid/non-string reason fields are not streamed.

Demo mode uses explicitly simulated summaries in the same UI. Pause, reading speed, Jump to latest, and chat auto-scroll continue to work. In live mode these controls pace the display; they do not pause Odoo. If the display falls behind, the interface labels the activity as recorded.

## Verification

- 7 offline streaming tests passed: partial JSON/escapes, top-level reason only, excluded hidden reasoning, split-secret redaction, length bounds, one model call, and interrupted requests.
- 13 existing dashboard tests and 19 second-screen tests passed.
- Frontend event-handler checks passed for growing text, one bubble per call, pause, replay, failures, ordering and scroll updates; JavaScript syntax passed.
- Browser visual testing was blocked because the local Chromium process could not launch. Real Ollama generation and Odoo actions were not run here; check the demo first, then your local live setup.

Run the added offline tests with `uv run python test_decision_stream.py`.
