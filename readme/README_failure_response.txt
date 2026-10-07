ERP_BAR - Procurement failure response update

Apply on top of your currently working project, including the latest Sales,
Inventory and Purchase decision-context updates. Extract into ERP_BAR and
replace the included files, preserving the src/erp_bar folder structure.

What changes
Purchase failure now reaches the nonterminal PROCUREMENT_FAILED mission state.
The supervisor chooses Sales / REPORT_PROCUREMENT_FAILURE. Sales invokes a
small deterministic Python response tool, then the mission ends FAILED.
The customer_message is stored on the mission and shown in the console.
This prepares a response for the caller/UI; it does not send email or messages.
The original failure and existing ERP record IDs remain recorded.
No purchase, sales, receipt or delivery records are automatically cancelled.

Test without Odoo changes (uses your configured Ollama):
    uv run python test_procurement_failure.py

Offline wiring check with controlled model replies:
    uv run python test_procurement_failure.py --mock-model

Both commands simulate a verified shortage and NO_VENDOR_FOUND. Odoo access
is blocked in this dedicated test. No real product/customer setup is required.
Expect: supervisor -> purchase_agent -> supervisor -> sales_agent.
The final business status is FAILED, and the last line is FAILURE HANDOFF PASSED.

Verify the existing successful live path separately:
    uv run python test_real_odoo_graph.py --quantity 5
This command still writes real Odoo records and starts a new mission.

Local validation: 133 regression tests passed using controlled model replies
and simulated ERP behavior, including an actual LangGraph failure-handoff run.
Live Ollama behavior for the new delegation still requires your test.

Current step covers procurement failures. Supplier creation/product linking,
durable storage/resumption and activity UI remain separate next steps. This
update does not add those features. Serialization preserves the new failure
fields but is not automatic durable storage. Unexpected supervisor/graph errors
retain the existing exception behavior; a response-tool error ends FAILED with
an internal error instead of claiming a customer response was prepared.

Included files:
  src/erp_bar/agents/sales_agent.py
  src/erp_bar/agents/supervisor_agent.py
  src/erp_bar/domain/decisions.py
  src/erp_bar/domain/mission.py
  src/erp_bar/orchestrator/agent_registry.py
  src/erp_bar/orchestrator/nodes.py
  src/erp_bar/orchestrator/state_machine.py
  src/erp_bar/runtime/supervisor_checkpoint.py
  src/erp_bar/tools/sales_schemas.py
  src/erp_bar/tools/sales_tools.py
  test_real_odoo_graph.py
  test_procurement_failure.py
