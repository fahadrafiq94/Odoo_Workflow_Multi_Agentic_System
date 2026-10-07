"""Start the local agent view. Default: labelled demo, no Odoo or Ollama calls."""
import argparse
from pathlib import Path
import sys
import webbrowser
import ipaddress
import json
import secrets
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--demo", action="store_true", help="Simulated visual preview (default)")
    mode.add_argument("--live", action="store_true", help="Use configured agents, Ollama and real Odoo actions")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-camera", action="store_true", help="Disable A’s browser camera; keep B as the smile trigger")
    parser.add_argument("--companion-host", help="Private IP of this computer; enables the paired second-screen API")
    parser.add_argument("--companion-port", type=int, default=8766)
    parser.add_argument("--smile-product", default="Lemonade")
    parser.add_argument("--odoo-display-url", default="", help="Odoo URL reachable from the second computer")
    parser.add_argument("--display-wait", type=float, default=4, help="Maximum seconds to wait for a draft order view on B (0 disables)")
    parser.add_argument("--window-wait", type=float, default=8, help="Maximum seconds to wait for B's Odoo window at mission start")
    args = parser.parse_args()
    if not 0 <= args.display_wait <= 10 or not 0 <= args.window_wait <= 20:
        parser.error("Use --display-wait between 0 and 10 and --window-wait between 0 and 20 seconds")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if not 1 <= args.companion_port <= 65535 or (args.companion_host and args.companion_port == args.port):
        parser.error("Choose a different companion port between 1 and 65535")
    if args.companion_host:
        try:
            address = ipaddress.ip_address(args.companion_host)
        except ValueError:
            parser.error("--companion-host must be this computer's private IPv4 address")
        if address.version != 4 or not address.is_private or address.is_unspecified or address.is_multicast:
            parser.error("Use this computer's private IPv4 address, or 127.0.0.1 for a local test")
    if args.live:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    from erp_bar.agent_view.server import Session, make_server
    session = Session(live=args.live)
    companion = gateway = assets = None
    if args.companion_host or not args.no_camera:
        from erp_bar.agent_view.companion_gateway import CompanionGateway, make_companion_server, BUILD, PROTOCOL
        pairing_path = ROOT / "companion_pairing.json"
        previous = json.loads(pairing_path.read_text()) if args.companion_host and pairing_path.exists() else {}
        pairing = {**previous, "brain_url": f"http://{args.companion_host}:{args.companion_port}",
                   "token": previous.get("token") or secrets.token_urlsafe(40),
                   "odoo_url": args.odoo_display_url or previous.get("odoo_url", ""),
                   "protocol": PROTOCOL, "build": BUILD}
        for key, value in {"camera_index": 0, "model_path": "face_landmarker.task", "browser_channel": "chromium"}.items():
            pairing.setdefault(key, value)
        gateway = CompanionGateway(session, pairing["token"], args.smile_product, ROOT / "companion_state" / "requests.sqlite3",
                                   display_wait_seconds=args.display_wait, window_wait_seconds=args.window_wait,
                                   smile_source="companion" if args.no_camera else "dashboard")
        gateway.start()
    if args.companion_host:
        companion = make_companion_server(gateway, args.companion_host, args.companion_port)
        pairing_path.write_text(json.dumps(pairing, indent=2))
        pairing_path.chmod(0o600)
        threading.Thread(target=companion.serve_forever, daemon=True).start()
        print(f"Second screen enabled. Copy {pairing_path.name} privately to the second computer.")
        print(f"Release {BUILD} · protocol {PROTOCOL} · SSE: {pairing['brain_url']}/v1/events")
    if not args.no_camera:
        from erp_bar.agent_view.camera_assets import CameraAssets
        assets = CameraAssets()
        assets.start()
    server = make_server(session, args.port, gateway if not args.no_camera else None, assets)
    url = f"http://127.0.0.1:{args.port}"
    print(f"ERP_BAR agent view: {url}")
    print("LIVE: starting a mission writes Odoo orders and validates receipts/delivery." if args.live
          else "DEMO: all displayed workflow events are simulated; no Odoo or Ollama access.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped. Closing the browser alone does not cancel a running mission.")
    finally:
        server.server_close()
        if gateway:
            gateway.close()
        if companion:
            companion.shutdown()
            companion.server_close()


if __name__ == "__main__":
    main()
