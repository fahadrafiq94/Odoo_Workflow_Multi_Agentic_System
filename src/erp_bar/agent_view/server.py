"""Single-mission, loopback-only dashboard with replayable server-sent events."""
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import secrets
import threading
import time
import traceback
from urllib.parse import urlsplit
from uuid import uuid4

from erp_bar.runtime.events import agent_scope, emit, event_sink, mission_snapshot

STATIC = Path(__file__).with_name("static")


class Session:
    def __init__(self, live=False, worker=None):
        self.live = live
        self.token = secrets.token_urlsafe(32)
        self.condition = threading.Condition(threading.RLock())
        self.events = deque(maxlen=2000)
        self.requests = {}
        self.sequence = 0
        self.busy = False
        self.demo_paused = False
        self.demo_speed = 1.0
        self.mission_id = None
        self.product, self.quantity = "Lemonade", 1
        self.worker = worker or (run_live if live else run_demo)
        self.event_listeners = []
        self.before_work = None
        self.after_event = None
        self.expected_product_id = None

    def publish(self, event):
        with self.condition:
            self.sequence += 1
            event = {**event, "id": self.sequence, "mission_id": self.mission_id,
                     "time": datetime.now(timezone.utc).isoformat(), "demo": not self.live}
            if event.get("kind") == "model_stream_end":
                # Keep the full final generation, not thousands of token events.
                # Connected clients get deltas; reconnecting clients get this snapshot.
                self.events = deque((item for item in self.events if not (
                    item.get("kind") == "model_stream" and item.get("stream_id") == event.get("stream_id")
                    and item.get("agent") == event.get("agent"))), maxlen=2000)
            self.events.append(event)
            # Listeners only persist public workflow events. Browser waits happen
            # after releasing this lock so SSE and acknowledgements can proceed.
            for listener in tuple(self.event_listeners):
                listener(event)
            self.condition.notify_all()
        if self.after_event:
            self.after_event(event)

    def snapshot(self):
        with self.condition:
            return {"mode": "live" if self.live else "demo", "busy": self.busy,
                    "demo_paused": self.demo_paused, "demo_speed": self.demo_speed,
                    "mission_id": self.mission_id, "product": self.product, "quantity": self.quantity,
                    "last_id": self.sequence, "events": list(self.events)}

    def control_demo(self, paused, speed):
        if self.live:
            raise ValueError("Presentation controls are available in demo mode only.")
        if not isinstance(paused, bool) or isinstance(speed, bool) or speed not in (0.5, 1, 2, 4):
            raise ValueError("Choose a valid demo speed and pause state.")
        with self.condition:
            self.demo_paused, self.demo_speed = paused, float(speed)
            self.publish({"kind": "demo_control", "paused": paused, "speed": speed})

    def demo_wait(self, seconds=3):
        # Short slices let presentation controls take effect during a reading beat.
        remaining = seconds
        while remaining > 0:
            with self.condition:
                while self.demo_paused:
                    self.condition.wait()
                speed = self.demo_speed
            time.sleep(0.1)
            remaining -= 0.1 * speed

    def start(self, product, quantity, request_id, expected_product_id=None):
        if not isinstance(product, str) or not product.strip() or len(product) > 120 or any(ord(c) < 32 for c in product):
            raise ValueError("Enter a product name or SKU (up to 120 characters).")
        if isinstance(quantity, bool) or not isinstance(quantity, (int, float)) or not math.isfinite(quantity) or quantity <= 0:
            raise ValueError("Quantity must be a finite, positive number.")
        if not isinstance(request_id, str) or not 8 <= len(request_id) <= 80:
            raise ValueError("A valid request identifier is required.")
        with self.condition:
            if request_id in self.requests:
                return self.requests[request_id]
            if self.busy:
                raise RuntimeError("A mission is already running. Wait for its final result.")
            self.busy = True
            self.mission_id = "MISSION-" + uuid4().hex[:12].upper()
            self.product, self.quantity = product.strip(), quantity
            self.expected_product_id = expected_product_id
            self.events.clear()
            self.requests[request_id] = self.mission_id
            if len(self.requests) > 100:
                del self.requests[next(iter(self.requests))]
            self.publish({"kind": "mission_start", "agent": "supervisor", "product": self.product,
                          "quantity": quantity, "message": f"Request received: {quantity:g} × {self.product}."})
            threading.Thread(target=self._work, daemon=True).start()
            return self.mission_id

    def _work(self):
        with event_sink(self.publish):
            try:
                if self.before_work:
                    self.before_work(self.mission_id)
                self.worker(self)
            except Exception:
                traceback.print_exc()
                emit("mission_end", status="FAILED", message="The workflow could not start. Check the local console.",
                     customer_message="We could not process your request. Please ask a staff member for help.")
            finally:
                with self.condition:
                    self.busy = False
                    self.publish({"kind": "session_idle", "agent": "supervisor"})


def run_live(session):
    # Lazy imports keep the visual preview independent of Odoo/Ollama packages.
    from erp_bar.domain.mission import OrderMission, MissionStatus
    from erp_bar.domain.policies import DEFAULT_BUSINESS_POLICY
    from erp_bar.odoo.client import get_odoo_bridge
    from erp_bar.orchestrator.failure_handling import finalize_failed_mission
    from erp_bar.orchestrator.graph import build_graph
    mission = OrderMission(mission_id=session.mission_id,
                           customer_request=f"I want {session.quantity:g} units of {session.product}")
    state = {"mission": mission, "supervisor_decision": None, "last_agent_decision": None}
    try:
        emit("connecting", message="Connecting to the configured Odoo warehouse and customer.")
        bridge = get_odoo_bridge()
        configuration = bridge.validate_runtime_configuration()
        mission.customer_id = configuration["customer_id"]
        verified_product_id = None
        for update in build_graph().stream(state, stream_mode="updates",
                                          config={"recursion_limit": DEFAULT_BUSINESS_POLICY.max_graph_steps}):
            for value in update.values():
                if isinstance(value, dict):
                    state.update(value)
                    items = state["mission"].requested_items
                    if items:
                        if (len(items) != 1 or items[0].product_query.strip().casefold() != session.product.casefold()
                                or not math.isclose(items[0].requested_qty, session.quantity, rel_tol=1e-9, abs_tol=1e-9)):
                            raise ValueError("Parsed product or quantity differs from the submitted request.")
                        product_id = items[0].product_id
                        if product_id is not None and session.expected_product_id is not None and product_id != session.expected_product_id:
                            raise ValueError("Resolved product differs from the product accepted for this smile request.")
                        if verified_product_id is not None and product_id != verified_product_id:
                            raise ValueError("Resolved product ID changed during the mission.")
                        if product_id is not None and verified_product_id is None:
                            rows = bridge.execute("product.product", "read", [product_id], fields=["name", "default_code", "barcode"])
                            if not rows or not any(isinstance(rows[0].get(key), str) and rows[0][key].strip().casefold() == session.product.casefold()
                                                   for key in ("name", "default_code", "barcode")):
                                raise ValueError("Resolved product is not an exact match for this request.")
                            verified_product_id = product_id
        mission = state["mission"]
        if not mission.is_terminal():
            state.update(finalize_failed_mission(state, "The graph ended without a verified final outcome."))
    except Exception as exc:
        traceback.print_exc()
        state.update(finalize_failed_mission(state, f"Dashboard runner stopped: {type(exc).__name__}: {exc}"))
    mission = state["mission"]
    message = (f"Delivered {session.quantity:g} × {session.product}." if mission.status == MissionStatus.DELIVERED
               else mission.customer_message or "This mission could not be completed.")
    emit("mission_end", message=message, **mission_snapshot(mission))


def run_demo(session):
    """Explicitly simulated events; never imports or calls ERP/model clients."""
    def wait():
        session.demo_wait()
    def explain(reason, response):
        stream_id = secrets.token_hex(8)
        output = json.dumps(response, ensure_ascii=False, indent=2)
        for phase, content in (("thinking", reason), ("output", output)):
            for start in range(0, len(content), 24):
                emit("model_stream", stream_id=stream_id, phase=phase, delta=content[start:start + 24])
                session.demo_wait(0.18)
        emit("model_stream_end", stream_id=stream_id, thinking=reason, output=output, interrupted=False)
        emit("model_complete", stream_id=stream_id, duration=0.6)
        return stream_id
    def delegate(target, capability, reason):
        with agent_scope("supervisor"):
            emit("agent_start", message="Reviewing the latest mission outcome.")
            emit("thinking", message="Selecting the next specialist."); wait()
            call_id = explain(reason, {"next_agent": target, "capability": capability, "objective": reason, "reason": reason})
            emit("proposal", stream_id=call_id, action=capability, message=reason, validated=False)
            wait()
            emit("instruction", target=target, action=capability, objective=reason,
                 message="The latest mission result supports this next task.", validated=True)
            wait()
            emit("agent_end", message="Routing decision complete.")
            emit("handoff", source="supervisor", target=target, action=capability, message=reason); wait()
    def task(agent, steps, status, **records):
        with agent_scope(agent):
            emit("agent_start", message="Reviewing the assigned task.")
            for action, reason, result in steps:
                emit("thinking", message="Selecting the next action from verified facts."); wait()
                call_id = explain(reason, {"action": action.upper(), "arguments": {}, "reason": reason})
                emit("proposal", stream_id=call_id, action=action.upper(), message=reason, validated=False)
                wait()
                emit("tool_start", action=action, message=action.replace("_", " ").capitalize()); wait()
                emit("tool_end", action=action, ok=True, result=result, duration=0.6, message="Simulated result returned.")
                wait()
            replies = {
                "PROCUREMENT_REQUIRED": f"Stock checked: no free units are available. We need {session.quantity:g} units from Purchase.",
                "GOODS_RECEIVED": f"Purchase order #27 is confirmed and {session.quantity:g} units have been received. Inventory can verify availability.",
                "STOCK_READY": f"Stock verified: {session.quantity:g} units are available for this order.",
                "SALES_ORDER_CONFIRMED": "Sales order #42 is confirmed. Inventory can now verify its reservations and deliver it.",
                "DELIVERED": f"Delivery #63 is done. {session.quantity:g} units have been delivered.",
            }
            emit("agent_end", status=status, message=replies.get(status, "Assigned task completed."), **records)
            wait()
            if status != "DELIVERED":
                emit("handoff", source=agent, target="supervisor", message="Return verified results to the supervisor."); wait()
    delegate("sales_agent", "INTERPRET_DEMAND", "First, identify the product and quantity in the customer request.")
    with agent_scope("sales_agent"):
        emit("agent_start", message="Interpreting the customer request.")
        emit("thinking", message="Identifying the requested product and quantity."); wait()
        explain("The customer request identifies the product and quantity. Return that structured demand to the supervisor.",
                {"product_query": session.product, "requested_qty": session.quantity, "is_ambiguous": False, "ambiguity_reason": None})
        emit("agent_end", status="NEW", message=f"Request understood: {session.quantity:g} units of {session.product}.")
        wait()
        emit("handoff", source="sales_agent", target="supervisor", message="Structured demand is ready.")
        wait()
    delegate("inventory_agent", "CHECK_INVENTORY", "The request is understood. Resolve the product and check free warehouse stock.")
    task("inventory_agent", [
        ("search_product", "Find the existing product before checking stock.", {"product_id":15}),
        ("get_available_stock", "Check unreserved stock in the configured warehouse.", {"available_qty":0}),
    ], "PROCUREMENT_REQUIRED")
    delegate("purchase_agent", "PROCURE_SHORTAGE", "A stock shortage is verified. Ask Purchase to source the required units.")
    task("purchase_agent", [
        ("get_product_vendors", "Find an existing configured supplier.", {"supplier_count":1}),
        ("create_purchase_order", "Purchase the verified shortage from the selected supplier.", {"purchase_order_id":27}),
        ("confirm_purchase_order", "Confirm the purchase order returned by the tool.", {"purchase_order_id":27,"state":"purchase"}),
        ("receive_purchase", "Receive the purchased units in the demonstration workflow.", {"received_qty":session.quantity}),
    ], "GOODS_RECEIVED", purchase_order_ids=[27])
    delegate("inventory_agent", "VERIFY_STOCK", "Goods were received. Independently verify that stock is ready for this order.")
    task("inventory_agent", [("get_available_stock", "Read fresh warehouse availability after receipt.", {"available_qty":session.quantity})], "STOCK_READY")
    delegate("sales_agent", "CREATE_SALES_ORDER", "Stock readiness is verified. Create and confirm the customer's order.")
    task("sales_agent", [
        ("get_available_stock", "Recheck stock immediately before creating the order.", {"available_qty":session.quantity}),
        ("create_sales_order", "Create the customer order; Python enforces the cost-plus-40% price floor.", {"sales_order_id":42,"unit_price":3.5}),
        ("get_available_stock", "Recheck availability before confirmation.", {"available_qty":session.quantity}),
        ("confirm_sales_order", "Confirm the verified customer order.", {"sales_order_id":42,"state":"sale"}),
    ], "SALES_ORDER_CONFIRMED", sales_order_id=42)
    delegate("inventory_agent", "FULFILL_DELIVERY", "The order is confirmed. Verify its delivery and reservations before fulfillment.")
    task("inventory_agent", [
        ("get_delivery", "Find the delivery linked to the confirmed order.", {"picking_id":63}),
        ("check_delivery_availability", "Verify stock reserved for this delivery.", {"reserved_qty":session.quantity}),
        ("validate_delivery", "Complete the delivery after availability is verified.", {"picking_id":63,"state":"done","delivered_qty":session.quantity}),
    ], "DELIVERED", sales_order_id=42, purchase_order_ids=[27], delivery_id=63)
    emit("mission_end", status="DELIVERED", sales_order_id=42, purchase_order_ids=[27], delivery_id=63,
         message=f"Demo complete: {session.quantity:g} × {session.product} delivered. No Odoo records were changed.")


def make_server(session, port=8765):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def allowed(self):
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def reply(self, code, body, content_type="application/json; charset=utf-8"):
            payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.allowed():
                return self.reply(403, {"error":"This dashboard is available on localhost only."})
            path = urlsplit(self.path).path
            if path == "/api/state":
                return self.reply(200, {**session.snapshot(), "token":session.token})
            if path == "/api/events":
                return self.stream()
            files = {"/": ("index.html","text/html"), "/app.js": ("app.js","text/javascript"), "/style.css": ("style.css","text/css")}
            if path not in files:
                return self.reply(404, {"error":"Not found"})
            filename, mime = files[path]
            return self.reply(200, (STATIC / filename).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            host = self.headers.get("Host", "")
            if (not self.allowed() or self.headers.get("Origin", "http://" + host) != "http://" + host
                    or not secrets.compare_digest(self.headers.get("X-ERP-Bar-Token", ""), session.token)):
                return self.reply(403, {"error":"Reload the dashboard before starting a mission."})
            if self.path not in ("/api/missions", "/api/demo-control"):
                return self.reply(404, {"error":"Not found"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError("Request size is invalid.")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Expected a request object.")
                if self.path == "/api/demo-control":
                    session.control_demo(data.get("paused"), data.get("speed"))
                    return self.reply(200, {"paused": session.demo_paused, "speed": session.demo_speed})
                mission_id = session.start(data.get("product"), data.get("quantity"), data.get("request_id"))
            except (ValueError, TypeError) as exc:
                return self.reply(400, {"error":str(exc)})
            except RuntimeError as exc:
                return self.reply(409, {"error":str(exc)})
            return self.reply(202, {"mission_id":mission_id})

        def stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            try:
                snapshot = session.snapshot()
                cursor = snapshot["last_id"]
                self.wfile.write(("event: snapshot\ndata: " + json.dumps(snapshot) + "\n\n").encode())
                self.wfile.flush()
                while True:
                    with session.condition:
                        if session.sequence <= cursor:
                            session.condition.wait(timeout=10)
                        events = [event for event in session.events if event["id"] > cursor]
                    if not events:
                        self.wfile.write(b": heartbeat\n\n")
                    for event in events:
                        self.wfile.write((f"id: {event['id']}\ndata: " + json.dumps(event) + "\n\n").encode())
                        cursor = event["id"]
                    self.wfile.flush()
            except (ConnectionError, OSError):
                pass

        def log_message(self, format, *args):
            pass

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
