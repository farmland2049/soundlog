import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import semantic_gold_web as ui


class GoldFormTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name).resolve()
        self.patch = patch.object(ui, 'PRIVATE_ROOT', self.root); self.patch.start()
        self.draft = self.root / 'draft.json'; self.out = self.root / 'labels.json'
        cases = [{'caseId': f'case-{i}', 'holdout': True, 'function': 'journal',
                  'evidenceIds': [f'ev-{i}'], 'sourceRows': [{'id': f'ev-{i}', 'start': '2026-11-14T10:00:00', 'text': 'source'}]}
                 for i in range(8)]
        self.draft.write_text(json.dumps({'state':'annotation_draft','generationStartedAt':None,'cases':cases}))
        self.server, self.token = ui.start_server(self.draft, self.out)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.payload = {'cases':[{'caseId':f'case-{i}','points':[{'description':'point','evidenceIds':[f'ev-{i}']}],
                                  'allowedUnknowns':[],'forbiddenInferences':[]} for i in range(8)]}

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.patch.stop(); self.temp.cleanup()

    def request(self, method, suffix, body=None, origin=None):
        c=http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        headers={'Origin': origin or f'http://127.0.0.1:{self.server.server_port}', 'Content-Type':'application/json'}
        c.request(method,'/'+self.token+suffix,body=json.dumps(body) if body is not None else None,headers=headers)
        r=c.getresponse();data=r.read();code=r.status;c.close();return code,data

    def test_valid_human_labels_are_create_only(self):
        self.assertEqual(self.request('GET','/api/cases')[0],200)
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],200)
        first=self.out.read_bytes();self.assertEqual(json.loads(first)['reviewerType'],'human')
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],400)
        self.assertEqual(self.out.read_bytes(),first)

    def test_rejects_cross_origin_and_foreign_evidence(self):
        self.assertEqual(self.request('POST','/api/save',self.payload,'https://outside.example')[0],400)
        self.payload['cases'][0]['points'][0]['evidenceIds']=['ev-other']
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],400)
        self.assertFalse(self.out.exists())

    def test_changed_draft_cannot_be_saved(self):
        self.draft.write_text(self.draft.read_text()+' ')
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],400)
        self.assertFalse(self.out.exists())

    def test_no_output_case_requires_reason(self):
        row = self.payload['cases'][0]
        row['expectedNoOutput'] = True
        row['points'] = []
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],400)
        row['forbiddenInferences'] = ['原文没有明确事项']
        self.assertEqual(self.request('POST','/api/save',self.payload)[0],200)
        labels = json.loads(self.out.read_text())
        self.assertTrue(labels['cases'][0]['gold']['expectedNoOutput'])

if __name__=='__main__':unittest.main()
