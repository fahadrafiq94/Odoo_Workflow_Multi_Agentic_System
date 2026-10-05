"""Automatic camera kiosk, durable requests and an authenticated mission stream."""
import json
from pathlib import Path
import queue
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timezone
from uuid import uuid4

from .smile import SmileGate, smile_score
from .odoo_display import OdooDisplay
from .diagnostics import BUILD, PROTOCOL, error_text
from .transport import BrainClient, NoRedirect, RequestRejected


def save_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


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
        self.camera_status = 'Starting camera'
        self.camera_thread = None
        self.demo_camera = demo_camera
        self.connected = False
        self.last_poll = 0.
        self.remote = {}
        self.message = 'Connecting to the agent team.'
        self.error = self.connection_error = self.processing_error = ''
        self.trace = deque(maxlen=30)
        self.pending_file = self.root / 'pending_request.json'
        self.pending = json.loads(self.pending_file.read_text()) if self.pending_file.exists() else None
        self.stream_file = self.root / 'stream_checkpoint.json'
        checkpoint = json.loads(self.stream_file.read_text()) if self.stream_file.exists() else {}
        self.stream_cursor = int(checkpoint.get('cursor', 0))
        self.stream_instance = checkpoint.get('instance_id')
        self.replayed_events = 0
        self.submitting = False
        self.recovering = False
        self.awaiting_initial_arm = False
        self.needs_new_expression = bool(self.pending)
        self.reset_since = None
        self.auto_display_mission = self.finished_display_mission = None
        self.display_attempt_mission = None
        self.display_attempts = 0
        self.next_display_attempt = 0.
        self.ack_queue = queue.Queue()
        self.odoo = OdooDisplay(config.get('odoo_url', ''), self.root / 'odoo_browser_profile',
            config.get('browser_channel', 'chromium'), hold_seconds=config.get('display_hold_seconds', 1.2),
            on_ready=self.queue_view_ready)
        self.screen_url = None
        if self.pending and not self.pending.get('terminal'):
            self.message = 'Checking the saved request with the agent team.'

    def record(self, stage, detail=''):
        self.trace.append({'time': datetime.now(timezone.utc).isoformat(), 'stage': stage, 'detail': detail})

    def describe_error(self, exc):
        return error_text(exc, (self.config.get('token'), self.token))

    def persist(self):
        save_json(self.pending_file, self.pending)

    def start(self, auto_camera=True):
        threading.Thread(target=self.stream_loop, daemon=True).start()
        threading.Thread(target=self.ack_loop, daemon=True).start()
        if auto_camera:
            self.camera_start()

    def stream_loop(self):
        while not self.stop.is_set():
            try:
                first_state = True
                for kind, payload, cursor in self.brain.events(self.stream_cursor):
                    if self.stop.is_set():
                        break
                    with self.lock:
                        if kind == 'replay':
                            # Replay is history only; do not reopen a finished order.
                            self.replayed_events += len(payload.get('events', []))
                        elif kind == 'heartbeat':
                            if payload.get('instance_id') == self.stream_instance and self.connected:
                                self.last_poll = time.monotonic()
                        elif kind == 'state':
                            if payload.get('protocol') != PROTOCOL:
                                raise ValueError('Update both computers to protocol 2 before starting a mission.')
                            self.processing_error = ''
                            self.ingest(payload)
                            self.stream_cursor = cursor if cursor is not None else payload.get('stream_id', 0)
                            self.stream_instance = payload['instance_id']
                            save_json(self.stream_file, {'cursor': self.stream_cursor, 'instance_id': self.stream_instance})
                            if first_state:
                                self.record('stream_connected', self.stream_instance)
                                self.recover_pending()
                                first_state = False
                    # A heartbeat also lets a failed browser launch retry, without
                    # polling A or waiting for the next business operation.
                    if kind == 'heartbeat':
                        self.sync_display()
            except Exception as exc:
                with self.lock:
                    detail = self.describe_error(exc)
                    if detail != self.connection_error:
                        self.record('stream_disconnected', detail)
                    self.connection_error = detail
                    self.connected = False
                    self.gate.since = None
            self.stop.wait(1)

    def poll_once(self):
        """Read-only diagnostic compatibility; normal operation uses stream_loop."""
        try:
            remote = self.brain.call('/v1/state')
            if not isinstance(remote, dict) or remote.get('mode') not in ('demo', 'live') or not isinstance(remote.get('events'), list):
                raise ValueError('Expected the paired workflow API on port 8766.')
            self.ingest(remote)
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.connection_error = self.describe_error(exc)

    def ingest(self, remote):
        with self.lock:
            was_busy = self.remote.get('busy', False)
            self.remote = remote
            self.connected = True
            self.connection_error = ''
            self.last_poll = time.monotonic()
            if remote.get('busy'):
                self.gate.disarm()
                self.gate.score = 0
                self.needs_new_expression = True
                self.reset_since = None
            elif was_busy:
                self.reset_since = None
            final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
            if self.pending and self.pending.get('mission_id') == remote.get('mission_id') and final:
                if not self.pending.get('terminal'):
                    self.finish_pending(final)
            if self.awaiting_initial_arm and self.camera_running and self.eligible() and not self.needs_new_expression:
                self.arm()
            self.sync_display()

    def finish_pending(self, final):
        self.pending['terminal'] = True
        self.pending['final_status'] = final.get('status')
        self.pending['message'] = final.get('customer_message') or final.get('message') or 'Your order is completed.'
        self.message = self.pending['message']
        self.error = ''
        self.needs_new_expression = True
        self.reset_since = None
        self.persist()

    def sync_display(self):
        with self.lock:
            remote = self.remote
            if remote.get('mode') != 'live':
                self.odoo.follow(False)
                return
            mission = remote.get('mission_id')
            final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
            try:
                # Identity is set before the browser worker can acknowledge startup.
                self.odoo.update_many(remote.get('odoo_targets') or ([remote['odoo_target']] if remote.get('odoo_target') else []), mission)
                if mission and remote.get('busy') and not final and (
                        mission != self.auto_display_mission or self.odoo.launch_failed is True):
                    self.try_open_odoo(mission)
                if final and mission != self.finished_display_mission:
                    self.finished_display_mission = mission
                    if mission != self.auto_display_mission and self.display_attempt_mission != mission:
                        self.odoo.status = 'Mission already finished before the customer view opened. Check its outcome on A.'
                    self.odoo.close_window()
            except Exception as exc:
                self.odoo.status = 'Odoo display error: ' + self.describe_error(exc)

    def try_open_odoo(self, mission):
        if mission != self.display_attempt_mission:
            self.display_attempt_mission, self.display_attempts, self.next_display_attempt = mission, 0, 0
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
            self.auto_display_mission = mission
            self.record('odoo_open_requested', mission)

    def queue_view_ready(self, mission, event_id):
        self.ack_queue.put({'mission_id': mission, 'event_id': event_id})

    def ack_loop(self):
        while not self.stop.is_set():
            try:
                data = self.ack_queue.get(timeout=.25)
            except queue.Empty:
                continue
            try:
                self.brain.call('/v1/view-ready', data)
                with self.lock:
                    self.record('view_ready', str(data['event_id']))
            except Exception as exc:
                with self.lock:
                    self.record('view_ack_failed', self.describe_error(exc))

    def eligible(self):
        return (self.connected and time.monotonic() - self.last_poll < 4 and not self.processing_error
                and self.remote.get('protocol') == PROTOCOL and self.remote.get('product_ready') is True
                and not self.remote.get('busy') and not self.submitting and not self.recovering
                and (not self.pending or self.pending.get('terminal')))

    def arm(self):
        with self.lock:
            if not self.camera_running:
                raise ValueError('Camera is not running. Check camera permissions and the model file.')
            if not self.eligible():
                raise ValueError('Wait for A to be ready and the current request to finish.')
            self.pending = None
            self.persist()
            self.gate.arm()
            self.record('camera_armed')
            self.awaiting_initial_arm = False
            self.needs_new_expression = False
            self.reset_since = None
            self.error = ''
            self.message = 'Hold your smile at 75% or above for a moment.'

    def request_one(self, source='smile'):
        with self.lock:
            if not self.eligible():
                raise ValueError('The agent team is not ready for a new customer.')
            self.gate.disarm()
            self.awaiting_initial_arm = False
            self.needs_new_expression = True
            self.reset_since = None
            self.pending = {'request_id': uuid4().hex, 'mission_id': None, 'terminal': False, 'source': source}
            try:
                self.persist()
            except Exception as exc:
                self.error = 'Cannot save request. Nothing was sent. ' + self.describe_error(exc)
                raise ValueError(self.error) from None
            self.error = ''
            self.message = 'Smile detected. Sending your request…'
            self.record('request_saved', self.pending['request_id'])
            self.send_pending()

    def score(self, score, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.remote.get('busy') or self.submitting:
                # Preview stays on, but smiles during a mission are never queued.
                self.gate.disarm()
                self.gate.score = 0
                self.reset_since = None
                return
            if not self.gate.armed and self.eligible() and self.needs_new_expression:
                if score is None or score < .4:
                    if self.reset_since is None:
                        self.reset_since = now
                    if now - self.reset_since >= 1.2 and now - self.gate.last_trigger >= self.gate.cooldown:
                        self.arm()
                else:
                    self.reset_since = None
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
            if self.eligible() and not self.needs_new_expression:
                self.arm()

    def open_split(self):
        if not self.screen_url:
            raise ValueError('The local camera screen is not ready.')
        self.odoo.open(split_url=self.screen_url)

    def apply_reply(self, result, request_id):
        with self.lock:
            if not self.pending or self.pending['request_id'] != request_id:
                return
            if result.get('state') in ('not_found', 'uncertain'):
                self.error = 'The saved request is not confirmed. Retry the same request or ask staff to check A.'
                self.record('request_unconfirmed', result['state'])
                return
            if not result.get('mission_id'):
                raise ValueError('A did not return a mission ID.')
            self.pending.update(mission_id=result['mission_id'], product=result['product'], product_info=result.get('product_info'))
            self.message = 'Your order is being prepared.'
            self.error = ''
            self.record('request_accepted', result['mission_id'])
            if result.get('final'):
                self.finish_pending(result['final'])
            else:
                self.persist()
                # A very fast mission may have finished in the SSE stream before
                # the POST response arrived. Reconcile with that same mission.
                if self.remote.get('mission_id') == result['mission_id']:
                    final = next((e for e in reversed(self.remote.get('events', [])) if e['kind'] == 'mission_end'), None)
                    if final:
                        self.finish_pending(final)

    def recover_pending(self):
        with self.lock:
            if not self.pending or self.pending.get('terminal') or self.submitting or self.recovering:
                return
            self.recovering = True
            request_id = self.pending['request_id']
        def recover():
            try:
                self.apply_reply(self.brain.call('/v1/requests/' + request_id), request_id)
            except Exception as exc:
                with self.lock:
                    self.error = 'Could not check the saved request. Retry the same request.'
                    self.record('recovery_failed', self.describe_error(exc))
            finally:
                with self.lock:
                    self.recovering = False
        threading.Thread(target=recover, daemon=True).start()

    def send_pending(self):
        with self.lock:
            if not self.pending or self.pending.get('terminal') or self.submitting:
                return
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
                self.apply_reply(self.brain.call('/v1/smile', {'request_id': request_id}), request_id)
            except RequestRejected as exc:
                with self.lock:
                    # A explicitly says no mission was accepted. Do not queue it.
                    self.pending.update(terminal=True, final_status='REJECTED', message=str(exc))
                    self.message, self.error = str(exc), ''
                    self.record('request_rejected', exc.code)
                    self.persist()
            except Exception as exc:
                with self.lock:
                    self.error = 'Request not confirmed. Retry this same request; do not start another customer.'
                    self.message = self.describe_error(exc)
                    self.record('request_unconfirmed', self.message)
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
                    self.score(None)
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
                with self.lock:
                    busy = self.remote.get('busy') or self.submitting
                result = None if busy else landmarker.detect_for_video(image, timestamp)
                self.score(smile_score(result.face_blendshapes[0]) if result and result.face_blendshapes else None)
                if result and result.face_landmarks:
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
            pending = self.pending or {}
            product = (remote.get('product_info') or {}).get('name') or remote.get('smile_product', 'your reward')
            final = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'mission_end'), None)
            external_mission = remote.get('busy') and pending.get('mission_id') != remote.get('mission_id')
            mission = remote.get('mission_id') if remote.get('busy') else pending.get('mission_id') or remote.get('mission_id')
            message = 'A mission started from the main dashboard is running. New smiles are paused.' if external_mission else self.message
            terminal = pending.get('terminal') or (not pending and bool(final))
            cooldown = max(0., self.gate.cooldown - (time.monotonic() - self.gate.last_trigger))
            reward = ''
            if not external_mission and pending.get('mission_id') and pending.get('product') and pending.get('final_status') not in ('FAILED', 'REJECTED'):
                reward = ('Demo: ' if remote.get('mode') == 'demo' else '') + 'You won a ' + pending['product'] + '!'
            if not self.connected:
                phase, title, instruction = 'connecting', 'Connecting to the agent team', 'The camera stays on while we reconnect.'
            elif remote.get('protocol') != PROTOCOL:
                phase, title, instruction = 'blocked', 'Both computers need the same update', 'Install the coordinated release on A and B, then restart.'
            elif self.submitting:
                phase, title, instruction = 'sending', 'Smile detected!', 'Sending your request to the agent team…'
            elif remote.get('busy'):
                phase, title, instruction = 'working', reward or 'The agents are working', 'Preparing the current order. New smiles are paused.'
            elif pending and not pending.get('terminal'):
                phase, title, instruction = 'checking', reward or 'Checking your request', 'Waiting for A to confirm the result. No new request will be sent.'
            elif not remote.get('product_ready'):
                phase, title, instruction = 'checking', 'Checking the reward', remote.get('readiness_message') or 'Waiting for the Odoo product check.'
            elif not self.camera_running:
                phase, title, instruction = 'camera', 'Camera needs attention', self.camera_status
            elif self.needs_new_expression:
                phase = 'finished'
                title = 'Please ask staff about your order' if pending.get('final_status') == 'FAILED' else reward or 'Ready for the next customer'
                instruction = f'Next customer in {int(cooldown)+1}s.' if cooldown > 0 else 'Relax your smile or step away briefly to welcome the next customer.'
            else:
                phase, title = 'ready', 'Smile to win a ' + product
                instruction = 'Hold your smile…' if self.gate.since is not None else 'Hold a smile at 75% or above for 0.6 seconds.'
            latest = next((e for e in reversed(remote.get('events', [])) if e['kind'] in ('tool_start','tool_end','instruction','agent_start','agent_end')), {})
            timeout = next((e for e in reversed(remote.get('events', [])) if e['kind'] == 'display_timeout'), None)
            return {'token': self.token, 'build': BUILD, 'protocol': PROTOCOL,
                'connected': self.connected, 'mode': remote.get('mode', 'unknown'), 'phase': phase, 'headline': title,
                'reward': reward, 'trigger_status': instruction, 'product': product, 'busy': remote.get('busy', False),
                'camera_running': self.camera_running, 'camera_status': self.camera_status, 'score': round(self.gate.score, 3),
                'armed': self.gate.armed, 'neutral_seen': self.gate.neutral_seen,
                'can_arm': self.eligible() and self.camera_running, 'can_start': self.eligible(),
                'can_retry': bool(pending and not pending.get('terminal') and (not pending.get('mission_id') or self.error)),
                'message': message, 'error': self.error, 'connection_error': self.connection_error, 'processing_error': self.processing_error,
                'request_id': pending.get('request_id'), 'mission_id': mission, 'terminal': bool(terminal), 'submitting': self.submitting,
                'activity': {'agent': latest.get('agent'), 'action': latest.get('action'), 'message': latest.get('message')},
                'odoo_target': remote.get('odoo_target'), 'odoo_status': self.odoo.status,
                'odoo_available': self.odoo.available, 'odoo_following': self.odoo.following, 'odoo_display': self.odoo.snapshot(),
                'display_notice': timeout.get('message') if timeout else '', 'demo_camera': self.demo_camera,
                'stream_cursor': self.stream_cursor, 'replayed_events': self.replayed_events}

    def diagnostics(self):
        with self.lock:
            state = self.snapshot()
            result = {k: state[k] for k in ('build','protocol','connected','mode','phase','headline','connection_error','processing_error',
                'camera_running','camera_status','score','armed','can_arm','can_retry','trigger_status','busy','request_id',
                'mission_id','submitting','terminal','error','message','odoo_status','odoo_available','odoo_following','stream_cursor','replayed_events','display_notice')}
            result.update(brain_url=self.config.get('brain_url'), odoo_url=self.config.get('odoo_url'),
                gateway_build=self.remote.get('build', 'unknown'), gateway_instance=self.remote.get('instance_id'),
                remote_mission_id=self.remote.get('mission_id'), product_ready=self.remote.get('product_ready'),
                last_poll_age_seconds=round(time.monotonic()-self.last_poll,2) if self.last_poll else None,
                pending_terminal=bool((self.pending or {}).get('terminal')), pending_mission_id=(self.pending or {}).get('mission_id'),
                display_attempts=self.display_attempts, display_launch_error=self.odoo.launch_error, trace=list(self.trace))
            return result

    def close(self):
        self.stop.set()
        self.camera_running = False
        self.odoo.stop.set()
