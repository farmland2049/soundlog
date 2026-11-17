import unittest
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import test_products as fixtures
from soundlog_memory.pipeline import Pipeline
from soundlog_memory.products import import_result


class PipelineTests(unittest.TestCase):
    fact = fixtures.ProductTests.fact
    block = fixtures.ProductTests.block
    envelope = fixtures.ProductTests.envelope
    tearDown = fixtures.ProductTests.tearDown
    # Reuse the synthetic source fixture, not recordings or local models.
    def setUp(self):
        fixtures.ProductTests.setUp(self)
        self.pipeline = Pipeline(self.root)
        self.pipeline.products = self.products
        self.pipeline.scenes = self.scenes

    def screening(self, rid):
        facts = json.loads((self.products/'results'/rid/'facts.json').read_text())['facts']
        return {'resultId': rid, 'reviewer': 'synthetic-test', 'rows': [
            {'id': f['id'], 'decision': 'retain', 'reason': 'explicit quoted request',
             'categories': ['actions', 'journal']} for f in facts]}

    def test_handoff_resume_publish_and_idle(self):
        state = self.pipeline.tick()
        self.assertEqual(state['state'], 'awaiting_agent')
        self.assertEqual(self.pipeline.tick(), state)
        state = self.pipeline.ingest(self.envelope())
        self.assertEqual(state['state'], 'awaiting_screening')
        result = self.pipeline.publish(state['resultId'], self.screening(state['resultId']))
        self.assertEqual(result['retained'], 2)
        self.assertEqual(self.pipeline.tick()['state'], 'awaiting_enrichment')
        self.pipeline.finish_products({'schemaVersion':1,'reviewer':'test','sourceResultId':state['resultId'],'topics':[]},[])
        self.assertEqual(self.pipeline.tick()['state'], 'idle')
        bundle = self.pipeline.delivery / result['bundle']
        self.assertIn('sources.html#', (bundle/'index.html').read_text())
        self.assertTrue((bundle/'2026-11-07'/'sources.html').exists())
        before = (self.pipeline.delivery/'latest.json').read_bytes()
        self.assertEqual(self.pipeline.publish(state['resultId'], self.screening(state['resultId']), adopt=True)['bundle'], result['bundle'])
        self.assertEqual(before, (self.pipeline.delivery/'latest.json').read_bytes())

    def test_start_keeps_existing_semantic_work_and_checks_new_inbox(self):
        before=self.pipeline.tick()
        inbox=self.root/'录音/待处理';inbox.mkdir(parents=True)
        (inbox/'20261115090000.mp3').write_bytes(b'synthetic pending input')
        with patch('soundlog_memory.pipeline.subprocess.run') as run:
            result=self.pipeline.start()
        run.assert_not_called()
        self.assertEqual(result['requestId'],before['requestId'])
        self.assertEqual(result['checkedAudioFiles'],['20261115090000.mp3'])
        self.assertFalse(result['complete'])

    def test_start_never_marks_enrichment_or_pending_questions_complete(self):
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope())
        self.pipeline.publish(state['resultId'],self.screening(state['resultId']))
        self.assertFalse(self.pipeline.start()['complete'])
        self.pipeline.finish_products({'schemaVersion':1,'reviewer':'test','sourceResultId':state['resultId'],'topics':[]},[])
        folder=self.pipeline.home/'questions/question-synthetic';folder.mkdir(parents=True)
        (folder/'request.json').write_text(json.dumps({'question':'synthetic question'}))
        result=self.pipeline.start()
        self.assertEqual(result['state'],'idle');self.assertFalse(result['complete'])
        self.assertEqual(result['pendingQuestions'][0]['question'],'synthetic question')
        (folder/'answer.json').write_text(json.dumps({'status':'unknown','unknown':'synthetic no evidence'}))
        self.assertTrue(self.pipeline.start()['complete'])

    def test_partial_output_and_incomplete_screening_never_publish(self):
        self.pipeline.tick()
        envelope = self.envelope(); envelope['results'].pop()
        with self.assertRaises(ValueError): self.pipeline.ingest(envelope)
        self.assertEqual(self.pipeline.state()['state'], 'awaiting_agent')
        state = self.pipeline.ingest(self.envelope())
        screening = self.screening(state['resultId']); screening['rows'].pop()
        with self.assertRaises(ValueError): self.pipeline.publish(state['resultId'], screening)
        self.assertFalse((self.pipeline.delivery/'latest.json').exists())
        self.assertEqual(self.pipeline.state()['state'], 'awaiting_screening')

    def test_undeclared_category_and_changed_source_rejected(self):
        self.pipeline.tick(); state = self.pipeline.ingest(self.envelope())
        screening = self.screening(state['resultId'])
        screening['rows'][0]['categories'] = ['child_learning']
        with self.assertRaises(ValueError): self.pipeline.publish(state['resultId'], screening)
        source = next((self.scenes).glob('snapshot-*/*_utterances.json'))
        source.write_text('{}')
        with self.assertRaises(ValueError): self.pipeline.publish(state['resultId'], self.screening(state['resultId']))
        self.assertFalse((self.pipeline.delivery/'latest.json').exists())

    def test_copy_in_progress_and_parallel_runner_are_safe(self):
        inbox = self.root/'录音/待处理'; inbox.mkdir(parents=True)
        (inbox/'20261115090000.mp3').write_bytes(b'not real audio')
        with patch('soundlog_memory.pipeline.subprocess.run') as run:
            self.assertEqual(self.pipeline.tick()['state'], 'waiting_for_stable_files')
            run.assert_not_called()
        with self.pipeline.lock():
            with self.assertRaises(ValueError): self.pipeline.tick()

    def test_daily_overview_uses_same_day_evidence(self):
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope());rid=state['resultId']
        screening=self.screening(rid)
        facts=json.loads((self.products/'results'/rid/'facts.json').read_text())['facts']
        screening['dailyReviews']={'2026-11-07':{'overview':'讨论设备充电安排。','highlights':[facts[1]['id']]}}
        with self.assertRaises(ValueError):self.pipeline.publish(rid,screening)
        self.assertFalse((self.pipeline.delivery/'latest.json').exists())
        screening['dailyReviews']['2026-11-07']['highlights']=[facts[0]['id']]
        result=self.pipeline.publish(rid,screening)
        day=self.pipeline.delivery/result['bundle']/'2026-11-07'
        self.assertTrue((day/'README.md').exists())
        timeline=json.loads((day/'timeline.json').read_text())
        self.assertEqual(timeline['rows'][0]['recordedStart'],facts[0]['recordedStart'])
        self.assertIn('不等于当前仍未完成',(day/'actions.md').read_text())
        self.assertIn('讨论设备充电安排',(day/'daily-review.md').read_text())

    def test_grounded_questions_and_task_mentions(self):
        from soundlog_memory.library_tools import task_ledger,ask,answer
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope());rid=state['resultId']
        self.pipeline.publish(rid,self.screening(rid))
        result=task_ledger(self.pipeline.delivery)
        self.assertEqual(result['mentions'],2)
        tasks=json.loads((self.pipeline.delivery/'tasks.json').read_text())['rows']
        self.assertTrue(all(t['currentState']=='unknown' for t in tasks))
        request=ask(self.pipeline.delivery,self.pipeline.home,'谁答应充电？',['充电'])
        data=json.loads((Path(request['directory'])/'request.json').read_text());e=data['facts'][0]['evidence'][0]
        response={'questionId':request['id'],'reviewer':'test','status':'answered','unknown':'说话人身份未知',
                  'claims':[{'text':'录音中提出充电的条件承诺。','evidence':[{'id':e['id'],'quote':e['quote']}]}]}
        self.assertEqual(answer(self.pipeline.home,request['id'],response)['state'],'answered')
        response['claims'][0]['evidence'][0]['quote']='凭空的原话'
        with self.assertRaises(ValueError):answer(self.pipeline.home,request['id'],response)

    def test_scene_rejects_other_day_and_learning_audience(self):
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope());rid=state['resultId']
        screening=self.screening(rid)
        facts=json.loads((self.products/'results'/rid/'facts.json').read_text())['facts']
        scene={'id':'scene-example','type':'work','title':'讨论','summary':'有依据的讨论',
               'factIds':[facts[1]['id']],'sections':[]}
        screening['dailyReviews']={'2026-11-07':{'overview':'当日讨论。','highlights':[], 'scenes':[scene]}}
        with self.assertRaises(ValueError):self.pipeline.publish(rid,screening)
        scene['factIds']=[facts[0]['id']];scene['type']='child_learning'
        with self.assertRaises(ValueError):self.pipeline.publish(rid,screening)
        self.assertFalse((self.pipeline.delivery/'latest.json').exists())

    def test_all_deferred_delivers_empty_content_without_invented_events(self):
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope());rid=state['resultId']
        screening=self.screening(rid)
        for row in screening['rows']:
            row['decision']='defer';row['reason']='对象不明，暂缓生成有意义记录';row.pop('categories')
        result=self.pipeline.publish(rid,screening)
        self.assertEqual(result['retained'],0)
        self.assertEqual(result['deferred'],2)
        folder=self.pipeline.delivery/result['bundle']
        self.assertEqual(json.loads((folder/'search.json').read_text())['facts'],[])
        self.assertEqual(json.loads((folder/'2026-11-07/timeline.json').read_text())['rows'],[])
        self.pipeline.finish_products({'schemaVersion':1,'reviewer':'test','sourceResultId':rid,'topics':[]},[])
        self.assertEqual(self.pipeline.state()['state'],'idle')

    def test_no_transcript_day_has_explicit_empty_coverage(self):
        from soundlog_memory.scenes import build_snapshot
        for path in self.runs.glob('*/*.json'):
            data=json.loads(path.read_text())
            if 'segments' in data:data['segments']=[];data['status']='completed_no_text'
            if path.name=='sound-events.json':
                day=path.parent.name
                data['events']=[{'absoluteStartLocal':day+'T10:00:00.000','absoluteEndLocal':day+'T10:00:02.000','category':'Speech','confidence':0.7,'startOffsetSeconds':0,'endOffsetSeconds':2,'sourceWindowIndices':[0]}]
            path.write_text(json.dumps(data))
        scenes=self.root/'empty-scenes';build_snapshot(self.runs,scenes)
        self.pipeline.scenes=scenes
        state=self.pipeline.tick()
        request=json.loads((Path(state['requestDirectory'])/'request.json').read_text())
        self.assertTrue(all(i['material'].get('noText') for i in request['items']))
        envelope={'schemaVersion':1,'requestId':state['requestId'],'processor':'test; no text read',
                  'results':[{'key':i['key'],'facts':[],'coverage':[]} for i in request['items']]}
        state=self.pipeline.ingest(envelope)
        result=self.pipeline.publish(state['resultId'],{'resultId':state['resultId'],'reviewer':'test','rows':[]})
        self.assertEqual(result['retained'],0)
        self.assertEqual(len(result['days']),2)

    def test_agent_can_expand_a_question_without_losing_original_queue_id(self):
        from soundlog_memory.library_tools import ask,expand_question,answer
        self.pipeline.tick();state=self.pipeline.ingest(self.envelope());self.pipeline.publish(state['resultId'],self.screening(state['resultId']))
        q=ask(self.pipeline.delivery,self.pipeline.home,'东西后来怎么样了？',['完全不命中的词'])
        self.assertEqual(q['matches'],0)
        expanded=expand_question(self.pipeline.delivery,self.pipeline.home,q['id'],['充电'],self.scenes)
        self.assertEqual(expanded['questionId'],q['id'])
        self.assertGreater(expanded['rawMatches'],0)
        request=json.loads((Path(q['directory'])/'retrieval.json').read_text());e=request['facts'][0]['evidence'][0]
        result=answer(self.pipeline.home,q['id'],{'questionId':q['id'],'reviewer':'test','status':'answered','claims':[{'text':'录音中提出充电安排。','evidence':[{'id':e['id'],'quote':e['quote']}]}],'unknown':'后续执行未知'})
        self.assertEqual(result['state'],'answered')
        with self.assertRaises(ValueError):expand_question(self.pipeline.delivery,self.pipeline.home,q['id'],['其他'])
