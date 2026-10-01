'use strict';
const $=id=>document.getElementById(id);
let state={},token='',frameUrl=null,actionError='';
const names={supervisor:'Supervisor',sales_agent:'Sales',inventory_agent:'Inventory',purchase_agent:'Purchase'};
const models={'product.product':'Product','purchase.order':'Purchase order','sale.order':'Sales order','stock.picking':'Delivery'};
const words=s=>(s||'Standing by').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
const set=(id,value)=>$(id).textContent=value;
function render(s){
 state=s;token=s.token;set('mode',s.mode==='live'?'LIVE · ODOO':s.mode==='demo'?'DEMO · SIMULATED':'CONNECTING');
 set('connection',s.connected?'Main system connected':'Main system offline');$('connection').classList.toggle('online',s.connected);
 set('product',s.product);set('customer-message',s.message);set('error',s.error||actionError);$('error').hidden=!(s.error||actionError);
 $('start-mission').disabled=!s.can_start;set('start-mission',s.mode==='demo'?'Run demo mission →':'Start live mission →');
 set('request-state',s.busy?'WITH THE AGENT TEAM':s.terminal?'REQUEST FINISHED':s.submitting?'SENDING YOUR REQUEST':s.mission_id?'WITH THE AGENT TEAM':s.armed?'READY FOR YOUR SMILE':'WAITING FOR YOUR SMILE');
 set('mission-id',s.mission_id||'');set('camera-button',s.camera_running?'Stop camera':'Start camera');
 $('arm').disabled=!s.can_arm||s.armed;set('arm',s.armed?'Waiting for your smile…':'Next customer →');
 $('simulate').hidden=!s.demo_camera||s.mode!=='demo';$('simulate').disabled=!s.armed;
 $('retry').hidden=!s.request_id||s.terminal||!s.error;$('retry').disabled=s.submitting||!s.connected;
 set('camera-status',s.camera_status);set('camera-tag',s.demo_camera&&s.camera_running?'SIMULATED CAMERA':s.camera_running?'CAMERA ON':'CAMERA OFF');
 set('camera-title',s.demo_camera&&s.camera_running?'Try the experience.':s.camera_running?'Looking for your smile.':'Ready when you are.');
 set('camera-description',s.demo_camera?'Simulated camera. No webcam access.':'Start the camera to enable one smile request.');
 if(!s.camera_running){$('camera').hidden=true;$('camera-placeholder').hidden=false;}
 set('smile-value',Math.round(s.score*100)+'%');$('smile-fill').style.width=(Math.round(s.score*100))+'%';
 set('smile-instruction',s.armed?(s.neutral_seen?'Hold your smile for a moment.':'Start with a relaxed expression.'):'Select Next customer when you are ready.');
 set('agent',names[s.activity.agent]||'The agent team');set('agent-avatar',(names[s.activity.agent]||'S').slice(0,2).toUpperCase());
 set('action',words(s.activity.action));set('activity-message',s.activity.message||'The main system coordinates sales, stock and purchasing.');
 const shown=s.odoo_display?.shown;const t=shown||s.odoo_target;set('odoo-record',s.mode==='demo'?(t?'Preview: '+(models[t.model]||t.model)+(t.record_id?' #'+t.record_id:' list'):'Demo uses simulated ERP records.'):(t?(shown?'On Odoo: ':'Next record: ')+(models[t.model]||t.model)+(t.record_id?' #'+t.record_id:' list'):'The Odoo window follows the latest recorded agent action.'));
 set('odoo-status',s.mode==='demo'?'Odoo stays closed while the main system is in demo mode.':s.odoo_status);
 $('odoo-open').disabled=s.mode!=='live';$('odoo-follow').disabled=s.mode!=='live'||!s.odoo_available;
 const waiting=s.odoo_display?.waiting||0;set('display-queue',waiting?`${waiting} record view${waiting===1?'':'s'} waiting · Odoo shows current data for each record`:(s.odoo_display?.layout||''));
 set('odoo-follow',s.odoo_following?'Pause following':'Follow Odoo');$('odoo-follow').classList.toggle('on',s.odoo_following);
}
async function action(name){try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Customer-Token':token},body:JSON.stringify({action:name})});const data=await r.json();if(!r.ok)throw Error(data.error);actionError='';await refresh();}catch(e){actionError=e.message;set('error',actionError);$('error').hidden=false;}}
async function refresh(){try{const r=await fetch('/api/state');if(!r.ok)throw Error();render(await r.json());}catch{set('connection','Local screen disconnected');$('connection').classList.remove('online');}}
async function poll(){await refresh();setTimeout(poll,450);}
async function camera(){try{if(state.camera_running&&!state.demo_camera){const r=await fetch('/camera.jpg');if(r.status===200){const blob=await r.blob();const next=URL.createObjectURL(blob);$('camera').src=next;$('camera').hidden=false;$('camera-placeholder').hidden=true;if(frameUrl)URL.revokeObjectURL(frameUrl);frameUrl=next;}}}catch{}setTimeout(camera,100);}
$('start-mission').onclick=()=>action('start_mission');
$('camera-button').onclick=()=>action(state.camera_running?'camera_stop':'camera_start');$('arm').onclick=()=>action('arm');$('simulate').onclick=()=>action('simulate_smile');$('retry').onclick=()=>action('retry');$('odoo-open').onclick=()=>action('odoo_open');$('odoo-follow').onclick=()=>action('odoo_follow');
poll();camera();
