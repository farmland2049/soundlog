import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.products import export_request, import_result, load_request
from soundlog_memory.scenes import build_snapshot
from soundlog_memory.store import write_json


class ProductTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root/'runs'
        self.runs.mkdir()
        for i, day in enumerate(['2026-11-07','2026-11-08']):
            p = self.runs/day
            p.mkdir()
            d = {'sourceSHA256': str(i+1)*64,'sourcePath':'/private/original/'+day+'.mp3',
                 'recordingStartLocal':day+'T10:00:00','status':'completed_with_text',
                 'segments':[{'startOffsetSeconds':0,'endOffsetSeconds':2,'text':'我明天拿回来充电，你要用就留家里','speakerCandidates':['S1']},
                             {'startOffsetSeconds':4,'endOffsetSeconds':6,'text':'不用买了，只是建议，明天能提报销吗','speakerCandidates':['S1']}]}
            write_json(p/'raw.json',d)
            write_json(p/'speaker-aligned-transcript.json',d)
            write_json(p/'sound-events.json',{**d,'events':[]})
        self.scenes=self.root/'scenes'
        build_snapshot(self.runs,self.scenes)
        self.products=self.root/'products'
        exported=export_request(self.scenes,self.products)
        self.request=load_request(self.products,exported['requestId'])

    def tearDown(self):
        self.temp.cleanup()

    def fact(self, item=None):
        item=item or self.request['items'][0]
        ev=item['material']['utterances'][0]
        return {'summary':'匿名发言计划明天拿回设备充电，如对方需要则留家中；设备和身份未确定。',
                'functionUses':['actions','journal'],'assertion':'explicit','subject':None,'sourceMedium':'unknown',
                'dueText':'明天','eventTimeText':None,'taskState':'commitment','evidence':[{'id':ev['id'],'quote':ev['text']}]}

    def block(self,item=None,facts=None):
        item=item or self.request['items'][0]
        facts=[self.fact(item)] if facts is None else facts
        used={e['id'] for f in facts for e in f['evidence']}
        return {'key':item['key'],'facts':facts,'coverage':[{'id':e['id'],'disposition':'used' if e['id'] in used else 'context',
                  'reason':'本条用于提炼' if e['id'] in used else '上下文保留，未形成另外的明确事实'} for e in item['material']['utterances']]}

    def envelope(self):
        return {'schemaVersion':1,'requestId':self.request['requestId'],'processor':'test',
                'results':[self.block(i) for i in self.request['items']]}

    def test_full_export_complete_multifunction_output_and_anonymous_status(self):
        result=import_result(self.products,self.envelope())
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['scope'],'full-date-request')
        self.assertEqual(result['byFunction']['journal'],2)
        self.assertEqual(result['byFunction']['actions'],2)
        root=Path(result['directory'])
        facts=json.loads((root/'facts.json').read_text())['facts']
        self.assertTrue(all(f['status']=='candidate' and f['subject'] is None for f in facts))
        self.assertIn('明天', (root/'2026-11-07_actions.md').read_text())
        self.assertIn('未提炼出本栏目', (root/'2026-11-07_learning.md').read_text())
        self.assertFalse((self.root/'记忆库').exists())

    def test_request_and_result_replay_idempotent(self):
        self.assertEqual(export_request(self.scenes,self.products)['execution'],'reuse')
        a=import_result(self.products,self.envelope())
        b=import_result(self.products,self.envelope())
        self.assertEqual(a['resultId'],b['resultId'])
        self.assertEqual(b['execution'],'reuse')

    def test_same_fact_multiple_functions_deduplicated(self):
        e=self.envelope()
        for b in e['results']:
            extra=copy.deepcopy(b['facts'][0]);extra['functionUses']=['minutes']
            extra['taskState']=None
            # State is meaningful in identity, so use journal-only duplicate first.
            extra=copy.deepcopy(b['facts'][0]);extra['functionUses']=['actions']
            b['facts'].append(extra)
        result=import_result(self.products,e)
        self.assertEqual(result['facts'],2)

    def test_fabricated_quote_and_out_of_chunk_reference_rejected(self):
        for change in ['quote','id']:
            e=self.envelope();ref=e['results'][0]['facts'][0]['evidence'][0]
            ref[change]='假的原话' if change=='quote' else self.request['items'][1]['material']['utterances'][0]['id']
            with self.subTest(change=change), self.assertRaises(ValueError):
                import_result(self.products,e)
        self.assertFalse((self.products/'results').exists())

    def test_arbitrary_identity_and_confirmed_field_rejected(self):
        for field,value in [('subject','强哥'),('status','confirmed'),('occurredAt','2026-11-07T10:00:00'),('sourceMedium','live')]:
            e=self.envelope();e['results'][0]['facts'][0][field]=value
            with self.subTest(field=field), self.assertRaises(ValueError):
                import_result(self.products,e)

    def test_due_date_guess_rejected(self):
        e=self.envelope();e['results'][0]['facts'][0]['dueText']='2026-11-08'
        with self.assertRaises(ValueError):import_result(self.products,e)

    def test_questions_and_suggestions_never_commitments(self):
        for assertion in ['question','suggestion','uncertain','hypothetical','negated','reported']:
            e=self.envelope();e['results'][0]['facts'][0]['assertion']=assertion
            with self.subTest(assertion=assertion), self.assertRaises(ValueError):
                import_result(self.products,e)

    def test_question_as_question_allowed_without_task_completion(self):
        e=self.envelope();b=e['results'][0];ev=self.request['items'][0]['material']['utterances'][1]
        b['facts'][0].update(summary='对话询问明天是否可提报销，尚未明确提交状态。',assertion='question',taskState='question',
                              evidence=[{'id':ev['id'],'quote':ev['text']}])
        b['coverage'][0]['disposition']='context';b['coverage'][1]['disposition']='used'
        self.assertEqual(import_result(self.products,e)['state'],'completed')

    def test_same_quote_from_different_excerpts_has_stable_identity(self):
        from soundlog_memory.products import validate_fact
        item=copy.deepcopy(self.request['items'][0]);raw=self.fact(item)
        raw['evidence'][0]['quote']='明天'
        one=validate_fact(raw,item)
        item['material']['utterances'][0]['text']='我明天拿回来充电'
        two=validate_fact(raw,item)
        self.assertEqual(one['id'],two['id'])

    def test_function_tags_required_and_valid(self):
        for tags in [[],['health'],None,'journal']:
            e=self.envelope();e['results'][0]['facts'][0]['functionUses']=tags
            with self.subTest(tags=tags), self.assertRaises(ValueError):import_result(self.products,e)

    def test_coverage_missing_or_false_use_rejected(self):
        for mode in ['missing','fakeused','duplicate','unknown']:
            e=self.envelope();rows=e['results'][0]['coverage']
            if mode=='missing':rows.pop()
            if mode=='fakeused':rows[1]['disposition']='used'
            if mode=='duplicate':rows.append(rows[0])
            if mode=='unknown':rows[0]['id']='bogus'
            with self.subTest(mode=mode), self.assertRaises(ValueError):import_result(self.products,e)

    def test_empty_facts_allowed_only_with_complete_coverage(self):
        e=self.envelope();e['results']=[self.block(i,[]) for i in self.request['items']]
        r=import_result(self.products,e)
        self.assertEqual(r['facts'],0);self.assertEqual(r['state'],'completed')

    def test_partial_not_marked_completed(self):
        e=self.envelope();e['results'].pop()
        r=import_result(self.products,e)
        self.assertEqual(r['state'],'partial')
        self.assertEqual(len(r['missingChunks']),1)
        self.assertFalse((self.products/'completed'/ (e['requestId']+'.json')).exists())
        self.assertIn('存在缺块', (Path(r['directory'])/'2026-11-08_actions.md').read_text())

    def test_unknown_and_duplicate_blocks_rejected(self):
        for mode in ['unknown','duplicate']:
            e=self.envelope()
            if mode=='unknown':e['results'][0]['key']='unknown'
            else:e['results'].append(e['results'][0])
            with self.subTest(mode=mode), self.assertRaises(ValueError):import_result(self.products,e)

    def test_selected_scope_and_invalid_selection(self):
        i=self.request['items'][0];ids=[e['id'] for e in i['material']['utterances']]
        choice=[{'key':'case-01','date':i['date'],'evidenceIds':ids,'focusFunctions':['learning']}]
        exp=export_request(self.scenes,self.products,selections=choice)
        req=load_request(self.products,exp['requestId'])
        env={'schemaVersion':1,'requestId':req['requestId'],'processor':'test','results':[self.block(req['items'][0],[])]}
        result=import_result(self.products,env)
        self.assertEqual(result['scope'],'selection')
        self.assertIn('局部选段', (Path(result['directory'])/'2026-11-07_learning.md').read_text())
        choice[0]['evidenceIds']=['bogus']
        with self.assertRaises(ValueError):export_request(self.scenes,self.products,selections=choice)

    def test_source_tampering_before_export_and_request_tampering_rejected(self):
        root=Path(self.request['sourceSnapshot']);(root/'2026-11-07_utterances.json').write_text('{}')
        with self.assertRaises(ValueError):export_request(self.scenes,self.products)
        p=self.products/'requests'/self.request['requestId']/'request.json';p.write_text('{}')
        with self.assertRaises(ValueError):import_result(self.products,self.envelope())

    def test_published_result_tampering_detected_on_replay(self):
        r=import_result(self.products,self.envelope())
        (Path(r['directory'])/'facts.json').write_text('{}')
        with self.assertRaises(ValueError):import_result(self.products,self.envelope())

    def test_write_failure_does_not_publish_completion(self):
        with patch('soundlog_memory.products.render_function',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):import_result(self.products,self.envelope())
        self.assertFalse((self.products/'completed').exists())
        self.assertEqual(list((self.products/'results').glob('.product-*')),[])

    def test_memory_function_tags_are_optional_and_do_not_change_ids(self):
        from soundlog_memory.engine import validate_candidate, public_record
        ev=self.request['items'][0]['material']['utterances'][0]
        c={'type':'event','content':'匿名发言提到充电','assertion':'reported','evidence':[{'id':ev['id'],'quote':ev['text']}]}
        old=validate_candidate(c,{ev['id']:ev},'2026-11-07')
        tagged=validate_candidate({**c,'functionUses':['journal','learning']},{ev['id']:ev},'2026-11-07')
        self.assertEqual(old['id'],tagged['id'])
        self.assertNotIn('functionUses',old)
        self.assertEqual(public_record(tagged)['functionUses'],['journal','learning'])
        with self.assertRaises(ValueError):validate_candidate({**c,'functionUses':['unknown']},{ev['id']:ev},'2026-11-07')

    def test_memory_exact_merge_unions_function_tags(self):
        from soundlog_memory.engine import MemoryEngine, validate_candidate
        from soundlog_memory.store import Store
        ev=self.request['items'][0]['material']['utterances'][0]
        c={'type':'event','content':'匿名发言提到充电','assertion':'reported','functionUses':['journal'],
           'evidence':[{'id':ev['id'],'quote':ev['text']}]}
        store=Store(self.root/'isolated-memory');store.init()
        first=validate_candidate(c,{ev['id']:ev},'2026-11-07')
        MemoryEngine(store).apply(first,{'test':'one'})
        second=validate_candidate({**c,'functionUses':['learning']},{ev['id']:ev},'2026-11-07')
        MemoryEngine(store).apply(second,{'test':'two'})
        self.assertEqual(len(store.records()),1)
        self.assertEqual(store.records()[0]['functionUses'],['journal','learning'])

    def test_export_never_writes_into_source_snapshot(self):
        with self.assertRaises(ValueError):
            export_request(self.scenes,Path(self.request['sourceSnapshot'])/'products')

    def test_range_core_is_separate_from_reference_context(self):
        exp=export_request(self.scenes,self.products,time_ranges=[{'from':'2026-11-07T10:00:04','until':'2026-11-07T10:00:07'}])
        req=load_request(self.products,exp['requestId']);item=req['items'][0]
        self.assertEqual(req['scope'],'time-range')
        self.assertEqual(len(item['material']['utterances']),1)
        self.assertEqual(len(item['material']['contextUtterances']),1)
        from soundlog_memory.products import validate_fact
        fact=self.fact(item)
        core=item['material']['utterances'][0];context=item['material']['contextUtterances'][0]
        fact.update(dueText=None,assertion='question',taskState='question')
        fact['evidence']=[{'id':core['id'],'quote':core['text']},{'id':context['id'],'quote':context['text']}]
        validated=validate_fact(fact,item)['evidence']
        self.assertEqual(len(validated),2)
        self.assertEqual(sum(e['contextOnly'] for e in validated),1)
        fact['evidence']=fact['evidence'][1:]
        with self.assertRaises(ValueError):validate_fact(fact,item)

    def test_ranges_reject_inverted_timezone_empty_and_mixed_modes(self):
        for ranges in [[],[{'from':'2026-11-07T11:00:00','until':'2026-11-07T10:00:00'}],
                       [{'from':'2026-11-07T10:00:00+08:00','until':'2026-11-07T11:00:00+08:00'}]]:
            with self.subTest(ranges=ranges),self.assertRaises(ValueError):
                export_request(self.scenes,self.products,time_ranges=ranges)
        with self.assertRaises(ValueError):export_request(self.scenes,self.products,days=['2026-11-07'],time_ranges=[])
        with self.assertRaises(ValueError):export_request(self.scenes,self.products,context_count=6)

    def test_overlapping_ranges_do_not_duplicate_core(self):
        ranges=[{'from':'2026-11-07T10:00:00','until':'2026-11-07T10:01:00'}]*2
        exp=export_request(self.scenes,self.products,time_ranges=ranges)
        req=load_request(self.products,exp['requestId'])
        ids=[e['id'] for i in req['items'] for e in i['material']['utterances']]
        self.assertEqual(len(set(ids)),2)

    def test_context_never_joins_remote_time_gap(self):
        path=self.runs/'2026-11-07/raw.json';doc=json.loads(path.read_text())
        doc['segments'][1]['startOffsetSeconds']=1000;doc['segments'][1]['endOffsetSeconds']=1002
        write_json(path,doc);write_json(path.with_name('speaker-aligned-transcript.json'),doc)
        build_snapshot(self.runs,self.scenes)
        exp=export_request(self.scenes,self.products,time_ranges=[{'from':'2026-11-07T10:16:40','until':'2026-11-07T10:16:43'}])
        item=load_request(self.products,exp['requestId'])['items'][0]
        self.assertEqual(item['material']['contextUtterances'],[])

    def test_partial_batches_combine_and_complete(self):
        from soundlog_memory.products import combine_results
        env=self.envelope();a={**env,'results':env['results'][:1]};b={**env,'results':env['results'][1:]}
        first=import_result(self.products,a);self.assertEqual(first['state'],'partial')
        merged,report=combine_results(self.products,[a,b,a])
        self.assertEqual(report['missingChunks'],[])
        self.assertEqual(len(merged['results']),2)
        self.assertEqual(import_result(self.products,merged)['state'],'completed')

    def test_combine_rejects_conflicts_other_requests_and_duplicate_blocks(self):
        from soundlog_memory.products import combine_results
        base=self.envelope();changed=copy.deepcopy(base)
        changed['results'][0]['facts'][0]['summary']='不同的修订'
        with self.assertRaises(ValueError):combine_results(self.products,[base,changed])
        other=copy.deepcopy(base);other['requestId']='prodreq-'+'a'*24
        with self.assertRaises(ValueError):combine_results(self.products,[base,other])
        dup=copy.deepcopy(base);dup['results'].append(dup['results'][0])
        with self.assertRaises(ValueError):combine_results(self.products,[dup])

    def test_old_request_without_context_is_still_importable(self):
        from soundlog_memory.evidence import digest
        req=copy.deepcopy(self.request)
        for item in req['items']:
            item['material'].pop('contextUtterances',None)
            item['material'].pop('omittedContextIds',None)
        req.pop('requestId');req['requestId']='prodreq-'+digest(req)[:24]
        write_json(self.products/'requests'/req['requestId']/'request.json',req)
        envelope=self.envelope();envelope['requestId']=req['requestId']
        self.assertEqual(import_result(self.products,envelope)['state'],'completed')

    def test_empty_range_in_mixed_request_is_not_silently_completed(self):
        ranges=[{'from':'2026-11-07T10:00:00','until':'2026-11-07T10:01:00'},
                {'from':'2026-11-07T16:00:00','until':'2026-11-07T16:01:00'}]
        with self.assertRaises(ValueError):export_request(self.scenes,self.products,time_ranges=ranges)

    def test_receipt_counts_processed_unique_core_and_duplicate_facts(self):
        env=self.envelope()
        env['results'][0]['facts'].append(copy.deepcopy(env['results'][0]['facts'][0]))
        result=import_result(self.products,env)
        self.assertEqual(result['duplicateFactsRemoved'],1)
        self.assertEqual(result['uniqueCoreUtterances'],4)
        self.assertEqual(result['processedCoreUtterances'],4)
        env['results'].pop()
        partial=import_result(self.products,env)
        self.assertEqual(partial['processedCoreUtterances'],2)
        self.assertEqual(partial['uniqueCoreUtterances'],4)

    def test_progress_does_not_count_export_or_local_drafts(self):
        from soundlog_memory.products import request_progress
        r=request_progress(self.products,self.request['requestId'])
        self.assertEqual(r['state'],'not_started');self.assertEqual(r['importedChunks'],0)
        write_json(self.products/'local-drafts'/'fake'/'result.json',self.envelope())
        self.assertEqual(request_progress(self.products,self.request['requestId'])['importedChunks'],0)

    def test_progress_partial_ready_and_completed_are_distinct(self):
        from soundlog_memory.products import request_progress,combine_results
        env=self.envelope();a={**env,'results':env['results'][:1]};b={**env,'results':env['results'][1:]}
        import_result(self.products,a)
        self.assertEqual(request_progress(self.products,env['requestId'])['state'],'partial')
        import_result(self.products,b)
        self.assertEqual(request_progress(self.products,env['requestId'])['state'],'ready_to_combine')
        merged,_=combine_results(self.products,[a,b]);import_result(self.products,merged)
        self.assertEqual(request_progress(self.products,env['requestId'])['state'],'completed')

    def test_progress_detects_tampered_completed_output(self):
        from soundlog_memory.products import request_progress
        result=import_result(self.products,self.envelope());(Path(result['directory'])/'facts.json').write_text('{}')
        with self.assertRaises(ValueError):request_progress(self.products,self.request['requestId'])

    def test_materials_have_no_absolute_source_paths(self):
        location=self.products/'requests'/self.request['requestId']
        s=(location/'materials.json').read_text()
        self.assertNotIn('/private/',s)
        self.assertNotIn(str(self.runs),s)

    def test_unified_search_keeps_raw_and_candidate_lanes_separate(self):
        from soundlog_memory.unified_search import search_soundlog
        result=import_result(self.products,self.envelope())
        out=search_soundlog(self.scenes,self.products,[result['resultId']], '明天',day='2026-11-07')
        self.assertEqual(out['rawEvidence']['totalMatches'],2)
        self.assertEqual(out['functionalCandidates']['totalMatches'],1)
        self.assertEqual(out['sourceSnapshotId'],self.request['sourceSnapshotId'])
        self.assertIn('不是自然语言问答',out['boundary'])

    def test_unified_search_rejects_different_snapshot(self):
        from soundlog_memory.unified_search import search_soundlog
        result=import_result(self.products,self.envelope())
        latest=self.newer_snapshot()
        with self.assertRaisesRegex(ValueError,'同一证据快照'):
            search_soundlog(latest,self.products,[result['resultId']],'明天')

    def newer_snapshot(self, *, change_day=None):
        number=getattr(self,'_newer_snapshot_number',0)+1;self._newer_snapshot_number=number
        runs=self.root/f'newer-runs-{number}';shutil.copytree(self.runs,runs)
        if change_day:
            for name in ('raw.json','speaker-aligned-transcript.json','sound-events.json'):
                path=runs/change_day/name;doc=json.loads(path.read_text())
                doc['segments'][0]['text']+=' 内容已变化'
                write_json(path,doc)
        day='2026-11-09';p=runs/day;p.mkdir()
        doc={'sourceSHA256':'3'*64,'sourcePath':'/private/original/'+day+'.mp3',
             'recordingStartLocal':day+'T10:00:00','status':'completed_with_text',
             'segments':[{'startOffsetSeconds':0,'endOffsetSeconds':2,'text':'第三天的独立测试原文','speakerCandidates':['S1']} ]}
        for name in ('raw.json','speaker-aligned-transcript.json'):
            write_json(p/name,doc)
        write_json(p/'sound-events.json',{**doc,'events':[]})
        scenes=self.root/f'newer-scenes-{number}';build_snapshot(runs,scenes)
        return scenes

    def test_rebase_exact_completed_reviews_across_new_snapshot(self):
        from soundlog_memory.products import rebase_completed_results
        sources=[]
        for day in ('2026-11-07','2026-11-08'):
            exp=export_request(self.scenes,self.products,days=[day])
            req=load_request(self.products,exp['requestId'])
            env={'schemaVersion':1,'requestId':req['requestId'],'processor':'test reviewer',
                 'results':[self.block(item) for item in req['items']]}
            sources.append(import_result(self.products,env)['resultId'])
        scenes=self.newer_snapshot()
        target=export_request(scenes,self.products,days=['2026-11-07','2026-11-08'])
        target_request=load_request(self.products,target['requestId'])
        source_requests=[load_request(self.products,import_result_path) for import_result_path in
                         [json.loads((self.products/'results'/rid/'input.json').read_text())['requestId'] for rid in sources]]
        self.assertNotEqual(source_requests[0]['sourceSnapshotId'],target_request['sourceSnapshotId'])
        envelope,report=rebase_completed_results(self.products,target['requestId'],sources)
        self.assertEqual(report['exactMaterialBlocks'],len(target_request['items']))
        self.assertEqual(report['uniqueCoreUtterances'],4)
        self.assertEqual(import_result(self.products,envelope)['state'],'completed')

    def test_rebase_rejects_changed_material_or_incomplete_coverage(self):
        from soundlog_memory.products import rebase_completed_results
        from soundlog_memory.evidence import digest
        old=import_result(self.products,self.envelope())
        changed_scenes=self.newer_snapshot(change_day='2026-11-07')
        changed=export_request(changed_scenes,self.products,days=['2026-11-07','2026-11-08'])
        with self.assertRaises(ValueError):
            rebase_completed_results(self.products,changed['requestId'],[old['resultId']])
        latest=self.newer_snapshot()
        target=export_request(latest,self.products,days=['2026-11-07','2026-11-08'])
        partial=import_result(self.products,{**self.envelope(),'results':self.envelope()['results'][:1]})
        with self.assertRaises(ValueError):
            rebase_completed_results(self.products,target['requestId'],[partial['resultId']])
        with self.assertRaises(ValueError):
            rebase_completed_results(self.products,target['requestId'],[old['resultId'],old['resultId']])
        changed_contract=copy.deepcopy(self.request);changed_contract.pop('requestId')
        changed_contract['contextCount']=1
        changed_contract['requestId']='prodreq-'+digest(changed_contract)[:24]
        write_json(self.products/'requests'/changed_contract['requestId']/'request.json',changed_contract)
        with self.assertRaises(ValueError):
            rebase_completed_results(self.products,changed_contract['requestId'],[old['resultId']])
        duplicate_target=copy.deepcopy(self.request);duplicate_target.pop('requestId')
        duplicate_target['items'].append(copy.deepcopy(duplicate_target['items'][0]))
        duplicate_target['requestId']='prodreq-'+digest(duplicate_target)[:24]
        write_json(self.products/'requests'/duplicate_target['requestId']/'request.json',duplicate_target)
        with self.assertRaises(ValueError):
            rebase_completed_results(self.products,duplicate_target['requestId'],[old['resultId']])


if __name__=='__main__':unittest.main()
