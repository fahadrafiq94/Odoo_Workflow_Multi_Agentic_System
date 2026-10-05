"""Enforce the V1 sales price floor inside the Odoo tools, before confirmation."""
from decimal import Decimal, ROUND_CEILING

from erp_bar.domain.policies import DEFAULT_BUSINESS_POLICY


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Pricing requires finite amounts.")
    return result


def price_floor(cost, rounding, markup):
    cost, rounding, markup = map(number, (cost, rounding, markup))
    if cost <= 0 or rounding <= 0 or markup < Decimal("0.40"):
        raise ValueError("Pricing requires positive cost/rounding and at least 40% markup.")
    return (cost * (1 + markup) / rounding).to_integral_value(rounding=ROUND_CEILING) * rounding


def read_one(bridge, model, record_id, fields):
    rows = bridge.execute(model, "read", [record_id], fields=fields)
    if len(rows) != 1 or rows[0]["id"] != record_id:
        raise ValueError(f"Cannot verify pricing record: {model} {record_id}.")
    return rows[0]


def relation(value):
    return int(value[0]) if value else None


def enforce_sales_price(bridge, sales_order_id, *, allow_update):
    """Price the single product line; reuse/confirmation also recheck the floor.

    Cost: this mission's received PO, otherwise the latest received PO for
    this company/product, otherwise Odoo standard_price. No guessed cost.
    V1 supports matching units/currencies and tax-exclusive sales taxes.
    """
    order = read_one(bridge, "sale.order", sales_order_id,
                     ["order_line", "client_order_ref", "state", "currency_id", "company_id", "warehouse_id"])
    if relation(order["warehouse_id"]) != bridge.warehouse_id:
        raise ValueError("Pricing order warehouse differs from configured warehouse.")
    lines = bridge.execute("sale.order.line", "read", order["order_line"],
                           fields=["display_type", "product_id", "product_uom", "product_uom_qty",
                                   "price_unit", "price_subtotal", "discount", "tax_id"])
    lines = [line for line in lines if not line.get("display_type")]
    if len(lines) != 1:
        raise ValueError("V1 pricing requires exactly one product line.")
    line = lines[0]
    quantity = number(line["product_uom_qty"])
    if quantity <= 0:
        raise ValueError("Sales pricing requires positive quantity.")
    company_id, currency_id = relation(order["company_id"]), relation(order["currency_id"])
    company = read_one(bridge, "res.company", company_id, ["currency_id"])
    user = read_one(bridge, "res.users", bridge.uid, ["company_id"])
    if relation(company["currency_id"]) != currency_id or relation(user["company_id"]) != company_id:
        raise ValueError("V1 pricing requires the order, service user and company currency to match.")
    product_id = relation(line["product_id"])
    product = read_one(bridge, "product.product", product_id, ["standard_price", "uom_id"])
    if relation(line["product_uom"]) != relation(product["uom_id"]):
        raise ValueError("V1 pricing requires the product's default sales unit.")
    domain = [["product_id", "=", product_id], ["order_id.company_id", "=", company_id],
              ["order_id.state", "in", ["purchase", "done"]], ["qty_received", ">", 0]]
    fields = ["price_subtotal", "product_qty", "product_uom", "currency_id"]
    mission_ref = order.get("client_order_ref")
    if not mission_ref:
        raise ValueError("Pricing requires the mission reference on the order.")
    purchases = bridge.execute("purchase.order.line", "search_read",
                               domain + [["order_id.origin", "=", mission_ref]], fields=fields, limit=2)
    source = "mission purchase"
    if len(purchases) > 1:
        raise ValueError("Multiple received purchase lines for this mission need review.")
    if not purchases:
        purchases = bridge.execute("purchase.order.line", "search_read", domain,
                                   fields=fields, order="date_order desc, id desc", limit=1)
        source = "latest received purchase"
    if purchases:
        purchase = purchases[0]
        if relation(purchase["currency_id"]) != currency_id or relation(purchase["product_uom"]) != relation(line["product_uom"]):
            raise ValueError("V1 pricing requires matching purchase/sales currencies and units.")
        purchased_qty = number(purchase["product_qty"])
        if purchased_qty <= 0:
            raise ValueError("Purchase cost quantity must be positive.")
        cost = number(purchase["price_subtotal"]) / purchased_qty
    else:
        source, cost = "Odoo product cost", number(product["standard_price"])
    currency = read_one(bridge, "res.currency", currency_id, ["rounding", "name"])
    floor = price_floor(cost, currency["rounding"], DEFAULT_BUSINESS_POLICY.minimum_sales_markup)
    taxes = bridge.execute("account.tax", "read", line["tax_id"], fields=["price_include"]) if line["tax_id"] else []
    if any(tax["price_include"] for tax in taxes):
        raise ValueError("V1 price-floor enforcement requires tax-exclusive sales taxes.")
    net = number(line["price_unit"]) * (1 - number(line["discount"]) / 100)
    # Do not let line-subtotal rounding conceal a discounted price below the floor.
    if net < floor:
        if not allow_update or order["state"] not in {"draft", "sent"}:
            raise ValueError("Sales order is below the required cost-plus-40% price floor.")
        bridge.execute("sale.order.line", "write", [line["id"]], {"price_unit": float(floor), "discount": 0.0})
        line = read_one(bridge, "sale.order.line", line["id"], ["price_unit", "discount", "price_subtotal"])
        net = number(line["price_unit"]) * (1 - number(line["discount"]) / 100)
    if net < floor or number(line["price_subtotal"]) + number(currency["rounding"]) / 2 < floor * quantity:
        raise ValueError("Odoo price readback is below the minimum tax-exclusive selling price.")
    print(f"[sales_pricing] Cost ({source}): {cost}; minimum unit price: {floor}; "
          f"verified net unit price: {net} {currency['name']} (before tax).")
    return float(net)
