#!/usr/bin/env python3
"""Loopback-only workbench with persistent agent-question queue."""
import argparse
import json
import mimetypes
import re
import secrets
import threading
import time
from soundlog_memory import agent_runner, mount_trigger, product_view, workbench_view
from soundlog_memory.store import write_json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, unquote
from soundlog_memory.pipeline import Pipeline
from soundlog_memory.library_tools import library, ask
from soundlog_memory.scenes import digest_bytes

UI_ROOT = Path(__file__).resolve().parent.parent/'界面/workbench'



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
 run_lock=threading.Lock()
 stop=threading.Event()
 last_access=time.monotonic()

 def pending_wakes():
  folder=pipeline.home/'mount-wakes'
  active=None
  mounted={}
  requests=[]
  for path in folder.glob('*.json'):
   if not re.fullmatch(r'[a-f0-9]{32}\.json',path.name) or path.is_symlink():
    continue
   requests.append(path)
   try:
    sources=json.loads(path.read_text())['sources']
    if active is None:
     active=mount_trigger.mounted_sources(root)
    for name,identity in sources.items():
     if active.get(name) is not None and active[name]==tuple(identity):
      mounted[name]=active[name]
   except (OSError, ValueError, KeyError, TypeError, AttributeError):
    continue
  return mounted,requests

 def start_run(*, wake=False):
  if not run_lock.acquire(blocking=False):
   return 'already_running'
  mounted=None
  requests=[]
  if wake:
   try:
    mounted,requests=pending_wakes()
    if not mounted:
     for path in requests:path.unlink(missing_ok=True)
     run_lock.release()
     return 'no_pending_wake'
   except BaseException:
    run_lock.release()
    raise
  receipt=pipeline.home/'manual-run.json'
  trigger='external_storage' if mounted is not None else 'manual'
  run_id=secrets.token_hex(8)

  def record(**status):
   write_json(receipt,{'trigger':trigger,'runId':run_id,**status})

  def run():
   try:
    record(state='running')
    for path in requests:
     path.unlink(missing_ok=True)
    from soundlog_memory.audio_sources import collect
    if mounted is None:
     with pipeline.lock():
      collect(root)
    else:
     while True:
      with pipeline.lock():
       active=mount_trigger.mounted_sources(root)
       directories=[path for path,identity in mounted.items() if active.get(path)==identity]
       imports=collect(root,mounted_directories=directories) if directories else {}
      if not imports.get('waiting'):
       break
      record(state='running',resultState='waiting_for_mounted_audio')
      if stop.wait(10):
       return
    while True:
     result=pipeline.start()
     if result['state']!='waiting_for_stable_files':
      break
     record(state='running',resultState=result['state'])
     if stop.wait(10):
      return
    record(state='completed' if result['complete'] else 'waiting',resultState=result['state'],
           updatedDates=result.get('updatedDates',[]),archiveIndex=result.get('archiveIndex'))
   except Exception as error:
    record(state='failed',error=str(error))
   finally:
    run_lock.release()

  try:
   threading.Thread(target=run,daemon=True).start()
  except RuntimeError:
   run_lock.release()
   raise
  return 'started'

 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def allowed(self):
   host=self.headers.get('Host','');port=self.server.server_port
   expected={f'127.0.0.1:{port}',f'localhost:{port}'}
   if host not in expected:return False
   origin=self.headers.get('Origin')
   if origin and origin not in {'http://'+x for x in expected}:return False
   path=urlsplit(self.path).path
   if path==prefix or path.startswith(prefix+'/'):
    nonlocal last_access
    last_access=time.monotonic()
   return True
  def reply(self,code,data,kind='application/json; charset=utf-8'):
   body=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
   self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
   self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
   self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; media-src 'self'; frame-src 'self'; base-uri 'none'; frame-ancestors 'self'")
   self.end_headers();self.wfile.write(body)
  def do_GET(self):
   if not self.allowed():self.send_error(404);return
   url=urlsplit(self.path);path=url.path
   try:
    if path==prefix:
     self.send_response(302);self.send_header('Location',prefix+'/');self.end_headers();return
    if path==prefix+'/':self.reply(200,(UI_ROOT/'product.html').read_bytes(),'text/html; charset=utf-8');return
    if path==prefix+'/debug':
     self.send_response(302);self.send_header('Location',prefix+'/debug/');self.end_headers();return
    if path==prefix+'/debug/':self.reply(200,(UI_ROOT/'index.html').read_bytes(),'text/html; charset=utf-8');return
    if path==prefix+'/api/products':
     from soundlog_memory.product_view import results
     self.reply(200,results(pipeline));return
    if path.startswith(prefix+'/assets/'):
     name=path[len(prefix+'/assets/'):]
     if name not in {'app.css','app.js','personal.js','product.css','product.js'}:raise ValueError('界面资源不存在')
     self.reply(200,(UI_ROOT/name).read_bytes(),'text/css; charset=utf-8' if name.endswith('.css') else 'text/javascript; charset=utf-8');return
    if path.startswith(prefix+'/audio/'):
     self.send_audio(path[len(prefix+'/audio/'):]);return
    if path==prefix+'/api/audio':
     from soundlog_memory.audio_access import open_verified,interval
     identifier=parse_qs(url.query).get('id',[''])[0]
     handle,row,size=open_verified(root,identifier)
     handle.close();self.reply(200,{**interval(row),'id':identifier,'bytes':size,'url':prefix+'/audio/'+identifier});return
    if path==prefix+'/api/voice':
     from soundlog_memory.voice_calibration import state
     self.reply(200,state(root));return
    if path==prefix+'/api/me':
     from soundlog_memory.voice_calibration import my_view
     self.reply(200,my_view(root));return
    if path==prefix+'/api/personal':
     from soundlog_memory.personal_items import view
     self.reply(200,view(root));return
    if path==prefix+'/api/health':
     import hashlib
     self.reply(200,{'application':'soundlog-workbench','version':2,'rootKey':hashlib.sha256(str(root).encode()).hexdigest()[:24]});return
    if path==prefix+'/api/history':
     from soundlog_memory.processing_history import history
     self.reply(200,history(pipeline));return
    if path==prefix+'/api/audio-sources':
     from soundlog_memory.audio_sources import settings
     self.reply(200,settings(root));return
    if path==prefix+'/api/agent-settings':
     self.reply(200,agent_runner.settings_view(pipeline));return
    if path==prefix+'/api/audio-imports':
     p=pipeline.home/'audio-import-receipt.json'
     self.reply(200,json.loads(p.read_text()) if p.exists() else {'copied':0,'duplicates':0,'skipped':0,'notes':[]});return
    if path==prefix+'/api/run-status':
     manual=pipeline.home/'manual-run.json'
     status=json.loads(manual.read_text()) if manual.exists() else {}
     phase=pipeline.audio_state()['state']
     running=run_lock.locked()
     result_state=status.get('resultState')
     if running:
      state='running'
      if result_state=='waiting_for_mounted_audio':
       message='正在等待外部录音写入完成…'
      elif result_state=='waiting_for_stable_files' and phase!='archiving_audio':
       message='正在等待录音文件稳定…'
      elif phase=='archiving_audio':
       message='正在校验按天归档…'
      else:
       message='正在导入或处理录音…'
     elif status.get('state')=='failed':
      state='failed';message='录音处理或归档未完成，可重试。'
     elif status.get('state')=='completed' and phase=='idle' and not pipeline.inventory():
      state='completed';message='本机录音处理与按天归档已完成。'
     elif status.get('state')=='waiting':
      state='waiting';message='仍有待处理录音，可再次启动处理。'
     else:
      state='idle';message=''
     self.reply(200,{'state':state,'message':message,'agentPrompt':None,
                     'updatedDates':status.get('updatedDates',[]),
                     'trigger':status.get('trigger'),'resultState':status.get('resultState'),
                     'runId':status.get('runId'),
                     'mountWake':not running and bool(pending_wakes()[0])});return
    if path==prefix+'/api/workbench':self.reply(200,workbench_view.overview(pipeline));return
    if path==prefix+'/api/day':self.reply(200,workbench_view.day_view(pipeline,parse_qs(url.query).get('date',[''])[0]));return
    if path==prefix+'/api/tasks':
     p=pipeline.delivery/'task-graph.json';self.reply(200,json.loads(p.read_text()) if p.exists() else {'tasks':[],'links':[]});return
    if path==prefix+'/api/knowledge':
     result=workbench_view.derived(pipeline.delivery)
     ids={fid for item in result.get('intents',[])+result.get('topics',[]) for fid in item.get('factIds',[])}
     result['referencedFacts']=[f for f in library(pipeline.delivery) if f['id'] in ids] if ids else []
     self.reply(200,result);return
    if path==prefix+'/api/connections':self.reply(200,workbench_view.connections(pipeline));return
    if path==prefix+'/api/reviews':self.reply(200,workbench_view.reviews(pipeline.delivery));return
    if path==prefix+'/api/search':
     query=parse_qs(url.query).get('q',[''])[0].strip()
     if not query or len(query)>200:raise ValueError('请输入1至200字的检索词')
     from soundlog_mcp import call
     self.reply(200,call(root,'soundlog_search',{'query':query}));return
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
      rows.append({'createdAt':(folder/'request.json').stat().st_mtime,'sources':sources,'id':folder.name,'question':request['question'],'state':'answered' if answer else status['state'],'error':status.get('error'),'answer':answer})
     self.reply(200,sorted(rows,key=lambda r:r['createdAt'],reverse=True));return
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
  def do_HEAD(self):
   if not self.allowed():self.send_error(404);return
   path=urlsplit(self.path).path
   if not path.startswith(prefix+'/audio/'):self.send_error(404);return
   try:self.send_audio(path[len(prefix+'/audio/'):],head=True)
   except (OSError,ValueError,KeyError) as error:self.reply(400,{'error':str(error)})
  def send_audio(self,identifier,head=False):
   from soundlog_memory.audio_access import open_verified,byte_range
   handle,row,size=open_verified(root,identifier)
   with handle:
    try:start,end,status=byte_range(self.headers.get('Range'),size)
    except ValueError:
     self.send_response(416);self.send_header('Content-Range','bytes */'+str(size));self.send_header('Content-Length','0');self.end_headers();return
    self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(row['sourceFile'])[0] or 'application/octet-stream')
    self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
    self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Content-Type-Options','nosniff')
    if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    self.end_headers()
    if head:return
    handle.seek(start);remaining=end-start+1
    try:
     while remaining:
      chunk=handle.read(min(65536,remaining))
      if not chunk:break
      self.wfile.write(chunk);remaining-=len(chunk)
    except (BrokenPipeError,ConnectionResetError):pass
  def do_POST(self):
   if not self.allowed():self.send_error(404);return
   if urlsplit(self.path).path==prefix+'/api/agent-settings':
    try:
     length=int(self.headers.get('Content-Length','0'))
     if not 0<length<=2048:raise ValueError('设置长度无效')
     self.reply(200,agent_runner.save_settings(pipeline,json.loads(self.rfile.read(length))))
    except (OSError,ValueError,KeyError,TypeError) as error:self.reply(400,{'error':str(error)})
    return
   if urlsplit(self.path).path==prefix+'/api/audio-sources':
    try:
     length=int(self.headers.get('Content-Length','0'))
     if not 0<length<=65536:raise ValueError('设置长度无效')
     from soundlog_memory.audio_sources import save_settings
     with pipeline.lock():result=save_settings(root,json.loads(self.rfile.read(length)))
     self.reply(200,result)
    except (OSError,ValueError,KeyError,TypeError) as error:self.reply(400,{'error':str(error)})
    return
   if urlsplit(self.path).path==prefix+'/api/voice/label':
    try:
     length=int(self.headers.get('Content-Length','0'))
     if not 0<length<=2048:raise ValueError('请求长度无效')
     from soundlog_memory.voice_calibration import label
     request=json.loads(self.rfile.read(length))
     with pipeline.lock():result=label(root,request)
     self.reply(200,result)
    except (OSError,ValueError,KeyError,TypeError) as error:self.reply(400,{'error':str(error)})
    return
   if urlsplit(self.path).path==prefix+'/api/run':
    wake=parse_qs(urlsplit(self.path).query).get('trigger')==['mount']
    self.reply(202,{'state':start_run(wake=wake)});return
   if urlsplit(self.path).path!=prefix+'/api/questions':self.send_error(404);return
   try:
    length=int(self.headers.get('Content-Length','0'))
    if not 0<length<=16384:raise ValueError('请求长度无效')
    body=json.loads(self.rfile.read(length));question=body.get('question','');queries=body.get('queries',[])
    if not isinstance(question,str) or not question.strip() or len(question)>2000 or not isinstance(queries,list) or len(queries)>12 or any(not isinstance(q,str) or len(q)>100 for q in queries):raise ValueError('问题或检索词无效')
    # Agent expands these terms before answering; the phrase alone is not treated as exhaustive retrieval.
    if not queries:queries=[question.strip()[:100]]
    snapshot=pipeline.scenes if (pipeline.scenes/'latest.json').exists() else None
    with pipeline.lock():result=ask(pipeline.delivery,pipeline.home,question,queries,snapshot,project_root=root)
    self.reply(201,result)
   except (OSError,ValueError,KeyError,TypeError) as e:self.reply(400,{'error':str(e)})
 def stop_after_idle(server):
  while not stop.wait(5):
   if time.monotonic()-last_access<90 or not run_lock.acquire(blocking=False):
    continue
   try:
    if time.monotonic()-last_access>=90:
     server.shutdown()
     return
   finally:
    run_lock.release()
 Handler.stop_after_idle=staticmethod(stop_after_idle)
 Handler.stop=staticmethod(stop.set)
 return Handler


def main():
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent);p.add_argument('--port',type=int,default=0);p.add_argument('--reuse-session',action='store_true');a=p.parse_args()
 token=secrets.token_urlsafe(24)
 previous=a.root/'记忆库/运行/自动管线/hub.json'
 if a.reuse_session and previous.exists():
  parsed=urlsplit(json.loads(previous.read_text())['url']);candidate=parsed.path.strip('/')
  if parsed.hostname!='127.0.0.1' or not re.fullmatch(r'[A-Za-z0-9_-]{24,}',candidate):raise ValueError('旧会话地址无效')
  token=candidate;a.port=a.port or parsed.port
 request_handler=handler(a.root,token)
 server=ThreadingHTTPServer(('127.0.0.1',a.port),request_handler)
 runtime=a.root/'记忆库/运行/自动管线';runtime.mkdir(parents=True,exist_ok=True)
 url=f'http://127.0.0.1:{server.server_port}/{token}/'
 (runtime/'hub.json').write_text(json.dumps({'url':url,'pid':__import__('os').getpid()}));print(url,flush=True)
 threading.Thread(target=request_handler.stop_after_idle,args=(server,),daemon=True).start()
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:
  request_handler.stop()
  server.server_close()
if __name__=='__main__':main()
