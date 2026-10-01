'use strict';
const $ = id => document.getElementById(id);
const EMPTY_FEED = $('feed').firstElementChild.cloneNode(true);
const AGENTS = {supervisor:{name:'Supervisor',color:'#a1de6b'},sales_agent:{name:'Sales',color:'#85b8f8'},inventory_agent:{name:'Inventory',color:'#70d4b8'},purchase_agent:{name:'Purchase',color:'#e8ba72'}};
const LABELS = {INTERPRET_DEMAND:'Interpret demand',CHECK_INVENTORY:'Check inventory',RESOLVE_PRODUCT:'Resolve product',VERIFY_STOCK:'Verify stock',PROCURE_SHORTAGE:'Procure shortage',CREATE_SALES_ORDER:'Create sales order',FULFILL_DELIVERY:'Fulfill delivery',REPORT_PROCUREMENT_FAILURE:'Prepare customer response'};
let instruction=null, demoPaused=false, demoSpeed=1;
let liveQueue=[], receivedId=0, sourceBusy=false, sourceOutcome='', beatRemaining=0, playbackTick=performance.now();
const LIVE_VIEW_KEY='erp-bar-live-presentation-v3';
const thinkingReveal=new Map(), thinkingNodes=new Map();
let typingTick=performance.now(),typingSavedAt=0;
function savedLiveView(){try{return JSON.parse(sessionStorage.getItem(LIVE_VIEW_KEY))||{};}catch{return {};}}
function saveLiveView(){try{sessionStorage.setItem(LIVE_VIEW_KEY,JSON.stringify({missionId,lastId,paused:demoPaused,speed:demoSpeed,inflight:events.filter(e=>e.kind==='model_stream'&&(!e.complete||thinkingPending(e))),typing:events.filter(thinkingPending).map(e=>[thinkingKey(e),thinkingCount(e)])}));}catch{}}
function readingBeat(e){return ['thinking','proposal','instruction','handoff','tool_start','tool_end','checkpoint_rejected','model_error','mission_end','connecting'].includes(e.kind)||(e.kind==='agent_end'&&e.agent!=='supervisor');}
function observeSource(e){
 if(e.kind==='mission_start'){sourceBusy=true;sourceOutcome='';}
 if(e.kind==='mission_end')sourceOutcome=e.status==='DELIVERED'?'Delivered':e.status==='FAILED'?'Failed':human(e.status)||'Ended';
 if(e.kind==='session_idle')sourceBusy=false;
}
function receive(e){
 if(mode==='demo'&&e.kind==='demo_control'){accept(e);return;}
 if(e.id<=receivedId)return;
 if(e.mission_id!==missionId){liveQueue=[];beatRemaining=0;lastId=0;reset(e.mission_id);sourceOutcome='';}
 receivedId=e.id;observeSource(e);liveQueue.push(e);render();
}
function drainLiveQueue(){
 const now=performance.now(),delta=Math.min(250,now-playbackTick);playbackTick=now;
 if(demoPaused||!connected)return;
 beatRemaining=Math.max(0,beatRemaining-delta*demoSpeed);
 if(beatRemaining>0||hasPendingThinking())return;
 let updated=false;
 while(liveQueue.length){const e=liveQueue.shift();accept(e,true);updated=true;if(thinkingPending(e)||hasPendingThinking())break;if(e.kind==='thinking'){beatRemaining=120;break;}if(e.kind==='decision_summary'){beatRemaining=180;break;}if(mode==='live'&&readingBeat(e)){beatRemaining=3000;break;}}
 if(updated){saveLiveView();render(true);}
}
setInterval(drainLiveQueue,50);
function thinkingKey(e){return e.agent+':'+e.stream_id;}
function thinkingCount(e){return thinkingReveal.get(thinkingKey(e))?.count||0;}
function thinkingPending(e){return e.kind==='model_stream'&&thinkingCount(e)<(e.thinking||'').length;}
function hasPendingThinking(){return events.some(thinkingPending);}
function settleThinking(){for(const e of events)if(e.kind==='model_stream')thinkingReveal.set(thinkingKey(e),{count:(e.thinking||'').length,credit:0});}
function revealThinking(){
 const now=performance.now(),delta=Math.min(100,now-typingTick);typingTick=now;
 if(demoPaused||!connected)return;
 const e=events.find(thinkingPending);if(!e)return;
 const key=thinkingKey(e),progress=thinkingReveal.get(key)||{count:0,credit:0};
 progress.credit+=delta*demoSpeed*38/1000;
 const before=progress.count;
 while(progress.credit>=1&&progress.count<e.thinking.length){progress.count+=e.thinking.codePointAt(progress.count)>0xffff?2:1;progress.credit--;}
 thinkingReveal.set(key,progress);
 if(before===progress.count)return;
 const target=thinkingNodes.get(key);
 if(target)target.textContent=e.thinking.slice(0,progress.count);
 scrollChatToLatest();
 if(!thinkingPending(e)){progress.credit=0;render();}
 if(now-typingSavedAt>200||!thinkingPending(e)){typingSavedAt=now;saveLiveView();}
}
setInterval(revealThinking,25);

const defaults = () => Object.fromEntries(Object.keys(AGENTS).map(key=>[key,{state:'standby',title:'Ready for a task',message:'Waiting for the supervisor to assign a task.',time:null,action:null} ]));
let agents=defaults(), events=[], selected='supervisor', active=null, route=null, filter='all', busy=false, connected=false, mode='demo', token='', missionId=null, started=null, ended=null, toolCount=0, handoffs=0, lastId=0, typeTimer=null, lastFocus='', pendingRequest=null;
const human = value => LABELS[value] || String(value || '').replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase());
const name = key => AGENTS[key]?.name || 'System';
const stamp = date => date ? new Date(date).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}) : '—';
function text(id,value){$(id).textContent=value;}
function reset(id){thinkingReveal.clear();thinkingNodes.clear();typingTick=performance.now();missionId=id;instruction=null;events=[];$('feed').replaceChildren(EMPTY_FEED.cloneNode(true));agents=defaults();active=null;selected='supervisor';route=null;started=null;ended=null;toolCount=handoffs=0;lastFocus='';clearInterval(typeTimer);$('outcome').hidden=true;text('sales-id','—');text('purchase-id','—');text('delivery-id','—');text('mission-id',id || 'No mission started');text('mission-status',id?'Starting mission':'Ready to begin');text('focus-title','The team is ready.');text('focus-text','Start a mission to see the supervisor select an agent, watch tools execute, and follow the results back to the team.');}
function accept(e, replay=false){
 if(e.mission_id!==missionId) reset(e.mission_id);
 if(!replay && e.id<=lastId)return;
 lastId=Math.max(lastId,e.id || 0);
 const a=agents[e.agent];
 if(e.kind==='demo_control'){demoPaused=e.paused;demoSpeed=e.speed;}
 if(e.kind==='mission_start'){busy=true;started=new Date(e.time).getTime();ended=null;text('mission-status','Mission in progress');$('product').value=e.product;$('quantity').value=e.quantity;}
 if(e.kind==='agent_start'&&a){active=e.agent;selected=e.agent;Object.assign(a,{state:'active',title:'Assessing the mission',message:e.message,time:e.time,action:null,detail:''});}
 if(e.kind==='thinking'&&a){a.streamId=e.stream_id;a.summary='';Object.assign(a,{state:'thinking',title:'Choosing the next action',message:'Generating a response. Follow the model in the chat.',time:e.time,action:null,detail:''});active=e.agent;selected=e.agent;}
 if(e.kind==='decision_summary'&&a){
   a.summary=e.message;a.message=e.message;a.state='thinking';a.title='Why this next step';a.streamId=e.stream_id;
   const previous=events.find(item=>item.kind==='decision_summary'&&item.stream_id===e.stream_id&&item.agent===e.agent);
   if(previous)Object.assign(previous,e);else {events.push({...e});if(events.length>400)events.shift();}
 }
 if(['model_stream','model_stream_end'].includes(e.kind)&&a){
   let generation=events.find(item=>item.kind==='model_stream'&&item.stream_id===e.stream_id&&item.agent===e.agent);
   if(!generation){generation={...e,kind:'model_stream',thinking:'',output:'',complete:false};events.push(generation);if(events.length>400)events.shift();}
   if(e.kind==='model_stream'){
     if(['thinking','output'].includes(e.phase)){generation[e.phase]+=e.delta||'';generation.phase=e.phase;}
   }else{generation.thinking=e.thinking||'';generation.output=e.output||'';generation.complete=true;generation.interrupted=Boolean(e.interrupted);}
   a.streamId=e.stream_id;a.state='thinking';a.title=e.phase==='thinking'?'Choosing the next action':'Preparing a proposal';
   a.message=e.phase==='thinking'?'Reviewing the task. Follow the model thinking in the chat.':'Generating the response. No action has been executed yet.';
 }
 if(['model_complete','model_error'].includes(e.kind)){
   const generation=events.find(item=>['model_stream','decision_summary'].includes(item.kind)&&item.stream_id===e.stream_id&&item.agent===e.agent);
   if(generation){generation.complete=true;generation.interrupted=e.kind==='model_error';}
 }
 if(e.kind==='model_complete'&&a){a.state='reviewing';a.title='Checking the response';a.message='The response is complete. Python checks it before any action.';}
 if(e.kind==='proposal'&&a){a.summary=e.message;Object.assign(a,{title:human(e.action),message:'Proposed next step · awaiting Python validation.',action:e.action,state:'proposal',time:e.time});
   const generation=events.find(item=>item.kind==='model_stream'&&item.stream_id===e.stream_id&&item.agent===e.agent);if(generation)generation.action=e.action;
 }
 if(e.kind==='instruction'&&e.validated===true){instruction=e;if(agents[e.target])agents[e.target].assigned=e.action;}
 if(e.kind==='tool_start'&&a){toolCount++;Object.assign(a,{state:'executing',title:runningAction(e.action),message:'Executing the approved action in Odoo.',action:e.action,time:e.time,detail:''});}
 if(e.kind==='tool_end'&&a){a.state=e.ok?'verified':'issue';a.time=e.time;a.title=human(e.action);a.message=e.ok?'The tool returned a successful result.':e.message;a.detail='Last result · '+Object.entries(e.result || {}).map(([k,v])=>`${human(k)}: ${v}`).join(' · ');if(!e.ok)a.message=e.message;}
 if(e.kind==='checkpoint_rejected'&&a){a.state='issue';a.title='Revising the proposal';a.message=e.message;const generation=events.findLast(item=>item.kind==='model_stream'&&item.agent===e.agent);if(generation)generation.rejected=true;}
 if(e.kind==='model_error'&&a){a.state='issue';a.title='Model request failed';a.message=e.message;}
 if(e.kind==='agent_end'&&a){a.state=e.status==='FAILED'||e.status==='PROCUREMENT_FAILED'||['MISSION_FAILED','PROCUREMENT_FAILED'].includes(e.decision)?'issue':'complete';a.time=e.time;a.message=e.message;if(e.agent!=='supervisor')a.summary=e.message;if(active===e.agent)active=null;}
 if(e.kind==='handoff'){route={source:e.source,target:e.target,message:e.message,action:e.action};handoffs++;if(agents[e.target]){selected=e.target;agents[e.target].title=human(e.action)||'Receiving task';if(e.target!=='supervisor')agents[e.target].message=instruction?.target===e.target?instruction.objective:e.message;} }
 if(e.status && e.kind!=='mission_end')text('mission-status',human(e.status));
 if(e.sales_order_id)text('sales-id',`#${e.sales_order_id}`);
 if(e.purchase_order_ids?.length)text('purchase-id',e.purchase_order_ids.map(id=>`#${id}`).join(', '));
 if(e.delivery_id)text('delivery-id',`#${e.delivery_id}`);
 if(e.kind==='mission_end'){
   ended=new Date(e.time).getTime();active=null;
   for(const a of Object.values(agents)) if(['thinking','executing','active','proposal','reviewing'].includes(a.state))a.state=e.status==='DELIVERED'?'complete':'issue';
   text('mission-status',e.status==='DELIVERED'?'Delivered successfully':'Could not complete');
   $('outcome').hidden=false;$('outcome').classList.toggle('failed',e.status!=='DELIVERED');
   text('outcome-title',e.status==='DELIVERED'?(mode==='demo'?'Demo mission complete':'Mission complete'):'Customer response');
   text('outcome-message',e.customer_message || e.message || 'The mission has ended.');
   text('announcer',$('outcome-message').textContent);
 }
 if(e.kind==='session_idle'){busy=false;pendingRequest=null;}
 if((['mission_start','connecting','instruction','proposal','handoff','tool_start','tool_end','model_error','checkpoint_rejected','mission_end'].includes(e.kind)||(e.kind==='agent_end'&&e.agent!=='supervisor'))){events.push(e);if(events.length>400)events.shift();}
 if(!replay)render(true);
}
function render(animate=false){
 text('tool-count',toolCount);text('handoff-count',handoffs);text('event-count',events.length);
 const occupied=busy||(mode==='live'&&(sourceBusy||liveQueue.length>0));
 $('start').disabled=occupied || !connected;$('product').disabled=occupied;$('quantity').disabled=occupied;
 $('start').querySelector('span').textContent=occupied?(mode==='live'&&!sourceBusy?'Reading activity…':'Mission running…'):(mode==='live'?'Start live mission':'Run demo mission');
 const canvas=$('canvas-state');canvas.classList.toggle('running',busy&&connected);
 canvas.lastChild.textContent=!connected?'Connection interrupted':active?`${name(active)} is working`:busy?'Handoff in progress':ended?'Mission finished':'Waiting for a mission';
 for(const [key,a] of Object.entries(agents)){
   const card=document.querySelector(`[data-agent="${key}"]`);
   card.classList.toggle('active',active===key&&busy&&connected);card.classList.toggle('selected',selected===key);card.classList.toggle('error',a.state==='issue');card.setAttribute('aria-pressed',String(selected===key));
   card.querySelector('.agent-state').textContent=active===key&&!connected?'OFFLINE':({thinking:'GENERATING',executing:'USING TOOL',complete:'COMPLETE',issue:'CHECK RESULT',active:'WORKING',reviewing:'REVIEWING',proposal:'PROPOSED',verified:'RESULT READY',standby:'STANDBY'})[a.state];
   card.querySelector('.agent-task').textContent=actionLabel(a);
 }
 renderRoutes();renderFocus(animate);renderFeed();renderDemoControls();
}
function runningAction(action){
 const labels={search_product:'Searching product',get_available_stock:'Checking stock',create_product:'Creating product',get_product_vendors:'Finding a supplier',create_purchase_order:'Creating purchase order',confirm_purchase_order:'Confirming purchase order',receive_purchase:'Receiving purchased stock',create_sales_order:'Creating sales order',confirm_sales_order:'Confirming sales order',get_delivery:'Finding the delivery',check_delivery_availability:'Checking reservations',validate_delivery:'Completing delivery',prepare_failure_response:'Preparing customer reply'};
 return labels[String(action||'').toLowerCase()]||human(action);
}
function actionLabel(a){
 if(a.state==='executing')return runningAction(a.action);
 if(a.state==='proposal')return human(a.action);
 if(a.state==='standby')return a.assigned?human(a.assigned):'Waiting for a task';
 if(a.state==='complete')return 'Task completed';
 return a.title;
}
function renderFocus(){
 const a=agents[selected];text('focus-agent',name(selected).toUpperCase());text('focus-kind',a.state==='thinking'?'GENERATING':a.state.toUpperCase());text('focus-title',actionLabel(a));text('focus-time',stamp(a.time));
 $('sound-bars').classList.toggle('working',active===selected&&busy&&connected&&!demoPaused);
 text('focus-detail',a.state==='executing'?'Approved action · awaiting Odoo result':a.state==='proposal'?'Proposed action · validation follows':'Model thinking appears progressively in the right chat');
 text('focus-text',a.state==='complete'?'The agent has returned its result to the team.':a.message);
 $('focus-text').classList.remove('summary-streaming');
}

function drawRoutes(){
 const canvas=$('agent-canvas').getBoundingClientRect(), hub=document.querySelector('[data-agent="supervisor"]').getBoundingClientRect();
 const g=$('route-lines');g.replaceChildren();
 const sx=hub.left+hub.width/2-canvas.left, sy=hub.bottom-canvas.top;
 for(const key of ['sales_agent','inventory_agent','purchase_agent']){
  const box=document.querySelector(`[data-agent="${key}"]`).getBoundingClientRect();
  const tx=box.left+box.width/2-canvas.left,ty=box.top-canvas.top;
  const bend=0, curve=Math.max(12,(ty-sy)*.55);
  const d=`M ${sx} ${sy} C ${sx+bend} ${sy+curve}, ${tx+bend} ${ty-curve}, ${tx} ${ty}`;
  for(const type of ['base','flow']){const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',d);p.setAttribute('class',`route-${type}`);p.dataset.route=key;p.style.setProperty('--route-color',AGENTS[key].color);g.append(p);}
  const dot=document.createElementNS('http://www.w3.org/2000/svg','circle');dot.setAttribute('r','5');dot.setAttribute('class','route-packet');dot.dataset.route=key;dot.style.setProperty('--route-color',AGENTS[key].color);dot.style.offsetPath=`path("${d}")`;g.append(dot);
 }
 renderRoutes();
}
function renderRoutes(){
 document.querySelectorAll('.route-flow,.route-packet').forEach(p=>{
  const key=p.dataset.route;const on=route&&connected&&busy&&((route.source==='supervisor'&&route.target===key)||(route.target==='supervisor'&&route.source===key));
  p.classList.toggle('active',Boolean(on));p.classList.toggle('reverse',Boolean(route&&route.target==='supervisor'));p.style.animationPlayState=demoPaused?'paused':'running';
 });
 if(route){text('exchange-route',`${name(route.source)} → ${name(route.target)}`);text('exchange-message',route.target==='supervisor'?'Result returned · '+route.message:'Task assigned · '+(human(route.action)||route.message));}
 else {text('exchange-route','THE COMMUNICATION ROUTE');text('exchange-message','Instructions go out. Verified results come back.');}
 $('exchange-route').parentElement.parentElement.classList.toggle('is-active',Boolean(route&&busy));
}
function renderDemoControls(){
 $('demo-controls').hidden=false;
 $('demo-pause').textContent=demoPaused?'▶ Resume display':'Ⅱ Pause display';
 $('demo-pause').setAttribute('aria-pressed',String(demoPaused));$('demo-speed').value=String(demoSpeed);
 const live=mode==='live';
 text('mission-section-label',live?'DISPLAYED MISSION STEP':'CURRENT MISSION');
 text('pace-note',live?'Display only. Odoo operations continue while you read.':demoPaused?'Paused for discussion. Resume when you are ready.':'A reading pause between decisions, actions and replies.');
 $('jump-latest').hidden=!live;$('jump-latest').disabled=liveQueue.length===0&&!hasPendingThinking();
 $('live-progress').hidden=!live;
 if(live){const actual=sourceOutcome?`Workflow ${sourceOutcome.toLowerCase()}`:sourceBusy?'Workflow running':'Workflow ready';text('live-progress',`${actual} · ${liveQueue.length?liveQueue.length+' updates waiting':hasPendingThinking()?'Revealing thinking text':'Display up to date'}`);}
 $('agent-canvas').classList.toggle('demo-paused',demoPaused);$('feed').classList.toggle('typing-paused',demoPaused||!connected);
 if(demoPaused)$('canvas-state').lastChild.textContent='Display paused · time to explain';
 else if(live&&(liveQueue.length||hasPendingThinking()))$('canvas-state').lastChild.textContent='Recorded activity · '+(active?name(active):'handoff');
 if(live&&(liveQueue.length||hasPendingThinking()))text('feed-note','Reading recorded activity · timestamps show when it happened');
}
async function controlDemo(paused,speed){
 if(mode==='live'){demoPaused=paused;demoSpeed=speed;saveLiveView();render();return;}
 try{const r=await fetch('/api/demo-control',{method:'POST',headers:{'Content-Type':'application/json','X-ERP-Bar-Token':token},body:JSON.stringify({paused,speed})});const data=await r.json();if(!r.ok)throw Error(data.error);demoPaused=data.paused;demoSpeed=data.speed;render();}
 catch(e){text('form-error',e.message||'Unable to change presentation pace.');}
}
$('jump-latest').addEventListener('click',()=>{
 if(mode!=='live')return;
 for(const e of liveQueue)accept(e,true);
 liveQueue=[];beatRemaining=0;settleThinking();saveLiveView();render();
});
$('demo-pause').addEventListener('click',()=>controlDemo(!demoPaused,demoSpeed));
$('demo-speed').addEventListener('change',()=>controlDemo(demoPaused,Number($('demo-speed').value)));
function node(tag,cls,value){const n=document.createElement(tag);n.className=cls;if(value!==undefined)n.textContent=value;return n;}
function avatar(agent){const n=node('div','chat-avatar',({supervisor:'S',sales_agent:'SA',inventory_agent:'IN',purchase_agent:'PU'})[agent]||'•');n.style.setProperty('--agent',AGENTS[agent]?.color||'#c2cec0');return n;}
function entry(e){
 if(e.kind==='model_stream')return generationEntry(e);
 const supervisor=e.agent==='supervisor', tool=e.kind.startsWith('tool_'), reply=e.kind==='agent_end';
 const failure=e.ok===false||['model_error','checkpoint_rejected'].includes(e.kind)||(reply&&(['FAILED','PROCUREMENT_FAILED'].includes(e.status)||['MISSION_FAILED','PROCUREMENT_FAILED'].includes(e.decision)));
 const li=node('article',`event-item chat-row ${supervisor?'from-supervisor':'from-specialist'} ${tool?'tool-row':''} ${e.kind==='instruction'?'instruction-row':''} ${reply?'reply-row':''} ${failure?'failure':''}`);li.dataset.kind=e.kind;
 const bubble=node('div','chat-bubble');const top=node('div','event-top');
 const who=node('span','event-agent',e.kind==='instruction'?`Supervisor → ${name(e.target)}`:reply?`${name(e.agent)} → ${e.status==='DELIVERED'?'Team':'Supervisor'}`:e.kind==='handoff'?`${name(e.source)} → ${name(e.target)}`:name(e.agent));
 top.append(who,node('time','event-time',stamp(e.time)));
 const title=({mission_start:'Customer request received',connecting:'Connecting to Odoo',instruction:'Your next task',handoff:'Handoff',decision_summary:e.interrupted?'Decision summary · interrupted':e.complete?'Decision summary':'Decision summary · streaming',proposal:'Proposed next step · '+human(e.action),tool_start:'Working on it · '+human(e.action),tool_end:(e.ok?'Result received · ':'Action unsuccessful · ')+human(e.action),agent_end:failure?'I could not complete this task':'Here is my result',model_error:'Model request failed',checkpoint_rejected:'Proposal needs revision',mission_end:e.status==='DELIVERED'?'Customer request fulfilled':'Customer response'})[e.kind]||human(e.kind);
 bubble.append(top,node('div','event-title',title),node('p','event-message',e.kind==='instruction'?e.objective:e.message||''));
 if(e.kind==='instruction'){bubble.append(node('span','message-tag','APPROVED BY CHECKPOINT'));}
 if(e.kind==='decision_summary'){bubble.append(node('span','message-tag',e.interrupted?'INCOMPLETE · MODEL REQUEST FAILED':e.complete?'PUBLIC EXPLANATION':'PUBLIC EXPLANATION · IN PROGRESS'));}
 if(e.kind==='proposal'){bubble.append(node('span','message-tag','PROPOSAL · VALIDATION FOLLOWS'));}
 if(e.result&&Object.keys(e.result).length){const meta=node('div','event-meta');Object.entries(e.result).forEach(([k,v])=>meta.append(node('span','',`${human(k)}: ${v}`)));bubble.append(meta);}
 if(reply&&e.status){bubble.append(node('span','message-tag',human(e.status)));}
 if(tool&&e.duration!==undefined)bubble.append(node('span','tool-duration',`${e.duration}s`));
 li.append(avatar(e.agent),bubble);return li;
}
function generationEntry(e){
 const li=node('article',`event-item chat-row ${e.agent==='supervisor'?'from-supervisor':'from-specialist'} generation-row`);li.dataset.kind='model_stream';li.dataset.streamId=e.stream_id;
 const bubble=node('div','chat-bubble');const top=node('div','event-top');top.append(node('span','event-agent',name(e.agent)),node('time','event-time',stamp(e.time)));bubble.append(top);
 const pending=thinkingPending(e);
 const status=pending?'Thinking…':e.interrupted?'Thinking interrupted':e.rejected?'Proposal needs revision':e.action?'Next step · '+human(e.action):e.complete?'Thinking complete':'Thinking…';
 bubble.append(node('div','event-title',status));
 if(e.thinking){
   bubble.append(node('div','stream-label','MODEL THINKING'));
   const paragraph=node('p','stream-thinking'+(pending||!e.complete?' is-writing':''),e.thinking.slice(0,thinkingCount(e)));
   thinkingNodes.set(thinkingKey(e),paragraph);bubble.append(paragraph);
 }else bubble.append(node('p','event-message',e.complete?'This model did not emit thinking text.':'Waiting for the model’s thinking…'));
 bubble.append(node('span','message-tag',e.demo?'SIMULATED THINKING':e.interrupted?'THINKING INTERRUPTED':e.rejected?'REJECTED BY PYTHON':pending?'READING PACE · MODEL THINKING':e.complete?'THINKING RECORDED':'MODEL THINKING · STREAMING'));
 li.append(avatar(e.agent),bubble);return li;
}
function renderFeed(){
 // Handoffs remain counted and animated; the instruction and actual reply tell the story once.
 thinkingNodes.clear();
 const shown=events.filter(e=>e.kind!=='mission_end'&&!(e.kind==='proposal'&&events.some(item=>item.kind==='model_stream'&&item.stream_id===e.stream_id&&item.agent===e.agent))&&(e.kind!=='handoff'||(e.target==='sales_agent'&&e.source!=='supervisor'))&&(filter==='all'||filter==='tools'&&e.kind.startsWith('tool_')||filter==='decisions'&&['instruction','model_stream','decision_summary','proposal','agent_end','checkpoint_rejected','mission_end'].includes(e.kind)));
 if(!events.length)return;
 const feed=$('feed');feed.replaceChildren(...shown.map(entry));
 if(active&&busy&&connected&&agents[active].state==='thinking'&&filter!=='tools'){
  const row=node('div','typing-row');row.append(avatar(active));const bubble=node('div','typing-bubble');bubble.append(node('span','',`${name(active)} is thinking`));const dots=node('span','typing-dots');for(let i=0;i<3;i++)dots.append(node('i',''));bubble.append(dots);row.append(bubble);feed.append(row);
 }
 if(!shown.length){feed.append(node('p','small muted','No matching events yet.'));}
 scrollChatToLatest();
 text('feed-note',!connected?'Connection interrupted · reconnecting':busy?(mode==='demo'?'Simulated model generation and tool activity':'Model generation and observed tool activity'):ended?'Final outcome recorded':'Ready for the next mission');
}
function setConnection(value){connected=value;const el=$('connection');el.className='connection '+(value?'connected':'disconnected');el.lastChild.textContent=value?'Connected':'Reconnecting';render();}
function configure(data){
 const switching=data.mode!==mode;mode=data.mode;
 if(mode==='demo'){demoPaused=data.demo_paused??demoPaused;demoSpeed=data.demo_speed??demoSpeed;}
 else if(switching){const saved=savedLiveView();demoPaused=saved.paused===true;demoSpeed=[.5,1,2,4].includes(saved.speed)?saved.speed:1;}
 token=data.token||token;const badge=$('mode-badge');badge.className='pill '+mode;badge.textContent=mode==='live'?'LIVE · ODOO WORKFLOW':'DEMO · SIMULATED';text('record-mode',mode==='demo'?'DEMO':'ODOO');text('mode-note',mode==='demo'?'Preview the complete flow. No ERP records are changed.':'Creates real Odoo orders and validates receipts and delivery.');
}
function snapshot(data){
 configure(data);
 const saved=savedLiveView(),cursor=mode==='live'&&saved.missionId===data.mission_id?Math.min(saved.lastId||0,data.last_id):0;
 reset(data.mission_id);lastId=0;liveQueue=[];beatRemaining=0;sourceOutcome='';
 if(mode==='live'){
  for(const e of data.events){observeSource(e);if(e.id<=cursor)accept(e,true);else liveQueue.push(e);}
  // Completed calls are compacted on the server. Preserve the visible partial
  // generation if a paused reader refreshes before reaching its final snapshot.
  if(saved.missionId===data.mission_id)for(const generation of saved.inflight||[]){
    if(events.some(e=>e.kind==='model_stream'&&e.stream_id===generation.stream_id))continue;
    for(const phase of ['thinking','output'])if(generation[phase])accept({...generation,id:cursor,kind:'model_stream',phase,delta:generation[phase]},true);
  }
  receivedId=data.last_id;sourceBusy=data.busy;
  busy=sourceBusy||liveQueue.length>0;
 }else{for(const e of data.events)accept(e,true);lastId=data.last_id;receivedId=data.last_id;busy=data.busy;}
 settleThinking();
 if(mode==='live'&&saved.missionId===data.mission_id)for(const [key,count] of saved.typing||[])if(thinkingReveal.has(key))thinkingReveal.set(key,{count,credit:0});
 if(busy){$('product').value=data.product;$('quantity').value=data.quantity;}
 render();
}
$('request-form').addEventListener('submit',async event=>{
 event.preventDefault();if(busy||!connected||(mode==='live'&&(sourceBusy||liveQueue.length)))return;text('form-error','');$('start').disabled=true;
 pendingRequest ||= crypto.randomUUID();
 try{const response=await fetch('/api/missions',{method:'POST',headers:{'Content-Type':'application/json','X-ERP-Bar-Token':token},body:JSON.stringify({product:$('product').value.trim(),quantity:Number($('quantity').value),request_id:pendingRequest})});const data=await response.json();if(!response.ok){if(response.status!==409)pendingRequest=null;throw Error(data.error || 'Unable to start the mission.');}pendingRequest=null;}
 catch(error){text('form-error',error.message || 'Connection lost. Reconnect before retrying.');}
 finally{render();}
});
document.querySelectorAll('[data-agent]').forEach(card=>card.addEventListener('click',()=>{selected=card.dataset.agent;lastFocus='';render();}));
document.querySelectorAll('[data-filter]').forEach(button=>button.addEventListener('click',()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>{const on=b===button;b.classList.toggle('selected',on);b.setAttribute('aria-pressed',String(on));});renderFeed();}));
function scrollChatToLatest(){
 const feed=$('feed');
 feed.scrollTop=feed.scrollHeight;
 requestAnimationFrame(()=>{feed.scrollTop=feed.scrollHeight;});
}
$('follow').addEventListener('click',scrollChatToLatest);
setInterval(()=>{const seconds=started?Math.max(0,Math.floor(((ended||Date.now())-started)/1000)):0;text('elapsed',`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')}`);for(const [key,a] of Object.entries(agents)){document.querySelector(`[data-agent="${key}"] .agent-timer`).textContent=active===key&&a.time&&busy&&connected&&!(mode==='live'&&(liveQueue.length||demoPaused))?`${Math.max(0,Math.floor((Date.now()-new Date(a.time))/1000))}s`:'';}},1000);
new ResizeObserver(drawRoutes).observe($('agent-canvas'));
new ResizeObserver(scrollChatToLatest).observe($('feed'));
async function connect(){
 try{const response=await fetch('/api/state');if(!response.ok)throw Error('Server unavailable');snapshot(await response.json());const stream=new EventSource('/api/events');stream.addEventListener('snapshot',e=>{setConnection(true);snapshot(JSON.parse(e.data));});stream.onmessage=e=>receive(JSON.parse(e.data));stream.onopen=()=>{setConnection(true);fetch('/api/state').then(r=>r.json()).then(configure).catch(()=>{});};stream.onerror=()=>setConnection(false);}
 catch(error){text('form-error','Could not connect to the local dashboard. Keep run_agent_view.py running.');setConnection(false);setTimeout(connect,3000);}
}
drawRoutes();connect();
