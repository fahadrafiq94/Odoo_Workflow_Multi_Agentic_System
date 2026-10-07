"""Offline dashboard/event tests: python test_agent_view.py (no ERP/model calls)."""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from erp_bar.agent_view.server import Session, make_server, run_demo
from erp_bar.runtime.events import agent_scope, emit, event_sink, observed_model, observed_tool


class EventTests(unittest.TestCase):
    def test_tool_events_surround_execution_and_do_not_publish_raw_errors(self):
        captured = []
        @observed_tool
        def read_stock():
            self.assertEqual(captured[-1]["kind"], "tool_start")
            return {"ok":False, "error":"password=private", "available_qty":0}
        with event_sink(captured.append), agent_scope("inventory_agent"):
            result = read_stock()
        self.assertFalse(result["ok"])
        self.assertEqual([e["kind"] for e in captured], ["tool_start","tool_end"])
        self.assertEqual(captured[0]["agent"], "inventory_agent")
        self.assertNotIn("private", json.dumps(captured))

    def test_broken_observer_cannot_repeat_or_fail_tool(self):
        calls=[]
        @observed_tool
        def write():
            calls.append(1)
            return {"ok":True}
        def broken(event):
            raise RuntimeError("UI disconnected")
        with event_sink(broken):
            self.assertTrue(write()["ok"])
        self.assertEqual(calls,[1])

    def test_model_reports_waiting_before_reply_and_only_explicit_summary(self):
        captured=[]
        @observed_model
        def model():
            self.assertEqual(captured[-1]["kind"], "thinking")
            return '<think>private chain</think>{"action":"GET_AVAILABLE_STOCK","reason":"Check stock using super-secret."}'
        with patch.dict("os.environ", {"ODOO_PASSWORD":"super-secret"}), event_sink(captured.append):
            model()
        content=json.dumps(captured)
        self.assertNotIn("private chain", content)
        self.assertNotIn("super-secret", content)
        self.assertFalse(captured[-1]["validated"])

    def test_sinks_do_not_leak_between_runs(self):
        first,second=[],[]
        with event_sink(first.append):
            emit("first")
            with event_sink(second.append):
                emit("second")
            emit("third")
        emit("ignored")
        self.assertEqual([e["kind"] for e in first],["first","third"])
        self.assertEqual([e["kind"] for e in second],["second"])

    def test_demo_never_needs_erp_or_llm_and_labels_every_event(self):
        session=Session()
        session.mission_id="MISSION-DEMO"
        with patch("erp_bar.agent_view.server.time.sleep"), event_sink(session.publish):
            run_demo(session)
        events=session.snapshot()["events"]
        self.assertTrue(all(event["demo"] for event in events))
        self.assertEqual(events[-1]["status"],"DELIVERED")
        self.assertTrue(any(e["kind"]=="handoff" and e["target"]=="purchase_agent" for e in events))


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.release=threading.Event()
        self.session=Session(worker=lambda _:self.release.wait(5))
        self.server=make_server(self.session,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.port=self.server.server_port

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def request(self, method, path, body=None, headers=None):
        conn=http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        conn.request(method,path,json.dumps(body) if body is not None else None,headers or {})
        response=conn.getresponse()
        status,payload=response.status,response.read()
        conn.close()
        return status,payload

    def start(self, request_id="test-request-001"):
        return self.request("POST","/api/missions",{"product":"Lemonade","quantity":1,"request_id":request_id},
                            {"X-ERP-Bar-Token":self.session.token})

    def test_local_assets_and_initial_state(self):
        status,body=self.request("GET","/")
        self.assertEqual(status,200)
        self.assertIn(b'id="feed"',body)
        status,body=self.request("GET","/api/state")
        self.assertEqual(json.loads(body)["mode"],"demo")

    def test_post_requires_token_and_same_origin(self):
        self.assertEqual(self.request("POST","/api/missions",{})[0],403)
        self.assertEqual(self.request("POST","/api/missions",{},
                         {"X-ERP-Bar-Token":self.session.token,"Origin":"https://other.example"})[0],403)
        self.assertFalse(self.session.busy)

    def test_no_path_traversal_or_foreign_host(self):
        self.assertEqual(self.request("GET","/../../.env")[0],404)
        self.assertEqual(self.request("GET","/api/state",headers={"Host":"attacker.example"})[0],403)

    def test_idempotent_retry_and_no_overlapping_mission(self):
        status,first=self.start()
        self.assertEqual(status,202)
        status,second=self.start()
        self.assertEqual(json.loads(first),json.loads(second))
        self.assertEqual(self.start("different-request")[0],409)
        self.assertEqual(sum(e["kind"]=="mission_start" for e in self.session.events),1)

    def test_invalid_requests_do_not_start_work(self):
        for qty in (0,-1,float("inf"),True):
            status,_=self.request("POST","/api/missions",{"product":"Lemonade","quantity":qty,"request_id":"bad-request"},
                                  {"X-ERP-Bar-Token":self.session.token})
            self.assertEqual(status,400)
        self.assertFalse(self.session.busy)

    def test_event_stream_replays_without_restarting_work(self):
        self.start()
        self.session.publish({"kind":"thinking","agent":"supervisor"})
        for _ in range(2):
            conn=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
            conn.request("GET","/api/events")
            response=conn.getresponse()
            self.assertEqual(response.readline().strip(),b"event: snapshot")
            snapshot=json.loads(response.readline().decode().removeprefix("data: "))
            self.assertEqual(len(snapshot["events"]),2)
            self.assertTrue(snapshot["busy"])
            response.close();conn.close()
        self.assertEqual(len(self.session.requests),1)

    def test_demo_controls_are_authenticated_validated_and_replayed(self):
        path = "/api/demo-control"
        headers = {"X-ERP-Bar-Token": self.session.token}
        self.assertEqual(self.request("POST", path, {"paused": True, "speed": 1})[0], 403)
        self.assertEqual(self.request("POST", path, {"paused": True, "speed": 0}, headers)[0], 400)
        self.assertEqual(self.request("POST", path, {"paused": True, "speed": 2}, headers)[0], 200)
        snapshot = json.loads(self.request("GET", "/api/state")[1])
        self.assertTrue(snapshot["demo_paused"])
        self.assertEqual(snapshot["demo_speed"], 2)
        self.assertEqual(snapshot["events"][-1]["kind"], "demo_control")
        self.session.live = True
        self.assertEqual(self.request("POST", path, {"paused": False, "speed": 1}, headers)[0], 400)

    def test_pause_blocks_demo_until_resume(self):
        self.session.control_demo(True, 1)
        completed = threading.Event()
        worker = threading.Thread(target=lambda: (self.session.demo_wait(0.1), completed.set()), daemon=True)
        worker.start()
        try:
            self.assertFalse(completed.wait(0.2))
            self.session.control_demo(False, 4)
            self.assertTrue(completed.wait(1))
        finally:
            self.session.control_demo(False, 1)
            worker.join(1)


if __name__=="__main__":
    unittest.main(verbosity=2)
