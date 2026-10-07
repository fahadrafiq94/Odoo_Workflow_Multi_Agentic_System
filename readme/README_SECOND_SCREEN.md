# ERP_BAR: second computer, smile camera and Odoo display

This update connects your existing agent dashboard on Computer A to a local
camera/customer screen on Computer B. The Odoo window is a separate real browser
window on Computer B. Place it beside the customer screen, or on another monitor.

## What is implemented

- Your MediaPipe approach: average mouthSmileLeft/mouthSmileRight, five-frame
  smoothing, threshold 0.75 and 15-second cooldown. A short 0.6-second hold and
  explicit Next customer/relaxed-face step prevent repeated orders from one smile.
- One smile creates one mission for exactly one configured existing product.
- Agent activity, customer outcome and record focus are read from the main system.
- The Odoo browser follows product, purchase-order, sales-order and delivery views.
  It opens known records and refreshes after successful tool results. It does not
  duplicate ERP writes through clicks, fill order forms, or pretend to type.
- Product/supplier creation, invoicing and pricing policies are unchanged. This
  is the existing one-unit sales workflow, not a new free-of-charge pricing policy.
- Camera frames are processed on Computer B and served only to its localhost
  browser. They are not saved, sent to Computer A or sent to Ollama.

## 1. Apply on Computer A (the existing ERP_BAR/Odoo/Ollama workflow computer)

Stop run_agent_view.py. Extract this archive into your existing ERP_BAR root.
Keep .env. The existing UI and its reading-speed controls are unchanged.

Replaced:
- run_agent_view.py
- src/erp_bar/runtime/events.py

Added:
- src/erp_bar/agent_view/companion_gateway.py
- customer_screen/ (copy this whole directory to Computer B)
- test_second_screen.py
- README_SECOND_SCREEN.md

The second-screen listener is opt-in. Without --companion-host, the previous
loopback-only agent dashboard works as before.

## 2. First try a demo

Find Computer A's private IPv4 address with `ipconfig` on Windows. The addresses
below are EXAMPLES; substitute the addresses used by your computers.

On Computer A, in ERP_BAR:

```powershell
uv run python run_agent_view.py --demo --companion-host 192.168.1.20
```

For a same-computer test use `--companion-host 127.0.0.1` instead.

The runner creates `companion_pairing.json` beside run_agent_view.py. Copy that
file privately into the customer_screen folder on Computer B. This file contains
an access token; do not publish it or include it in source control. The token is
reused across restarts. Main-system request IDs are retained in
`companion_state/requests.sqlite3`; keep this ledger when updating the project.

On Computer B, inside customer_screen, a dependency-free simulated-camera preview
can run with your existing Python:

```powershell
python run_customer_screen.py --demo-camera
```

Open http://127.0.0.1:8770. Select Start camera, Next customer, then Simulate smile.
Computer A should start exactly one demo mission. The customer screen shows its
final result. Odoo navigation is intentionally unavailable for demo record IDs.

## 3. Set up the real webcam on Computer B

The camera app has its own Python environment. It uses Python 3.12; it does not
change the main project's Python environment.

From customer_screen:

```powershell
uv sync --python 3.12
uv run python -m playwright install chromium
```

Copy `face_landmarker.task` from your already-working smile detector into
customer_screen (beside run_customer_screen.py). The camera model is not included
in this archive. Its official download URL is:

https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

If needed, download it in PowerShell:

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' -OutFile face_landmarker.task
```

Settings in companion_pairing.json:

| Setting | Purpose |
| --- | --- |
| brain_url | Computer A's paired endpoint, e.g. http://192.168.1.20:8766 |
| token | Generated pairing token; leave unchanged |
| odoo_url | Odoo base URL accessible from Computer B; no password or /web suffix |
| camera_index | 0 by default; change if another camera is needed |
| model_path | face_landmarker.task, relative to customer_screen, or an absolute path |
| browser_channel | chromium by default; msedge or chrome can use an installed browser |

## 4. Run the real workflow

On Computer A:

```powershell
uv run python run_agent_view.py --live --companion-host 192.168.1.20 --odoo-display-url http://192.168.1.30:8069 --smile-product Lemonade
```

Use the exact existing product name/SKU. Replace the Odoo URL with your actual
address. If Odoo is also on Computer A, that address may use the same IP. A URL
containing localhost points to the computer opening it, so do not copy a
localhost Odoo URL to Computer B unless Odoo actually runs there.

Copy the updated companion_pairing.json to Computer B before starting its app.
On Computer B, inside customer_screen:

```powershell
uv run python run_customer_screen.py
```

In the customer screen:

1. Select Open Odoo window. A dedicated browser profile opens.
2. Sign in to Odoo manually and select the same database/company as the agents.
   The account needs access to the product, sales, purchasing and inventory views.
3. Select Follow Odoo. This only navigates/refreshes; it never clicks Create,
   Confirm or Validate. Pause following before manually editing a record.
4. Arrange the customer window and Odoo window side by side (Windows Snap works).
5. Select Start camera, then Next customer. Look at the camera with a relaxed
   expression and then smile. Camera access is through local Python/OpenCV.
6. Watch the main agent screen, customer message and Odoo records update. Start
   another customer only after the current request ends and the cooldown expires.

The Odoo view follows the latest real tool event, not the main dashboard's
optionally delayed reading-speed playback. Fast events may coalesce between
polls; the browser shows the current record state, not a historical recording of
keystrokes. Before a create result supplies an ID it opens the corresponding
standard Odoo list action. Purchase receipt processing is shown on the purchase
order; outbound fulfillment is shown on its stock picking.

## Connections and sign-in

The agent dashboard stays on Computer A at 127.0.0.1:8765. The paired API listens
only on the private IP you pass, port 8766. The customer screen stays on Computer
B at 127.0.0.1:8770. Odoo retains its own server URL and authentication.

Use this pairing over a trusted private LAN. HTTP on port 8766 is authenticated
but not encrypted; use an encrypted tunnel/VPN if the network is not trusted.
Do not expose the paired port to the public internet. Odoo credentials are never
put into the pairing file. Its browser cookies stay in Computer B's private
`customer_state/odoo_browser_profile` directory.

If Windows Firewall blocks Computer A's port, allow TCP 8766 on its Private
network profile for Computer B's IP only. Do not open the local dashboard port
8765. Both computers must be able to reach the configured Odoo URL.

## Recovery and duplicate prevention

The client persists the request ID BEFORE sending it. Retry the same request
reuses that ID; refreshing or losing a response cannot deliberately create a
second order. The main system also persists accepted/uncertain request IDs.
Overlapping missions are rejected, and the paired endpoint never accepts a
client-selected quantity or arbitrary product.

If a response was lost, use Retry the same request. If Computer A restarted or
its mission history has already moved on, the client blocks the next customer
until staff reconciles the recorded mission/order. This update does not add
workflow resume after a process restart. Do not delete the main request ledger
to bypass that block. After staff has reconciled an uncertain request, stop the
customer app, archive its customer_state/pending_request.json and restart it.

Closing either browser does not cancel a mission already running on Computer A.
Stop camera releases it. Ctrl+C stops the local customer process; existing main
missions continue.

## Troubleshooting

- Main system offline: check pairing URL/token, private IP, port and firewall.
- Camera off/error: close other webcam apps, check camera_index, confirm the
  model file exists and install dependencies in the separate Python 3.12 project.
- No smile trigger: select Next customer, start with a relaxed face, then hold a
  smile briefly. The detector needs a full five-frame history and a fresh main
  connection. A running/uncertain mission blocks new requests.
- Odoo does not follow: sign in first, check database/company and access rights,
  then select Follow Odoo. If redirected to login, complete login and re-enable.
- Custom Odoo navigation: standard /web record links and standard window actions
  are used. Your Odoo version/custom modules may need route adjustments; actual
  record navigation still needs verification on your instance.
- Demo: simulated IDs never open real Odoo records; --demo-camera never opens the
  webcam and its Simulate smile button is disabled against a live main system.

## Validation in the development environment

191 offline tests passed: 32 focused second-screen/dashboard tests plus 159
workflow regressions. They cover smile gates, duplicate/restart handling,
authentication, request scope, Odoo target mapping, manual-login/follow behavior,
refresh-without-writes and existing agent behavior.

A browser test used the actual paired HTTP servers and a simulated mission:
arm -> simulated smile -> one-unit mission -> refresh -> customer outcome.
Desktop and mobile layout checks passed. Browser tests did not access a webcam,
Ollama or an actual Odoo instance. Physical camera detection, LAN/firewall and
live Odoo navigation must be checked on your two computers.

Offline checks on Computer A:

```powershell
uv run python test_second_screen.py
uv run python test_agent_view.py
```

## Implementation references

- Original supplied smile_detector_llm_hud(6).py (detector settings and score).
- MediaPipe Face Landmarker Python guide:
  https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker/python
- Playwright persistent browser context API:
  https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context
- Odoo window action reference:
  https://www.odoo.com/documentation/19.0/developer/reference/backend/actions.html
