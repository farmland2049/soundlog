import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import test_pipeline
from soundlog_memory.product_view import publish,results

class ProductViewTests(unittest.TestCase):
 def setUp(self):
  self.fixture=test_pipeline.PipelineTests();self.fixture.setUp();self.p=self.fixture.pipeline
  self.p.tick();r=self.p.ingest(self.fixture.envelope());self.p.publish(r['resultId'],self.fixture.screening(r['resultId']))
  from soundlog_memory.library_tools import library
  self.f=library(self.p.delivery)[0]
 def tearDown(self):self.fixture.tearDown()
 def spec(self):
  f=self.f
  return {'schemaVersion':1,'reviewer':'test reviewer','activities':[{'id':'meeting-a','kind':'meeting','date':f['date'],'title':'讨论会','summary':'会议内容','factIds':[f['id']],'minutes':[{'text':'讨论重点','factIds':[f['id']]}],'actions':[],'decisions':[],'openItems':[]}]}
 def test_result_api_keeps_evidence_and_runtime_out(self):
  publish(self.p.root,self.spec());d=results(self.p);a=next(x for x in d['activities'] if x['kind']=='meeting')
  self.assertEqual(a['minutes'],[{'text':'讨论重点'}]);self.assertEqual(a['title'],'讨论会')
  wire=json.dumps(d)
  for secret in ['sourceSHA256','evidence','startOffsetSeconds','sourceFile','factIds','pipeline','bindings']:
   self.assertNotIn(secret,wire)
 def test_out_of_scope_day_and_unrelated_paragraph_refs_rejected(self):
  s=self.spec();s['activities'][0]['date']='2026-12-31'
  with self.assertRaises(ValueError):publish(self.p.root,s)
  s=self.spec();s['activities'][0]['minutes'][0]['factIds']=['missing-fact']
  with self.assertRaises(ValueError):publish(self.p.root,s)
 def test_changed_product_artifact_is_rejected(self):
  r=publish(self.p.root,self.spec());p=self.p.delivery/'product-views'/r['id']/'view.json';p.write_text('{}')
  with self.assertRaises(ValueError):results(self.p)
 def test_updated_source_cannot_leave_old_meeting_visible(self):
  publish(self.p.root,self.spec());p=self.p.delivery/'catalog.json';c=json.loads(p.read_text());c['days'].pop(self.f['date']);p.write_text(json.dumps(c))
  with self.assertRaises(ValueError):results(self.p)
