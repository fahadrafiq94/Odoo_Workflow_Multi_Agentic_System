import {SmileGate} from '/smile-gate.mjs';
const $ = id => document.getElementById(id);
const gate = new SmileGate();
// A reload must not treat an already-held smile as a new customer's expression.
gate.needsNeutral = true;
const storageKey = 'erp-bar-dashboard-smile-v1';
let state, lastState = 0, stream, worker, detectorReady = false, initializing = false;
let frameBusy = false, lastFrame = 0, requestBusy = false, pending = null;
let cameraError = '', storageError = '', reward = '', ownsCamera = false, releaseCamera;
let enabled = false, stopped = false, started = false, detectorTimer;
const video = $('camera-video');
try {
  pending = JSON.parse(localStorage.getItem(storageKey) || 'null');
  const lastSmile = Number(localStorage.getItem(storageKey + '-last-trigger') || 0);
  if (Number.isFinite(lastSmile) && lastSmile > 0) gate.lastTrigger = performance.now() - Math.max(0, Date.now() - lastSmile);
  if (pending && (typeof pending.request_id !== 'string' || !/^[a-zA-Z0-9_-]{16,74}$/.test(pending.request_id)))
    throw new Error('Invalid saved request');
  localStorage.setItem(storageKey + '-check', '1'); localStorage.removeItem(storageKey + '-check');
} catch { storageError = 'Allow site storage, then reload. Automatic orders are paused.'; }

function savePending(value) {
  // Persist before sending; an interrupted acknowledgement must never create a second order.
  try {
    if (value) localStorage.setItem(storageKey, JSON.stringify(value));
    else localStorage.removeItem(storageKey);
    pending = value; return true;
  } catch { storageError = 'Cannot save request recovery information. Automatic orders are paused.'; return false; }
}
async function api(path, body) {
  const response = await fetch(path, {cache: 'no-store', signal: AbortSignal.timeout(5000),
    ...(body ? {method: 'POST', headers: {'Content-Type': 'application/json', 'X-ERP-Bar-Token': state.token}, body: JSON.stringify(body)} : {})});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || 'Request failed');
    error.rejected = data.accepted === false; throw error;
  }
  return data;
}
function eligible() {
  return ownsCamera && detectorReady && !cameraError && !storageError && !pending && !requestBusy &&
    state?.product_ready && state.smile_source === 'dashboard' && !state.busy &&
    performance.now() - lastState < 3500 && !document.hidden && window.erpBarCanAcceptSmile?.() === true;
}
function render() {
  if (!enabled) return;
  if ($('camera-reward').textContent !== reward) $('camera-reward').textContent = reward;
  $('camera-reward').hidden = !reward;
  let message;
  if (cameraError || storageError) message = cameraError || storageError;
  else if (!state || performance.now() - lastState >= 3500) message = 'Reconnecting to the dashboard. New smiles paused.';
  else if (!ownsCamera) message = 'Camera is open in another dashboard tab. Close that tab and reload here.';
  else if (pending?.uncertain) message = 'Order status is uncertain. Ask staff to check before another order.';
  else if (pending && !pending.mission_id) message = 'Smile registered. Confirming your request…';
  else if (state.busy || pending) message = 'The team is working. New smiles paused.';
  else if (!stream) message = 'Allow camera access in this browser to continue.';
  else if (!detectorReady) message = state.assets?.message || 'Starting smile detection…';
  else if (!state.product_ready) message = state.readiness_message;
  else if (window.erpBarCanAcceptSmile?.() !== true) message = 'Waiting for the agent conversation. New smiles paused.';
  else if (gate.needsNeutral) message = 'Relax your smile or step away briefly for the next order.';
  else if (performance.now() - gate.lastTrigger < 15000) message = 'Getting ready for the next customer…';
  else message = gate.since == null ? 'Smile at 75% for a moment to start.' : 'Hold that smile…';
  if ($('camera-status').textContent !== message) $('camera-status').textContent = message;
  $('camera-live').textContent = state?.mode === 'live' ? 'LIVE CAMERA' : 'DEMO CAMERA';
  $('camera-score').textContent = gate.score == null ? '—' : `${Math.round(gate.score * 100)}%`;
  $('camera-meter').style.width = `${Math.round((gate.score || 0) * 100)}%`;
  $('camera-preview').classList.toggle('camera-paused', !eligible());
}
async function submit() {
  if (!eligible()) return;
  // Gate has already consumed this expression. Rejections require a new smile too.
  reward = '';
  try { localStorage.setItem(storageKey + '-last-trigger', String(Date.now())); }
  catch { storageError = 'Allow site storage, then reload. Automatic orders are paused.'; return; }
  if (!savePending({request_id: crypto.randomUUID()})) return;
  window.erpBarSmileRegistered?.();
  await reconcile();
}
function celebrateReward() {
  const layer = $('reward-confetti');
  layer.replaceChildren();
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = ['#96cc64', '#f3c653', '#70b6d8', '#dd91af', '#b89bd6'];
  for (let i = 0; i < 24; i++) {
    const piece = document.createElement('i');
    piece.style.setProperty('--confetti-x', `${(i % 2 ? 1 : -1) * (18 + Math.random() * 85)}px`);
    piece.style.setProperty('--confetti-y', `${-25 - Math.random() * 75}px`);
    piece.style.setProperty('--confetti-turn', `${Math.random() * 540 - 270}deg`);
    piece.style.setProperty('--confetti-delay', `${Math.random() * 120}ms`);
    piece.style.backgroundColor = colors[i % colors.length];
    layer.append(piece);
    piece.addEventListener('animationend', () => piece.remove(), {once: true});
  }
}
async function reconcile() {
  if (!pending || requestBusy || pending.uncertain || !ownsCamera) return;
  requestBusy = true; render();
  try {
    let result = await api('/api/smile-requests/' + pending.request_id);
    if (result.state === 'not_found') {
      // Retry the same identifier only. The backend serializes/rejects busy requests.
      await api('/api/smile', {request_id: pending.request_id});
      result = await api('/api/smile-requests/' + pending.request_id);
    }
    if (result.state === 'uncertain') {
      savePending({...pending, uncertain: true});
    } else if (['accepted', 'completed'].includes(result.state)) {
      const prefix = result.product_info?.simulated ? 'Demo: ' : '';
      const productName = result.product_info?.name || result.product;
      const successful = result.state === 'accepted' || result.final?.status === 'DELIVERED';
      reward = `${prefix}You have won ${/^[aeiou]/i.test(productName) ? 'an' : 'a'} ${productName}!`;
      if (successful && !pending.celebrated) {
        if (savePending({...pending, celebrated: true})) celebrateReward();
      }
      if (result.state === 'completed') {
        if (result.final?.status !== 'DELIVERED') reward = 'The order needs attention. Please ask staff.';
        savePending(null); gate.pause();
      } else savePending({...pending, mission_id: result.mission_id});
    }
  } catch (error) {
    if (error.rejected) { savePending(null); gate.pause(); reward = ''; }
    // Lost responses remain pending; next poll recovers their original identifier.
  } finally { requestBusy = false; render(); }
}
function initDetector() {
  if (!stream || initializing || detectorReady || state?.assets?.state !== 'ready' || cameraError) return;
  initializing = true;
  worker = new Worker('/camera-worker.js');
  const fail = () => {
    clearTimeout(detectorTimer); detectorReady = false; frameBusy = false;
    cameraError = 'Smile detection could not start. Run setup_dashboard_camera.py and reload.';
    worker?.terminate(); render();
  };
  detectorTimer = setTimeout(fail, 60000);
  worker.onerror = fail;
  worker.onmessage = ({data}) => {
    if (data.kind === 'ready') { clearTimeout(detectorTimer); detectorReady = true; render(); }
    if (data.kind === 'error') fail();
    if (data.kind === 'score') {
      frameBusy = false;
      if (gate.update(data.score, performance.now(), eligible())) void submit();
      render();
    }
  };
  worker.postMessage({kind: 'init'});
}
async function frames(now) {
  if (stopped) return;
  if (detectorReady && !frameBusy && !document.hidden && video.readyState >= 2 && now - lastFrame >= 100) {
    frameBusy = true; lastFrame = now;
    try {
      const bitmap = await createImageBitmap(video, {resizeWidth: 480, resizeHeight: Math.round(480 * video.videoHeight / video.videoWidth)});
      if (stopped) bitmap.close();
      else worker.postMessage({kind: 'frame', bitmap, timestamp: now}, [bitmap]);
    } catch { frameBusy = false; }
  }
  requestAnimationFrame(frames);
}
async function startCamera() {
  ownsCamera = true;
  try {
    stream = await navigator.mediaDevices.getUserMedia({video: {width: {ideal: 640}, height: {ideal: 480}, facingMode: 'user'}, audio: false});
    if (stopped) { stream.getTracks().forEach(track => track.stop()); return; }
    video.srcObject = stream; await video.play();
    $('camera-placeholder').hidden = true;
    stream.getVideoTracks()[0].onended = () => { cameraError = 'Camera disconnected. Reconnect it and reload.'; detectorReady = false; render(); };
    initDetector(); requestAnimationFrame(frames);
  } catch (error) {
    cameraError = error.name === 'NotAllowedError' ? 'Allow Camera in this browser’s site settings, then reload.' :
      'Camera unavailable. Connect a webcam and close other apps using it, then reload.';
    render();
  }
}
function acquireCamera() {
  if (!navigator.locks || !navigator.mediaDevices?.getUserMedia) {
    cameraError = 'Open this dashboard in current Chrome or Edge at http://127.0.0.1:8765.'; render(); return;
  }
  navigator.locks.request('erp-bar-dashboard-camera', {ifAvailable: true}, async lock => {
    if (!lock) { render(); return; }
    const held = new Promise(resolve => { releaseCamera = resolve; });
    await startCamera(); await held;
  }).catch(() => { cameraError = 'Camera ownership could not be established. Reload this tab.'; render(); });
}
async function poll() {
  if (stopped) return;
  try {
    state = await api('/api/camera-state'); lastState = performance.now();
    enabled = state.enabled;
    $('dashboard-camera').hidden = !enabled;
    if (!enabled) { $('manual-order').open = true; return; }
    if (!started) { started = true; acquireCamera(); }
    if (state.busy) gate.pause();
    initDetector(); await reconcile();
  } catch { /* Keep preview on; stale connection blocks all new requests. */ }
  render(); setTimeout(poll, 600);
}
document.addEventListener('visibilitychange', () => { if (document.hidden) gate.pause(); });
window.addEventListener('pagehide', () => {
  stopped = true; clearTimeout(detectorTimer); worker?.terminate();
  stream?.getTracks().forEach(track => track.stop()); releaseCamera?.();
});
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
void poll();
