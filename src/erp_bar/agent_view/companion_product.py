"""Read-only product handshake using its own bounded XML-RPC connection."""

def resolve_product(query):
    from erp_bar.odoo.bridge import OdooBridge
    bridge = OdooBridge(rpc_timeout=4)
    bridge.validate_runtime_configuration()
    # Match the live runner's exact identity rule. Reject ambiguous products.
    ids = bridge.execute('product.product', 'search', [
        '|', '|', ['default_code', '=', query], ['barcode', '=', query], ['name', '=ilike', query]
    ], limit=2)
    if len(ids) != 1:
        raise ValueError('Configure a unique existing product name, SKU or barcode for --smile-product.')
    rows = bridge.execute('product.product', 'read', ids, fields=['name', 'default_code', 'barcode'])
    if not rows or not any(isinstance(rows[0].get(k), str) and rows[0][k].strip().casefold() == query.strip().casefold()
                           for k in ('name', 'default_code', 'barcode')):
        raise ValueError('Configured smile product is not an exact Odoo match.')
    return {'product_id': int(rows[0]['id']), 'name': rows[0]['name'], 'query': query, 'quantity': 1}
