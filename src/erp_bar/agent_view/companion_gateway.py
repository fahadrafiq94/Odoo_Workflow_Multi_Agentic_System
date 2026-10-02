"""Paired, limited companion API. The dashboard remains loopback-only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit, parse_qs

ACTIONS = {
    'search_product': ('product.product', 'product_id'),
    'create_product': ('product.product', 'product_id'),
    'get_available_stock': ('product.product', 'product_id'),
    'get_product_vendors': ('product.product', 'product_id'),
    'setup_product_vendor': ('product.product', 'product_id'),
    'create_sales_order': ('sale.order', 'sales_order_id'),
    'confirm_sales_order': ('sale.order', 'sales_order_id'),
    'create_purchase_order': ('purchase.order', 'purchase_order_id'),
    'confirm_purchase_order': ('purchase.order', 'purchase_order_id'),
    'receive_purchase': ('purchase.order', 'purchase_order_id'),
    'get_delivery': ('stock.picking', 'picking_id'),
    'check_delivery_availability': ('stock.picking', 'picking_id'),
    'assign_delivery': ('stock.picking', 'picking_id'),
    'validate_delivery': ('stock.picking', 'picking_id'),
}


def display_target(event, known):
    """Map observed tools to record views; never to browser write commands."""
    action = event.get('action')
    if event.get('kind') not in ('tool_start', 'tool_end') or action not in ACTIONS:
        return None
    if event['kind'] == 'tool_end' and not event.get('ok'):
        return None
    model, key = ACTIONS[action]
    values = event.get('result', {}) if event['kind'] == 'tool_end' else event.get('record_ids', {})
    for name in ('product_id', 'sales_order_id', 'purchase_order_id', 'picking_id'):
        value = values.get(name)
        if type(value) is int and value > 0:
            known[name] = value
    # Creation/search starts at the list, even if another record is known.
    record_id = None if event['kind'] == 'tool_start' and action in (
        'search_product', 'create_product', 'create_sales_order', 'create_purchase_order', 'get_delivery'
    ) else known.get(key)
    return {'model': model, 'record_id': record_id, 'action': action,
            'agent': event.get('agent'), 'phase': event['kind'], 'event_id': event['id']}


class CompanionGateway:
    def __init__(self, session, token, product, ledger_path):
        if len(token) < 32:
            raise ValueError('Pairing token must have at least 32 characters.')
        if not product.strip() or len(product) > 120:
            raise ValueError('Choose a valid smile product name.')
        self.session, self.token, self.product = session, token, product.strip()
        self.lock = threading.RLock()
        self.ledger = Path(ledger_path)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, mission_id TEXT, state TEXT NOT NULL)')

    def connect(self):
        return sqlite3.connect(self.ledger, timeout=10)

    def request(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,74}', request_id):
            raise ValueError('A stable request identifier is required.')
        with self.lock, self.session.condition:
            with self.connect() as db:
                row = db.execute('SELECT mission_id, state FROM requests WHERE request_id=?', (request_id,)).fetchone()
                if row:
                    if row[1] != 'accepted':
                        raise RuntimeError('Request outcome is uncertain. Staff must check the main system before another attempt.')
                    return row[0]
                if self.session.busy:
                    raise RuntimeError('The agents are handling another request. Wait for completion.')
                # Commit before starting work: a lost reply or process restart cannot create a second mission.
                db.execute('INSERT INTO requests VALUES (?, NULL, ?)', (request_id, 'pending'))
            mission_id = self.session.start(self.product, 1, 'smile-' + request_id)
            with self.connect() as db:
                db.execute('UPDATE requests SET mission_id=?, state=? WHERE request_id=?', (mission_id, 'accepted', request_id))
            return mission_id

    def snapshot(self):
        data = self.session.snapshot()
        known, target, targets = {}, None, []
        product_name = None
        for event in data['events']:
            if event.get('kind') == 'tool_end' and event.get('ok') and event.get('action') in ('search_product', 'create_product'):
                name = event.get('result', {}).get('product_name')
                if isinstance(name, str) and name.strip():
                    product_name = name
            candidate = display_target(event, known)
            if candidate:
                target = candidate
                targets.append(candidate)
        return {'mode': data['mode'], 'busy': data['busy'], 'mission_id': data['mission_id'],
                'last_id': data['last_id'], 'events': [e for e in data['events'] if e['kind'] in {'mission_start','mission_end','tool_start','tool_end','instruction','agent_end','handoff'}],
                'odoo_target': target, 'odoo_targets': targets,
                'smile_product': self.product, 'smile_quantity': 1,
                'verified_product_name': product_name}


def make_companion_server(gateway, host='127.0.0.1', port=8766):
    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
            # This endpoint is for the paired local Python client, never a browser origin.
            return not self.headers.get('Origin') and secrets.compare_digest(
                self.headers.get('Authorization', ''), 'Bearer ' + gateway.token)

        def reply(self, code, value):
            payload = json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Pairing required.'})
            if self.path != '/v1/state':
                return self.reply(404, {'error': 'Not found.'})
            return self.reply(200, gateway.snapshot())

        def do_POST(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Pairing required.'})
            if self.path != '/v1/smile':
                return self.reply(404, {'error': 'Not found.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict) or set(data) != {'request_id'}:
                    raise ValueError('Only a request identifier is accepted; product and quantity are fixed on the main system.')
                mission_id = gateway.request(data['request_id'])
                self.reply(202, {'mission_id': mission_id, 'product': gateway.product, 'quantity': 1})
            except (ValueError, TypeError):
                self.reply(400, {'error': 'Invalid smile request.'})
            except RuntimeError as exc:
                self.reply(409, {'error': str(exc)})
            except Exception:
                self.reply(503, {'error': 'Request outcome is uncertain. Retry only with the same request ID.'})

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer((host, port), Handler)
