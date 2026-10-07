ERP_BAR: final Sales response and existing-product/supplier scope

Apply on top of ERP_BAR_pricing_and_graph_fix.zip. Extract into the existing
ERP_BAR folder, preserving src/erp_bar paths, and replace included files.
Keep your existing .env. Restart Python after applying the update.

CURRENT SCOPE
BusinessPolicy.auto_create_products=False and auto_create_vendors=False.
Inventory can resolve existing products and inspect stock. Purchase can use
existing linked suppliers. Missing products or unavailable procurement lead
to a customer response; creation proposals are rejected by Python checkpoints.
Supplier profiles can remain in .env, but they do not authorize creation while
these flags are false. Existing records are not deleted. Pricing remains at
least 40% markup on verified purchase cost as in the previous update.

FINAL CUSTOMER RESPONSE
Previously only procurement failure had a complete Sales response handoff.
Now inventory, demand parsing, sales-order, delivery and supervisor failures
also receive a final response from Sales. The graph routes failed missions
without a prepared response to sales_failure_response, owned by Sales.

Normal agent planning remains autonomous. Preparing the final message is a
required closing operation using the existing Python response tool. It does
not require another model call or Odoo action, so it also works when Ollama
is unavailable. This operation does not retry ERP writes or cancel records.

Examples:
- Missing product: We could not complete your order for 1 unit of Lemonade.
  The requested product is not available in our product catalog. Please ask
  a staff member to check before trying again. Reference: MISSION-...
- Sales-order failure: We could not complete your order for 1 unit of Lemonade.
  Please ask a staff member to check before trying again. Reference: MISSION-...
- Confirmed order, delivery unverified: Your order for 1 unit of Lemonade was
  confirmed, but we could not verify delivery. Please ask a staff member to
  check before trying again. Reference: MISSION-...
- Ambiguous request: We could not understand your request. Please tell us
  which product you want and how many units.

The response uses the requested customer quantity, never the purchase buffer.
Internal exceptions stay in mission.errors; they are not copied into the
customer message. Unverified/mismatched response-tool output uses a standard
fallback. The message is stored in mission.customer_message and the decision
log. customer_response_prepared prevents duplicate preparation; failure_stage
preserves the last business status. These fields survive serialization, but
this update does not add a durable restart/resume store.

Uncaught agent-node exceptions are recorded and routed to Sales. Graph-level
exceptions, including recursion exhaustion, are handled by the live runner
through finalize_failed_mission. A future frontend runner must call that same
finalizer when its own graph execution raises after a mission has started.
Delivered missions are not relabelled failed by this cleanup. Process crashes
and failures before mission creation are not durable recovery scenarios.

TEST WITHOUT ODOO OR OLLAMA
    uv run python test_order_failure.py

Expected: Ran 10 tests ... OK. The test uses simulated agent outcomes and
controlled model/tool replies, blocks live ERP access, and creates no records.
It covers failures, unavailable model, disabled product creation, preservation
of confirmed/purchased IDs, ambiguous demand, fallback messages, idempotence,
terminal missions and the live runner's graph-recursion-error handler.

LIVE TEST WITH AN EXISTING CONFIGURED PRODUCT
    uv run python test_real_odoo_graph.py --quantity 1

This uses ODOO_PRODUCT_TEMPLATE_ID from your existing .env. It starts a NEW
mission and may write Odoo purchase/sales orders and validate receipt/delivery.
It does not resume previous missions. On failure look for:
    [sales_agent] Customer response: ...
    FINAL MISSION
    Status: FAILED
    Customer response: ...

166 combined local regression tests passed, plus the standalone offline test
entry point. Live Odoo/Ollama has not been accessed from this workspace.

NEXT: TWO FRONTEND VIEWS (NOT IMPLEMENTED IN THIS UPDATE)
1. Agent overview: supervisor, Sales, Inventory and Purchase; active agent;
   routes/handoffs; proposed actions and short decision explanations; Python
   tool start/result; mission outcome. Display observed events and decision
   summaries, not fabricated progress or hidden model reasoning.
2. Smile/customer view: integrate the user's working smile-detection code;
   trigger the one-lemonade customer request; show customer status/final reply;
   synchronize a separate Odoo view with the relevant order or stock record.

ERP actions currently use Python/XML-RPC, not browser clicks. The Odoo window
will be a synchronized view of the relevant records; browser navigation needs
its own small display integration. Implementation waits for the user's working
smile-detection code and layout instructions. No frontend framework, UI,
camera loop, reward-accounting change or external message sending is added.
