import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import test_pipeline
from soundlog_memory.period_review import period_material,publish_period_review

class PeriodReviewTests(unittest.TestCase):
 def setUp(self):
  self.fixture=test_pipeline.PipelineTests();self.fixture.setUp();self.p=self.fixture.pipeline
  self.p.tick();state=self.p.ingest(self.fixture.envelope());self.rid=state['resultId']
  self.p.publish(self.rid,self.fixture.screening(self.rid))
  self.material=period_material(self.p.delivery,'2026-11-07','2026-11-09')
 def tearDown(self):self.fixture.tearDown()
 def spec(self):
  return {'start':'2026-11-07','end':'2026-11-09','reviewer':'synthetic reviewer',
   'sections':[{'title':'历史安排','text':'当时谈及充电安排，当前状态未知。','category':'actions','factIds':[self.material['facts'][0]['id']]}]}
 def test_date_gaps_and_narrative_versioning(self):
  self.assertEqual(self.material['missingDays'],['2026-11-09'])
  result=publish_period_review(self.p.delivery,'2026-11-07','2026-11-09',self.spec())
  self.assertEqual(result,publish_period_review(self.p.delivery,'2026-11-07','2026-11-09',self.spec()))
  folder=self.p.delivery/'reviews'/result['id'];text=(folder/'README.md').read_text()
  self.assertIn('2026-11-09',text);self.assertIn('sources.md#',text)
  refresh=publish_period_review(self.p.delivery,'2026-11-07','2026-11-09')
  self.assertEqual(refresh['selected'],result['id'])
  self.assertEqual(refresh['selection'],'kept_reviewed_version')
 def test_unreviewed_index_is_explicit_and_empty_range_rejected(self):
  result=publish_period_review(self.p.delivery,'2026-11-07','2026-11-09')
  self.assertEqual(result['mode'],'evidence_index')
  with self.assertRaises(ValueError):publish_period_review(self.p.delivery,'2026-12-01','2026-12-02')
  with self.assertRaises(ValueError):period_material(self.p.delivery,'2026-11-09','2026-11-07')
 def test_out_of_range_and_child_adult_misclassification_rejected(self):
  s=self.spec();s['sections'][0]['factIds']=['fact-missing']
  with self.assertRaises(ValueError):publish_period_review(self.p.delivery,s['start'],s['end'],s)
  s=self.spec();s['sections'][0]['category']='child_learning'
  with self.assertRaises(ValueError):publish_period_review(self.p.delivery,s['start'],s['end'],s)
  s=self.spec();s['start']='2026-11-08'
  with self.assertRaises(ValueError):publish_period_review(self.p.delivery,'2026-11-07',s['end'],s)
 def test_changed_source_and_changed_existing_output_rejected(self):
  r=publish_period_review(self.p.delivery,'2026-11-07','2026-11-09',self.spec())
  (self.p.delivery/'reviews'/r['id']/'README.md').write_text('tampered')
  with self.assertRaises(ValueError):publish_period_review(self.p.delivery,'2026-11-07','2026-11-09',self.spec())
  bundle=self.material['days'][0]['bundle']
  (self.p.delivery/bundle/'2026-11-07/daily-review.json').write_text('{}')
  with self.assertRaises(ValueError):period_material(self.p.delivery,'2026-11-07','2026-11-09')
