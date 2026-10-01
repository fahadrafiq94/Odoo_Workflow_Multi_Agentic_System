"""Loopback-only customer screen; pairing credentials never reach its browser."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

STATIC = Path(__file__).with_name('static')


def make_server(app, port=8770):
    class Handler(BaseHTTPRequestHandler):
        def local(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def reply(self, code, value, mime='application/json'):
            payload = value if isinstance(value, bytes) else json.dumps(value).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' blob:; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.local():
                return self.reply(403, {'error':'Local screen only.'})
            path = urlsplit(self.path).path
            if path == '/api/state':
                return self.reply(200, app.snapshot())
            if path == '/camera.jpg':
                with app.lock:
                    frame = app.frame
                return self.reply(200, frame, 'image/jpeg') if frame else self.reply(204, b'')
            assets = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css')}
            if path not in assets:
                return self.reply(404, {'error':'Not found.'})
            name, mime = assets[path]
            return self.reply(200, (STATIC/name).read_bytes(), mime + '; charset=utf-8')

        def do_POST(self):
            host = self.headers.get('Host', '')
            if not self.local() or self.headers.get('Origin', 'http://' + host) != 'http://' + host or not secrets.compare_digest(self.headers.get('X-Customer-Token',''), app.token):
                return self.reply(403, {'error':'Reload this local screen.'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024:
                    raise ValueError('Invalid request.')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError('Invalid request.')
                action = data.get('action')
                if action == 'camera_start':
                    app.camera_start()
                elif action == 'camera_stop':
                    app.camera_running = False
                    app.gate.disarm()
                    app.camera_status = 'Camera off'
                elif action == 'start_mission':
                    app.request_one('button')
                elif action == 'arm':
                    app.arm()
                elif action == 'retry':
                    app.send_pending()
                elif action == 'odoo_open':
                    if app.remote.get('mode') != 'live':
                        raise ValueError('Demo uses simulated ERP records. Odoo navigation is available in live mode.')
                    app.open_split()
                elif action == 'odoo_follow':
                    if app.remote.get('mode') != 'live':
                        raise ValueError('Odoo following requires live mode.')
                    app.odoo.follow(not app.odoo.following)
                elif action == 'simulate_smile' and app.demo_camera and app.remote.get('mode') == 'demo':
                    now = time.monotonic()
                    for i in range(5):
                        app.score(.05, now + i*.05)
                    for i in range(25):
                        app.score(.98, now + .3 + i*.08)
                else:
                    raise ValueError('Unknown or unavailable action.')
                return self.reply(200, {'ok':True})
            except (ValueError, TypeError, RuntimeError) as exc:
                return self.reply(400, {'error':str(exc)})
            except Exception:
                return self.reply(500, {'error':'This action could not be completed. Check the local console.'})

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    app.screen_url = f'http://127.0.0.1:{server.server_port}'
    return server
