"""Local camera client, paired request transport and customer state."""
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
import ipaddress
from uuid import uuid4

from .smile import SmileGate, smile_score
from .odoo_display import OdooDisplay


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('The paired endpoint must not redirect.')


class BrainClient:
    def __init__(self, config):
        self.url = config['brain_url'].rstrip('/')
        parsed = urlsplit(self.url)
        if parsed.scheme not in ('http', 'https') or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('brain_url must be a private HTTP(S) host and port.')
        host = parsed.hostname
        if host != 'localhost':
            address = ipaddress.ip_address(host)
            if not address.is_private or address.is_unspecified or address.is_multicast:
                raise ValueError('Use a private network or localhost pairing address.')
        self.token = config['token']
        if not isinstance(self.token, str) or len(self.token) < 32:
            raise ValueError('Invalid pairing token.')
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, path, data=None):
        request = urllib.request.Request(self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with self.http.open(request, timeout=4) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                message = json.load(exc).get('error', 'Request rejected.')
            except Exception:
                message = 'Request rejected.'
            raise RuntimeError(message) from None


class CustomerApp:
    def __init__(self, config, root, client=None, demo_camera=False):
        self.config, self.root = config, Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.token = secrets.token_urlsafe(32)
        self.brain = client or BrainClient(config)
        self.gate = SmileGate()
        self.frame = None
        self.camera_running = False
        self.camera_status = 'Camera off'
        self.camera_thread = None
        self.demo_camera = demo_camera
        self.connected = False
        self.last_poll = 0
        self.remote = {}
        self.message = 'Start a mission with the button, or start the camera and smile.'
        self.error = ''
        self.pending_file = self.root / 'pending_request.json'
        self.pending = json.loads(self.pending_file.read_text()) if self.pending_file.exists() else None
        self.submitting = False
        self.odoo = OdooDisplay(config.get('odoo_url', ''), self.root / 'odoo_browser_profile', config.get('browser_channel', 'chromium'), hold_seconds=config.get('display_hold_seconds', 1.2))
        self.screen_url = None
        if self.pending:
            self.message = self.pending.get('message') or 'Restored request. Reconnecting to the main system.'

    def persist(self):
        temporary = self.pending_file.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.pending, indent=2))
        temporary.replace(self.pending_file)

    def start(self):
        threading.Thread(target=self.poll, daemon=True).start()

    def ingest(self, remote):
        with self.lock:
            self.remote = remote
            self.connected = True
            self.last_poll = time.monotonic()
            if remote.get("busy"):
                self.gate.disarm()
            if self.pending and self.pending.get('mission_id'):
                if self.pending['mission_id'] == remote.get('mission_id'):
                    final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
                    if final and not self.pending.get('terminal'):
                        self.pending['terminal'] = True
                        self.pending['message'] = final.get('customer_message') or final.get('message') or 'Request completed. Please ask staff for the result.'
                        self.message = self.pending['message']
                        self.persist()
                elif not self.pending.get('terminal'):
                    self.message = 'This request is no longer in the main system’s current view. Ask staff to check its mission ID before another order.'
            # A demo event must never navigate a real Odoo browser to simulated record IDs.
            if remote.get('mode') == 'live':
                self.odoo.update_many(remote.get('odoo_targets') or ([remote['odoo_target']] if remote.get('odoo_target') else []), remote.get('mission_id'))
            else:
                self.odoo.follow(False)

    def poll(self):
        while not self.stop.is_set():
            try:
                self.ingest(self.brain.call('/v1/state'))
            except Exception:
                with self.lock:
                    self.connected = False
            self.stop.wait(.6)

    def eligible(self):
        return (self.connected and time.monotonic() - self.last_poll < 3 and
                not self.remote.get('busy') and not self.submitting and
                (not self.pending or self.pending.get('terminal')))

    def arm(self):
        with self.lock:
            if not self.camera_running:
                raise ValueError('Start the camera first.')
            if not self.eligible():
                raise ValueError('Wait for the current request or reconnect to the main system.')
            self.pending = None
            self.persist()
            self.gate.arm()
            self.error = ''
            self.message = 'Look at the camera with a relaxed face, then smile.'

    def request_one(self, source='button'):
        with self.lock:
            if not self.eligible():
                raise ValueError('Wait for the current request or reconnect to the main system.')
            self.gate.disarm()
            self.pending = {'request_id': uuid4().hex, 'mission_id': None, 'terminal': False, 'source': source}
            try:
                self.persist()
            except Exception:
                self.error = 'Cannot save the request identifier. No request was sent.'
                raise ValueError(self.error) from None
            self.error = ''
            self.message = ('Smile recognised. ' if source == 'smile' else '') + 'Requesting one ' + self.remote.get('smile_product', 'Lemonade') + '.'
            self.send_pending()

    def score(self, score, now=None):
        with self.lock:
            if self.gate.update(score, now, eligible=self.eligible()):
                try:
                    self.request_one('smile')
                except ValueError as exc:
                    self.error = str(exc)

    def camera_ready(self):
        with self.lock:
            self.camera_running = True
            # Starting the camera arms exactly one customer if the workflow is ready.
            if self.eligible():
                self.arm()

    def open_split(self):
        if not self.screen_url:
            raise ValueError('The local camera screen is not ready.')
        self.odoo.open(split_url=self.screen_url)

    def send_pending(self):
        with self.lock:
            if not self.pending or self.pending.get('terminal') or self.submitting:
                return
            self.submitting = True
            request_id = self.pending['request_id']
        def send():
            try:
                result = self.brain.call('/v1/smile', {'request_id': request_id})
                with self.lock:
                    self.pending['mission_id'] = result['mission_id']
                    self.message = 'The agents are preparing your request for one ' + result['product'] + '.'
                    self.error = ''
                    self.persist()
            except Exception as exc:
                with self.lock:
                    self.error = 'Request not yet confirmed. Retry this same request; do not start another customer.'
                    self.message = str(exc) if isinstance(exc, RuntimeError) else 'Connection interrupted. The request may already have started.'
            finally:
                with self.lock:
                    self.submitting = False
        threading.Thread(target=send, daemon=True).start()

    def camera_start(self):
        with self.lock:
            if self.camera_thread and self.camera_thread.is_alive():
                return
            self.camera_status = 'Starting camera'
            self.camera_thread = threading.Thread(target=self.camera_loop, daemon=True)
            self.camera_thread.start()

    def camera_loop(self):
        cap, landmarker = None, None
        try:
            if self.demo_camera:
                self.camera_ready()
                self.camera_status = 'Simulated camera · no webcam access'
                while not self.stop.wait(.2) and self.camera_running:
                    pass
                return
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            model = Path(self.config.get('model_path', 'face_landmarker.task'))
            if not model.is_absolute():
                model = self.root.parent / model
            if not model.is_file():
                raise FileNotFoundError('Copy face_landmarker.task from your working detector into customer_screen.')
            landmarker = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model)),
                output_face_blendshapes=True, num_faces=1, running_mode=vision.RunningMode.VIDEO))
            cap = cv2.VideoCapture(int(self.config.get('camera_index', 0)))
            if not cap.isOpened():
                raise RuntimeError('Webcam not available. Close other camera apps or change camera_index.')
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)
            self.camera_ready()
            self.camera_status = 'Camera on · processed on this computer'
            previous_ms = -1
            while not self.stop.is_set() and self.camera_running:
                ok, frame = cap.read()
                if not ok:
                    raise RuntimeError('Camera stopped returning frames.')
                frame = cv2.flip(frame, 1)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                timestamp = max(previous_ms + 1, int(time.monotonic() * 1000))
                previous_ms = timestamp
                result = landmarker.detect_for_video(image, timestamp)
                self.score(smile_score(result.face_blendshapes[0]) if result.face_blendshapes else None)
                if result.face_landmarks:
                    h, w = frame.shape[:2]
                    points = result.face_landmarks[0]
                    a = (int(min(p.x for p in points)*w), int(min(p.y for p in points)*h))
                    b = (int(max(p.x for p in points)*w), int(max(p.y for p in points)*h))
                    cv2.rectangle(frame, a, b, (122, 238, 177), 2)
                ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    with self.lock:
                        self.frame = encoded.tobytes()
                self.stop.wait(.025)
        except Exception as exc:
            self.camera_status = str(exc) if isinstance(exc, (FileNotFoundError, RuntimeError)) else 'Camera unavailable: ' + type(exc).__name__
        finally:
            self.camera_running = False
            self.gate.disarm()
            self.frame = None
            if cap is not None:
                cap.release()
            if landmarker is not None:
                landmarker.close()

    def snapshot(self):
        with self.lock:
            remote = self.remote
            observed_final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
            watching_other = bool(remote.get('mission_id')) and (not self.pending or (self.pending.get('terminal') and self.pending.get('mission_id') != remote.get('mission_id')))
            message = self.message
            if watching_other and remote.get('busy'):
                message = 'The agents are running a mission started on the main dashboard.'
            elif watching_other and observed_final:
                message = observed_final.get('customer_message') or observed_final.get('message') or 'Mission finished.'
            latest = next((e for e in reversed(remote.get('events', [])) if e['kind'] in ('tool_start','tool_end','instruction','agent_end')), {})
            return {'token': self.token, 'connected': self.connected, 'mode': remote.get('mode', 'unknown'),
                    'product': remote.get('smile_product', 'Lemonade'), 'busy': remote.get('busy', False),
                    'camera_running': self.camera_running, 'camera_status': self.camera_status,
                    'score': round(self.gate.score, 3), 'armed': self.gate.armed, 'neutral_seen': self.gate.neutral_seen,
                    'can_arm': self.eligible() and self.camera_running, 'can_start': self.eligible(), 'message': message, 'error': self.error,
                    'request_id': (self.pending or {}).get('request_id'), 'mission_id': remote.get('mission_id') if watching_other else (self.pending or {}).get('mission_id'),
                    'terminal': bool(observed_final) if watching_other else bool((self.pending or {}).get('terminal')), 'submitting': self.submitting,
                    'activity': {'agent': latest.get('agent'), 'action': latest.get('action'), 'message': latest.get('message')},
                    'odoo_target': remote.get('odoo_target'), 'odoo_status': self.odoo.status,
                    'odoo_available': self.odoo.available, 'odoo_following': self.odoo.following,
                    'odoo_display': self.odoo.snapshot(),
                    'demo_camera': self.demo_camera}

    def close(self):
        self.stop.set()
        self.camera_running = False
        self.odoo.stop.set()
