import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.scenes import digest_bytes
from soundlog_memory.store import write_json
import soundlog_memory.basic_memory_sync as sync
from memory_v2_preview import _target_note, verify_preview


class BasicMemorySyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.preview = self.root / 'preview-aaaaaaaaaaaaaaaaaaaaaaaa'
        (self.preview / 'sources').mkdir(parents=True)
        (self.preview / 'candidates/2026-11-07').mkdir(parents=True)
        (self.preview / 'daily').mkdir()
        date = '2026-11-07'
        fact_id = 'fact-' + 'a' * 24
        files = {
            'sources/index.md': _target_note('Source index', 'soundlog_source_index',
                                             'soundlog/sources', {}, 'source index'),
            f'sources/{date}.md': _target_note(
                'Source record', 'soundlog_source_record', f'soundlog/sources/{date}',
                {'date': date}, '<a id="e-ev-test"></a>source line'),
            f'candidates/{date}/{fact_id}.md': _target_note(
                'Candidate', 'soundlog_candidate', f'soundlog/candidates/{date}/{fact_id}',
                {'status': 'candidate', 'lifecycle': 'candidate', 'subject': None,
                 'sourceMedium': 'unknown', 'id': fact_id, 'date': date,
                 'functionUses': ['journal']},
                f'[[soundlog/sources/{date}]] · 证据ID `ev-test`'),
            f'daily/{date}.md': _target_note(
                'Daily index', 'soundlog_daily_index', f'soundlog/daily/{date}',
                {'date': date}, f'[[soundlog/candidates/{date}/{fact_id}]]'),
        }
        for relative, value in files.items():
            (self.preview / relative).write_text(value, encoding='utf-8')
        (self.preview / 'README.md').write_text('preview\n', encoding='utf-8')
        (self.preview / 'mapping.json').write_text('{}\n', encoding='utf-8')
        summary = {
            'previewId': self.preview.name,
            'formalTargetNamespace': str(self.root / 'formal' / 'soundlog'),
            'dates': ['2026-11-07'], 'functionalCandidates': 1,
            'sourceUtterances': 1, 'evidenceReferences': 1,
            'semanticAssessment': 'not_independently_verified',
        }
        artifacts = {str(p.relative_to(self.preview)): digest_bytes(p)
                     for p in self.preview.rglob('*') if p.is_file()}
        write_json(self.preview / 'manifest.json', {
            'schemaVersion': 1, 'previewId': self.preview.name,
            'summary': summary, 'artifacts': artifacts,
        })
        self.sandbox = self.root / '允许模拟写入' / 'run'

    def apply(self, preview=None, sandbox=None, fail_after=None):
        with patch.object(sync, 'PROJECT_ROOT', self.root), patch.object(
                sync, 'DEFAULT_SIMULATION_ROOT', self.root / '允许模拟写入'):
            return sync.apply_preview(preview or self.preview, sandbox or self.sandbox, fail_after)

    def verify(self):
        with patch.object(sync, 'PROJECT_ROOT', self.root), patch.object(
                sync, 'DEFAULT_SIMULATION_ROOT', self.root / '允许模拟写入'):
            return sync.verify_applied(self.preview, self.sandbox)

    def revoke(self, operation_id):
        with patch.object(sync, 'PROJECT_ROOT', self.root), patch.object(
                sync, 'DEFAULT_SIMULATION_ROOT', self.root / '允许模拟写入'):
            return sync.revoke(operation_id, self.sandbox)

    def tearDown(self):
        self.temp.cleanup()

    def test_apply_readback_and_repeat_are_idempotent(self):
        first = self.apply()
        second = self.apply()
        readback = self.verify()
        self.assertEqual(first['created'], 4)
        self.assertEqual(second['created'], 0)
        self.assertEqual(second['reused'], 4)
        self.assertEqual(second['state'], 'reused')
        self.assertEqual(readback['readback'], 'passed')
        with self.assertRaisesRegex(ValueError, '仅能撤销'):
            self.revoke(second['operationId'])

    def test_mid_write_failure_rolls_back_and_retry_succeeds(self):
        with self.assertRaisesRegex(OSError, '模拟写入中断'):
            self.apply(fail_after=2)
        self.assertEqual(self.verify()['matched'], 0)
        retry = self.apply()
        self.assertEqual(retry['created'], 4)
        self.assertEqual(self.verify()['readback'], 'passed')

    def test_conflicting_destination_is_preserved_without_partial_write(self):
        target = self.sandbox / self.preview.name / 'soundlog'
        target.mkdir(parents=True)
        conflict = target / 'sources/index.md'
        conflict.parent.mkdir(parents=True)
        conflict.write_text('user edit\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '未写入任何文件'):
            self.apply()
        self.assertEqual(conflict.read_text(encoding='utf-8'), 'user edit\n')
        self.assertFalse((target / 'daily/2026-11-07.md').exists())

    def test_revoke_refuses_edited_file_then_removes_only_owned_files(self):
        result = self.apply()
        target = Path(result['target'])
        edited = target / 'soundlog/daily/2026-11-07.md'
        original = edited.read_text(encoding='utf-8')
        edited.write_text('changed after apply\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '拒绝删除'):
            self.revoke(result['operationId'])
        self.assertEqual(edited.read_text(encoding='utf-8'), 'changed after apply\n')
        edited.write_text(original, encoding='utf-8')
        revoked = self.revoke(result['operationId'])
        self.assertEqual(revoked['removed'], 4)
        self.assertEqual(self.verify()['matched'], 0)

    def test_revoke_rejects_tampered_duplicate_paths_before_deleting(self):
        result = self.apply()
        receipt_path = self.sandbox / 'operations' / (result['operationId'] + '.json')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        receipt['createdPaths'].append(receipt['createdPaths'][0])
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '缺失或重复'):
            self.revoke(result['operationId'])
        self.assertEqual(self.verify()['matched'], 4)

    def test_formal_memory_root_is_outside_simulation_allowlist(self):
        formal = self.root / 'BasicMemory' / '笔记'
        formal.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, '只能写入'):
            self.apply(sandbox=formal)

    def test_symlink_destination_is_rejected(self):
        target = self.sandbox / self.preview.name
        target.parent.mkdir(parents=True)
        outside = self.root / 'outside'
        outside.mkdir()
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            self.apply()
        self.assertEqual(list(outside.iterdir()), [])

    def test_symlink_in_allowlist_parent_is_rejected(self):
        actual = self.root / 'actual-parent'
        actual.mkdir()
        linked = self.root / 'linked-parent'
        linked.symlink_to(actual, target_is_directory=True)
        allowed = linked / '允许模拟写入'
        with patch.object(sync, 'PROJECT_ROOT', self.root), patch.object(
                sync, 'DEFAULT_SIMULATION_ROOT', allowed):
            with self.assertRaisesRegex(ValueError, '符号链接'):
                sync._safe_simulation_root(allowed / 'run')

    def test_preview_rejects_source_anchor_count_mismatch(self):
        manifest_path = self.preview / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        manifest['summary']['sourceUtterances'] = 2
        write_json(manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, '来源原文锚点数量'):
            verify_preview(self.preview)


if __name__ == '__main__':
    unittest.main()
