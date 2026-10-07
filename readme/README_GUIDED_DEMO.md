# ERP_BAR guided demo view

Apply over your existing conversation-view version. Stop the dashboard, extract
this archive into your ERP_BAR root and replace the matching files. Keep .env.

Run:

```powershell
uv run python run_agent_view.py --demo
```

Open http://127.0.0.1:8765 and press Ctrl+F5 to refresh the assets.

## Presentation

- The separate supervisor banner is removed. Instructions remain in the chat.
- The left request panel, conversation and four-agent diagram remain.
- Curved routes and travelling markers highlight the latest communication path.
  They show direction, not additional messages or tool calls. Instructions travel
  from Supervisor to a specialist; results return to Supervisor. The display
  does not invent direct specialist-to-specialist conversations.
- Each agent retains its activity state and latest decision summary.
- Guided speed (1x) gives approximately 3 seconds per reading beat, about
  4.6 minutes for the complete simulated scenario. Choose 0.5x for more time,
  2x or 4x for faster playback. Browser/system scheduling can add a little time.
- Pause holds the simulation at its next reading boundary. Resume continues
  the same mission. Speed and pause settings survive browser refresh while the
  local server remains running. They also apply to subsequent demo missions.
- Demo controls affect the shared local demo session in all open dashboard tabs.
- Demo events and ERP IDs remain explicitly simulated; no Odoo/Ollama access.

The layout also works with `--live`. Live execution has no presentation delay
or pause controls. The live business workflow, policies and tools are unchanged.

## Replacement files

- src/erp_bar/agent_view/static/index.html
- src/erp_bar/agent_view/static/style.css
- src/erp_bar/agent_view/static/app.js
- src/erp_bar/agent_view/server.py
- test_agent_view.py

## Validation

29 focused offline tests passed with simulated model replies. These include
pause/resume, valid speeds, replayed settings, authentication, live-mode rejection,
approved-only instructions and failure replies. Desktop (1512x982) and mobile
(390x844) browser checks covered a complete demo, refresh/replay, pause/resume,
speed selection, directional routes, filters, HTML escaping and layout overflow.
No live Odoo/Ollama run was performed.

Run the dashboard checks locally:

```powershell
uv run python test_agent_view.py
uv run python test_conversation_view.py
```
