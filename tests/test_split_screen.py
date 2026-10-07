"""Offline split-screen/trigger integration. No real camera, Odoo or model calls."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace, ModuleType
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'customer_screen')]
from erp_bar.agent_view.server import Session, make_server as main_server
from erp_bar.agent_view.companion_gateway import CompanionGateway, make_companion_server
from erp_bar_customer.app import CustomerApp
from erp_bar_customer.server import make_server
from erp_bar_customer.odoo_display import OdooDisplay, split_bounds, place_window


def wait_for(test, predicate):
    end=time.monotonic()+4
    while not predicate() and time.monotonic()<end:time.sleep(.01)
    test.assertTrue(predicate())


def target(event,model,record):
    return dict(event_id=event,model=model,record_id=record,phase='tool_end',action='test',agent='purchase_agent')


class FollowTests(unittest.TestCase):
    def setUp(self):
        self.display=OdooDisplay('http://localhost:8069',Path('profile'),hold_seconds=0)
        self.display.available=True
        self.display.follow(True)

    def test_split_covers_odd_width_and_negative_monitor(self):
        left,right=split_bounds({'left':-1921,'top':20,'width':1921,'height':1040})
        self.assertEqual(left['width']+right['width'],1921)
        self.assertEqual(left['left']+left['width'],right['left'])
        self.assertEqual(right['left']+right['width'],0)
        self.assertEqual(left['top'],right['top'])

    def test_three_fast_record_changes_survive_one_poll(self):
        targets=[target(1,'product.product',15),target(2,'purchase.order',27),target(3,'sale.order',42)]
        self.display.update_many(targets,'M1');self.display.update_many(targets,'M1')
        self.assertEqual([t['model'] for t in self.display.pending],['product.product','purchase.order','sale.order'])
        self.assertEqual(self.display.snapshot()['waiting'],3)

    def test_adjacent_same_record_updates_are_coalesced(self):
        self.display.update_many([target(1,'purchase.order',None),target(2,'purchase.order',27),target(3,'purchase.order',27)],'M1')
        self.assertEqual(len(self.display.pending),1)
        self.assertEqual(self.display.pending[0]['event_id'],3)

    def test_new_mission_clears_previous_record_queue(self):
        self.display.update_many([target(1,'purchase.order',27)],'M1')
        self.display.update_many([target(2,'sale.order',42)],'M2')
        self.assertEqual([t['record_id'] for t in self.display.pending],[42])

    def test_resume_follows_current_record(self):
        self.display.follow(False)
        self.display.update_many([target(1,'purchase.order',27),target(2,'sale.order',42)],'M1')
        self.assertFalse(self.display.pending)
        self.display.follow(True)
        self.assertEqual([t['record_id'] for t in self.display.pending],[42])

    def test_split_url_must_be_loopback(self):
        for url in ['https://example.org','http://user@localhost:8770','http://127.0.0.1:8770/?redirect=x']:
            with self.assertRaises(ValueError):self.display.open(split_url=url)

    def test_real_browser_protocol_arranges_both_halves_without_writes(self):
        contexts=[]
        class Page:
            def __init__(self):self.url='about:blank';self.visits=[]
            def goto(self,url,**kwargs):self.url=url;self.visits.append(url)
            def is_closed(self):return False
            def evaluate(self,script):return {'left':0,'top':0,'width':1920,'height':1040}
            def reload(self,**kwargs):pass
        class Context:
            def __init__(self):self.pages=[Page()];self.calls=[];self.closed=False
            def close(self):self.closed=True
            def new_cdp_session(self,page):
                outer=self
                class CDP:
                    def send(self,method,params=None):
                        outer.calls.append((method,params));return {'windowId':1}
                    def detach(self):pass
                return CDP()
        def launch(*args,**kwargs):
            self.assertFalse(kwargs['headless']);self.assertTrue(kwargs['no_viewport'])
            context=Context();contexts.append(context);return context
        class PW:
            def __enter__(self):return SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
            def __exit__(self,*args):pass
        module=ModuleType('playwright.sync_api');module.sync_playwright=PW
        with tempfile.TemporaryDirectory() as directory,patch.dict(sys.modules,{'playwright.sync_api':module}):
            display=OdooDisplay('http://localhost:8069',Path(directory)/'odoo',hold_seconds=0)
            try:
                display.open(split_url='http://127.0.0.1:8770')
                wait_for(self,lambda:display.layout_status=='Camera left · Odoo right')
                odoo,camera=contexts
                self.assertEqual(camera.calls[-1][1]['bounds'],{'left':0,'top':0,'width':960,'height':1040})
                self.assertEqual(odoo.calls[-1][1]['bounds'],{'left':960,'top':0,'width':960,'height':1040})
                display.follow(True);display.update_many([target(1,'purchase.order',27),target(2,'sale.order',42)],'M1')
                wait_for(self,lambda:display.shown and display.shown['record_id']==42)
                self.assertIn('id=27',odoo.pages[0].visits[-2]);self.assertIn('id=42',odoo.pages[0].visits[-1])
            finally:display.stop.set();display.thread.join(3)
            self.assertTrue(all(c.closed for c in contexts))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.release=threading.Event()
        self.session=Session(live=True,worker=lambda _:self.release.wait(8))
        self.gateway=CompanionGateway(self.session,'x'*40,'Lemonade',Path(self.tmp.name)/'requests.sqlite')
        self.remote=make_companion_server(self.gateway,port=0)
        self.main=main_server(self.session,0)
        self.app=CustomerApp({'brain_url':f'http://127.0.0.1:{self.remote.server_port}','token':'x'*40},Path(self.tmp.name)/'customer',demo_camera=True)
        self.customer=make_server(self.app,0)
        self.servers=[self.remote,self.main,self.customer]
        self.threads=[]
        for server in self.servers:
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.threads.append(thread)
        self.app.ingest(self.gateway.snapshot())

    def tearDown(self):
        self.release.set();self.app.close()
        wait_for(self,lambda:not self.app.submitting)
        for server in self.servers:server.shutdown();server.server_close()
        for thread in self.threads:thread.join(2)
        self.tmp.cleanup()

    def post(self,server,path,data,header,token):
        client=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=4)
        client.request('POST',path,json.dumps(data),{header:token,'Content-Type':'application/json'})
        result=client.getresponse();status=result.status;body=json.loads(result.read());client.close();return status,body

    def test_customer_manual_button_starts_one_lemonade_without_camera(self):
        self.assertFalse(self.app.camera_running)
        code,_=self.post(self.customer,'/api/action',{'action':'start_mission'},'X-Customer-Token',self.app.token)
        self.assertEqual(code,200)
        wait_for(self,lambda:self.session.busy and not self.app.submitting)
        self.assertEqual((self.session.product,self.session.quantity),('Lemonade',1))
        code,_=self.post(self.customer,'/api/action',{'action':'start_mission'},'X-Customer-Token',self.app.token)
        self.assertEqual(code,400);self.assertEqual(len(self.session.requests),1)

    def test_camera_start_arms_one_smile_and_sends_exactly_one_request(self):
        self.app.camera_ready();self.assertTrue(self.app.gate.armed)
        now=time.monotonic()
        for n in range(5):self.app.score(.1,now+n*.05)
        for n in range(30):self.app.score(.99,now+1+n*.1)
        wait_for(self,lambda:self.session.busy and not self.app.submitting)
        self.assertEqual(self.session.quantity,1);self.assertEqual(len(self.session.requests),1)
        self.assertFalse(self.app.gate.armed)
        self.assertEqual(self.app.pending['source'],'smile')

    def test_main_dashboard_button_appears_on_customer_and_disarms_smile(self):
        self.app.camera_ready()
        code,_=self.post(self.main,'/api/missions',{'product':'Lemonade','quantity':1,'request_id':'main-button-test'},'X-ERP-Bar-Token',self.session.token)
        self.assertEqual(code,202)
        self.app.ingest(self.gateway.snapshot())
        view=self.app.snapshot()
        self.assertTrue(view['busy']);self.assertEqual(view['mission_id'],self.session.mission_id)
        self.assertIn('main dashboard',view['message']);self.assertFalse(view['can_start']);self.assertFalse(self.app.gate.armed)

    def test_gateway_exposes_all_record_views_without_model_text(self):
        for action,result in [('create_purchase_order',{'purchase_order_id':27}),('create_sales_order',{'sales_order_id':42})]:
            self.session.publish({'kind':'tool_end','agent':'purchase_agent','action':action,'ok':True,'result':result})
        self.session.publish({'kind':'model_stream_end','agent':'purchase_agent','thinking':'not needed on the camera screen','output':'{}'})
        data=self.gateway.snapshot()
        self.assertEqual([t['model'] for t in data['odoo_targets']],['purchase.order','sale.order'])
        self.assertNotIn('not needed',json.dumps(data))

    def test_split_action_uses_actual_local_port(self):
        with patch.object(self.app.odoo,'open') as opening:
            code,_=self.post(self.customer,'/api/action',{'action':'odoo_open'},'X-Customer-Token',self.app.token)
        self.assertEqual(code,200)
        opening.assert_called_once_with(split_url=f'http://127.0.0.1:{self.customer.server_port}')

if __name__=='__main__':unittest.main(verbosity=2)
