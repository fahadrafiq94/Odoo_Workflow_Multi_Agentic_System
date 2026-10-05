"""Authenticated HTTP requests and a reconnectable SSE reader for Computer A."""
import ipaddress
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('The paired endpoint must not redirect.')


class RequestRejected(RuntimeError):
    """A expressly confirms that no mission was accepted or queued."""
    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class BrainClient:
    def __init__(self, config):
        self.url = config['brain_url'].rstrip('/')
        parsed = urlsplit(self.url)
        if parsed.scheme not in ('http', 'https') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('brain_url must be a private HTTP(S) host and port.')
        if parsed.hostname != 'localhost':
            address = ipaddress.ip_address(parsed.hostname)
            if not address.is_private or address.is_unspecified or address.is_multicast:
                raise ValueError('Use a private network or localhost pairing address.')
        self.token = config['token']
        if not isinstance(self.token, str) or len(self.token) < 32:
            raise ValueError('Invalid pairing token.')
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        self.stream_response = None

    def request(self, path, data=None, headers=None):
        return urllib.request.Request(self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json', **(headers or {})})

    def call(self, path, data=None):
        try:
            with self.http.open(self.request(path, data), timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                body = json.load(exc)
            except Exception:
                body = {}
            message = body.get('error', f'HTTP {exc.code}: request rejected.')
            if body.get('accepted') is False:
                raise RequestRejected(message, body.get('code', 'rejected')) from None
            raise RuntimeError(message) from None

    def events(self, cursor=0):
        headers = {'Accept': 'text/event-stream', 'Last-Event-ID': str(cursor)}
        with self.http.open(self.request('/v1/events', headers=headers), timeout=5) as response:
            if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                raise ValueError('A did not return an event stream. Update both computers to the same release.')
            self.stream_response = response
            kind, event_id, lines = 'message', None, []
            try:
                for raw in response:
                    line = raw.decode('utf-8').rstrip('\r\n')
                    if not line:
                        if lines:
                            yield kind, json.loads('\n'.join(lines)), event_id
                        kind, event_id, lines = 'message', None, []
                    elif line.startswith('event:'):
                        kind = line[6:].strip()
                    elif line.startswith('id:'):
                        event_id = int(line[3:].strip())
                    elif line.startswith('data:'):
                        lines.append(line[5:].lstrip())
                raise ConnectionError('The event stream closed. Reconnecting to A.')
            finally:
                self.stream_response = None
