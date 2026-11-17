'use strict';
const base=location.pathname.replace(/\/$/,''),out=document.querySelector('#content');
const names={all:'每日记录',meeting:'会议纪要',conversation:'交谈记录',event:'生活与事件',actions:'待办与开口项',knowledge:'学习与知识',writing:'创作素材',reviews:'跨天复盘'};
const descriptions={all:'会议、交谈和生活里值得留下的事。',meeting:'会上的重点、下一步要做的事，以及还没解决的问题。',conversation:'聊过什么，留下了什么。',event:'生活中值得记住的片刻。',actions:'按会议与交谈整理的行动安排和待解决问题。',knowledge:'把听到的内容，变成可以再用的知识。',writing:'已有材料整理成的写作提纲。',reviews:'回看这段时间的重要内容。'};
let data,view='all';
const el=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e};
const append=(p,...cs)=>{for(const c of cs)if(c)p.append(c);return p};
const section=(title,rows)=>{if(!rows?.length)return null;const s=el('section',undefined,'section'),ul=el('ul');s.append(el('h3',title));for(const row of rows){const item=el('li',typeof row==='string'?row:row.text);if(row.owner||row.due)item.append(el('span',[row.owner,row.due].filter(Boolean).join(' · '),'owner'));ul.append(item)}return append(s,ul)};
function activity(a,taskOnly=false){const card=el('article',undefined,'activity');append(card,append(el('div',undefined,'meta'),el('span',({meeting:'会议',conversation:'交谈',event:'事件'})[a.kind],'badge '+a.kind),el('span',a.time)),el('h2',a.title));if(!taskOnly){append(card,el('p',a.summary,'summary'),section(a.kind==='meeting'?'会议纪要':'内容要点',a.minutes),section('结论与方向',a.decisions))}const cols=el('div',undefined,'columns');append(cols,section('待办清单',a.actions),section('开口项',a.openItems));if(cols.children.length)card.append(cols);return card}
function matches(x,q){return !q||JSON.stringify(x).toLowerCase().includes(q.toLowerCase())}
function render(){if(!data)return;view=names[location.hash.slice(1)]?location.hash.slice(1):'all';document.querySelector('#title').textContent=names[view];document.querySelector('#description').textContent=descriptions[view];document.querySelector('#filters').hidden=['knowledge','writing','reviews'].includes(view);for(const b of document.querySelectorAll('[data-view]')){b.classList.toggle('active',b.dataset.view===view);b.setAttribute('aria-current',b.dataset.view===view?'page':'false')}out.replaceChildren();const date=document.querySelector('#date').value,q=document.querySelector('#search').value.trim();
 if(['all','meeting','conversation','event','actions'].includes(view)){const rows=data.activities.filter(a=>(!date||a.date===date)&&matches(a,q)&&(view==='all'||view==='actions'?(view!=='actions'||a.actions.length||a.openItems.length):a.kind===view));let last='';for(const a of rows){if(a.date!==last){out.append(el('h2',a.date.replaceAll('-',' / '),'day-heading'));last=a.date}out.append(activity(a,view==='actions'))}}
 else if(view==='knowledge'){const grid=el('div',undefined,'knowledge-grid');for(const k of data.knowledge){const c=append(el('article',undefined,'activity'),el('span',k.audience==='child'?'儿童学习':'成人学习与讨论','badge'),el('h2',k.title));for(const[key,label]of [['concepts','重点'],['methods','方法'],['examples','例子'],['questions','思考问题']])append(c,section(label,k[key]));if(k.sprouts?.length){const d=append(el('details'),el('summary','延伸思考'));append(d,section('可以继续想想',k.sprouts));c.append(d)}grid.append(c)}out.append(grid)}
 else if(view==='writing'){for(const w of data.writing){const c=append(el('article',undefined,'activity'),el('span','写作提纲','badge'),el('h2',w.title));for(const s of w.sections)append(c,section(s.title,s.texts));out.append(c)}}
 else if(view==='reviews'){for(const r of data.reviews.filter(x=>x.updated)){const c=append(el('article',undefined,'activity'),el('h2',r.start+' — '+r.end));for(const s of r.sections)append(c,section(s.title,[s.text]));if(r.missingDays.length)c.append(el('p','缺少记录的日期：'+r.missingDays.join('、'),'quiet'));out.append(c)}}
 if(!out.children.length||out.children.length===1&&!out.firstChild.children.length)out.replaceChildren(el('div','这组筛选下还没有记录。','empty'));
}
async function load(){try{const r=await fetch(base+'/api/products',{cache:'no-store'});const d=await r.json();if(!r.ok)throw Error(d.error||'读取失败');data=d;const select=document.querySelector('#date'),previous=select.value;select.replaceChildren(new Option('全部日期',''));for(const d of data.days)select.append(new Option(d.date,d.date));select.value=previous;render()}catch(error){out.replaceChildren(el('p','暂时无法打开记录：'+error.message,'empty'))}}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>location.hash=b.dataset.view;
window.addEventListener('hashchange',render);document.querySelector('#date').onchange=render;document.querySelector('#search').oninput=render;document.querySelector('#refresh').onclick=load;load();

const startRun=document.querySelector('#start-run'),runStatus=document.querySelector('#run-status');
let runTimer=null;
async function checkRun(){
 try{
  const r=await fetch(base+'/api/run-status',{cache:'no-store'});if(!r.ok)throw Error('读取失败');const s=await r.json();
  runStatus.textContent=s.message;startRun.disabled=s.state==='running';startRun.textContent=s.state==='running'?'正在处理…':'开始处理录音';
  if(s.state==='running'){clearTimeout(runTimer);runTimer=setTimeout(checkRun,3000)}else{clearTimeout(runTimer);await load()}
 }catch{runStatus.textContent='连接中断，请刷新后查看。';startRun.disabled=false}
}
startRun.onclick=async()=>{
 startRun.disabled=true;runStatus.textContent='正在检查录音…';
 try{const r=await fetch(base+'/api/run',{method:'POST'});if(!r.ok)throw Error('启动失败');await checkRun()}
 catch{runStatus.textContent='暂时无法启动，请重试。';startRun.disabled=false}
};
checkRun();
