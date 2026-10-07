# Camera + Odoo: the second-screen experience

This update builds on your working agent dashboard. Computer A runs the existing agents/Ollama workflow. Computer B shows the local webcam on the left half of its screen and the real Odoo browser on the right half.

## What you will see

- **Left half:** live camera, smile meter, one-Lemonade request, a Start live mission button, current agent activity and Odoo-follow controls.
- **Right half:** your signed-in Odoo software. During purchasing it opens the purchase order; during sales it opens the sales order; during fulfillment it opens the delivery. Product searches and stock reads show the product/list.
- Both the existing main dashboard button and the new camera-screen button work. Starting the camera arms one smile request automatically if the system is ready. A relaxed face followed by a held smile submits exactly **one Lemonade**.
- After a smile/manual request, choose **Next customer** to re-arm the camera. It does not repeatedly order while somebody keeps smiling. A mission started on the main dashboard also disarms a waiting smile trigger when observed.

The two halves are real browser windows, automatically arranged by the companion app. Odoo remains interactive and uses its own login. The agent tools perform the actual Odoo writes; the display opens records and refreshes after results. It does not replay typing or click Create/Confirm a second time.

## 1. Apply the update on Computer A

Wait for the current mission to finish, then stop `run_agent_view.py`.

Extract the archive into your current ERP_BAR project root. Merge folders and replace included files. Keep your `.env`, existing `companion_pairing.json`, and `companion_state` request ledger. This package does not replace the working agent dashboard frontend or agent logic.

Included main-computer changes:

- `run_agent_view.py`: companion startup options, included for first-time setup.
- `src/erp_bar/agent_view/companion_gateway.py`: fixed one-unit requests and the full sequence of Odoo record targets.
- `customer_screen/`: the complete application to copy to Computer B.

Find Computer A's private IPv4 address with `ipconfig`. Substitute your real addresses below; the example IPs are placeholders.

```powershell
uv run python run_agent_view.py --live --companion-host 192.168.58.78 --odoo-display-url http://192.168.43.155:8069 --smile-product Lemonade
```

`--smile-product` should be the exact existing product name/SKU you already use. It is Lemonade by default. The camera/manual companion request always uses quantity **1**. The main dashboard retains its own product/quantity fields.

The runner creates or updates `companion_pairing.json`. Copy this file privately, together with the entire `customer_screen` folder, to Computer B. Put the pairing file inside that folder, beside `run_customer_screen.py`.

The Odoo URL must be reachable from Computer B and should be the base URL, without `/web`, credentials or query parameters. If Odoo runs on Computer A, use Computer A's LAN address, not `localhost`. The login must use the same Odoo database/company as the agents.

## 2. Set up Computer B

In a terminal inside `customer_screen`:

```powershell
uv sync --python 3.12
uv run python -m playwright install chromium
```

Copy `face_landmarker.task` from your existing smile detector beside `run_customer_screen.py`. The model file is not bundled. If needed, download the official MediaPipe model:

```powershell
Invoke-WebRequest -Uri 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task' -OutFile face_landmarker.task
```

Then run:

```powershell
uv run python run_customer_screen.py
```

The local page opens at `http://127.0.0.1:8770`.

## 3. Arrange the screen and run a mission

1. Wait for **Main system connected** and **LIVE · ODOO**.
2. Click **Open split screen**. A managed camera window opens on the left and a dedicated Odoo window on the right. You may close the original setup tab.
3. Sign in to Odoo manually, selecting the correct database/company. This browser profile remembers the session.
4. In the camera half, click **Follow Odoo**.
5. Either click **Start live mission**, use the button on Computer A's dashboard, or click **Start camera**, relax your face and then hold a smile briefly.
6. Watch the agent activity and the corresponding Odoo records. Select **Next customer** to enable a new smile request after completion.

If automatic placement is unsupported by your window manager, use Windows Snap: camera window on the left, Odoo on the right. Clicking Open split screen again re-applies positioning. Pause following before manually editing an Odoo record.

## Following fast agent actions

The companion reads actual workflow events, independently of the main dashboard's reading-speed playback. It keeps transitions between distinct records, so a purchase record is not discarded just because a sales step follows quickly. Adjacent updates of the same record are coalesced, and successful results refresh that view.

Each displayed record stays visible for about 1.2 seconds. If agents run faster, the camera screen reports how many record views are waiting. The display then catches up. A new mission clears the old display queue. Pausing and resuming Follow Odoo jumps to the latest known record.

**Odoo shows the current database state**, not historical screenshots. A rapidly confirmed order may already appear confirmed by the time its page opens. The display cannot reconstruct the intermediate draft state. Purchase receipts are followed on the related purchase order; outbound deliveries are shown on their stock picking.

## Optional pairing settings on Computer B

Edit `companion_pairing.json` and restart the customer process after changing settings:

| Setting | Default / purpose |
| --- | --- |
| `camera_index` | `0`; change for a different webcam |
| `model_path` | `face_landmarker.task`, relative to customer_screen |
| `browser_channel` | `chromium`; `msedge` or `chrome` can use an installed browser |
| `display_hold_seconds` | `1.2`; accepted range 0–5 seconds between record views |
| `odoo_url` | Odoo base URL reachable from Computer B |

Leave the generated pairing token unchanged. Camera frames stay on Computer B; the main computer receives the request and returns workflow activity. Odoo credentials are entered only in the Odoo browser.

## Demo without real orders

On Computer A:

```powershell
uv run python run_agent_view.py --demo --companion-host 192.168.1.20
```

Copy the pairing file to Computer B, then run there:

```powershell
uv run python run_customer_screen.py --demo-camera
```

Use **Run demo mission**, or **Start camera → Simulate smile**. This validates the two-computer request path without a webcam or Odoo writes. Odoo opening/following is disabled for simulated record IDs. You can test on one computer by using `127.0.0.1` for `--companion-host`.

## Connection and recovery

- Computer B must reach Computer A's paired port **8766** and the Odoo URL. If needed, allow TCP 8766 in Computer A's Windows Firewall on the Private profile for Computer B's address.
- The existing main dashboard remains local on port 8765; the camera page remains local on 8770.
- Use the paired API on a trusted private LAN or encrypted tunnel. The pairing file contains its access token.
- Both launch methods share the main mission lock. A running mission blocks another request. The companion saves its request ID before sending; **Retry the same request** reuses it.
- If a request's outcome is uncertain, reconcile its mission/order before starting another customer. Keep the ledger and pending-request file during updates.
- No smile trigger: check the connection, camera/model file, and whether the camera is armed; relax your face before smiling. Detection uses the existing 75% threshold, five-frame smoothing, 0.6-second hold and 15-second cooldown.
- If the camera starts while disconnected/busy, click Next customer after the system becomes ready.
- If Odoo redirects to login or a page fails, complete sign-in/check the window, then re-enable Follow Odoo. Actual routes and permissions may require adjustment on customized Odoo deployments.
- Closing a window does not cancel an accepted mission. Ctrl+C stops the companion; the main workflow continues.

## Verification

Passed: 19 existing companion tests and 12 new split-screen/HTTP integration tests. These cover manual and smile triggers, the main dashboard button, one-unit scope, duplicate handling, authentication, recorded-target queues, login/follow behavior and left/right window bounds using a mocked browser. Frontend checks verify control wiring, busy states, record labels, queue information and demo gating. Python compilation and JavaScript syntax pass.

Physical webcam detection, rendered screen layout, actual window placement and navigation in your Odoo instance still need an on-device check. No live Odoo writes or real camera access were performed during these tests.

Offline checks from ERP_BAR:

```powershell
uv run python test_second_screen.py
uv run python test_split_screen.py
```
