import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import test_pipeline
import test_hub
from soundlog_memory import workbench_view as view
from soundlog_memory.pipeline import Pipeline
from soundlog_memory.period_review import publish_period_review
from launch_soundlog import healthy,root_key

class WorkbenchViewTests(unittest.TestCase):
 def setUp(self):
  self.f=test_pipeline.PipelineTests();self.f.setUp();self.p=self.f.pipeline
  self.p.tick();r=self.p.ingest(self.f.envelope());self.p.publish(r['resultId'],self.f.screening(r['resultId']))
 def tearDown(self):self.f.tearDown()
 def test_day_and_overview_use_real_selected_content(self):
  result=view.overview(self.p);self.assertEqual(result['totals']['days'],2);self.assertEqual(result['totals']['facts'],2)
  self.assertEqual(result['pipeline']['state'],'awaiting_enrichment')
  day=view.day_view(self.p,'2026-11-07');self.assertEqual(len(day['facts']),1)
  self.assertEqual(day['facts'][0]['summary'],self.f.fact()['summary'])
  with self.assertRaises(ValueError):view.day_view(self.p,'../../state')
 def test_changed_artifact_never_renders_as_trusted_content(self):
  day=view.day_view(self.p,'2026-11-07');path=self.p.delivery/day['bundle']/'2026-11-07/daily-review.json'
  path.write_text('{}')
  with self.assertRaises(ValueError):view.overview(self.p)
 def test_review_update_badge_detects_source_coverage_change(self):
  publish_period_review(self.p.delivery,'2026-11-07','2026-11-09')
  self.assertFalse(view.reviews(self.p.delivery)[0]['needsRefresh'])
  path=self.p.delivery/'catalog.json';data=json.loads(path.read_text());data['days'].pop('2026-11-08');path.write_text(json.dumps(data))
  self.assertTrue(view.reviews(self.p.delivery)[0]['needsRefresh'])
 def test_empty_installation_is_a_real_empty_view(self):
  with tempfile.TemporaryDirectory() as temp:
   result=view.overview(Pipeline(temp));self.assertEqual(result['totals']['facts'],0);self.assertEqual(result['days'],[])
 def test_launcher_rejects_unknown_destination_and_wrong_workspace(self):
  self.assertFalse(healthy({'url':'https://example.com/'},self.f.root))
  workspace=self.f.root
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self):return json.dumps({'application':'soundlog-workbench','rootKey':root_key(workspace)}).encode()
  with patch('launch_soundlog.local_urlopen',return_value=Response()):
   self.assertTrue(healthy({'url':'http://127.0.0.1:1234/'+'a'*24+'/'},self.f.root))
   self.assertFalse(healthy({'url':'http://127.0.0.1:1234/'+'a'*24+'/'},Path('/different-root')))

class WorkbenchHTTPTests(unittest.TestCase):
 setUp=test_hub.HubTests.setUp
 tearDown=test_hub.HubTests.tearDown
 req=test_hub.HubTests.req
 def test_new_api_and_assets_cover_empty_derivatives_and_scoped_day(self):
  code,body=self.req('/token/api/health');self.assertEqual(code,200);self.assertEqual(json.loads(body)['application'],'soundlog-workbench')
  for endpoint in ['workbench','day?date=2026-11-07','knowledge','tasks','reviews','connections']:
   self.assertEqual(self.req('/token/api/'+endpoint)[0],200,endpoint)
  self.assertEqual(self.req('/token/assets/app.js')[0],200)
  import http.client
  client=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
  client.request('GET','/token/assets/app.css');response=client.getresponse()
  self.assertEqual(response.status,200);self.assertIn("style-src 'self'",response.getheader('Content-Security-Policy'))
  self.assertIn('text/css',response.getheader('Content-Type'));response.read();client.close()
  self.assertEqual(self.req('/token/assets/../../README.md')[0],400)
  self.assertEqual(self.req('/token/api/day?date=2026-12-01')[0],400)
  self.assertEqual(self.req('/token/api/run','POST',{},'https://evil.example')[0],404)

 def test_product_root_and_debug_are_separate_and_products_are_available(self):
  code,body=self.req('/token/');self.assertEqual(code,200);self.assertIn('assets/product.js',body.decode())
  self.assertNotIn('open-comparison',body.decode())
  code,body=self.req('/token/debug/');self.assertEqual(code,200);self.assertIn('../assets/app.js',body.decode())
  self.assertIn('调试后台',body.decode())
  code,body=self.req('/token/api/products');self.assertEqual(code,200);self.assertIn('activities',json.loads(body))
  for asset in ['product.css','product.js']:
   self.assertEqual(self.req('/token/assets/'+asset)[0],200)
 def test_run_status_does_not_report_semantic_handoff_as_complete(self):
  code,body=self.req('/token/api/run-status');self.assertEqual(code,200)
  self.assertEqual(json.loads(body)['state'],'needs_agent')
  self.assertNotIn('requestDirectory',body.decode())
 def test_run_status_shows_failure_without_exposing_logs(self):
  from soundlog_memory.store import write_json
  write_json(self.p.home/'manual-run.json',{'state':'failed','error':'private/path/audio.log'})
  code,body=self.req('/token/api/run-status');self.assertEqual(code,200)
  self.assertEqual(json.loads(body)['state'],'failed');self.assertNotIn('private/path',body.decode())
 def test_audio_source_settings_round_trip_and_origin_guard(self):
  setting={'voiceMemos':False,'directories':['/Volumes/Disconnected/RECORD']}
  self.assertEqual(self.req('/token/api/audio-sources','POST',setting)[0],200)
  self.assertEqual(json.loads(self.req('/token/api/audio-sources')[1]),setting)
  self.assertEqual(self.req('/token/api/audio-sources','POST',setting,'https://evil.example')[0],404)
  self.assertEqual(self.req('/token/api/audio-imports')[0],200)
 def test_collectors_finish_before_pipeline_starts(self):
  import time
  from unittest.mock import patch
  from soundlog_memory.pipeline import Pipeline
  calls=[]
  def collect(root):calls.append('collect');return {'copied':0}
  def start(pipeline):calls.append('pipeline');return {'complete':True,'state':'idle','pendingQuestions':[]}
  with patch('soundlog_memory.audio_sources.collect',collect),patch.object(Pipeline,'start',start):
   self.assertEqual(self.req('/token/api/run','POST')[0],202)
   for _ in range(100):
    status=json.loads(self.req('/token/api/run-status')[1])
    if status['state']!='running':break
    time.sleep(.01)
  self.assertEqual(calls,['collect','pipeline'])

 def test_agent_prompt_describes_live_handoff_without_exposing_transcript(self):
  code,body=self.req('/token/api/run-status')
  self.assertEqual(code,200)
  prompt=json.loads(body)['agentPrompt']
  self.assertIn(str(self.p.root),prompt)
  self.assertIn('scripts/pipeline-agent.md',prompt)
  self.assertIn('完成派生成果和发布',prompt)
  self.assertNotIn(self.f.fact()['summary'],prompt)

 def test_completed_question_does_not_leave_stale_handoff(self):
  from soundlog_memory.store import write_json
  self.p.save({'state':'idle'})
  write_json(self.p.home/'manual-run.json',{'state':'awaiting_agent','pendingQuestions':1})
  folder=self.p.home/'questions/question-example'
  folder.mkdir(parents=True)
  write_json(folder/'request.json',{'question':'private question'})
  _,body=self.req('/token/api/run-status')
  self.assertIn('待答问题 1 条',json.loads(body)['agentPrompt'])
  write_json(folder/'answer.json',{})
  _,body=self.req('/token/api/run-status')
  self.assertIsNone(json.loads(body)['agentPrompt'])

 def test_button_invokes_codex_and_rejects_exit_without_pipeline_completion(self):
  import threading
  from soundlog_memory import agent_runner
  entered=threading.Event()
  release=threading.Event()
  calls=[]

  def run(pipeline,prompt):
   calls.append(prompt)
   entered.set()
   release.wait(3)

  with patch('soundlog_memory.audio_sources.collect'), patch.object(agent_runner,'run_codex',run):
   try:
    self.assertEqual(self.req('/token/api/run','POST')[0],202)
    self.assertTrue(entered.wait(3))
    self.assertIn('$soundlog',calls[0])
    status=json.loads(self.req('/token/api/run-status')[1])
    self.assertEqual(status['state'],'running')
    self.assertIsNone(status['agentPrompt'])
    self.assertEqual(json.loads(self.req('/token/api/run','POST')[1])['state'],'already_running')
   finally:
    release.set()
   import time
   for _ in range(100):
    status=json.loads(self.req('/token/api/run-status')[1])
    if status['state']=='agent_failed':break
    time.sleep(.01)
   self.assertEqual(status['state'],'agent_failed')
   self.assertIn('$soundlog',status['agentPrompt'])
   self.assertEqual(len(calls),1)
