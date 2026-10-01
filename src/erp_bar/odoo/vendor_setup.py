"""Controlled supplier/variant linking for the single-company V1 workflow."""
from math import isclose


def _read_one(bridge, model, record_id, fields):
    rows = bridge.execute(model, "read", [record_id], fields=fields, context={"active_test": False})
    if len(rows) != 1 or rows[0]["id"] != record_id:
        raise ValueError(f"Could not verify {model} record {record_id}.")
    return rows[0]


def _id(value):
    return int(value[0]) if value else None


def _created_id(value):
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if type(value) is not int or value <= 0:
        raise ValueError("Odoo did not return a valid created record ID.")
    return value


def setup_product_vendor(bridge, product_id, profile):
    """Search before each create; retries reuse the configured identity/link.

    There is no cross-RPC transaction or concurrent uniqueness guarantee.
    A failed call may leave a supplier or link behind; the next call reads it.
    """
    product = _read_one(bridge, "product.product", product_id, ["product_tmpl_id", "active", "uom_id", "uom_po_id"])
    if not product["active"] or _id(product["uom_id"]) != _id(product["uom_po_id"]):
        raise ValueError("Supplier setup requires an active product with matching sales and purchase units in V1.")
    template_id = _id(product["product_tmpl_id"])
    warehouse = _read_one(bridge, "stock.warehouse", bridge.warehouse_id, ["company_id"])
    company_id = _id(warehouse["company_id"])
    user = _read_one(bridge, "res.users", bridge.uid, ["company_id"])
    if company_id is None or _id(user["company_id"]) != company_id:
        raise ValueError("Supplier setup requires the warehouse and service user's current company to match.")
    company = _read_one(bridge, "res.company", company_id, ["currency_id"])
    currency_id = _id(company["currency_id"])
    if template_id is None or currency_id is None:
        raise ValueError("Product template or company currency is missing.")

    reference = "ERP_BAR_SUPPLIER:" + profile.supplier_key
    partner_fields = ["name", "email", "ref", "active", "parent_id", "company_id", "property_purchase_currency_id"]
    ids = bridge.execute("res.partner", "search", ["|", ["ref", "=", reference], ["email", "=ilike", profile.email]],
                         limit=3, context={"active_test": False})
    if len(ids) > 1:
        raise ValueError("Supplier identity is ambiguous; resolve duplicate email/reference records in Odoo.")
    vendor_created = False
    if ids:
        vendor_id = ids[0]
    else:
        # A name match with a different/missing email needs deliberate resolution.
        names = bridge.execute("res.partner", "search", [["name", "=ilike", profile.name]],
                               limit=1, context={"active_test": False})
        if names:
            raise ValueError("A supplier name already exists with different identity details; review it before linking.")
        vendor_id = _created_id(bridge.execute("res.partner", "create", [{
            "name": profile.name, "email": profile.email, "ref": reference,
            "is_company": True, "supplier_rank": 1,
        }]))
        vendor_created = True
    partner = _read_one(bridge, "res.partner", vendor_id, partner_fields)
    if (
        not partner["active"] or partner.get("parent_id")
        or str(partner.get("name") or "").strip().casefold() != profile.name.casefold()
        or str(partner.get("email") or "").strip().lower() != profile.email
        or _id(partner.get("company_id")) not in {None, company_id}
        or _id(partner.get("property_purchase_currency_id")) not in {None, currency_id}
        or (str(partner.get("ref") or "").startswith("ERP_BAR_SUPPLIER:") and partner["ref"] != reference)
    ):
        raise ValueError("Supplier identity, active status, company or purchase currency conflicts with configured details.")

    # Accept an existing all-variant or exact-variant relationship, but never
    # silently overwrite conflicting prices or make duplicate relationship rows.
    links = bridge.execute("product.supplierinfo", "search", [
        ["partner_id", "=", vendor_id], ["product_tmpl_id", "=", template_id],
        ["product_id", "in", [False, product_id]], ["company_id", "in", [False, company_id]],
    ], limit=3)
    if len(links) > 1:
        raise ValueError("Multiple supplier relationships apply to this variant; review them in Odoo.")
    link_created = False
    if links:
        link_id = links[0]
    else:
        link_id = _created_id(bridge.execute("product.supplierinfo", "create", [{
            "partner_id": vendor_id, "product_tmpl_id": template_id, "product_id": product_id,
            "company_id": company_id, "currency_id": currency_id,
            "price": profile.unit_price, "min_qty": 0.0,
        }]))
        link_created = True
    link = _read_one(bridge, "product.supplierinfo", link_id, [
        "partner_id", "product_tmpl_id", "product_id", "company_id", "currency_id",
        "price", "min_qty", "date_start", "date_end",
    ])
    if (
        _id(link["partner_id"]) != vendor_id or _id(link["product_tmpl_id"]) != template_id
        or _id(link["product_id"]) not in {None, product_id}
        or _id(link["company_id"]) not in {None, company_id} or _id(link["currency_id"]) != currency_id
        or not isclose(float(link["price"]), profile.unit_price, rel_tol=1e-9, abs_tol=1e-9)
        or float(link["min_qty"]) != 0 or link.get("date_start") or link.get("date_end")
    ):
        raise ValueError("Supplier relationship conflicts with configured product, currency, price or unrestricted quantity/date terms.")
    return dict(vendor_id=vendor_id, supplierinfo_id=link_id, supplier_key=profile.supplier_key,
                vendor_created=vendor_created, link_created=link_created)
