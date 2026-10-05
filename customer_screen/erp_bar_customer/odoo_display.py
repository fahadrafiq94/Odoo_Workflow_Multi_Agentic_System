"""Own browser window: manual login, navigation/refresh only, no ERP writes."""
import threading
import time
from urllib.parse import urlencode, urlsplit
from .diagnostics import error_text

LIST_ACTIONS = {'product.product': 'product.product_normal_action_sell',
                'sale.order': 'sale.action_orders', 'purchase.order': 'purchase.purchase_rfq',
                'stock.picking': 'stock.action_picking_tree_all'}
MODELS = set(LIST_ACTIONS)


def record_url(base, target):
    parsed = urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an Odoo base URL without credentials, query or fragment.')
    if target.get('model') not in MODELS:
        raise ValueError('Unsupported Odoo record model.')
    values = {'model': target['model'], 'view_type': 'list'}
    record_id = target.get('record_id')
    if record_id is not None:
        if type(record_id) is not int or record_id <= 0:
            raise ValueError('Invalid Odoo record ID.')
        values.update(id=record_id, view_type='form')
    else:
        values = {'action': LIST_ACTIONS[target['model']]}
    return base.rstrip('/') + '/web#' + urlencode(values)


def split_bounds(screen):
    """Browser screen coordinates are device-independent, including negative monitors."""
    width, height = int(screen['width']), int(screen['height'])
    if not 640 <= width <= 16384 or not 400 <= height <= 16384:
        raise ValueError('Unsupported screen dimensions.')
    left, top = int(screen.get('left', 0)), int(screen.get('top', 0))
    half = width // 2
    return ({'left': left, 'top': top, 'width': half, 'height': height},
            {'left': left + half, 'top': top, 'width': width - half, 'height': height})


def place_window(context, page, bounds):
    session = context.new_cdp_session(page)
    try:
        window_id = session.send('Browser.getWindowForTarget')['windowId']
        session.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': {'windowState': 'normal'}})
        session.send('Browser.setWindowBounds', {'windowId': window_id, 'bounds': bounds})
    finally:
        session.detach()


class OdooDisplay:
    def __init__(self, base, profile, channel='chromium', hold_seconds=1.2, on_ready=None):
        from collections import deque
        self.base, self.profile, self.channel = base, profile, channel
        self.hold_seconds = max(0., min(5., float(hold_seconds)))
        self.status = 'Closed'
        self.following = False
        self.available = False
        self.target = None
        self.shown = None
        self.last_event = None
        self.mission_id = None
        self.cursor = 0
        self.pending = deque()
        self.lock = threading.RLock()
        self.split_url = None
        self.layout_requested = False
        self.layout_status = 'Open split screen to arrange both windows'
        self.thread = None
        self.stop = threading.Event()
        self.window_requested = False
        self.auto_follow = False
        self.launch_failed = False
        self.launch_error = ''
        self.camera_requested = False
        self.on_ready = on_ready or (lambda mission, event: None)
        self.announced_window = None

    def open(self, split_url=None, auto_follow=False):
        if not self.base:
            raise ValueError('Set odoo_url in the pairing file first.')
        record_url(self.base, {'model': 'sale.order'})
        with self.lock:
            self.window_requested = True
            self.auto_follow = auto_follow
            if auto_follow:
                self.following = True
                if self.target and not self.pending:
                    self.pending.append(dict(self.target))
            if split_url:
                url = urlsplit(split_url)
                if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
                    raise ValueError('The camera window must use its local screen URL.')
                self.split_url = split_url
                self.camera_requested = True
                self.layout_requested = True
            if self.thread and self.thread.is_alive():
                return
            self.launch_failed = False
            self.launch_error = ''
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def close_window(self):
        """Close only our Odoo window; keep the camera window and login profile."""
        with self.lock:
            self.window_requested = False
            self.following = False
            self.auto_follow = False
            self.pending.clear()
            self.announced_window = None

    def follow(self, enabled):
        with self.lock:
            if enabled and not self.available:
                raise ValueError('Open the Odoo window and sign in first.')
            self.following = enabled
            self.pending.clear()
            if enabled:
                self.last_event = None
                if self.target:
                    self.pending.append(dict(self.target))

    def update(self, target, mission_id):
        self.update_many([target] if target else [], mission_id)

    def update_many(self, targets, mission_id):
        with self.lock:
            if mission_id != self.mission_id:
                self.mission_id = mission_id
                self.cursor = 0
                self.pending.clear()
                self.target = None
                self.shown = None
                self.last_event = None
            for item in targets:
                if item.get('event_id', 0) <= self.cursor:
                    continue
                record_url(self.base or 'http://localhost', item)
                target = {**item, 'mission_id': mission_id}
                self.cursor = item['event_id']
                self.target = target
                if not self.following:
                    continue
                # Adjacent updates of the same record share one view. Keep transitions
                # between distinct records so a fast purchase cannot disappear in a poll.
                previous = self.pending[-1] if self.pending else None
                if previous and not previous.get('wait_for_view') and previous['model'] == target['model'] and (
                        previous.get('record_id') == target.get('record_id') or previous.get('record_id') is None):
                    self.pending[-1] = target
                else:
                    self.pending.append(target)

    def snapshot(self):
        with self.lock:
            return {'shown': dict(self.shown) if self.shown else None,
                    'waiting': len(self.pending), 'layout': self.layout_status,
                    'latest_event': self.cursor}

    def open_camera(self, url):
        parsed = urlsplit(url)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost') or parsed.path not in ('','/') or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('The camera must use its local screen URL.')
        with self.lock:
            self.split_url = url
            self.camera_requested = True
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def run(self):
        camera_context = context = page = camera_page = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                options = {'headless': False, 'no_viewport': True, 'args': ['--window-size=960,900']}
                if self.channel != 'chromium':
                    options['channel'] = self.channel
                def camera_bounds():
                    return camera_page.evaluate('({left:screen.availLeft||0,top:screen.availTop||0,width:screen.availWidth,height:screen.availHeight})')
                def layout(split):
                    if camera_page is None or camera_page.is_closed():
                        return
                    try:
                        screen = camera_bounds()
                        left, right = split_bounds(screen)
                        place_window(camera_context, camera_page, left if split else {k:int(v) for k,v in screen.items()})
                        if split:
                            place_window(context, page, right)
                        self.layout_status = 'Camera left · Odoo right' if split else 'Camera ready'
                    except Exception:
                        self.layout_status = 'Use Windows Snap if automatic window placement is unavailable.'
                next_change = 0.
                try:
                    while not self.stop.wait(.1):
                        # The camera window has its own browser profile and lifetime.
                        if self.camera_requested and (camera_page is None or camera_page.is_closed()):
                            try:
                                if camera_context is not None:
                                    camera_context.close()
                                camera_context = pw.chromium.launch_persistent_context(str(self.profile.parent/'camera_browser_profile'), **options)
                                camera_page = camera_context.pages[0] if camera_context.pages else camera_context.new_page()
                                camera_page.goto(self.split_url, wait_until='domcontentloaded', timeout=15000)
                                layout(False)
                            except Exception as exc:
                                self.camera_requested = False
                                self.layout_status = 'Camera browser could not open: ' + error_text(exc)
                        if not self.window_requested:
                            if context is not None:
                                context.close()
                                context = page = None
                                self.available = False
                                self.status = 'Mission finished · Odoo closed'
                                layout(False)
                            continue
                        if context is None:
                            try:
                                self.status = 'Opening Odoo'
                                context = pw.chromium.launch_persistent_context(str(self.profile), **options)
                                page = context.pages[0] if context.pages else context.new_page()
                                page.goto(self.base.rstrip('/') + '/web', wait_until='domcontentloaded', timeout=20000)
                                self.available = True
                                self.launch_failed = False
                                self.launch_error = ''
                                self.status = 'Odoo opened · sign in if requested'
                                self.layout_requested = True
                                next_change = 0
                            except Exception as exc:
                                self.launch_failed = True
                                self.launch_error = error_text(exc)
                                self.status = 'Browser unavailable: ' + self.launch_error
                                self.window_requested = False
                                self.available = False
                                if context is not None:
                                    context.close()
                                context = page = None
                                continue
                        if page.is_closed():
                            self.close_window()
                            continue
                        if self.layout_requested:
                            self.layout_requested = False
                            layout(True)
                        if not self.following:
                            continue
                        if '/web/login' in page.url or '/web/database/' in page.url:
                            self.status = 'Sign in to Odoo; following resumes automatically'
                            continue
                        if self.mission_id and self.announced_window != self.mission_id:
                            # Loading the web client is a display acknowledgement,
                            # never evidence that an ERP operation succeeded.
                            try:
                                page.wait_for_selector('.o_web_client', state='visible', timeout=1500)
                            except Exception:
                                continue
                            self.announced_window = self.mission_id
                            self.on_ready(self.mission_id, 0)
                        if time.monotonic() < next_change:
                            continue
                        with self.lock:
                            target = self.pending.popleft() if self.pending else None
                        if not target:
                            continue
                        try:
                            url = record_url(self.base, target)
                            description = target['model'] + (' #' + str(target['record_id']) if target.get('record_id') else ' list')
                            self.status = 'Opening ' + description
                            if page.url == url:
                                if target['phase'] == 'tool_end':
                                    page.reload(wait_until='domcontentloaded', timeout=15000)
                            else:
                                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                                # Force a fresh page for draft-order synchronization;
                                # hash-only navigation can leave the prior form visible.
                                if target.get('wait_for_view'):
                                    page.reload(wait_until='domcontentloaded', timeout=15000)
                            if '/web/login' in page.url or '/web/database/' in page.url:
                                with self.lock:
                                    self.pending.appendleft(target)
                                self.status = 'Sign in to Odoo; following resumes automatically'
                                continue
                            page.wait_for_selector('.o_form_view' if target.get('record_id') else '.o_action_manager', state='visible', timeout=3000)
                            with self.lock:
                                if target['mission_id'] != self.mission_id or not self.window_requested:
                                    continue
                                self.shown = target
                                self.last_event = (target['mission_id'], target['event_id'])
                            if target.get('wait_for_view'):
                                self.on_ready(target['mission_id'], target['event_id'])
                            next_change = time.monotonic() + self.hold_seconds
                            self.status = 'Showing ' + description
                        except Exception as exc:
                            self.follow(False)
                            self.status = 'Odoo view could not load: ' + error_text(exc)
                finally:
                    if context:
                        context.close()
                    if camera_context:
                        camera_context.close()
        except Exception as exc:
            self.launch_failed = True
            self.launch_error = error_text(exc)
            self.status = 'Browser unavailable: ' + self.launch_error
        finally:
            self.available = False
            self.following = False
