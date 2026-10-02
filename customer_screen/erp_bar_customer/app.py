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
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4

from .smile import SmileGate, smile_score
from .odoo_display import OdooDisplay
from .diagnostics import BUILD, error_text


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
        self.message = 'Start the camera and hold your smile to begin.'
        self.error = ''
        self.connection_error = ''
        self.processing_error = ''
        self.trace = deque(maxlen=30)
        self.pending_file = self.root / 'pending_request.json'
        self.pending = json.loads(self.pending_file.read_text()) if self.pending_file.exists() else None
        self.submitting = False
        self.awaiting_initial_arm = False
        self.auto_display_mission = None
        self.finished_display_mission = None
        self.display_attempt_mission = None
        self.display_attempts = 0
        self.next_display_attempt = 0
        self.odoo = OdooDisplay(config.get('odoo_url', ''), self.root / 'odoo_browser_profile', config.get('browser_channel', 'chromium'), hold_seconds=config.get('display_hold_seconds', 1.2))
        self.screen_url = None
        if self.pending:
            self.message = self.pending.get('message') or 'Restored request. Reconnecting to the main system.'
            if not self.pending.get('terminal') and not self.pending.get('mission_id'):
                self.error = 'A saved request has no acknowledgement. Use Retry the same request to check it safely.'

    def record(self, stage, detail=''):
        self.trace.append({'time': datetime.now(timezone.utc).isoformat(), 'stage': stage, 'detail': detail})

    def describe_error(self, exc):
        return error_text(exc, (self.config.get('token'), self.token))

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
            self.connection_error = ''
            self.last_poll = time.monotonic()
            if remote.get("busy"):
                self.gate.disarm()
            elif self.awaiting_initial_arm and self.camera_running and self.eligible():
                self.arm()
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
                mission_id = remote.get('mission_id')
                final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
                if mission_id and remote.get('busy') and not final and (
                        mission_id != self.auto_display_mission or self.odoo.launch_failed is True):
                    self.try_open_odoo(mission_id)
                try:
                    self.odoo.update_many(remote.get('odoo_targets') or ([remote['odoo_target']] if remote.get('odoo_target') else []), remote.get('mission_id'))
                except Exception as exc:
                    self.odoo.status = 'Odoo display update failed: ' + self.describe_error(exc)
                if final and mission_id != self.finished_display_mission:
                    self.finished_display_mission = mission_id
                    if mission_id != self.auto_display_mission and self.display_attempt_mission != mission_id:
                        self.odoo.status = 'Mission already finished before B observed it running. Check the outcome on A.'
                    self.odoo.close_window()
            else:
                self.odoo.follow(False)

    def try_open_odoo(self, mission_id):
        if mission_id != self.display_attempt_mission:
            self.display_attempt_mission = mission_id
            self.display_attempts = 0
            self.next_display_attempt = 0
        if self.display_attempts >= 3 or time.monotonic() < self.next_display_attempt:
            return
        self.display_attempts += 1
        self.next_display_attempt = time.monotonic() + 5
        try:
            self.odoo.open(split_url=self.screen_url, auto_follow=True)
        except Exception as exc:
            self.odoo.status = 'Cannot open Odoo: ' + self.describe_error(exc)
            self.record('odoo_open_failed', self.odoo.status)
        else:
            self.auto_display_mission = mission_id
            self.record('odoo_open_requested', mission_id)

    def poll_once(self):
        try:
            remote = self.brain.call('/v1/state')
            if not isinstance(remote, dict) or remote.get('mode') not in ('demo', 'live') or not isinstance(remote.get('events'), list):
                raise ValueError('The paired endpoint did not return ERP_BAR workflow state. Check brain_url and port 8766.')
        except Exception as exc:
            with self.lock:
                self.connected = False
                detail = self.describe_error(exc)
                if detail != self.connection_error:
                    self.record('connection_failed', detail)
                self.connection_error = detail
            return
        with self.lock:
            if not self.connected:
                self.record('connected', remote.get('mode', 'unknown'))
            self.processing_error = ''
            try:
                self.ingest(remote)
            except Exception as exc:
                # HTTP succeeded: local processing/display errors are separate.
                self.processing_error = self.describe_error(exc)
                self.record('state_processing_failed', self.processing_error)

    def poll(self):
        while not self.stop.is_set():
            self.poll_once()
            self.stop.wait(.6)

    def eligible(self):
        return (self.connected and time.monotonic() - self.last_poll < 3 and
                not self.processing_error and
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
            self.record('camera_armed')
            self.awaiting_initial_arm = False
            self.error = ''
            self.message = 'Hold a smile at 75% or above for a moment.'

    def request_one(self, source='button'):
        with self.lock:
            if not self.eligible():
                raise ValueError('Wait for the current request or reconnect to the main system.')
            self.gate.disarm()
            self.awaiting_initial_arm = False
            self.pending = {'request_id': uuid4().hex, 'mission_id': None, 'terminal': False, 'source': source}
            try:
                self.persist()
            except Exception:
                self.error = 'Cannot save the request identifier. No request was sent.'
                raise ValueError(self.error) from None
            self.error = ''
            self.message = ('Smile recognised. ' if source == 'smile' else '') + 'Requesting one ' + self.remote.get('smile_product', 'Lemonade') + '.'
            self.record('request_saved', self.pending['request_id'])
            self.send_pending()

    def score(self, score, now=None):
        with self.lock:
            if self.gate.update(score, now, eligible=self.eligible()):
                self.record('smile_registered')
                try:
                    self.request_one('smile')
                except ValueError as exc:
                    self.error = str(exc)

    def camera_ready(self):
        with self.lock:
            self.camera_running = True
            self.awaiting_initial_arm = True
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
            # Retry never transmits a new ID unless its local persistence worked.
            try:
                self.persist()
            except Exception as exc:
                self.error = 'Cannot save request; nothing was sent. ' + self.describe_error(exc)
                return
            self.submitting = True
            request_id = self.pending['request_id']
            self.record('request_sending', request_id)
        def send():
            try:
                result = self.brain.call('/v1/smile', {'request_id': request_id})
                with self.lock:
                    self.pending['mission_id'] = result['mission_id']
                    self.record('request_accepted', result['mission_id'])
                    self.message = 'The agents are preparing your request for one ' + result['product'] + '.'
                    self.error = ''
                    self.persist()
            except Exception as exc:
                with self.lock:
                    self.record('request_unconfirmed', self.describe_error(exc))
                    self.error = 'Request not yet confirmed. Retry this same request; do not start another customer.'
                    self.message = self.describe_error(exc) + ' The request may already have started.'
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
            reward = ''
            if self.pending and self.pending.get('source') == 'smile' and (
                    not self.pending.get('mission_id') or self.pending.get('mission_id') == remote.get('mission_id')):
                same_mission = self.pending.get('mission_id') == remote.get('mission_id')
                verified = remote.get('verified_product_name') if same_mission else None
                reward = 'You won a ' + verified + '!' if verified else 'Smile registered! Checking your reward…'
                if remote.get('mode') == 'demo':
                    reward = 'Demo: You won a ' + remote.get('smile_product', 'Lemonade') + '!'
                if self.pending.get('terminal') and observed_final and observed_final.get('status') == 'FAILED':
                    reward = 'Smile registered — please ask staff about your reward.'
            cooldown = max(0, self.gate.cooldown - (time.monotonic() - self.gate.last_trigger))
            if not self.camera_running:
                trigger_status = 'Start the camera to begin.'
            elif not self.connected:
                trigger_status = 'Waiting for Computer A to connect.'
            elif self.processing_error:
                trigger_status = 'Local state error. See diagnostics before starting another request.'
            elif remote.get('busy') or self.submitting:
                trigger_status = 'The agents are handling the current request.'
            elif not self.eligible():
                trigger_status = 'Waiting for confirmation of the previous request. Retry the same request if needed.'
            elif not self.gate.armed:
                trigger_status = 'Select Next customer to enable another smile.'
            elif cooldown > 0:
                trigger_status = f'Ready in {int(cooldown) + 1} seconds.'
            elif self.gate.since is not None:
                trigger_status = 'Smile detected — keep holding…'
            else:
                trigger_status = 'Ready! Hold your smile at 75% or above for 0.6 seconds.'
            return {'token': self.token, 'connected': self.connected, 'mode': remote.get('mode', 'unknown'),
                    'build': BUILD, 'connection_error': self.connection_error, 'processing_error': self.processing_error,
                    'can_retry': bool(self.pending and not self.pending.get('terminal') and (
                        not self.pending.get('mission_id') or self.error)),
                    'reward': reward, 'trigger_status': trigger_status,
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

    def diagnostics(self):
        """Allowlisted read-only report: never include tokens, model text or credentials."""
        with self.lock:
            state = self.snapshot()
            result = {key: state[key] for key in (
                'build', 'connected', 'mode', 'connection_error', 'processing_error',
                'camera_running', 'camera_status', 'score', 'armed', 'can_arm', 'can_retry',
                'trigger_status', 'busy', 'request_id', 'mission_id', 'submitting',
                'terminal', 'error', 'message', 'odoo_status', 'odoo_available', 'odoo_following')}
            result.update(brain_url=self.config.get('brain_url'), odoo_url=self.config.get('odoo_url'),
                gateway_build=self.remote.get('build', 'unknown'), gateway_instance=self.remote.get('instance_id'),
                remote_mission_id=self.remote.get('mission_id'),
                last_poll_age_seconds=round(time.monotonic() - self.last_poll, 2) if self.last_poll else None,
                pending_terminal=bool((self.pending or {}).get('terminal')),
                pending_mission_id=(self.pending or {}).get('mission_id'),
                display_attempts=self.display_attempts,
                display_launch_error=self.odoo.launch_error, trace=list(self.trace))
            return result

    def close(self):
        self.stop.set()
        self.camera_running = False
        self.odoo.stop.set()
