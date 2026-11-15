import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import semantic_merge_gold as merge
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json
from soundlog_memory.semantic_gate import prepare_pack, score_run, sha256
from semantic_blind_packet import build_packet


class MergeGoldTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name).resolve()
        self.patch=patch.object(merge,'PRIVATE_ROOT',self.root);self.patch.start()
        self.scenes=self.root/'snapshot';self.scenes.mkdir(); self.products=self.root/'products';self.products.mkdir()
        cases=[];rows=[]
        for f in ('journal','minutes','actions','learning'):
            for i in range(6):
                n=len(rows); eid=f'ev-{n}'
                rows.append({'id':eid,'text':'source','sourceSHA256':f'{n:064x}',
                             'startOffsetSeconds':0,'endOffsetSeconds':10,'start':'2026-11-14T10:00:00',
                             'end':'2026-11-14T10:00:10','sourceFile':'mock.mp3','speakers':[]})
                cases.append({'caseId':f+'-'+str(i),'date':'2026-11-14','function':f,'holdout':i<2,'evidenceIds':[eid]})
        day=self.scenes/'2026-11-14_utterances.json';write_json(day,{'utterances':rows})
        write_json(self.scenes/'receipt.json',{'state':'completed','snapshotId':'a'*64,'artifacts':{day.name:digest_bytes(day)}})
        self.selection=self.root/'selection.json';write_json(self.selection,{'schemaVersion':1,'cases':cases})
        self.draft=self.root/'draft.json';prepare_pack(scenes_root=self.scenes,results_root=self.products,selection_file=self.selection,output_file=self.draft)
        data=json.loads(self.draft.read_text());held=[c for c in data['cases'] if c['holdout']];dev=[c for c in data['cases'] if not c['holdout']]
        self.holdout=self.root/'holdout.json';write_json(self.holdout,{**data,'cases':held})
        def gold(c):return {'requiredPoints':[{'pointId':'p1','description':'point','evidenceIds':c['evidenceIds']}], 'allowedUnknowns':[], 'forbiddenInferences':[]}
        self.human=self.root/'human.json';write_json(self.human,{'draftSHA256':sha256(self.holdout),'reviewerType':'human','cases':[{'caseId':c['caseId'],'gold':gold(c)} for c in held]})
        self.dev=self.root/'labels';self.dev.mkdir()
        for c in dev:write_json(self.dev/(c['caseId']+'.json'),{'caseId':c['caseId'],'gold':gold(c),'reviewer':'current-agent-before-generation'})
        self.merged=self.root/'merged.json';self.frozen=self.root/'frozen.json'

    def tearDown(self):self.patch.stop();self.temp.cleanup()

    def run_merge(self):
        return merge.merge_and_freeze(draft_path=self.draft,holdout_path=self.holdout,human_path=self.human,
          dev_dir=self.dev,selection_path=self.selection,merged_path=self.merged,frozen_path=self.frozen,
          scenes_root=self.scenes,products_root=self.products)

    def test_freezes_matching_labels_and_refuses_overwrite(self):
        result=self.run_merge();self.assertEqual(result['holdout'],8)
        data=json.loads(self.frozen.read_text());self.assertEqual(data['state'],'gold_frozen')
        self.assertEqual(sum(c['goldReviewer']=='human' for c in data['cases']),8)
        with self.assertRaises(ValueError):self.run_merge()

    def test_rejects_mismatched_holdout_hash_before_writing(self):
        data=json.loads(self.human.read_text());data['draftSHA256']='b'*64;write_json(self.human,data)
        with self.assertRaisesRegex(ValueError,'不匹配'):self.run_merge()
        self.assertFalse(self.merged.exists());self.assertFalse(self.frozen.exists())

    def test_full_synthetic_freeze_generate_and_bound_review(self):
        self.run_merge()
        packet=self.root/'packet.json';build_packet(self.frozen,packet)
        source=json.loads(packet.read_text());prompt=self.root/'prompt.txt';prompt.write_text('synthetic prompt')
        generated_at=(datetime.now(timezone.utc)+timedelta(seconds=1)).isoformat()
        rows=[];assessments=[]
        for case in source['cases']:
            row=case['sourceRows'][0]
            claim={'claimId':'c1','text':'synthetic statement','evidence':[{'id':row['id'],'quote':row['text']}]}
            rows.append({'caseId':case['caseId'],'claims':[claim]})
            assessments.append({'caseId':case['caseId'],'pointCoverage':[{'pointId':'p1','covered':True,'claimIds':['c1']}],
                                'claims':[{**claim,'support':'supported','violations':[]}]})
        generation=self.root/'generation.json'
        write_json(generation,{'runId':'synthetic','generatedAt':generated_at,'promptSHA256':sha256(prompt),
                               'packetSHA256':sha256(packet),'cases':rows})
        review=self.root/'review.json'
        write_json(review,{'runId':'synthetic','generatedAt':generated_at,'promptSHA256':sha256(prompt),
                           'frozenSHA256':sha256(self.frozen),'generationSHA256':sha256(generation),
                           'reviewer':'synthetic','cases':assessments})
        report=self.root/'report.json'
        result=score_run(self.frozen,review,report,generation_file=generation,packet_file=packet,prompt_file=prompt)
        self.assertTrue(result['passed'])
        self.assertEqual(result['holdout']['cases'],8)
        self.assertEqual(json.loads(report.read_text())['generationBinding']['packetSHA256'],sha256(packet))

if __name__=='__main__':unittest.main()
