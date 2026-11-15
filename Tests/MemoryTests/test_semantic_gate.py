import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json
from soundlog_memory.evidence import digest
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
        return {'frozenSHA256': sha256(frozen_path), 'generatedAt': (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
                'promptSHA256': 'a' * 64, 'runId': 'run-1', 'reviewer': 'reviewer-1', 'cases': cases}

    def test_prepares_only_unprocessed_case_material(self):
        output = self.root / 'prepared.json'
        result = prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                              selection_file=self.selection, output_file=output)
        self.assertEqual((result['cases'], result['holdout']), (24, 8))
        self.assertEqual(json.loads(output.read_text())['generationStartedAt'], None)

    def existing_result(self, evidence_id='ev-00', start=0, end=10, snapshot_id=None):
        product_id = 'product-' + 'c' * 24
        folder = self.results_root / 'results' / product_id
        folder.mkdir(parents=True)
        source = {'id': evidence_id, 'sourceSHA256': '0' * 64,
                  'startOffsetSeconds': start, 'endOffsetSeconds': end}
        request = {'items': [{'key': 'prior', 'material': {'utterances': [source]}}]}
        request_id = 'prodreq-' + digest(request)[:24]
        write_json(self.results_root / 'requests' / request_id / 'request.json',
                   {**request, 'requestId': request_id})
        facts = {'facts': []}
        coverage = {'processed': [{'key': 'prior', 'evidence': [{'id': evidence_id, 'disposition': 'context', 'reason': 'test'}]}],
                    'missingChunks': []}
        write_json(folder / 'facts.json', facts)
        write_json(folder / 'coverage.json', coverage)
        write_json(folder / 'receipt.json', {
            'resultId': product_id, 'requestId': request_id, 'sourceSnapshotId': snapshot_id or self.snapshot_id,
            'state': 'completed', 'artifacts': {
                'facts.json': digest_bytes(folder / 'facts.json'),
                'coverage.json': digest_bytes(folder / 'coverage.json'),
            },
        })
    def test_existing_processed_evidence_cannot_become_holdout(self):
        self.existing_result()
        with self.assertRaisesRegex(ValueError, '已有产品结果处理过'):
            prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                         selection_file=self.selection, output_file=self.root / 'rejected.json')

    def test_processed_evidence_in_older_snapshot_cannot_become_holdout(self):
        self.existing_result(snapshot_id='a' * 64)
        with self.assertRaisesRegex(ValueError, '已有产品结果处理过'):
            prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                         selection_file=self.selection, output_file=self.root / 'rejected-old-snapshot.json')

    def test_retranscribed_same_audio_overlap_is_rejected(self):
        self.existing_result(evidence_id='ev-old-transcript', start=1, end=9, snapshot_id='a' * 64)
        with self.assertRaisesRegex(ValueError, '源音频时间范围重叠'):
            prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                         selection_file=self.selection, output_file=self.root / 'rejected-overlap.json')

    def test_non_overlapping_time_in_same_audio_remains_eligible(self):
        self.existing_result(evidence_id='ev-old-transcript', start=11, end=20, snapshot_id='a' * 64)
        result = prepare_pack(scenes_root=self.snapshot, results_root=self.results_root,
                              selection_file=self.selection, output_file=self.root / 'accepted.json')
        self.assertEqual(result['cases'], 24)

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

    def test_no_output_holdout_rejects_false_positive(self):
        draft_path = self.prepared_draft()
        draft = json.loads(draft_path.read_text())
        case = next(c for c in draft['cases'] if c['holdout'])
        case['gold'] = {'requiredPoints': [], 'expectedNoOutput': True,
                        'allowedUnknowns': [], 'forbiddenInferences': ['不能生成无依据的本类事项']}
        write_json(draft_path, draft)
        frozen_path = self.root / 'no-output-frozen.json'
        freeze_gold(draft_path, frozen_path)
        frozen = json.loads(frozen_path.read_text())
        review = self.review_for(frozen_path, frozen)
        row = next(r for r in review['cases'] if r['caseId'] == case['caseId'])
        claim = row['claims'][0]
        row['pointCoverage'] = []; row['claims'] = []
        review_path = self.root / 'no-output-review.json'; write_json(review_path, review)
        passed = score_run(frozen_path, review_path, self.root / 'no-output-passed.json')
        self.assertTrue(passed['passed'])
        self.assertEqual(passed['holdout']['noOutputCorrect'], 1)
        row['claims'] = [claim]; write_json(review_path, review)
        failed = score_run(frozen_path, review_path, self.root / 'no-output-failed.json')
        self.assertFalse(failed['passed'])
        self.assertEqual(failed['holdout']['noOutputFalsePositives'], 1)

    def test_generation_must_follow_freeze_and_use_exact_hash(self):
        frozen_path, frozen, _ = self.frozen()
        review = self.review_for(frozen_path, frozen)
        review['generatedAt'] = '2026-11-13T00:00:00Z'
        review_path = self.root / 'review.json'
        write_json(review_path, review)
        with self.assertRaisesRegex(ValueError, '晚于'):
            score_run(frozen_path, review_path, self.root / 'score.json')

    def test_bound_score_requires_exact_generated_claims(self):
        from semantic_blind_packet import build_packet
        frozen_path, frozen, _ = self.frozen()
        packet_path = self.root / 'packet.json'
        build_packet(frozen_path, packet_path)
        prompt_path = self.root / 'prompt.txt'
        prompt_path.write_text('actual prompt')
        review = self.review_for(frozen_path, frozen)
        review['promptSHA256'] = sha256(prompt_path)
        generated = {'runId': review['runId'], 'generatedAt': review['generatedAt'],
                     'promptSHA256': review['promptSHA256'], 'packetSHA256': sha256(packet_path),
                     'cases': [{'caseId': r['caseId'],
                                'claims': [{k: c[k] for k in ('claimId', 'text', 'evidence')}
                                           for c in r['claims']]} for r in review['cases']]}
        generation_path = self.root / 'generation.json'; write_json(generation_path, generated)
        review['generationSHA256'] = sha256(generation_path)
        review_path = self.root / 'bound-review.json'; write_json(review_path, review)
        result = score_run(frozen_path, review_path, self.root / 'bound-score.json',
                           generation_file=generation_path, packet_file=packet_path, prompt_file=prompt_path)
        self.assertTrue(result['passed'])
        self.assertEqual(json.loads((self.root / 'bound-score.json').read_text())['generationBinding']['generationSHA256'], sha256(generation_path))
        review['cases'][0]['claims'] = []
        review['cases'][0]['pointCoverage'][0].update(covered=False, claimIds=[])
        write_json(review_path, review)
        with self.assertRaisesRegex(ValueError, '逐条匹配'):
            score_run(frozen_path, review_path, self.root / 'tampered-score.json',
                      generation_file=generation_path, packet_file=packet_path, prompt_file=prompt_path)

    def test_unverifiable_generated_evidence_is_counted_as_failure(self):
        frozen_path, frozen, _ = self.frozen()
        review = self.review_for(frozen_path, frozen)
        holdout_ids = {c['caseId'] for c in frozen['cases'] if c['holdout']}
        claim = next(r for r in review['cases'] if r['caseId'] in holdout_ids)['claims'][0]
        claim['evidence'][0]['quote'] = 'invented quote'
        review_path = self.root / 'review-invalid.json'; write_json(review_path, review)
        with self.assertRaisesRegex(ValueError, '无效引文'):
            score_run(frozen_path, review_path, self.root / 'invalid.json')
        claim['support'] = 'unsupported'; claim['violations'] = ['fabricated_quote']
        write_json(review_path, review)
        result = score_run(frozen_path, review_path, self.root / 'counted.json')
        self.assertFalse(result['passed'])
        self.assertEqual(result['holdout']['criticalViolationCount'], 1)


if __name__ == '__main__':
    unittest.main()
