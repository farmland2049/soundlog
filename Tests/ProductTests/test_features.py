import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import test_pipeline
from soundlog_memory.task_graph import build_task_graph,publish_task_graph
from soundlog_memory.derived_products import publish_derived
from soundlog_memory.library_tools import library

class FeatureTests(unittest.TestCase):
 def setUp(self):
  self.fixture=test_pipeline.PipelineTests();self.fixture.setUp();self.p=self.fixture.pipeline
  self.p.tick();state=self.p.ingest(self.fixture.envelope());self.p.publish(state['resultId'],self.fixture.screening(state['resultId']))
  self.fs=library(self.p.delivery)
 def tearDown(self):self.fixture.tearDown()
 def link(self,relation='same_task'):
  return {'id':'link-charge','from':self.fs[0]['id'],'to':self.fs[1]['id'],'relation':relation,'reason':'synthetic same device testimony','reviewer':'fixture'}
 def test_reviewed_merge_possible_conflict_and_revoke(self):
  self.assertEqual(len(build_task_graph(self.p.delivery,[self.link('possible_same_task')])['tasks']),2)
  merged=build_task_graph(self.p.delivery,[self.link()]);self.assertEqual(len(merged['tasks']),1)
  self.assertEqual(merged['tasks'][0]['currentState'],'unknown')
  conflict=build_task_graph(self.p.delivery,[self.link('contradicts')])
  self.assertEqual(len(conflict['tasks']),2)
  self.assertTrue(all(t['conflicts'] and t['stateLabel']=='存在冲突' for t in conflict['tasks']))
  self.assertTrue(all(t['currentState']=='unknown' for t in conflict['tasks']))
  revoke={'id':'undo','relation':'revoke','target':'link-charge','reviewer':'fixture','reason':'wrong linkage'}
  self.assertEqual(len(build_task_graph(self.p.delivery,[self.link(),revoke])['tasks']),2)
  for _ in range(2):publish_task_graph(self.p.delivery,self.p.home,[self.link()])
  self.assertEqual(len((self.p.home/'task-history.jsonl').read_text().splitlines()),1)
 def spec(self):
  f=self.fs[0];e=f['evidence'][0]
  return {'schemaVersion':1,'reviewer':'test','topics':[{'id':'charge','title':'充电条件','audience':'adult','factIds':[f['id']],
   'concepts':[{'text':f['summary'],'factIds':[f['id']]}],'sprouts':['如何确认后续是否完成？']}],
   'cleanDocuments':[{'id':'clean-charge','paragraphs':[{'evidenceId':e['id'],'sourceText':e['text'],'cleanText':e['text'],'reason':'保留条件与不确定性'}]}],
   'marks':[{'evidenceId':e['id'],'classification':'not_instruction','reason':'历史对话，不是当前执行授权'}],
   'intents':[{'id':'draft-charge','factIds':[f['id']],'request':'仅作为历史事项','state':'draft'}],
   'writingPlans':[{'id':'outline','title':'充电安排说明','format':'report','factIds':[f['id']], 'sections':[{'title':'当时安排','factIds':[f['id']]}]}]}
 def test_derivatives_have_links_and_incremental_reuse(self):
  spec=self.spec();r=publish_derived(self.p.delivery,spec);p=self.p.delivery/'derived'/r['id']
  self.assertTrue((p/'mindmap.mmd').exists());self.assertIn('Agent新增联想',(p/'knowledge/charge.md').read_text())
  self.assertEqual(publish_derived(self.p.delivery,spec),r)
  self.assertIn('原文',(p/'writing/outline.md').read_text())
 def test_invalid_child_classification_forged_raw_and_lost_condition_block(self):
  s=self.spec();s['topics'][0]['audience']='child'
  with self.assertRaises(ValueError):publish_derived(self.p.delivery,s)
  s=self.spec();s['cleanDocuments'][0]['paragraphs'][0]['sourceText']='伪造'
  with self.assertRaises(ValueError):publish_derived(self.p.delivery,s)
  s=self.spec();s['cleanDocuments'][0]['paragraphs'][0]['cleanText']='已经充电了'
  with self.assertRaises(ValueError):publish_derived(self.p.delivery,s)
 def test_quoted_mark_cannot_execute(self):
  s=self.spec();s['marks'][0]['classification']='quoted';s['intents'][0]['state']='execute'
  with self.assertRaises(ValueError):publish_derived(self.p.delivery,s)
 def test_relative_dates_need_explicit_anchor(self):
  from soundlog_memory.task_graph import resolve_due
  self.assertIsNone(resolve_due('明天',None)['date'])
  self.assertEqual(resolve_due('明天',{'date':'2026-12-31','reason':'explicit event date','reviewer':'test'})['date'],'2027-01-01')
  with self.assertRaises(ValueError):resolve_due('明天',{'date':'2026-12-31'})
