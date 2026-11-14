import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json
from soundlog_memory.semantic_gate import FUNCTIONS, freeze_gold, prepare_pack, score_run, sha256


class SemanticGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.snapshot = self.root / 'snapshot'
        self.snapshot.mkdir()
        self.snapshot_id = 'b' * 64
        rows = [{'id': f'ev-{n:02d}', 'start': f'2026-11-07T10:{n:02d}:00',
                 'end': f'2026-11-07T10:{n:02d}:10', 'text': f'source line {n}',
                 'sourceFile': f'{n:02d}.mp3', 'sourceSHA256': str(n).zfill(64),
                 'startOffsetSeconds': n * 60, 'endOffsetSeconds': n * 60 + 10, 'speakers': []}
                for n in range(24)]
        source_path = self.snapshot / '2026-11-07_utterances.json'
        write_json(source_path, {'utterances': rows})
        write_json(self.snapshot / 'receipt.json', {
            'state': 'completed', 'snapshotId': self.snapshot_id,
            'artifacts': {source_path.name: digest_bytes(source_path)},
        })
        self.results_root = self.root / 'products'
        self.results_root.mkdir()
        selections, n = [], 0
        for function in sorted(FUNCTIONS):
            for slot in range(6):
                selections.append({'caseId': f'{function}-{slot}', 'date': '2026-11-07',
                                   'function': function, 'holdout': slot < 2,
                                   'evidenceIds': [f'ev-{n:02d}']})
                n += 1
        self.selection = self.root / 'selection.json'
        write_json(self.selection, {'schemaVersion': 1, 'cases': selections})

    def tearDown(self):
        self.temp.cleanup()

    def prepared_draft(self):
        output = self.root / 'draft.json'
        prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                     selection_file=self.selection, output_file=output)
        draft = json.loads(output.read_text())
        for case in draft['cases']:
            case['gold']['requiredPoints'] = [{
                'pointId': 'point-1', 'description': 'Expected information',
                'evidenceIds': case['evidenceIds'],
            }]
        write_json(output, draft)
        return output

    def frozen(self):
        draft = self.prepared_draft()
        output = self.root / 'frozen.json'
        result = freeze_gold(draft, output)
        return output, json.loads(output.read_text()), result

    def review_for(self, frozen_path, frozen):
        cases = []
        for case in frozen['cases']:
            row = case['sourceRows'][0]
            cases.append({
                'caseId': case['caseId'],
                'pointCoverage': [{'pointId': 'point-1', 'covered': True, 'claimIds': ['claim-1']}],
                'claims': [{'claimId': 'claim-1', 'text': 'Reviewed generated statement',
                            'evidence': [{'id': row['id'], 'quote': row['text']}],
                            'support': 'supported', 'violations': []}],
            })
        return {'frozenSHA256': sha256(frozen_path), 'generatedAt': '2026-11-14T12:00:00Z',
                'promptSHA256': 'a' * 64, 'runId': 'run-1', 'reviewer': 'reviewer-1', 'cases': cases}

    def test_prepares_only_unprocessed_case_material(self):
        output = self.root / 'prepared.json'
        result = prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                              selection_file=self.selection, output_file=output)
        self.assertEqual((result['cases'], result['holdout']), (24, 8))
        self.assertEqual(json.loads(output.read_text())['generationStartedAt'], None)

    def test_existing_processed_evidence_cannot_become_holdout(self):
        product_id = 'product-' + 'c' * 24
        folder = self.results_root / 'results' / product_id
        folder.mkdir(parents=True)
        facts = {'facts': [{'evidence': [{'id': 'ev-00'}]}]}
        coverage = {'processed': [{'evidence': [{'id': 'ev-00', 'disposition': 'used', 'reason': 'test'}]}],
                    'missingChunks': []}
        write_json(folder / 'facts.json', facts)
        write_json(folder / 'coverage.json', coverage)
        write_json(folder / 'receipt.json', {
            'resultId': product_id, 'sourceSnapshotId': self.snapshot_id,
            'state': 'completed', 'artifacts': {
                'facts.json': digest_bytes(folder / 'facts.json'),
                'coverage.json': digest_bytes(folder / 'coverage.json'),
            },
        })
        with self.assertRaisesRegex(ValueError, '已有产品结果处理过'):
            prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                         selection_file=self.selection, output_file=self.root / 'rejected.json')

    def test_freeze_and_holdout_metrics_pass_only_from_manual_labels(self):
        frozen_path, frozen, freeze_result = self.frozen()
        self.assertEqual(freeze_result['holdout'], 8)
        review_path = self.root / 'review.json'
        write_json(review_path, self.review_for(frozen_path, frozen))
        result = score_run(frozen_path, review_path, self.root / 'score.json')
        self.assertTrue(result['passed'])
        self.assertEqual(result['holdout']['recall'], 1.0)
        self.assertEqual(result['holdout']['evidenceSupportRate'], 1.0)

    def test_holdout_critical_violation_fails_gate(self):
        frozen_path, frozen, _ = self.frozen()
        review = self.review_for(frozen_path, frozen)
        holdout = next(row for row in review['cases'] if row['caseId'] in {
            c['caseId'] for c in frozen['cases'] if c['holdout']})
        holdout['claims'][0]['violations'] = ['negation_flip']
        review_path = self.root / 'review.json'
        write_json(review_path, review)
        result = score_run(frozen_path, review_path, self.root / 'score.json')
        self.assertFalse(result['passed'])
        self.assertEqual(result['holdout']['criticalViolationCount'], 1)

    def test_generation_must_follow_freeze_and_use_exact_hash(self):
        frozen_path, frozen, _ = self.frozen()
        review = self.review_for(frozen_path, frozen)
        review['generatedAt'] = '2026-11-13T00:00:00Z'
        review_path = self.root / 'review.json'
        write_json(review_path, review)
        with self.assertRaisesRegex(ValueError, '晚于'):
            score_run(frozen_path, review_path, self.root / 'score.json')


if __name__ == '__main__':
    unittest.main()
