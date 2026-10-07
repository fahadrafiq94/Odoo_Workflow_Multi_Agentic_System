# ERP_BAR — Clean Phase 2 Baseline

This archive contains only the code needed through Phase 2 of the ERP_BAR agentic implementation.

## Included

- uv + requirements.txt dependency setup
- Ollama / ChatOllama configuration
- OrderMission and mission state machine
- structured demand schema
- shared agent contracts (AgentDecision, AgentContext, capabilities, handoffs)
- Sales demand interpreter
- Supervisor Agent
- deterministic capability -> specialist registry
- LangGraph entry point proving Supervisor -> Sales routing

## Intentionally not included yet

- mock product/inventory tools from the earlier learning graph
- Inventory Agent implementation (Phase 3)
- Purchase Agent implementation (Phase 4)
- real Odoo XML-RPC tools (later phase; existing user implementations will be integrated)
- realtime UI/event stream
- Smile Detector integration

## Setup

```bash
uv venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\Activate.ps1
uv pip install -r requirements.txt
cp .env.example .env
```

Set `OLLAMA_MODEL` in `.env` to a model installed in Ollama.

## Run Phase 2 graph

Linux/macOS:

```bash
PYTHONPATH=src uv run python test_graph.py
```

PowerShell:

```powershell
$env:PYTHONPATH="src"
uv run python test_graph.py
```

Expected high-level flow:

```text
START
  -> Supervisor
  -> capability: INTERPRET_DEMAND
  -> registry selects Sales Agent
  -> Sales Agent parses customer demand
  -> END (Phase 2 boundary)
```
