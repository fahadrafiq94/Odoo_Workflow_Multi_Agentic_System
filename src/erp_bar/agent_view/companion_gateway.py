"""Paired, limited companion API. The dashboard remains loopback-only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import urlsplit
from uuid import uuid4

import time
from .companion_protocol import BUILD, PROTOCOL, EventJournal
from .companion_product import resolve_product

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
            'agent': event.get('agent'), 'phase': event['kind'], 'event_id': event['id'],
            'wait_for_view': event['kind'] == 'tool_end' and action in ('create_purchase_order', 'create_sales_order')}


class RequestRejected(RuntimeError):
    def __init__(self, message, code='not_ready'):
        super().__init__(message)
        self.code = code


class CompanionGateway:
    def __init__(self, session, token, product, ledger_path, product_resolver=None,
                 display_wait_seconds=4, window_wait_seconds=8, smile_source="companion"):
        if len(token) < 32:
            raise ValueError('Pairing token must have at least 32 characters.')
        if not isinstance(product, str) or not product.strip() or len(product) > 120:
            raise ValueError('Choose a valid smile product name.')
        self.session, self.token, self.product = session, token, product.strip()
        if smile_source not in ("dashboard", "companion"):
            raise ValueError("Unknown smile source")
        self.smile_source = smile_source
        self.instance_id = uuid4().hex[:12]
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.ledger = Path(ledger_path)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        self.journal = EventJournal(self.ledger)
        self.product_resolver = product_resolver or resolve_product
        self.product_info = None
        self.product_error = 'Checking the configured Odoo product.'
        self.product_checked = 0.
        self.views = threading.Condition(threading.RLock())
        self.expected_views = set()
        self.ready_views = set()
        self.active_streams = 0
        self.display_wait = max(0., min(10., float(display_wait_seconds)))
        self.window_wait = max(0., min(20., float(window_wait_seconds)))
        self.product_thread = None
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS requests (request_id TEXT PRIMARY KEY, mission_id TEXT, state TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS companion_request_details (request_id TEXT PRIMARY KEY, product TEXT NOT NULL)')
        if not session.live:
            self.product_info = {'product_id': None, 'name': self.product, 'query': self.product, 'quantity': 1, 'simulated': True}
            self.product_error = ''
            self.product_checked = time.monotonic()
        # Session is the one common entry point for both A's button and B's smile.
        session.event_listeners.append(self.on_event)
        session.before_work = self.before_work
        session.after_event = self.after_event

    def connect(self):
        return sqlite3.connect(self.ledger, timeout=10)

    def start(self):
        if self.session.live and not self.product_thread:
            self.product_thread = threading.Thread(target=self.product_loop, daemon=True)
            self.product_thread.start()

    def close(self):
        self.stop.set()
        with self.views:
            self.views.notify_all()
        with self.journal.condition:
            self.journal.condition.notify_all()

    def refresh_product(self):
        try:
            info = self.product_resolver(self.product)
            if not isinstance(info, dict) or type(info.get('product_id')) is not int or info['product_id'] <= 0 or not isinstance(info.get('name'), str) or not info['name'].strip():
                raise ValueError('The product lookup returned no verified product identity.')
            info = {'product_id': info['product_id'], 'name': info['name'], 'query': self.product, 'quantity': 1, 'simulated': False}
            error = ''
        except Exception as exc:
            info = None
            # Tracebacks belong on A's console, not in a customer's reward text.
            error = str(exc) if isinstance(exc, ValueError) else f'Odoo product check failed ({type(exc).__name__}). Check A’s configuration and connection.'
        with self.lock:
            changed = info != self.product_info or error != self.product_error
            self.product_info, self.product_error = info, error
            self.product_checked = time.monotonic()
        if changed or info:
            self.journal.append({'kind': 'product_ready' if info else 'product_error', 'product': info, 'message': error})
        return bool(info)

    def product_loop(self):
        while not self.stop.is_set():
            if not self.session.busy:
                self.refresh_product()
            self.stop.wait(10)

    def on_event(self, event):
        self.journal.append(event)
        mission = event.get('mission_id')
        with self.views:
            if event['kind'] == 'mission_start':
                self.expected_views = {(mission, 0)}
                self.ready_views.clear()
            elif event['kind'] == 'tool_end' and event.get('ok') and event.get('action') in ('create_purchase_order', 'create_sales_order'):
                self.expected_views.add((mission, event['id']))

    def before_work(self, mission_id):
        self.wait_for_view(mission_id, 0, self.window_wait)

    def after_event(self, event):
        if event['kind'] == 'tool_end' and event.get('ok') and event.get('action') in ('create_purchase_order', 'create_sales_order'):
            self.wait_for_view(event['mission_id'], event['id'], self.display_wait)

    def wait_for_view(self, mission_id, event_id, timeout):
        if not self.session.live or timeout <= 0 or not self.active_streams or self.stop.is_set():
            return
        key = (mission_id, event_id)
        with self.views:
            if key in self.ready_views:
                return
        self.session.publish({'kind': 'display_wait', 'view_event_id': event_id,
                              'message': 'Waiting briefly for the customer Odoo view.'})
        end = time.monotonic() + timeout
        with self.views:
            while key not in self.ready_views and not self.stop.is_set():
                remaining = end - time.monotonic()
                if remaining <= 0:
                    break
                self.views.wait(remaining)
            ready = key in self.ready_views
        self.session.publish({'kind': 'display_ready' if ready else 'display_timeout', 'view_event_id': event_id,
            'message': 'Customer view is ready.' if ready else 'Customer view did not become ready in time. Workflow continues; check B.'})

    def acknowledge_view(self, mission_id, event_id):
        if not isinstance(mission_id, str) or type(event_id) is not int:
            raise ValueError('Invalid view acknowledgement.')
        key = (mission_id, event_id)
        with self.views:
            if key not in self.expected_views or mission_id != self.session.mission_id:
                raise ValueError('This view does not belong to the current mission.')
            self.ready_views.add(key)
            self.views.notify_all()

    def request(self, request_id, source="companion"):
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,74}', request_id):
            raise ValueError('A stable request identifier is required.')
        # Always acquire Session before gateway locks, matching event publication.
        with self.session.condition, self.lock:
            with self.connect() as db:
                row = db.execute('SELECT mission_id, state FROM requests WHERE request_id=?', (request_id,)).fetchone()
                if row:
                    if row[1] != 'accepted':
                        raise RuntimeError('Request outcome is uncertain. Staff must check the main system before another attempt.')
                    return row[0]
                if source != self.smile_source:
                    raise RequestRejected("Smile detection is active on Computer A." if self.smile_source == "dashboard" else "Smile detection is active on Computer B.", "wrong_source")
                if self.session.busy:
                    raise RequestRejected('The agents are handling another customer. This request was not queued.', 'busy')
                if not self.product_info or (self.session.live and time.monotonic() - self.product_checked > 60):
                    raise RequestRejected(self.product_error or 'Product information is stale; waiting for a fresh Odoo check.')
                db.execute('INSERT INTO requests VALUES (?, NULL, ?)', (request_id, 'pending'))
                db.execute('INSERT INTO companion_request_details VALUES (?,?)', (request_id, json.dumps(self.product_info)))
            mission_id = self.session.start(self.product, 1, 'smile-' + request_id,
                                            expected_product_id=self.product_info.get('product_id'))
            with self.connect() as db:
                db.execute('UPDATE requests SET mission_id=?, state=? WHERE request_id=?', (mission_id, 'accepted', request_id))
            return mission_id

    def request_state(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,74}', request_id):
            raise ValueError('Invalid request identifier.')
        with self.connect() as db:
            row = db.execute('SELECT r.mission_id,r.state,d.product FROM requests r LEFT JOIN companion_request_details d USING(request_id) WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            return {'request_id': request_id, 'state': 'not_found'}
        mission, status, product = row
        final = self.journal.final(mission) if mission else None
        info = json.loads(product) if product else {'name': self.product, 'query': self.product, 'quantity': 1}
        if final:
            status = 'completed'
        elif status != 'accepted' or mission != self.session.mission_id:
            status = 'uncertain'
        return {'request_id': request_id, 'mission_id': mission, 'state': status,
                'product': info['name'], 'product_info': info, 'quantity': 1, 'final': final}

    def snapshot(self):
        # Reading the stream cursor before Session ensures concurrent events can
        # only be delivered twice, never silently skipped by the checkpoint.
        cursor = self.journal.latest()
        data = self.session.snapshot()
        events = self.journal.mission_events(data['mission_id'])
        # Synthetic diagnostics/tests may publish without a mission ID.
        if not events:
            events = [e for e in data['events'] if e.get('kind') in ('mission_start','mission_end','tool_start','tool_end','instruction','agent_end','handoff')]
        known, targets, product_name = {}, [], None
        for event in events:
            if event.get('kind') == 'tool_end' and event.get('ok') and event.get('action') in ('search_product', 'create_product'):
                name = event.get('result', {}).get('product_name')
                if isinstance(name, str) and name.strip():
                    product_name = name
            target = display_target(event, known)
            if target:
                targets.append(target)
        with self.lock:
            info = dict(self.product_info) if self.product_info else None
            ready = bool(info) and (not self.session.live or time.monotonic() - self.product_checked <= 60)
            product_error = self.product_error
        return {'service': 'ERP_BAR companion gateway', 'build': BUILD, 'protocol': PROTOCOL,
                'instance_id': self.instance_id, 'stream_id': cursor,
                'mode': data['mode'], 'busy': data['busy'], 'mission_id': data['mission_id'],
                'last_id': data['last_id'], 'events': events,
                'odoo_target': targets[-1] if targets else None, 'odoo_targets': targets,
                'smile_product': self.product, 'smile_quantity': 1, 'smile_source': self.smile_source,
                'product_info': info, 'product_ready': ready,
                'readiness_message': product_error if not ready else ('Preparing the current order.' if data['busy'] else 'Ready for a smile.'),
                'accepting_requests': ready and not data['busy'],
                'verified_product_name': product_name or (info['name'] if info else None)}


def make_companion_server(gateway, host='127.0.0.1', port=8766):
    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
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

        def sse(self, kind, data, cursor=None):
            text = ('id: ' + str(cursor) + '\n' if cursor is not None else '')
            text += 'event: ' + kind + '\ndata: ' + json.dumps(data) + '\n\n'
            self.wfile.write(text.encode())
            self.wfile.flush()

        def stream(self):
            try:
                after = int(self.headers.get('Last-Event-ID', '0'))
                if after < 0:
                    raise ValueError()
            except ValueError:
                return self.reply(400, {'error': 'Invalid event cursor.'})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache, no-store')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()
            self.connection.settimeout(5)
            with gateway.views:
                gateway.active_streams += 1
            try:
                # Replay is history only: the following snapshot is authoritative
                # for which mission may open windows or accept a smile now.
                high = gateway.journal.latest()
                if 0 < after <= high:
                    cursor = after
                    while cursor < high:
                        batch = [item for item in gateway.journal.since(cursor) if item['cursor'] <= high]
                        if not batch:
                            break
                        self.sse('replay', {'events': batch})
                        cursor = batch[-1]['cursor']
                state = gateway.snapshot()
                cursor = state['stream_id']
                self.sse('state', state, cursor)
                while not gateway.stop.is_set():
                    with gateway.journal.condition:
                        if gateway.journal.latest() <= cursor:
                            gateway.journal.condition.wait(timeout=1)
                    if gateway.stop.is_set():
                        break
                    if gateway.journal.latest() > cursor:
                        state = gateway.snapshot()
                        cursor = state['stream_id']
                        self.sse('state', state, cursor)
                    else:
                        self.sse('heartbeat', {'instance_id': gateway.instance_id, 'stream_id': cursor})
            except (OSError, ConnectionError):
                pass
            finally:
                with gateway.views:
                    gateway.active_streams -= 1

        def do_GET(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Pairing required.'})
            path = urlsplit(self.path).path
            if path in ('/v1/state', '/v1/handshake'):
                return self.reply(200, gateway.snapshot())
            if path == '/v1/events':
                return self.stream()
            if path.startswith('/v1/requests/'):
                try:
                    return self.reply(200, gateway.request_state(path.rsplit('/', 1)[1]))
                except ValueError as exc:
                    return self.reply(400, {'error': str(exc)})
            return self.reply(404, {'error': 'Not found.'})

        def do_POST(self):
            if not self.authorized():
                return self.reply(403, {'error': 'Pairing required.'})
            if self.path not in ('/v1/smile', '/v1/view-ready'):
                return self.reply(404, {'error': 'Not found.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('Invalid request size.')
                data = json.loads(self.rfile.read(size))
                if self.path == '/v1/view-ready':
                    if not isinstance(data, dict) or set(data) != {'mission_id', 'event_id'}:
                        raise ValueError('Invalid view acknowledgement.')
                    gateway.acknowledge_view(data['mission_id'], data['event_id'])
                    return self.reply(200, {'ok': True})
                if not isinstance(data, dict) or set(data) != {'request_id'}:
                    raise ValueError('Only a request identifier is accepted; product and quantity are fixed on A.')
                gateway.request(data['request_id'])
                self.reply(202, gateway.request_state(data['request_id']))
            except RequestRejected as exc:
                self.reply(409, {'error': str(exc), 'code': exc.code, 'accepted': False})
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc), 'accepted': False})
            except RuntimeError as exc:
                self.reply(409, {'error': str(exc), 'code': 'uncertain'})
            except Exception:
                self.reply(503, {'error': 'Request outcome is uncertain. Retry only with the same request ID.', 'code': 'uncertain'})

        def log_message(self, *_):
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True
        def shutdown(self):
            gateway.close()
            super().shutdown()
    server = Server((host, port), Handler)
    gateway.start()
    return server
