'use strict';
const $=id=>document.getElementById(id);
const set=(id,value)=>$(id).textContent=value||'';
let state={},token='',frameUrl=null,actionError='';
const names={supervisor:'Supervisor',sales_agent:'Sales',inventory_agent:'Inventory',purchase_agent:'Purchase'};
const models={'product.product':'Product','purchase.order':'Purchase order','sale.order':'Sales order','stock.picking':'Delivery'};
const words=s=>(s||'Standing by').replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
function render(s){
 state=s;token=s.token;document.body.dataset.phase=s.phase;
 set('mode',s.mode==='live'?'LIVE':s.mode==='demo'?'DEMO':'CONNECTING');
 set('connection',s.connected?'Agent team connected':'Reconnecting…');$('connection').classList.toggle('online',s.connected);
 set('headline',s.headline);set('smile-instruction',s.trigger_status);
 set('customer-message',s.phase==='working'?'Watch your order happen in Odoo.':s.phase==='ready'?'No button needed. Just smile.':s.message);
 set('error',s.error||actionError);$('error').hidden=!(s.error||actionError);
 set('request-state',s.busy?'PREPARING':s.submitting?'SENDING':s.armed?'READY':(s.phase||'CONNECTING').toUpperCase());
 set('mission-id',s.mission_id);set('camera-button',s.camera_running?'Pause camera':'Start camera');
 $('arm').disabled=!s.can_arm||s.armed;
 $('simulate').hidden=!s.demo_camera||s.mode!=='demo';$('simulate').disabled=!s.armed||s.busy||s.submitting;
 $('retry').hidden=!s.can_retry;$('retry').disabled=s.submitting||!s.connected;
 set('camera-status',s.camera_status);set('camera-tag',s.demo_camera?'SIMULATED':s.camera_running?'ON · LOCAL ONLY':'STARTING');
 set('camera-title',s.demo_camera?'Try your first demo smile.':'A little smile goes a long way.');
 set('camera-description',s.demo_camera?'Use the demo smile button below.':s.camera_running?'Looking for your smile…':s.camera_status);
 if(!s.camera_running){$('camera').hidden=true;$('camera-placeholder').hidden=false;}
 const paused=s.busy||s.submitting;set('meter-label',paused?'NEW SMILES PAUSED':'YOUR SMILE');
 set('smile-value',paused?'PAUSED':(s.score*100).toFixed(1)+'%');$('smile-fill').style.width=paused?'0%':(s.score*100)+'%';
 set('agent',names[s.activity.agent]||'The agent team');set('agent-avatar',(names[s.activity.agent]||'S').slice(0,2).toUpperCase());set('action',words(s.activity.action));
 const t=s.odoo_display?.shown||s.odoo_target;
 set('odoo-record',t?(models[t.model]||t.model)+(t.record_id?' #'+t.record_id:' list'):'Odoo opens automatically for a live mission.');
 set('odoo-status',s.mode==='demo'?'Demo records are simulated. Odoo stays closed.':s.odoo_status);
 set('connection-detail',s.connection_error||s.processing_error||`Release ${s.build} · event stream connected`);
 set('display-notice',s.display_notice);
 $('odoo-open').disabled=s.mode!=='live';$('odoo-follow').disabled=s.mode!=='live'||!s.odoo_available;
 set('display-queue',s.odoo_display?.waiting?`${s.odoo_display.waiting} record views waiting`:s.odoo_display?.layout);
 set('odoo-follow',s.odoo_following?'Pause following':'Follow Odoo');
}
async function action(name){try{const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-Customer-Token':token},body:JSON.stringify({action:name})});const data=await r.json();if(!r.ok)throw Error(data.error);actionError='';await refresh();}catch(e){actionError=e.message;set('error',actionError);$('error').hidden=false;}}
async function refresh(){try{const r=await fetch('/api/state');if(!r.ok)throw Error();render(await r.json());}catch{set('connection','Customer screen disconnected');$('connection').classList.remove('online');}}
async function poll(){await refresh();setTimeout(poll,250);}
async function camera(){try{if(state.camera_running&&!state.demo_camera){const r=await fetch('/camera.jpg');if(r.status===200){const next=URL.createObjectURL(await r.blob());$('camera').src=next;$('camera').hidden=false;$('camera-placeholder').hidden=true;if(frameUrl)URL.revokeObjectURL(frameUrl);frameUrl=next;}}}catch{}setTimeout(camera,100);}
$('camera-button').onclick=()=>action(state.camera_running?'camera_stop':'camera_start');$('arm').onclick=()=>action('arm');$('simulate').onclick=()=>action('simulate_smile');$('retry').onclick=()=>action('retry');$('odoo-open').onclick=()=>action('odoo_open');$('odoo-follow').onclick=()=>action('odoo_follow');
poll();camera();
