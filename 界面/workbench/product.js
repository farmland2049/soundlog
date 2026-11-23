'use strict';
const base=location.pathname.replace(/\/$/,''),out=document.querySelector('#content');
const names={all:'每日记录',meeting:'会议纪要',conversation:'交谈记录',event:'生活与事件',actions:'待办与开口项',knowledge:'学习与知识',writing:'创作素材',reviews:'跨天复盘',history:'处理历史'};
const descriptions={all:'会议、交谈和生活里值得留下的事。',meeting:'会上的重点、下一步要做的事，以及还没解决的问题。',conversation:'聊过什么，留下了什么。',event:'生活中值得记住的片刻。',actions:'按会议与交谈整理的行动安排和待解决问题。',knowledge:'把听到的内容，变成可以再用的知识。',writing:'已有材料整理成的写作提纲。',reviews:'回看这段时间的重要内容。',history:'查看录音文件是否完成处理。'};
let data,view='all';
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const append=(p,...cs)=>{for(const c of cs)if(c)p.append(c);return p};
const section=(title,rows)=>{if(!rows?.length)return null;const s=el('section',undefined,'section'),ul=el('ul');s.append(el('h3',title));for(const row of rows){const item=el('li',typeof row==='string'?row:row.text);if(row.owner||row.due)item.append(el('span',[row.owner,row.due].filter(Boolean).join(' · '),'owner'));ul.append(item)}return append(s,ul)};
function activity(a,taskOnly=false){const card=el('article',undefined,'activity');append(card,append(el('div',undefined,'meta'),el('span',({meeting:'会议',conversation:'交谈',event:'事件'})[a.kind],'badge '+a.kind),el('span',a.time)),el('h2',a.title));if(!taskOnly){append(card,el('p',a.summary,'summary'),section(a.kind==='meeting'?'会议纪要':'内容要点',a.minutes),section('结论与方向',a.decisions))}const cols=el('div',undefined,'columns');append(cols,section('待办清单',a.actions),section('开口项',a.openItems));if(cols.children.length)card.append(cols);return card}
function matches(x,q){return !q||JSON.stringify(x).toLowerCase().includes(q.toLowerCase())}
function documentDetails(title,path){
 const details=append(el('details',undefined,'record-details'),el('summary',title));
 details.addEventListener('toggle',()=>{
  if(!details.open||details.querySelector('iframe'))return;
  const frame=el('iframe');
  frame.title=title;
  frame.src=base+'/files/'+path.split('/').map(encodeURIComponent).join('/');
  details.append(frame);
 });
 return details;
}
const archiveLabels={pending:'待准备归档',draft_ready:'待归档',archived:'已归档到 Basic Memory',
 needs_update:'交付已更新 · 待重新归档',draft_error:'归档草稿准备失败',verification_failed:'归档核验失败'};
function appendDay(date,q){
 const rows=data.activities.filter(item=>item.date===date.date&&matches(item,q)&&
  (view==='all'||(view==='actions'?(item.actions.length||item.openItems.length):item.kind===view)));
 const personal=(data.personal||[]).filter(item=>item.date===date.date&&matches(item,q)&&
  (view==='conversation'?item.kind==='expression':view==='actions'&&item.kind!=='expression'));
 const showDay=view==='all'&&matches(date.summary,q);
 const showMinutes=view==='meeting'&&date.minutes&&(!q||rows.length);
 if(!rows.length&&!personal.length&&!showDay&&!showMinutes)return;
 out.append(el('h2',date.date.replaceAll('-',' / '),'day-heading'));
 if(view==='all'){
  const archive=date.archive||{};
  const dayCard=append(el('article',undefined,'activity'),el('p',archiveLabels[archive.state]||'待准备归档','badge'));
  if(date.summary)dayCard.append(el('p',date.summary,'summary'));
  if(date.reviewDocument)dayCard.append(documentDetails('查看每日复盘',date.reviewDocument));
  if(archive.draft&&archive.state!=='archived')dayCard.append(documentDetails('查看归档草稿',archive.draft));
  out.append(dayCard);
 }
 if(showMinutes)out.append(documentDetails('查看当天完整纪要及依据',date.minutes));
 for(const item of personal){
  const label={expression:'本人表达',commitment:'本人当时的承诺',request_to_me:'当时交给我的请求'}[item.kind];
  const card=append(el('article',undefined,'activity'),el('span',label,'badge'),el('p',item.summary,'summary'));
  if(item.kind!=='expression')card.append(el('p','当前是否完成仍待核实。','quiet'));
  out.append(card);
 }
 for(const item of rows)out.append(activity(item,view==='actions'));
}

function renderFollowups(date,q){
 const items=(data.followups||[]).filter(item=>(!date||item.timeline.some(row=>row.date===date))&&matches(item,q));
 if(!items.length)return;
 const details=append(el('details',undefined,'activity'),el('summary','跨天跟进线索（'+items.length+'）'));
 for(const item of items){
  append(details,el('h3',item.label),el('p',item.reason,'quiet'),section('录音时间线',
   item.timeline.map(row=>row.date+' · '+row.summary)));
 }
 details.append(el('p','这些是历史线索，当前状态仍待核实。','quiet'));
 out.append(details);
}
function render(){if(!data)return;view=names[location.hash.slice(1)]?location.hash.slice(1):'all';document.querySelector('#title').textContent=names[view];document.querySelector('#description').textContent=descriptions[view];document.querySelector('#filters').hidden=['knowledge','writing','reviews','history'].includes(view);for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-current',b.dataset.view===view?'page':'false')}out.replaceChildren();const date=document.querySelector('#date').value,q=document.querySelector('#search').value.trim();
 if(view==='history'){showHistory();return}
 if(['all','meeting','conversation','event','actions'].includes(view)){
  if(view==='actions')renderFollowups(date,q);
  for(const day of data.days)if(!date||day.date===date)appendDay(day,q);
 }
 else if(view==='knowledge'){const grid=el('div',undefined,'knowledge-grid');for(const k of data.knowledge){const c=append(el('article',undefined,'activity'),el('span',k.audience==='child'?'儿童学习':'成人学习与讨论','badge'),el('h2',k.title));for(const[key,label]of [['concepts','重点'],['methods','方法'],['examples','例子'],['questions','思考问题']])append(c,section(label,k[key]));if(k.sprouts?.length){const d=append(el('details'),el('summary','延伸思考'));append(d,section('可以继续想想',k.sprouts));c.append(d)}grid.append(c)}out.append(grid)}
 else if(view==='writing'){for(const w of data.writing){const c=append(el('article',undefined,'activity'),el('span','写作提纲','badge'),el('h2',w.title));for(const s of w.sections)append(c,section(s.title,s.texts));out.append(c)}}
 else if(view==='reviews'){for(const r of data.reviews.filter(x=>x.updated)){const c=append(el('article',undefined,'activity'),el('h2',r.start+' — '+r.end));for(const s of r.sections)append(c,section(s.title,[s.text]));if(r.missingDays.length)c.append(el('p','缺少记录的日期：'+r.missingDays.join('、'),'quiet'));out.append(c)}}
 if(!out.children.length||out.children.length===1&&!out.firstChild.children.length)out.replaceChildren(el('div','这组筛选下还没有记录。','empty'));
}
async function load(){try{const r=await fetch(base+'/api/products',{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'读取失败');data=d;const select=document.querySelector('#date'),previous=select.value;select.replaceChildren(new Option('全部日期',''));for(const d of data.days)select.append(new Option(d.date,d.date));select.value=previous;render()}catch(error){out.replaceChildren(el('p','暂时无法打开记录：'+error.message,'empty'))}}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>location.hash=b.dataset.view;
window.addEventListener('hashchange',render);document.querySelector('#date').onchange=render;document.querySelector('#search').oninput=render;

const startRun=document.querySelector('#start-run'),runStatus=document.querySelector('#run-status');
const pipelineProgress=document.querySelector('#pipeline-progress');
const pipelineStage=document.querySelector('#pipeline-stage');
const pipelineStageCount=document.querySelector('#pipeline-stage-count');
const pipelineTrack=document.querySelector('#pipeline-progress-track');
const pipelineFill=document.querySelector('#pipeline-progress-fill');
const agentHandoff=document.querySelector('#agent-handoff');
const agentDialog=document.querySelector('#agent-dialog');
const agentPrompt=document.querySelector('#agent-prompt');
const agentCopyStatus=document.querySelector('#agent-copy-status');
let runTimer=null;
let latestAgentPrompt='';
let lastRunStatus='';
const desktopWindow=new URLSearchParams(location.search).get('desktop')==='1';
let startingRun=false;

function updateProgress(progress){
 if(!progress)return;
 const total=progress.total||6,step=progress.step||0,percent=Math.max(0,Math.min(100,progress.percent||0));
 pipelineStage.textContent=progress.label||'等待开始';
 pipelineStageCount.textContent=step+'/'+total;
 pipelineFill.style.width=percent+'%';
 pipelineProgress.dataset.state=progress.state||'idle';
 pipelineTrack.setAttribute('aria-valuenow',String(percent));
 pipelineTrack.setAttribute('aria-valuetext',`${progress.label||'等待开始'}，第${step}阶段，共${total}阶段，约${percent}%`);
}
function progressFor(status, pipeline){
 const phase=pipeline?.state,manual=pipeline?.manual?.state,total=6;
 const make=(step,percent,label,state)=>({step,total,percent,label,state});
 const phaseState=['failed','agent_failed'].includes(status.state)?'failed':status.state==='running'?'running':'waiting';
 if(status.state==='completed')return make(6,100,'处理与成果核验完成','completed');
 if(status.resultState==='waiting_for_mounted_audio'&&status.state==='running'){
  return make(1,8,'等待外部录音写入完成','waiting');
 }
 if(status.state==='waiting')return make(1,5,'等待录音文件稳定','waiting');
 if(status.state==='running'&&manual==='running'){
  return phase==='processing_audio'?make(2,25,'转写与声音分析','running'):make(1,8,'检查录音来源','running');
 }
 if(phase==='processing_audio')return make(2,25,'转写与声音分析',phaseState);
 if(phase==='audio_failed')return make(2,25,'音频处理失败（原音保留）','failed');
 if(phase==='awaiting_agent')return make(3,43,'语义提炼与问题处理',phaseState);
 if(phase==='awaiting_screening')return make(4,60,'逐项筛选与每日交付',phaseState);
 if(phase==='awaiting_enrichment')return make(5,78,'纪要、事项、知识与复盘',phaseState);
 if(status.state==='running'&&manual==='agent_running')return make(6,94,'核对成果发布与队列','running');
 if(status.state==='needs_agent')return make(3,43,'语义提炼与问题处理','waiting');
 if(['failed','agent_failed'].includes(status.state))return make(1,8,'处理未完成','failed');
 return make(0,0,'等待开始','idle');
}

agentHandoff.onclick=()=>{
 agentPrompt.value=latestAgentPrompt;
 agentCopyStatus.textContent='';
 agentDialog.showModal();
};
document.querySelector('#close-agent-dialog').onclick=()=>agentDialog.close();
document.querySelector('#copy-agent-prompt').onclick=async()=>{
 try{
  await navigator.clipboard.writeText(agentPrompt.value);
  agentCopyStatus.textContent='已复制，请粘贴到 Agent 对话发送。';
 }catch{
  agentPrompt.focus();
  agentPrompt.select();
  agentCopyStatus.textContent='已选中提示词，请按 ⌘C（Windows 为 Ctrl+C）复制。';
 }
};
async function checkRun(force=false){
 clearTimeout(runTimer);
 try{
  const r=await fetch(base+'/api/run-status',{cache:'no-store'});if(!r.ok)throw Error('读取失败');const s=await r.json();
  if(desktopWindow&&s.mountWake&&!startingRun){
   await startProcessing('mount');
   return;
  }
  const statusKey=JSON.stringify(s);
  if(!force&&s.state!=='running'&&statusKey===lastRunStatus)return;
  lastRunStatus=statusKey;
  let pipeline=null;
  try{const p=await fetch(base+'/api/workbench',{cache:'no-store'});if(p.ok)pipeline=(await p.json()).pipeline}catch{}
  latestAgentPrompt=s.agentPrompt||'';
  updateProgress(progressFor(s,pipeline));
  agentHandoff.hidden=s.state!=='agent_failed'||!latestAgentPrompt;
  runStatus.textContent=s.message;startRun.disabled=s.state==='running';startRun.textContent=s.state==='running'?'正在处理…':'开始处理录音';
  if(s.state!=='running')await load();
 }catch{lastRunStatus='';agentHandoff.hidden=true;runStatus.textContent='连接中断，请刷新后查看。';startRun.disabled=false;if(force||!data)await load()}
 finally{clearTimeout(runTimer);runTimer=setTimeout(checkRun,3000)}
}
async function startProcessing(trigger='manual'){
 if(startingRun)return;
 startingRun=true;
 startRun.disabled=true;agentHandoff.hidden=true;runStatus.textContent='正在检查录音…';
 updateProgress({step:1,total:6,percent:5,label:'检查录音来源',state:'running'});
 try{
  const path=trigger==='mount'?'/api/run?trigger=mount':'/api/run';
  const r=await fetch(base+path,{method:'POST'});
  if(!r.ok)throw Error('启动失败');
  await checkRun(true);
 }
 catch{runStatus.textContent='暂时无法启动，请重试。';startRun.disabled=false}
 finally{startingRun=false}
}
startRun.onclick=()=>startProcessing();
document.querySelector('#refresh').onclick=()=>checkRun(true);
checkRun();

const settingsDialog=document.querySelector('#settings-dialog'),settingsStatus=document.querySelector('#settings-status');
const agentForm=document.querySelector('#agent-settings-form');
const defaultAgent=document.querySelector('#default-agent');
const defaultModel=document.querySelector('#default-model');
const agentStatus=document.querySelector('#agent-settings-status');
const agentSave=agentForm.querySelector('button[type="submit"]');
let savedAgentSettings=null;
let agentLoadRevision=0;

function setAgentFieldsEnabled(enabled){
 defaultAgent.disabled=!enabled;
 defaultModel.disabled=!enabled;
 agentSave.disabled=!enabled||!defaultAgent.value||defaultAgent.selectedOptions[0]?.disabled;
}

async function loadAgentSettings(){
 const revision=++agentLoadRevision;
 agentStatus.textContent='正在读取整理设置…';
 setAgentFieldsEnabled(false);
 try{
  const response=await fetch(base+'/api/agent-settings',{cache:'no-store'});
  if(!response.ok)throw Error('读取失败');
  const settings=await response.json();
  if(revision!==agentLoadRevision)return;
  savedAgentSettings=settings;
  defaultAgent.replaceChildren(...settings.agents.map(agent=>{
   const option=new Option(agent.label+(agent.available?'':'（本机不可用）'),agent.id);
   option.disabled=!agent.available;
   return option;
  }));
  defaultAgent.value=settings.agent;
  defaultModel.value=settings.model;
  setAgentFieldsEnabled(true);
  agentStatus.textContent=agentSave.disabled?'请选择本机可用的 Agent。':'';
 }catch{
  if(revision===agentLoadRevision)agentStatus.textContent='暂时无法读取整理设置，请关闭后重试。';
 }
}

defaultAgent.onchange=()=>{
 defaultModel.value=defaultAgent.value===savedAgentSettings?.agent?savedAgentSettings.model:'';
 setAgentFieldsEnabled(true);
 agentStatus.textContent='';
};
agentForm.onsubmit=async event=>{
 event.preventDefault();
 const revision=agentLoadRevision;
 const data={agent:defaultAgent.value,model:defaultModel.value.trim()};
 setAgentFieldsEnabled(false);
 try{
  const response=await fetch(base+'/api/agent-settings',{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const settings=await response.json();
  if(!response.ok)throw Error(settings.error||'保存失败');
  if(revision!==agentLoadRevision)return;
  savedAgentSettings=settings;
  defaultModel.value=settings.model;
  agentStatus.textContent='已保存，下次调用 Agent 时生效。';
 }catch(error){
  if(revision===agentLoadRevision)agentStatus.textContent=error.message;
 }finally{
  if(revision===agentLoadRevision)setAgentFieldsEnabled(true);
 }
};
document.querySelector('#open-settings').onclick=async()=>{
 settingsStatus.textContent='';settingsDialog.showModal();
 loadAgentSettings();
 try{const r=await fetch(base+'/api/audio-sources');if(!r.ok)throw Error('读取失败');const s=await r.json();document.querySelector('#sources-form button[type="submit"]').disabled=false;document.querySelector('#source-memos').checked=s.voiceMemos;document.querySelector('#source-auto-mount').checked=Boolean(s.autoProcessOnMount);document.querySelector('#source-directories').value=s.directories.join('\n');const history=await fetch(base+'/api/audio-imports');if(history.ok){const last=await history.json();if(last.date)settingsStatus.textContent='最近检查：导入 '+last.copied+' 份，重复 '+last.duplicates+' 份，跳过 '+last.skipped+' 份。'}}
 catch{settingsStatus.textContent='读取设置失败，请关闭后重试。';document.querySelector('#sources-form button[type="submit"]').disabled=true}
};
document.querySelector('#close-settings').onclick=()=>settingsDialog.close();
document.querySelector('#sources-form').onsubmit=async event=>{
 event.preventDefault();const b=event.submitter;b.disabled=true;
 try{const r=await fetch(base+'/api/audio-sources',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({voiceMemos:document.querySelector('#source-memos').checked,autoProcessOnMount:document.querySelector('#source-auto-mount').checked,directories:document.querySelector('#source-directories').value.split('\n').map(x=>x.trim()).filter(Boolean)})});const s=await r.json();if(!r.ok)throw Error(s.error||'保存失败');settingsStatus.textContent=s.autoProcessOnMount?'已保存，匹配的外部存储接入后将自动处理。':'已保存。点击“开始处理录音”可手动导入。'}catch(e){settingsStatus.textContent=e.message}finally{b.disabled=false}
};

let historyRevision=0;
async function showHistory(){const ticket=++historyRevision;out.replaceChildren(el('p','正在读取历史…','quiet'));try{const r=await fetch(base+'/api/history',{cache:'no-store'});if(!r.ok)throw Error('读取失败');const d=await r.json();if(ticket!==historyRevision||view!=='history')return;out.replaceChildren();for(const f of d.files){const c=el('article',undefined,'activity');append(c,el('p',f.recordedTime,'meta'),el('h2',f.name));const processed=['completed','archived'].includes(f.audioState);append(c,el('p','处理状态：'+({completed:'已处理',failed:'处理失败',processing:'处理中',archived:'已处理',waiting:'未处理'})[f.audioState],'summary'));if(f.note)c.append(el('p',f.note,'quiet'));if(processed){const b=el('button','查看当日记录','history-open');b.onclick=()=>{document.querySelector('#date').value=f.date;location.hash='all'};c.append(b)}out.append(c)}if(!d.files.length)out.append(el('div','还没有录音文件记录。','empty'))}catch{if(view==='history')out.replaceChildren(el('p','暂时无法读取处理历史，请刷新重试。','empty'))}}
