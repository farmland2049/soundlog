import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory import formal_sync
from soundlog_memory.scenes import digest_bytes


class FormalSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.target = self.root / 'target'; self.target.mkdir()
        self.preview = self.root / 'preview'; self.preview.mkdir()
        (self.preview / 'manifest.json').write_text('{}')
        rows = []
        entries = [(Path('soundlog/sources') / f'{d}.md', 'soundlog_source_record') for d in ('2026-11-13', '2026-11-14')]
        entries += [(Path('soundlog/candidates') / ('2026-11-13' if i < 100 else '2026-11-14') /
                     f'fact-{i:024x}.md', 'soundlog_candidate') for i in range(220)]
        entries += [(Path('soundlog/daily') / f'{d}.md', 'soundlog_daily_index') for d in ('2026-11-13', '2026-11-14')]
        for i, (rel, kind) in enumerate(entries):
            source = self.preview / rel.relative_to('soundlog'); source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(f'---\ntitle: "synthetic {i}"\ntype: {kind}\npermalink: {rel.with_suffix("")}\nsoundlog: {{}}\n---\n\n# synthetic {i}\n')
            rows.append({'destination': str(rel), 'sha256': digest_bytes(source),
                         'permalink': str(rel.with_suffix('')), 'noteType': kind})
        self.plan = self.root / 'plan.json'
        self.plan.write_text(json.dumps({'mode': 'read_only_proposed_two_day_pilot', 'previewId': 'preview-test',
                                        'previewManifestSHA256': digest_bytes(self.preview / 'manifest.json'),
                                        'targetRoot': str(self.target.resolve()), 'projectExternalId': 'test',
                                        'dates': ['2026-11-13', '2026-11-14'], 'files': rows}))
        self.audit = patch.object(formal_sync, 'verify_preview', return_value={'previewId': 'preview-test'})
        self.audit.start()

    def tearDown(self):
        self.audit.stop(); self.temp.cleanup()

    def test_body_preserved_and_pending_readback(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        receipt = formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        self.assertEqual(receipt['state'], 'needs_mcp_readback')
        self.assertEqual(len(receipt['created']), 224)
        original = (self.preview / Path(receipt['created'][0]['destination']).relative_to('soundlog')).read_bytes()
        written = (self.target / receipt['created'][0]['destination']).read_bytes()
        self.assertEqual(written, formal_sync.without_embeddings(original))
        self.assertEqual(written.split(b'\n---\n', 1)[1], original.split(b'\n---\n', 1)[1])
        with self.assertRaisesRegex(ValueError, '命名空间已存在'):
            formal_sync.prepare(self.plan, self.preview, self.target)

    def test_conflict_is_detected_before_any_write(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        conflict = self.target / prepared['files'][3]['destination']
        conflict.parent.mkdir(parents=True); conflict.write_text('user data')
        with self.assertRaises(ValueError):
            formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        self.assertFalse((self.root / 'receipt.json').exists())
        self.assertEqual(conflict.read_text(), 'user data')

    def test_rejects_modified_preview(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        path = self.preview / Path(prepared['files'][0]['destination']).relative_to('soundlog')
        path.write_text('modified')
        with self.assertRaises(ValueError):
            formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        self.assertFalse((self.root / 'receipt.json').exists())

    def test_rejects_symlink_in_destination(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        outside = self.root / 'outside'; outside.mkdir()
        (self.target / 'soundlog').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        self.assertEqual(list(outside.iterdir()), [])

    def test_readback_needs_every_matching_file_and_mcp_metadata(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        receipt = formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        rows = [{'file_path': x['destination'], 'permalink': x['permalink'], 'checksum': x['sha256']}
                for x in receipt['created']]
        self.assertEqual(formal_sync.verify_readback(receipt, rows[:-1], self.target)['state'], 'needs_confirmation')
        self.assertEqual(formal_sync.verify_readback(receipt, rows, self.target)['state'], 'verified')
        path = self.target / rows[0]['file_path']; path.write_text('changed')
        self.assertEqual(formal_sync.verify_readback(receipt, rows, self.target)['state'], 'needs_confirmation')

    def test_mcp_preflight_requires_fresh_exact_empty_index(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        now = datetime.now(timezone.utc)
        proof = {'schemaVersion': 1, 'checkedAt': now.isoformat(),
                 'project': {'external_id': 'test', 'source': 'local', 'local_path': str(self.target)},
                 'namespaceFind': {'path': 'soundlog', 'total': 0, 'has_more': False},
                 'permalinkSearch': {'query': 'soundlog/*', 'total': 0, 'total_is_exact': True, 'has_more': False}}
        self.assertTrue(formal_sync.validate_mcp_preflight(proof, prepared, now))
        proof['checkedAt'] = (now - timedelta(seconds=121)).isoformat()
        with self.assertRaises(ValueError):
            formal_sync.validate_mcp_preflight(proof, prepared, now)
        proof['checkedAt'] = now.isoformat(); proof['permalinkSearch']['total_is_exact'] = False
        with self.assertRaises(ValueError):
            formal_sync.validate_mcp_preflight(proof, prepared, now)

    def test_interrupt_leaves_reconciliation_receipt(self):
        prepared = formal_sync.prepare(self.plan, self.preview, self.target)
        original = formal_sync.os.open
        calls = []
        def fail_second(path, flags, *args):
            if flags & formal_sync.os.O_EXCL and Path(path).is_relative_to(self.target):
                calls.append(path)
                if len(calls) == 2:
                    raise OSError('synthetic interruption')
            return original(path, flags, *args)
        with patch.object(formal_sync.os, 'open', side_effect=fail_second):
            with self.assertRaises(OSError):
                formal_sync.apply(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        receipt = json.loads((self.root / 'receipt.json').read_text())
        self.assertEqual(receipt['state'], 'interrupted_needs_reconciliation')
        self.assertEqual(len(receipt['created']), 1)
        unrecorded = prepared['files'][1]
        target = self.target / unrecorded['destination']; target.parent.mkdir(parents=True, exist_ok=True)
        source = self.preview / Path(unrecorded['destination']).relative_to('soundlog')
        target.write_bytes(formal_sync.without_embeddings(source.read_bytes()))
        result = formal_sync.reconcile(prepared, receipt, self.target)
        self.assertEqual(len(result['recorded_match']), 1)
        self.assertEqual(len(result['unrecorded_match']), 1)
        self.assertEqual(len(result['missing']), 222)
        self.assertTrue(target.exists())
        with self.assertRaisesRegex(ValueError, '未记录文件'):
            formal_sync.resume(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        target.unlink()
        resumed = formal_sync.resume(prepared, self.plan, self.preview, self.target, self.root / 'receipt.json')
        self.assertEqual(resumed['state'], 'needs_mcp_readback')
        self.assertEqual(len(resumed['created']), 224)


if __name__ == '__main__':
    unittest.main()
