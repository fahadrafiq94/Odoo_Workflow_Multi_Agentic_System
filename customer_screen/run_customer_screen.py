"""Run this on the second computer, alongside its webcam and Odoo window."""
import argparse
import json
from pathlib import Path
from erp_bar_customer.app import CustomerApp
from erp_bar_customer.server import make_server
from erp_bar_customer.diagnostics import BUILD


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairing', default='companion_pairing.json')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--no-camera', action='store_true', help='Start the diagnostic screen without accessing the webcam')
    parser.add_argument('--demo-camera', action='store_true', help='Simulate smile input with a button; works only with a demo main system')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Choose a port between 1 and 65535.')
    pairing = Path(args.pairing).resolve()
    if not pairing.is_file():
        parser.error('Copy companion_pairing.json from the main ERP_BAR computer first.')
    app = CustomerApp(json.loads(pairing.read_text(encoding='utf-8-sig')), Path(__file__).resolve().parent / 'customer_state', demo_camera=args.demo_camera)
    server = make_server(app, args.port)
    app.start(auto_camera=not args.no_camera)
    url = f'http://127.0.0.1:{args.port}'
    print(f'ERP_BAR customer screen: {url}')
    print(f'Build {BUILD} · pairing: {pairing}')
    print(f'Main system: {app.brain.url} · Odoo: {app.config.get("odoo_url") or "NOT CONFIGURED"}')
    print('Camera starts automatically. Wait for Ready, then hold a smile at 75% or above. One customer at a time; relax after completion to welcome the next customer.')
    if not args.no_browser:
        app.odoo.open_camera(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nCustomer screen stopped. Existing main-system missions continue.')
    finally:
        app.close()
        server.server_close()


if __name__ == '__main__':
    main()
