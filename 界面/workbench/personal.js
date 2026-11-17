'use strict';
async function personal(){
 const d=await api('personal'),body=H('div');
 add(body,title('与我有关的事。','我的承诺、别人交办我的事，以及我表达过的想法。每项都有原文依据，历史说法与当前进度分开。'));
 const names={commitment:'我的承诺',request_to_me:'别人交办我的事',expression:'我的想法与表达'},stats=H('div',null,'stats');
 for(const[k,name]of Object.entries(names))add(stats,add(H('div',null,'stat'),H('div',name,'stat-label'),H('strong',d.counts[k])));
 add(body,stats);
 if(d.stale.length)add(body,H('p',d.stale.length+' 项声音确认已变化，相关个人内容已隐藏，等待重新审阅。','notice'));
 for(const[k,name]of Object.entries(names)){
  add(body,heading(name));const list=H('div',null,'cards two');
  for(const item of d.items.filter(x=>x.kind===k)){
   const card=H('article',null,'card');
   add(card,add(H('div',null,'tag-row'),tag(k==='commitment'?'当时承诺':k==='request_to_me'?'当时请求':'本人表达'),tag(k==='expression'?'保留当时说法':'当前进度未知','gray')),H('h3',item.summary),H('p',item.recordedStart,'muted'));
   if(k!=='expression')add(card,H('p','未提取明确期限；不据此判断逾期、未完成或已完成。','muted'));
   const details=H('details');add(details,H('summary','查看原文与审阅说明'),H('p',item.reason,'notice'));
   for(const e of item.evidence)add(details,H('blockquote',e.quote),H('p',e.start+' · '+e.sourceFile+' · '+e.startOffsetSeconds+'秒','muted'),e.voiceAttribution?tag(e.voiceAttribution.role==='self'?'本人 · 用户确认':'他人 · 用户排除本人','gray'):tag('声音归属未确认','amber'),audioControl(e));
   add(card,details);list.append(card);
  }
  if(!list.children.length)list.append(empty(k==='request_to_me'?'目前没有足够证据确认交办给你的事项。仅听到别人提出要求，不能判断对象就是你。':'目前没有经审阅且归属明确的内容。'));
  body.append(list);
 }
 if(d.ignored.length){
  const details=H('details',null,'card');add(details,H('summary',d.ignored.length+' 段已审阅，本轮不生成个人内容'));
  for(const item of d.ignored)add(details,H('h3',item.summary),H('p',item.reason,'muted'));body.append(details);
 }
 add(body,H('p',d.reviewBoundary||d.boundary,'muted'));return body;
}
