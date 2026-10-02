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
    def __init__(self, base, profile, channel='chromium', hold_seconds=1.2):
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

    def open(self, split_url=None, auto_follow=False):
        if not self.base:
            raise ValueError('Set odoo_url in the pairing file first.')
        record_url(self.base, {'model': 'sale.order'})
        with self.lock:
            self.window_requested = True
            self.auto_follow = auto_follow
            if auto_follow:
                self.following = True
            if split_url:
                url = urlsplit(split_url)
                if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
                    raise ValueError('The camera window must use its local screen URL.')
                self.split_url = split_url
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
                if previous and previous['model'] == target['model'] and (
                        previous.get('record_id') == target.get('record_id') or previous.get('record_id') is None):
                    self.pending[-1] = target
                else:
                    self.pending.append(target)

    def snapshot(self):
        with self.lock:
            return {'shown': dict(self.shown) if self.shown else None,
                    'waiting': len(self.pending), 'layout': self.layout_status,
                    'latest_event': self.cursor}

    def run(self):
        self.status = 'Opening browser'
        camera_context = context = page = None
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                options = {'headless': False, 'no_viewport': True,
                           'args': ['--window-size=960,900']}
                if self.channel != 'chromium':
                    options['channel'] = self.channel
                try:
                    next_change = 0
                    while not self.stop.wait(.1):
                        if not self.window_requested:
                            if context is not None:
                                context.close()
                                context = page = None
                                self.available = False
                                self.status = 'Mission finished · Odoo closed'
                            continue
                        if context is None:
                            context = pw.chromium.launch_persistent_context(str(self.profile), **options)
                            page = context.pages[0] if context.pages else context.new_page()
                            page.goto(self.base.rstrip('/') + '/web', wait_until='domcontentloaded', timeout=30000)
                            self.available = True
                            self.status = 'Odoo opened · sign in if requested'
                            next_change = 0
                        if page.is_closed():
                            self.close_window()
                            continue
                        if self.layout_requested:
                            self.layout_requested = False
                            try:
                                if camera_context is None:
                                    camera_profile = self.profile.parent / 'camera_browser_profile'
                                    camera_context = pw.chromium.launch_persistent_context(str(camera_profile), **options)
                                camera_page = next((p for p in camera_context.pages if not p.is_closed()), None)
                                if camera_page is None:
                                    camera_page = camera_context.new_page()
                                if camera_page.url != self.split_url:
                                    camera_page.goto(self.split_url, wait_until='domcontentloaded', timeout=15000)
                                screen = camera_page.evaluate('({left:screen.availLeft||0,top:screen.availTop||0,width:screen.availWidth,height:screen.availHeight})')
                                left, right = split_bounds(screen)
                                place_window(camera_context, camera_page, left)
                                place_window(context, page, right)
                                self.layout_status = 'Camera left · Odoo right'
                            except Exception:
                                self.layout_status = 'Automatic placement unavailable. Snap camera left and Odoo right; following still works.'
                        if not self.following or time.monotonic() < next_change:
                            continue
                        # Keep queued views during manual login. Auto-follow resumes
                        # when login finishes, without another button click.
                        if '/web/login' in page.url or '/web/database/' in page.url:
                            self.status = 'Sign in to Odoo; following resumes automatically'
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
                                    page.reload(wait_until='domcontentloaded', timeout=20000)
                            else:
                                page.goto(url, wait_until='domcontentloaded', timeout=20000)
                            if '/web/login' in page.url or '/web/database/' in page.url:
                                with self.lock:
                                    self.pending.appendleft(target)
                                self.status = 'Sign in to Odoo; following resumes automatically'
                                continue
                            with self.lock:
                                self.shown = target
                                self.last_event = (target['mission_id'], target['event_id'])
                            next_change = time.monotonic() + self.hold_seconds
                            self.status = 'Showing ' + description
                        except Exception:
                            self.follow(False)
                            self.status = 'Odoo view could not load. Check the window, then enable Follow Odoo again.'
                finally:
                    if camera_context:
                        camera_context.close()
                    if context:
                        context.close()
        except Exception as exc:
            self.launch_failed = True
            self.launch_error = error_text(exc)
            self.status = 'Browser unavailable: ' + self.launch_error
        finally:
            self.available = False
            self.following = False
