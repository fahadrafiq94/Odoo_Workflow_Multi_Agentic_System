"""Offline second-screen checks; no webcam, Odoo writes or browser login."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import types
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'customer_screen')]
from erp_bar.agent_view.server import Session
from erp_bar.agent_view.companion_gateway import CompanionGateway, make_companion_server, display_target
from erp_bar.runtime.events import event_sink, observed_tool
from erp_bar_customer.app import CustomerApp
from erp_bar_customer.smile import SmileGate
from erp_bar_customer.odoo_display import record_url, OdooDisplay
from erp_bar_customer.server import make_server

class SmileTests(unittest.TestCase):
    def smiles(self,g,start=1,eligible=True):return [g.update(.99,start+i*.1,eligible) for i in range(20)]
    def neutral(self,g,start=0):
        for i in range(5):g.update(.1,start+i*.1)
    def test_relaxed_face_and_once_only(self):
        g=SmileGate();g.arm();self.assertFalse(any(self.smiles(g)))
        self.neutral(g,4);self.assertEqual(sum(self.smiles(g,5)),1)
        self.assertFalse(any(self.smiles(g,25)))
    def test_cooldown_survives_rearm(self):
        g=SmileGate();g.arm();self.neutral(g)
        self.assertTrue(any(self.smiles(g)));g.arm();self.neutral(g,3)
        self.assertFalse(any(self.smiles(g,4)));self.assertTrue(any(self.smiles(g,20)))
    def test_missing_face_clears_history(self):
        g=SmileGate();g.arm();self.neutral(g);g.update(None,1)
        self.assertEqual(len(g.scores),0);self.assertFalse(any(self.smiles(g,2)))
    def test_busy_and_disconnect_block(self):
        g=SmileGate();g.arm();self.neutral(g);self.assertFalse(any(self.smiles(g,1,False)))

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.release=threading.Event()
        self.session=Session(worker=lambda _:self.release.wait(10))
        self.gateway=CompanionGateway(self.session,'x'*40,'Lemonade',Path(self.tmp.name)/'ledger.sqlite')
        self.server=make_companion_server(self.gateway,port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
    def tearDown(self):
        self.release.set();self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def req(self,method,path,data=None,auth=True,origin=None):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        h={'Authorization':'Bearer '+'x'*40} if auth else {}
        if origin:h['Origin']=origin
        c.request(method,path,json.dumps(data) if data is not None else None,h)
        r=c.getresponse();v=(r.status,json.loads(r.read()));c.close();return v
    def test_auth_origin_and_no_token_leak(self):
        self.assertEqual(self.req('GET','/v1/state',auth=False)[0],403)
        self.assertEqual(self.req('GET','/v1/state',origin='https://example.org')[0],403)
        code,data=self.req('GET','/v1/state');self.assertEqual(code,200);self.assertNotIn('token',data)
    def test_remote_cannot_select_quantity(self):
        self.assertEqual(self.req('POST','/v1/smile',{'request_id':'a'*32,'quantity':99})[0],400)
        self.assertFalse(self.session.busy)
    def test_repeat_id_once_and_busy_blocks_other(self):
        a=self.req('POST','/v1/smile',{'request_id':'a'*32});b=self.req('POST','/v1/smile',{'request_id':'a'*32})
        self.assertEqual(a,b);self.assertEqual(a[0],202);self.assertEqual(self.session.quantity,1)
        self.assertEqual(len(self.session.requests),1)
        self.assertEqual(self.req('POST','/v1/smile',{'request_id':'b'*32})[0],409)
    def test_restart_does_not_recreate(self):
        mission=self.gateway.request('a'*32);other=Session(worker=lambda _:None)
        restarted=CompanionGateway(other,'x'*40,'Lemonade',self.gateway.ledger)
        self.assertEqual(restarted.request('a'*32),mission);self.assertFalse(other.busy)
    def test_uncertain_claim_blocks_repeat(self):
        with self.gateway.connect() as db:db.execute('INSERT INTO requests VALUES (?,NULL,?)',('a'*32,'pending'))
        with self.assertRaises(RuntimeError):self.gateway.request('a'*32)
        self.assertFalse(self.session.busy)

class DisplayTests(unittest.TestCase):
    def test_creation_waits_for_actual_record(self):
        known={'sales_order_id':8}
        self.assertIsNone(display_target({'id':1,'kind':'tool_start','action':'create_sales_order'},known)['record_id'])
        self.assertEqual(display_target({'id':2,'kind':'tool_end','action':'create_sales_order','ok':True,'result':{'sales_order_id':42}},known)['record_id'],42)
    def test_failure_does_not_focus_success_record(self):
        self.assertIsNone(display_target({'id':1,'kind':'tool_end','action':'create_sales_order','ok':False,'result':{'sales_order_id':42}},{}))
    def test_only_input_record_ids_observed(self):
        @observed_tool
        def tool(value):return {'ok':True}
        captured=[]
        with event_sink(captured.append):tool(SimpleNamespace(product_id=15,password='private'))
        self.assertEqual(captured[0]['record_ids'],{'product_id':15});self.assertNotIn('private',json.dumps(captured))
    def test_url_allowlist(self):
        self.assertEqual(record_url('http://localhost:8069',{'model':'sale.order','record_id':42}),'http://localhost:8069/web#model=sale.order&view_type=form&id=42')
        for t in [{'model':'res.users','record_id':1},{'model':'sale.order','record_id':'1&action=delete'},{'model':'sale.order','record_id':True}]:
            with self.assertRaises(ValueError):record_url('http://localhost:8069',t)

    def test_browser_login_follow_and_refresh_without_writes(self):
        class Page:
            url='about:blank'
            def __init__(self):self.visits=[];self.reloads=0
            def goto(self,url,**kwargs):
                self.visits.append(url);self.url=url+'/login' if url.endswith('/web') else url
            def reload(self,**kwargs):self.reloads+=1
            def is_closed(self):return False
        page=Page()
        context=SimpleNamespace(pages=[page],close=lambda:None)
        class Playwright:
            def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=lambda *a,**k:context))
            def __exit__(self,*a):pass
        module=types.ModuleType('playwright.sync_api');module.sync_playwright=Playwright
        def wait_for(predicate):
            deadline=time.monotonic()+3
            while not predicate() and time.monotonic()<deadline:time.sleep(.02)
            self.assertTrue(predicate())
        with tempfile.TemporaryDirectory() as folder, patch.dict(sys.modules,{'playwright.sync_api':module}):
            display=OdooDisplay('http://localhost:8069',Path(folder))
            try:
                display.open();wait_for(lambda:display.available)
                target={'model':'sale.order','record_id':42,'event_id':1,'phase':'tool_start'}
                display.update(target,'M1');time.sleep(.3)
                self.assertEqual(len(page.visits),1)
                display.follow(True);wait_for(lambda:not display.following)
                self.assertEqual(len(page.visits),1)
                page.url='http://localhost:8069/web#home'
                display.follow(True);wait_for(lambda:len(page.visits)==2)
                self.assertIn('id=42',page.visits[-1])
                display.update({**target,'event_id':2,'phase':'tool_end'},'M1')
                wait_for(lambda:page.reloads==1)
            finally:
                display.stop.set()
                if display.thread:display.thread.join(3)

class CustomerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.calls=[]
        class Client:
            def call(inner,path,data=None):
                self.calls.append((path,data));return {'mission_id':'M1','product':'Lemonade','quantity':1}
        self.app=CustomerApp({},self.tmp.name,client=Client(),demo_camera=True)
        self.app.camera_running=True;self.app.ingest({'mode':'demo','busy':False,'mission_id':None,'events':[]})
    def tearDown(self):self.app.close();self.tmp.cleanup()
    def wait_sent(self):
        for _ in range(100):
            if not self.app.submitting:return
            time.sleep(.01)
        self.fail('Submission did not finish')
    def test_smile_once_and_stable_retry(self):
        self.app.arm();now=time.monotonic()
        for i in range(5):self.app.score(.1,now+i*.05)
        for i in range(20):self.app.score(.99,now+1+i*.1)
        self.wait_sent();self.assertEqual(len(self.calls),1)
        self.assertEqual(json.loads(self.app.pending_file.read_text())['mission_id'],'M1')
        with self.assertRaises(ValueError):self.app.arm()
        self.app.send_pending();self.wait_sent();self.assertEqual(self.calls[0][1],self.calls[1][1])
    def test_terminal_response_and_rearm(self):
        self.app.pending={'request_id':'a'*32,'mission_id':'M1','terminal':False}
        self.app.ingest({'mode':'demo','busy':False,'mission_id':'M1','events':[{'kind':'mission_end','status':'FAILED','customer_message':'Please ask staff.'}]})
        self.assertTrue(self.app.pending['terminal']);self.assertEqual(self.app.message,'Please ask staff.')
        self.app.arm();self.assertTrue(self.app.gate.armed)
    def test_demo_ids_never_navigate_real_odoo(self):
        self.app.odoo.following=True
        self.app.ingest({'mode':'demo','busy':False,'mission_id':'M1','events':[],'odoo_target':{'model':'sale.order','record_id':42}})
        self.assertFalse(self.app.odoo.following);self.assertIsNone(self.app.odoo.target)
    def test_unknown_old_mission_blocks_new_customer(self):
        self.app.pending={'request_id':'a'*32,'mission_id':'OLD','terminal':False}
        self.app.ingest({'mode':'live','busy':False,'mission_id':'NEW','events':[]})
        self.assertFalse(self.app.eligible())
        with self.assertRaises(ValueError):self.app.arm()
    def test_local_api_csrf(self):
        server=make_server(self.app,0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            c.request('POST','/api/action',json.dumps({'action':'arm'}));r=c.getresponse();self.assertEqual(r.status,403);r.read();c.close()
            self.assertNotIn('brain_url',self.app.snapshot())
        finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
