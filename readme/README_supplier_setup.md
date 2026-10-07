# ERP_BAR: controlled supplier creation and product linking

Apply this update on top of the current working project, including the Purchase
context update and procurement-failure response handoff. Extract into ERP_BAR,
keeping the src/erp_bar paths. Only replacement/new files are included.

## Business behavior

Purchase first calls GET_PRODUCT_VENDORS. After a verified NO_VENDOR_FOUND,
it may choose SETUP_PRODUCT_VENDOR with arguments {} when auto_create_vendors
is true and an operator-supplied profile exists for this exact product query.
Python creates or reuses the supplier and adds a supplier relationship for the
verified product variant. The agent then calls GET_PRODUCT_VENDORS again before
selecting the PO supplier and quantity. Setup alone does not authorize a PO.

Existing linked suppliers remain the first choice. Without an approved profile,
the existing procurement-failure -> Sales response path remains available.
No public-web supplier discovery, supplier contact, or real supply confirmation
is added. Receipt validation retains the V1 simulation used by the project.

## 1. Test the new agent decision path first

    uv run python test_supplier_setup.py

This uses configured Ollama with simulated ERP tools. Odoo access is blocked.
The test supplies its own demonstration profile; it needs no new .env setting.
Expect: lookup -> setup -> lookup -> create PO -> confirm -> receive -> success.
The last line starts with SUPPLIER SETUP PASSED.

For a fully offline wiring check:

    uv run python test_supplier_setup.py --mock-model

This is a focused Purchase test. It does not represent a live Odoo write or a
full customer delivery test.

## 2. Configure the real Odoo path

Add the example line from supplier_setup.env.example to your existing .env,
using the intended test product and approved supplier details. Keep all existing
Odoo/Ollama settings. Restart the Python process after changing configuration.

Each product-query entry requires:

- supplier_key: stable identifier (letters, digits, underscore or hyphen), reused
  for the same supplier across products/missions. New partners get an Odoo ref
  of ERP_BAR_SUPPLIER:<supplier_key>.
- name: supplier name.
- email: supplier email used for identity checking; no email is sent.
- unit_price: positive numeric purchase unit price in the configured warehouse
  company's currency. The product's sales and purchase units must match in V1.

The key is the exact requested product name or SKU, ignoring outer whitespace
and case. For example, if the runner prints a SKU as its product query, configure
that SKU. A name-based entry also supports a product created during the mission,
because its variant ID need not be known when the profile is configured.
Different products may share the same supplier_key/name/email with different
unit prices. Conflicting identities are rejected during policy validation.

An empty mapping (the default) enables no new supplier setup. Setting the existing
BusinessPolicy.auto_create_vendors to false blocks this operation even with a
profile. Buffer configuration and customer quantities retain their existing rules.

## 3. Verify with Odoo

Use a separate demonstration product with zero available stock and no supplier
rows, and configure it through your existing ODOO_PRODUCT_TEMPLATE_ID setting.
Do not remove suppliers from a working product just to force this test. Configure
a matching profile, then run:

    uv run python test_real_odoo_graph.py --quantity 5

This is the existing live runner: it creates a new mission and writes real Odoo
records. If enough stock is already available, Purchase is skipped; if a supplier
is already linked, supplier setup is skipped. These are expected behaviors.

Check Odoo Contacts/Purchase vendors for the supplier and the product's Purchase
vendor list for the relationship and configured price. Verify one PO, receipt,
confirmed customer SO and completed delivery as reported by the existing runner.
A repeated mission may need no supplier setup because the link already exists.

The standard live runner preselects an existing product. The generic graph also
supports the missing-product branch; local tests exercise product creation,
supplier setup, purchasing, stock verification, sales and delivery together.

## Duplicate checks and operating limits

Before creation the tool searches all active/archived contacts by supplier ref
or email. It verifies name/email, active status, company and purchase currency.
A matching existing supplier is reused without overwriting its contact fields.
Name-only conflicts, duplicate identity matches, child contacts, archived contacts
and conflicting ERP_BAR refs stop setup for deliberate review.

The link is variant-specific; existing global or exact-variant relationships can
be reused if their company, currency, price and unrestricted quantity/date terms
match. Conflicting or multiple applicable relationships are not overwritten.
Vendor lookup now excludes links belonging only to another product variant.

Supplier profile and product ID are locked on the mission before the write.
After any setup attempt, including a lost response, another supplier lookup is
required. A retry uses the same profile, searches before creating, and is bounded
by max_procurement_attempts. A failed call can leave a supplier or link behind;
it does not roll back earlier writes. Serialization preserves the lock, but this
update does not implement durable storage or restart/resume orchestration.
Search-before-create is not an atomic concurrency guarantee; use the existing
single-process V1 demonstration setup. Multi-company sourcing, currency conversion,
complex purchase units, supplier quotes and supply-capacity checks are not added.

The service user's current company must match the warehouse company. Existing
supplier purchase currency must be unset or match that company's currency.
Odoo permissions still apply; RPC/permission failures become tool failures and
can lead to the existing Sales failure response.

## Verification

147 local regression tests passed with controlled model replies and simulated ERP
behavior. Tests cover actual supplier/link Python logic against an RPC fixture,
reuse and lost responses after either write, profile validation, policy gates,
locked inputs, retry limits, variant filtering, required post-setup lookup and
the complete missing-product-to-delivery graph. The standalone --mock-model
runner also passed. Live Qwen3 1.7B/Odoo behavior still requires the checks above.

Odoo 17 field reference used for the new operation:
[Supplier information model](https://github.com/odoo/odoo/blob/17.0/addons/product/models/product_supplierinfo.py)
and [Purchase partner fields](https://github.com/odoo/odoo/blob/17.0/addons/purchase/models/res_partner.py).

## Included Python files

- src/erp_bar/agents/purchase_agent.py
- src/erp_bar/domain/mission.py
- src/erp_bar/domain/policies.py
- src/erp_bar/odoo/bridge.py
- src/erp_bar/runtime/specialist_checkpoint.py
- src/erp_bar/tools/purchase_schemas.py
- src/erp_bar/tools/purchase_tools.py
- test_procurement_failure.py
- src/erp_bar/domain/supplier_profile.py
- src/erp_bar/odoo/vendor_setup.py
- test_supplier_setup.py
