import hashlib,json,sys,tempfile,unittest,subprocess
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory import memory_exchange as m,action_outbox as a,identity_scope as i

class IntegrationTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.target=self.root/'memory';self.target.mkdir()
 def tearDown(self):self.tmp.cleanup()
 def plan(self,status='candidate',managed=None):return m.prepare(self.target,'project-local',[{'id':'fact-test','body':'原文及候选内容','status':status}],managed)
 def approval(self,p):return {'planSHA256':m.checksum(p),'targetRoot':p['targetRoot'],'operationIds':[r['id'] for r in p['operations']]}
 def preflight(self):return {'checkedAt':datetime.now(timezone.utc).isoformat(),'projectId':'project-local','source':'local','localPath':str(self.target)}
 def test_memory_create_readback_update_revocation_and_conflict(self):
  p=self.plan();receipt=m.apply(p,self.approval(p),self.preflight(),self.root/'receipt.json');o=p['operations'][0]
  self.assertEqual(receipt['state'],'needs_mcp_readback');self.assertIn('embed: false',(self.target/o['path']).read_text())
  metadata=[{'file_path':o['path'],'checksum':o['sha256'],'permalink':o['permalink']}]
  self.assertEqual(m.confirm(receipt,metadata)['state'],'verified')
  with self.assertRaises(ValueError):m.confirm(receipt,[])
  managed={o['path']:o['sha256']};new=self.plan('revoked',managed)
  m.apply(new,self.approval(new),self.preflight(),self.root/'revoke.json')
  self.assertIn('status: revoked',(self.target/o['path']).read_text())
  self.assertEqual(len(list((self.root/'prior-versions').iterdir())),1)
  (self.target/o['path']).write_text('外部修改')
  with self.assertRaises(ValueError):self.plan('candidate',managed)
 def test_no_authorization_and_symlink_never_write(self):
  p=self.plan()
  with self.assertRaises(ValueError):m.apply(p,{},self.preflight(),self.root/'receipt.json')
  with self.assertRaises(ValueError):self.plan('confirmed')
  (self.target/'soundlog').symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(ValueError):self.plan()
 def action(self):return {'kind':'calendar_event','title':'合成测试，未写入应用','start':'2026-12-01T10:00:00+08:00','end':'2026-12-01T10:30:00+08:00','calendar':'仅测试日历','description':'Synthetic adapter test'}
 def test_action_hash_scope_failures_retry_and_revoke(self):
  d=a.draft(self.root,self.action());approval={'actionSHA256':d['sha256'],'decision':'approve','userAuthorization':'synthetic test only'}
  with self.assertRaises(ValueError):a.execute(self.root,d['id'],{})
  calls=[]
  def fail(script):return SimpleNamespace(returncode=1,stdout='',stderr='refused')
  with self.assertRaises(ValueError):a.execute(self.root,d['id'],approval,runner=fail)
  def run(script):calls.append(script);return SimpleNamespace(returncode=0,stdout=json.dumps({'status':'created','uid':'test-event-id','title':self.action()['title'],'calendar':self.action()['calendar'],'start':self.action()['start'],'end':self.action()['end']}),stderr='')
  r=a.execute(self.root,d['id'],approval,runner=run);self.assertEqual(r['mode'],'test_adapter')
  self.assertEqual(a.execute(self.root,d['id'],approval,runner=run),r);self.assertEqual(len(calls),1)
  revoked=a.revoke(self.root,d['id'],{**approval,'decision':'revoke'},runner=lambda s:SimpleNamespace(returncode=0,stdout=json.dumps({'status':'revoked','actionId':d['id']}),stderr=''))
  self.assertEqual(revoked['state'],'revoked')
 def test_identity_scope_does_not_propagate_and_can_unbind(self):
  op={'kind':'confirm','factId':'fact-one','alias':'本人'};sha=hashlib.sha256(json.dumps(op,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  auth={'operationSHA256':sha,'userStatement':'用户确认仅该条'};r=i.update(self.root,op,auth);self.assertEqual(set(r['bindings']),{'fact-one'})
  op={**op,'kind':'revoke'};auth['operationSHA256']=hashlib.sha256(json.dumps(op,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  self.assertEqual(i.update(self.root,op,auth)['bindings'],{})
 def test_mcp_stdio_list_works_without_any_runtime_data(self):
  script=Path(__file__).resolve().parents[2]/'scripts/soundlog_mcp.py'
  messages=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}}},{'jsonrpc':'2.0','method':'notifications/initialized'},{'jsonrpc':'2.0','id':2,'method':'tools/list'}]
  r=subprocess.run([sys.executable,str(script),'--root',str(self.root)],input='\n'.join(json.dumps(x) for x in messages)+'\n',capture_output=True,text=True,check=True)
  responses=[json.loads(x) for x in r.stdout.splitlines()];self.assertEqual(len(responses),2);self.assertEqual(len(responses[1]['result']['tools']),6)
