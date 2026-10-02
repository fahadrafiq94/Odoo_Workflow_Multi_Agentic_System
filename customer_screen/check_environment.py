"""Read-only Computer B checks. No POST, mission, webcam, browser launch or ERP writes."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from erp_bar_customer.app import BrainClient, NoRedirect
from erp_bar_customer.diagnostics import BUILD, error_text
from erp_bar_customer.odoo_display import record_url

LOCAL_FIELDS = (
    'build', 'connected', 'mode', 'brain_url', 'odoo_url', 'gateway_build', 'gateway_instance',
    'last_poll_age_seconds', 'camera_running', 'camera_status', 'score', 'armed', 'can_arm',
    'can_retry', 'trigger_status', 'busy', 'submitting', 'request_id', 'mission_id',
    'remote_mission_id', 'pending_mission_id', 'pending_terminal', 'terminal',
    'connection_error', 'processing_error', 'error', 'message', 'odoo_status',
    'odoo_available', 'odoo_following', 'display_attempts', 'display_launch_error', 'trace',
)


def get_json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(url, timeout=4) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError('Expected a JSON object.')
    return data


def inspect_environment(pairing, port):
    report = {'checker_build': BUILD, 'pairing_path': str(pairing), 'checks': []}
    checks = report['checks']
    def add(name, status, detail):
        checks.append({'check': name, 'status': status, 'detail': detail})
    config = {}
    remote = None
    add('Python environment', 'PASS' if (3, 11) <= sys.version_info[:2] < (3, 13) else 'FAIL',
        f'{sys.version.split()[0]} · {sys.executable} (Computer B requires Python 3.11 or 3.12)')
    try:
        parsed_config = json.loads(pairing.read_text(encoding='utf-8-sig'))
        if not isinstance(parsed_config, dict):
            raise ValueError('Pairing must be a JSON object.')
        config = parsed_config
        add('Pairing file', 'PASS', str(pairing))
        client = BrainClient(config)
        add('Main address', 'PASS', client.url)
        remote = client.call('/v1/state')
        if not isinstance(remote, dict) or remote.get('mode') not in ('live', 'demo') or not isinstance(remote.get('events'), list):
            raise ValueError('Wrong service: expected the paired workflow API on port 8766.')
        report['main'] = {key: remote.get(key) for key in (
            'build', 'instance_id', 'mode', 'busy', 'mission_id', 'last_id', 'smile_product', 'verified_product_name')}
        final = next((e for e in reversed(remote['events']) if e.get('kind') == 'mission_end'), None)
        report['main']['final_status'] = final.get('status') if final else None
        add('Authenticated connection to A', 'PASS', 'GET /v1/state succeeded; pairing token was not printed.')
        add('Main mode', 'PASS' if remote['mode'] == 'live' else 'WARN',
            remote['mode'] + (' · Odoo will stay closed in demo mode.' if remote['mode'] == 'demo' else ''))
        add('Gateway version', 'PASS' if remote.get('build') == BUILD else 'WARN',
            f"{remote.get('build', 'older build')} · expected {BUILD}; restart A after applying the update.")
    except Exception as exc:
        add('Pairing / connection to A', 'FAIL', error_text(exc, (config.get('token'),)))

    odoo = config.get('odoo_url', '')
    try:
        if not odoo:
            raise ValueError('odoo_url is empty. Copy A’s updated live pairing file to B and restart B.')
        record_url(odoo, {'model': 'sale.order'})
        parsed = urlsplit(odoo)
        port_odoo = parsed.port or (443 if parsed.scheme == 'https' else 80)
        socket.getaddrinfo(parsed.hostname, port_odoo, type=socket.SOCK_STREAM)
        add('Odoo DNS', 'PASS', parsed.hostname)
        with socket.create_connection((parsed.hostname, port_odoo), timeout=3):
            pass
        add('Odoo TCP connection', 'PASS', f'{parsed.hostname}:{port_odoo} · sign-in still needs checking in the browser.')
    except Exception as exc:
        add('Odoo address / reachability', 'FAIL', error_text(exc))

    for package in ('mediapipe', 'opencv-contrib-python', 'playwright'):
        try:
            add(package, 'PASS', importlib.metadata.version(package))
        except importlib.metadata.PackageNotFoundError:
            add(package, 'FAIL', 'Not installed in this environment; run uv sync --python 3.12 inside customer_screen.')
    if config.get('browser_channel', 'chromium') == 'chromium':
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                executable = Path(pw.chromium.executable_path)
            add('Chromium binary', 'PASS' if executable.is_file() else 'FAIL',
                str(executable) if executable.is_file() else 'Run uv run python -m playwright install chromium.')
        except Exception as exc:
            add('Chromium binary', 'FAIL', error_text(exc))
    else:
        add('Browser channel', 'WARN', f"{config.get('browser_channel')}: verify it opens with Open split screen.")

    model = Path(config.get('model_path', 'face_landmarker.task'))
    if not model.is_absolute():
        model = Path(__file__).resolve().parent / model
    add('Face-landmarker model', 'PASS' if model.is_file() else 'FAIL', str(model))
    pending = Path(__file__).resolve().parent / 'customer_state' / 'pending_request.json'
    try:
        saved = json.loads(pending.read_text()) if pending.exists() else None
        report['saved_request'] = {k: saved.get(k) for k in ('request_id', 'mission_id', 'terminal', 'source')} if saved else None
        if saved and not saved.get('terminal'):
            add('Saved request', 'WARN', 'Unfinished request saved. Do not delete it. Check A’s mission and use Retry the same request if unacknowledged.')
        else:
            add('Saved request', 'PASS', 'No unfinished local request.')
    except Exception as exc:
        add('Saved request', 'FAIL', error_text(exc))

    try:
        url = f'http://127.0.0.1:{port}'
        try:
            local = get_json(url + '/api/diagnostics')
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            local = get_json(url + '/api/state')
            add('Running companion version', 'WARN', 'Older process: apply update, stop/restart B, then Ctrl+F5.')
        report['companion'] = {k: local[k] for k in LOCAL_FIELDS if k in local}
        add('Local customer server', 'PASS', url)
        add('Running companion build', 'PASS' if local.get('build') == BUILD else 'WARN',
            str(local.get('build', 'unknown')) + f' · expected {BUILD}')
        for field in ('brain_url', 'odoo_url'):
            if field in local and local[field] != config.get(field):
                add('Loaded ' + field, 'FAIL', 'Running B has different settings from the pairing file. Stop and restart B with this file.')
        if remote and local.get('gateway_instance') and remote.get('instance_id') != local['gateway_instance']:
            add('Same A instance', 'WARN', 'B’s last state came from another gateway process. Wait for reconnect, then check addresses.')
        elif remote and local.get('gateway_instance'):
            add('Same A instance', 'PASS', local['gateway_instance'])
        if local.get('connected') is not True:
            add('B polling A', 'FAIL', local.get('connection_error') or 'B is not connected. Check its pairing path and restart it.')
        else:
            add('B polling A', 'PASS', f"mode={local.get('mode')}; remote mission={local.get('remote_mission_id', local.get('mission_id'))}")
        if local.get('processing_error'):
            add('Local state processing', 'FAIL', local['processing_error'])
        if local.get('display_launch_error'):
            add('Odoo browser launch', 'FAIL', local['display_launch_error'])
    except Exception as exc:
        add('Local customer server', 'FAIL', error_text(exc) + ' · keep run_customer_screen.py running in another terminal.')
    # A malformed external response must never expose the configured bearer token.
    text = json.dumps(report, ensure_ascii=False)
    if isinstance(config.get('token'), str) and config['token']:
        text = text.replace(config['token'], '[redacted]')
    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pairing', default='companion_pairing.json')
    parser.add_argument('--port', type=int, default=8770)
    parser.add_argument('--json', action='store_true', help='Print a credential-free JSON report.')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    report = inspect_environment(Path(args.pairing).resolve(), args.port)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"ERP_BAR read-only check · build {BUILD}\nNo mission or Odoo write will be performed.\n")
        for check in report['checks']:
            print(f"[{check['status']}] {check['check']}: {check['detail']}")
        print('\nCurrent state (no tokens):')
        print(json.dumps({k: v for k, v in report.items() if k != 'checks'}, indent=2, ensure_ascii=False))
    return 1 if any(c['status'] == 'FAIL' for c in report['checks']) else 0


if __name__ == '__main__':
    raise SystemExit(main())
