"""Pinned browser-only detector assets; downloaded once and served from localhost."""
from pathlib import Path
import os
import threading
from urllib.request import urlopen

ROOT = Path(__file__).parent / 'camera_assets'
BASE = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.21/'
ASSETS = {
    'vision_bundle.mjs': (BASE + 'vision_bundle.mjs', 'text/javascript'),
    **{f'wasm/{name}': (BASE + 'wasm/' + name, 'application/wasm' if name.endswith('.wasm') else 'text/javascript')
       for name in ('vision_wasm_internal.js', 'vision_wasm_internal.wasm',
                    'vision_wasm_nosimd_internal.js', 'vision_wasm_nosimd_internal.wasm')},
    'face_landmarker.task': ('https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', 'application/octet-stream'),
}

class CameraAssets:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.state = 'loading'
        self.message = 'Preparing smile detection (first run downloads the model).'
        self.thread = None

    def snapshot(self):
        with self.lock:
            return {'state': self.state, 'message': self.message}

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self.prepare, daemon=True)
            self.thread.start()

    def prepare(self):
        try:
            for name, (url, _) in ASSETS.items():
                target = self.root / name
                if target.is_file() and target.stat().st_size > 1024:
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + f'.{os.getpid()}.download')
                try:
                    with urlopen(url, timeout=30) as response, temporary.open('wb') as out:
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > 40 * 1024 * 1024:
                                raise ValueError('Unexpected camera asset size')
                            out.write(chunk)
                    if total <= 1024:
                        raise ValueError('Incomplete camera asset')
                    if name.endswith('.wasm'):
                        with temporary.open('rb') as check:
                            if check.read(4) != b'\x00asm':
                                raise ValueError('Invalid WebAssembly asset')
                    temporary.replace(target)
                finally:
                    temporary.unlink(missing_ok=True)
            with self.lock:
                self.state, self.message = 'ready', 'Smile detection ready.'
        except Exception as exc:
            with self.lock:
                self.state = 'error'
                self.message = f'Camera model setup failed ({type(exc).__name__}). Run setup_dashboard_camera.py, then restart the dashboard.'
            print(self.message, flush=True)

    def asset(self, name):
        if name not in ASSETS or self.snapshot()['state'] != 'ready':
            return None
        return self.root / name, ASSETS[name][1]
