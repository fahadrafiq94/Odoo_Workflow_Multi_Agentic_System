# Full Ollama streaming and inventory JSON correction

This update replaces the previous decision-summary-only streaming update. Apply it to the main ERP_BAR computer. The second-computer companion keeps its existing setup.

## Install

1. Let the current mission finish, then stop the dashboard.
2. Extract this ZIP into the ERP_BAR project root. Merge the folders and replace all included files. Keep your existing `.env` and pairing configuration.
3. Restart using your usual command and companion flags. Refresh the browser.

Demo: `uv run python run_agent_view.py --demo`

Live: `uv run python run_agent_view.py --live`

No new dependencies are required beyond the existing project's langchain-ollama package.

## Right chat: the model's full generation

Each model call has one growing chat bubble, with two clearly labelled sections:

- **Model thinking:** text emitted by your local Ollama model in its reasoning channel.
- **Generated response:** the full generated response, including JSON fields, even for calls that do not have a `reason` field.

The next-step title appears only once the complete response parses. Invalid responses remain visible for diagnosis and are marked as needing revision. The old duplicated summary/proposal chat bubbles are removed for streamed calls. Model text is not an executed action; approved tool activity appears separately.

Known environment credentials are redacted before display. The stream uses the same model call that chooses the action. There is no second summarization call and no invented live reasoning. Models that emit no thinking text show only their generated response. Interrupted streams keep their partial text and show a failure state.

Demo mode uses simulated thinking and JSON in the same layout and labels it as simulated. Live mode uses actual model chunks. Reading speed and pause pace the display; live Odoo operations continue. The interface labels recorded activity when the reader is behind. Auto-scroll remains on. Completed model calls retain their full generation for replay without keeping every token event forever.

## Middle diagram: current action

The relevant agent bubble shows a short state/action: choosing the next action, a proposed action, Searching product, Checking stock, Creating purchase order, and so on. A proposal remains labelled PROPOSED until the execution event arrives. The long model stream stays in the right chat.

## Inventory error

`Extra data: line 2 column 1` means the JSON parser found content after a JSON value. The pasted log does not contain the full raw response, so the exact trailing text cannot be identified from it.

This update:

- Removes the previous global instruction to put `reason` first. Each agent retains its original response schema, including Sales demand extraction, which has no `reason` field.
- Uses Ollama's native `format="json"` to constrain the generated answer to JSON.
- Enables separate reasoning with `reasoning=True`, keeping the model's thinking out of the executable JSON string.
- Uses one strict parser for the agents and the dashboard. It handles code fences and external `<think>` wrappers, preserves text inside JSON strings, and rejects duplicate keys, trailing prose, or multiple objects. It never silently chooses one of multiple proposals.
- Retains the existing domain checks and tool-execution checkpoints.

For the project's Qwen3 model, reasoning is enabled by default. If you deliberately switch to a model that does not support thinking, set `OLLAMA_REASONING=auto` or `OLLAMA_REASONING=false` in `.env` and restart. Its generated answer still streams.

If the failure recurs, the right chat now shows the complete **Generated response** that was rejected. Share that response together with the rejection message to diagnose the exact format.

## Verification

Passed locally with controlled model/tool fixtures:

- 161 workflow tests, including two new Inventory regressions.
- 16 streaming/parser tests.
- 13 dashboard tests and 19 second-screen tests.
- Frontend event-handler checks: separate thinking/output, full long responses, one bubble per model call, action labels, pause, refresh after history compaction, replay, failure states, filters and auto-scroll.
- JavaScript syntax check.

Real Ollama and Odoo were not available here. Browser visual testing was blocked by the local Chromium launch failure. Check the demo, then your configured local live workflow.

Run the streaming/parser tests with `uv run python test_decision_stream.py`.
