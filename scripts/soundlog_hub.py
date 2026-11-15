#!/usr/bin/env python3
"""Loopback-only workbench with persistent agent-question queue."""
import argparse
import json
import mimetypes
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote
from soundlog_memory.pipeline import Pipeline
from soundlog_memory.library_tools import library, ask
from soundlog_memory.scenes import digest_bytes

PAGE='''<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Soundlog 工作台</title><style>body{font:17px/1.65 system-ui;max-width:1080px;margin:24px auto;padding:20px;background:#f5f5f1}section,article{padding:20px;margin:16px 0;background:white;border-radius:12px}input,button{font:inherit;padding:10px}input{width:72%}button{cursor:pointer}pre{white-space:pre-wrap}a{color:#285d48}.muted{color:#666}</style><h1>Soundlog 工作台</h1><p>录音资料、历史事项和证据问答</p><section><h2>证据问答</h2><input id="question" aria-label="问题" placeholder="例如：我答应发送哪些资料？"><button id="ask">提交问题</button><p class="muted">由agent读取原文后回答，按定时任务处理；等待状态会保留。检索提示词可在下方填写。</p><input id="queries" aria-label="检索提示词" placeholder="可选：仿真,资料（多个词以逗号分隔）"></section><section><h2>问题与回答</h2><div id="questions"></div></section><section><h2>资料入口</h2><div id="links"></div></section><section><h2>事项变化</h2><div id="tasks"></div></section><p id="error"></p><script>
const base=location.pathname.replace(/\/$/,''),el=(tag,text)=>{let x=document.createElement(tag);x.textContent=text;return x};
async function api(path,options){let r=await fetch(base+'/api/'+path,options);let d=await r.json();if(!r.ok)throw Error(d.error||r.status);return d}
function link(text,path){let a=el('a',text);a.href=base+'/files/'+path;return a}
async function load(){try{let d=await api('overview'),l=document.querySelector('#links');l.replaceChildren();for(let row of d.links)l.append(link(row.title,row.path),el('br',''));let tasks=document.querySelector('#tasks');tasks.replaceChildren();for(let t of d.tasks){let a=el('article','');a.append(el('h3',t.stateLabel),el('p',t.timeline.map(x=>x.date+' '+x.summary).join('\\n')));tasks.append(a)}let q=await api('questions'),out=document.querySelector('#questions');out.replaceChildren();for(let x of q){let a=el('article','');a.append(el('h3',x.question),el('p',({'awaiting_agent':'等待agent处理','processing':'正在处理','answered':'已完成','failed':'处理失败'})[x.state]||x.state));if(x.error)a.append(el('p',x.error));if(x.answer){for(let c of x.answer.claims){a.append(el('p',c.text));for(let e of c.evidence){let s=x.sources[e.id]||{};a.append(el('p',(s.start||'')+' '+(s.sourceFile||'')+' '+(s.startOffsetSeconds??'')+'秒'),el('pre',e.quote))}}a.append(el('p','尚不明确：'+x.answer.unknown))}out.append(a)}}catch(e){document.querySelector('#error').textContent=e.message}}
document.querySelector('#ask').onclick=async()=>{try{let question=document.querySelector('#question').value.trim(),queries=document.querySelector('#queries').value.split(/[,，]/).map(x=>x.trim()).filter(Boolean);await api('questions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,queries})});await load()}catch(e){document.querySelector('#error').textContent=e.message}};load();setInterval(load,10000);
</script>'''


def markdown_html(text):
 import html
 def inline(line):
  escaped=html.escape(line)
  def link(m):
   target=html.unescape(m.group(2))
   if target.startswith('/') or ':' in target or target.startswith('\\'):return m.group(0)
   return '<a href="'+html.escape(target,quote=True)+'">'+m.group(1)+'</a>'
  return re.sub(r'\[([^\]]+)\]\(([^)]+)\)',link,escaped)
 lines=[];code=False
 for line in text.splitlines():
  if line.startswith('```'):
   lines.append('</pre>' if code else '<pre>');code=not code;continue
  if code:lines.append(html.escape(line));continue
  anchor=re.fullmatch(r'<a id="([a-zA-Z0-9_-]+)"></a>',line)
  if anchor:lines.append('<a id="'+anchor[1]+'"></a>');continue
  heading=re.match(r'^(#{1,6}) (.*)',line)
  if heading:lines.append('<h'+str(len(heading[1]))+'>'+inline(heading[2])+'</h'+str(len(heading[1]))+'>')
  else:lines.append('<p>'+inline(line)+'</p>')
 if code:lines.append('</pre>')
 return '<!doctype html><meta charset="utf-8"><style>body{font:17px/1.65 system-ui;max-width:1000px;margin:32px auto;padding:20px}pre{white-space:pre-wrap}a{color:#285d48}</style>'+''.join(lines)


def handler(root,token):
 root=Path(root).resolve(); pipeline=Pipeline(root);prefix='/'+token
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def allowed(self):
   host=self.headers.get('Host','');port=self.server.server_port
   expected={f'127.0.0.1:{port}',f'localhost:{port}'}
   if host not in expected:return False
   origin=self.headers.get('Origin')
   return not origin or origin in {'http://'+x for x in expected}
  def reply(self,code,data,kind='application/json; charset=utf-8'):
   body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
   self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
   self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
   self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
   self.end_headers();self.wfile.write(body)
  def do_GET(self):
   if not self.allowed():self.send_error(404);return
   url=urlsplit(self.path);path=url.path
   try:
    if path in {prefix,prefix+'/'}:self.reply(200,PAGE.encode(),'text/html; charset=utf-8');return
    if path==prefix+'/api/questions':
     rows=[]
     for folder in sorted((pipeline.home/'questions').glob('question-*')):
      request=json.loads((folder/'request.json').read_text());answer_path=folder/'answer.json';status_path=folder/'status.json'
      status=json.loads(status_path.read_text()) if status_path.exists() else {'state':'awaiting_agent'}
      answer=json.loads(answer_path.read_text()) if answer_path.exists() else None
      retrieval=folder/'retrieval.json'
      if retrieval.exists():
       extra=json.loads(retrieval.read_text());request={**request,'facts':request['facts']+extra['facts'],'rawEvidence':request.get('rawEvidence',[])+extra['rawEvidence']}
      sources={e['id']:e for f in request['facts'] for e in f['evidence']}
      for part in request.get('rawEvidence',[]):sources.update({e['id']:e for e in part['matches']})
      rows.append({'sources':sources,'id':folder.name,'question':request['question'],'state':'answered' if answer else status['state'],'error':status.get('error'),'answer':answer})
     self.reply(200,rows);return
    if path==prefix+'/api/overview':
     catalog=json.loads((pipeline.delivery/'catalog.json').read_text());links=[{'title':'全部日期检索','path':'index.html'},{'title':'事项跟踪','path':'task-tracking.md'}]
     for day,bundle in sorted(catalog['days'].items()):links.append({'title':day+' 每日首页','path':bundle+'/'+day+'/README.md'})
     p=pipeline.delivery/'derived/latest.json'
     if p.exists():links.append({'title':'知识、脑图、规整与写作','path':'derived/'+json.loads(p.read_text())['id']+'/README.md'})
     if (pipeline.delivery/'reviews/README.md').exists():links.append({'title':'跨天与每周复盘','path':'reviews/README.md'})
     graph=pipeline.delivery/'task-graph.json';tasks=json.loads(graph.read_text())['tasks'] if graph.exists() else []
     self.reply(200,{'links':links,'tasks':[t for t in tasks if t['links']]});return
    if path.startswith(prefix+'/files/'):
     rel=unquote(path[len(prefix+'/files/'):]);file=(pipeline.delivery/rel).resolve()
     if not file.is_relative_to(pipeline.delivery.resolve()) or not file.is_file():raise ValueError('文件不存在或越界')
     # Verify bundles against their declared immutable checksum before serving.
     parent=file.parent
     while parent!=pipeline.delivery:
      receipt=parent/'receipt.json'
      if receipt.exists():
       metadata=json.loads(receipt.read_text());name=str(file.relative_to(parent))
       if name!='receipt.json' and metadata.get('artifacts',{}).get(name)!=digest_bytes(file):raise ValueError('交付工件校验失败')
       break
      parent=parent.parent
     kind=mimetypes.guess_type(file.name)[0] or 'text/plain'
     if file.suffix=='.md':
      text=file.read_text();self.reply(200,markdown_html(text).encode(),'text/html; charset=utf-8')
     else:self.reply(200,file.read_bytes(),kind+'; charset=utf-8')
     return
    self.send_error(404)
   except (OSError,ValueError,KeyError,TypeError) as e:self.reply(400,{'error':str(e)})
  def do_POST(self):
   if not self.allowed() or urlsplit(self.path).path!=prefix+'/api/questions':self.send_error(404);return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=16384:raise ValueError('请求长度无效')
    body=json.loads(self.rfile.read(length));question=body.get('question','');queries=body.get('queries',[])
    if not isinstance(question,str) or not question.strip() or len(question)>2000 or not isinstance(queries,list) or len(queries)>12 or any(not isinstance(q,str) or len(q)>100 for q in queries):raise ValueError('问题或检索词无效')
    # Agent expands these terms before answering; the phrase alone is not treated as exhaustive retrieval.
    if not queries:queries=[question.strip()[:100]]
    snapshot=pipeline.scenes if (pipeline.scenes/'latest.json').exists() else None
    with pipeline.lock():result=ask(pipeline.delivery,pipeline.home,question,queries,snapshot)
    self.reply(201,result)
   except (OSError,ValueError,KeyError,TypeError) as e:self.reply(400,{'error':str(e)})
 return Handler


def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);p.add_argument('--port',type=int,default=0);p.add_argument('--reuse-session',action='store_true');a=p.parse_args()
 token=secrets.token_urlsafe(24)
 previous=a.root/'记忆库/运行/自动管线/hub.json'
 if a.reuse_session and previous.exists():
  parsed=urlsplit(json.loads(previous.read_text())['url']);candidate=parsed.path.strip('/')
  if parsed.hostname!='127.0.0.1' or not re.fullmatch(r'[A-Za-z0-9_-]{24,}',candidate):raise ValueError('旧会话地址无效')
  token=candidate;a.port=a.port or parsed.port
 server=ThreadingHTTPServer(('127.0.0.1',a.port),handler(a.root,token))
 runtime=a.root/'记忆库/运行/自动管线';runtime.mkdir(parents=True,exist_ok=True)
 url=f'http://127.0.0.1:{server.server_port}/{token}/'
 (runtime/'hub.json').write_text(json.dumps({'url':url,'pid':__import__('os').getpid()}));print(url,flush=True)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
if __name__=='__main__':main()
