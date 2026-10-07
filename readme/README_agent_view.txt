ERP_BAR Agent View — installation and use

APPLY TO YOUR EXISTING PROJECT
This update assumes ERP_BAR_final_sales_response_update.zip is already applied,
including the preceding pricing/graph update. Extract into the ERP_BAR root
and merge/replace the included files, keeping all src/erp_bar directories.
Keep your .env. No pyproject.toml changes or frontend build/install are needed.
The ZIP contains only new/replacement files, not the full project.

1. PREVIEW THE INTERFACE WITHOUT ODOO OR OLLAMA
    uv run python run_agent_view.py --demo

Or use regular Python for the standard-library-only demo:
    python run_agent_view.py --demo

The browser opens http://127.0.0.1:8765. Click Run demo mission. The demo is
explicitly labelled SIMULATED and shows the procurement/delivery branch. Its
sample IDs and prices are fixtures, not your Odoo records. No ERP/model calls
are made. The interface does not start a mission simply because it was opened.

2. RUN YOUR ACTUAL AGENTS
Stop the demo server with Ctrl+C, then:
    uv run python run_agent_view.py --live

Use your existing Odoo/Ollama .env configuration. Enter an existing product
name or SKU (e.g. Lemonade), set the customer quantity, and click Start live
mission. Product selection comes from this form; ODOO_PRODUCT_TEMPLATE_ID is
not used by this view. ODOO_WALK_IN_CUSTOMER_ID and ODOO_WAREHOUSE_ID still apply.
The parsed name/quantity and resolved product ID are checked before advancing.

LIVE mode uses the existing Supervisor/Sales/Inventory/Purchase graph and its
Python tools. Starting a mission can create/confirm Odoo orders and validate
receipts/delivery. The V1 receipt simulation remains unchanged. One mission
runs at a time. Closing or refreshing the browser does not cancel it; reopening
the page restores the current session. Starting again after completion creates
a NEW mission. The server does not resume previously interrupted missions.

If the port is occupied:
    uv run python run_agent_view.py --live --port 8766
Use --no-browser if you prefer to open the URL manually.

WHAT THE VIEW SHOWS
- Agent cards: standby, model thinking, proposed action, tool execution,
  returned result, and completed task.
- Supervisor routes: animated, recently observed handoffs, not a fixed linear
  sequence. Sales can run more than once; Inventory also handles delivery.
- Focus panel: click a card to inspect its latest activity; a newly active
  agent is selected automatically. Explicit proposal explanations receive a
  short typewriter animation inspired by your existing smile HUD.
- Live activity: All, Decisions and Tools filters, including rejected proposals;
  Follow/Resume controls; tool results and recorded ERP IDs.
- Mission outcome and the final Sales customer response for handled failures.

Thinking means a model call is in progress. The displayed explanation is the
model's explicit proposal summary after it returns, not hidden reasoning or
live token generation. Proposed actions are not marked as executed; tool-start
signals follow Python checkpoints. Successful tool results are reported as
returned evidence; agent validation and final mission status remain authoritative.

HOW IT CONNECTS
An optional ContextVar event sink receives structured observations from the
existing agent/model/tool functions. It does not choose actions, change prompts,
change policy or retry writes. Agent entry/exit, proposals, rejected proposals,
tool start/result, handoffs and final outcomes are streamed to the browser.
There is no stdout parsing and no monkey-patching of production tool dispatch.
Outside this runner the observer is inactive and the CLI workflow still works.

The local server uses Python's standard library. The interface uses HTML/CSS/JS
with no framework, build step, CDN fonts or external UI assets. Server-sent events
provide updates and reconnect snapshots. The most recent 2,000 events of the
current mission are retained in memory; the feed displays up to 400 entries.
This is a local, single-user development/demo view, bound to 127.0.0.1, not a
hosted production service. Startup-request tokens and a single-job guard prevent
cross-origin starts and overlapping missions. Restarting Python clears the
in-memory display/session and idempotency history; it does not undo ERP records.

Customer-facing messages and selected business result fields reach the UI.
Raw prompts, hidden thinking, raw RPC tracebacks and connection credentials are
not streamed. Detailed internal errors remain in your existing local console.

UNCHANGED BUSINESS SCOPE
Existing products and suppliers only under the last update's default policy;
no new creation is enabled here. The existing purchase buffer, at-least-40%
markup on cost, failure responses, and stop-after-delivery rule remain in place.
No invoice/payment steps or additional agent business capabilities are added.

SMILE AND ODOO WINDOW: NEXT STEP
Your uploaded smile_detector_llm_hud(6).py is untouched. Its background workflow
and event-queue approach informed this view. Webcam detection, smile cooldowns,
the customer display and synchronized Odoo browser navigation are not connected
in this update. The current backend uses Python/XML-RPC, not browser clicking.
This step is the agent screen only, as requested.

CHECKS
    python test_agent_view.py

11 offline tests run without Odoo/Ollama. These check event order, observer
isolation, redaction, labelled demo behavior, request validation, token/origin
checks, duplicate submissions, concurrent-run prevention and stream replay.

180 combined local project/backend regression tests passed. Chromium checks
passed at desktop 1512x982 and mobile 390x844: mission start, busy controls,
refresh/replay, all 14 demo tool calls and 11 handoffs, final outcome, filters,
agent selection, follow toggle, horizontal layout and escaped user input.
There were no browser JavaScript errors in that run. Live Odoo/Qwen3 execution
has not been exercised here and must be checked with your local installation.

PROTOCOL REFERENCES
https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events
https://docs.python.org/3/library/http.server.html
