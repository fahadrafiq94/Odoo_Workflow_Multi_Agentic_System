"""Read the configured smile product by its Odoo template ID, never by a name search."""
import os


def _positive_id(name, required=True):
    raw = os.environ.get(name, '').strip()
    if not raw and not required:
        return None
    if not raw.isascii() or not raw.isdecimal() or int(raw) <= 0:
        raise ValueError(f'Set {name} in .env to a positive Odoo database ID, then restart Computer A.')
    return int(raw)


def resolve_product(_legacy_query=None):
    template_id = _positive_id('ODOO_PRODUCT_TEMPLATE_ID')
    variant_id = _positive_id('ODOO_PRODUCT_VARIANT_ID', required=False)
    from erp_bar.odoo.bridge import OdooBridge
    bridge = OdooBridge(rpc_timeout=4)
    bridge.validate_runtime_configuration()
    domain = [['product_tmpl_id', '=', template_id], ['active', '=', True]]
    if variant_id is not None:
        domain.append(['id', '=', variant_id])
    ids = bridge.execute('product.product', 'search', domain, limit=2)
    if not ids:
        raise ValueError(f'No active accessible product variant for ODOO_PRODUCT_TEMPLATE_ID={template_id}'
                         + (f' and ODOO_PRODUCT_VARIANT_ID={variant_id}' if variant_id else '')
                         + '. Check these IDs in the configured ODOO_DB, then restart Computer A.')
    if len(ids) != 1:
        raise ValueError(f'Product template {template_id} has multiple variants. Set ODOO_PRODUCT_VARIANT_ID in .env to the intended variant ID, then restart Computer A.')
    rows = bridge.execute('product.product', 'read', ids, fields=['name', 'product_tmpl_id', 'active'])
    if (not rows or rows[0].get('id') != ids[0] or not rows[0].get('active')
            or not rows[0].get('product_tmpl_id') or rows[0]['product_tmpl_id'][0] != template_id):
        raise ValueError('The configured smile product is no longer available. Check the product IDs in .env.')
    name = rows[0].get('name')
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        raise ValueError('The configured Odoo product needs a name between 1 and 120 characters.')
    return {'product_id': int(ids[0]), 'product_template_id': template_id,
            'name': name, 'query': name.strip(), 'quantity': 1}
