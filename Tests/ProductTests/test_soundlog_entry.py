import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import soundlog

class SelectedSnapshotTests(unittest.TestCase):
    def test_uses_selected_snapshot_instead_of_latest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); old=root/'snapshot-old'; old.mkdir()
            (old/'receipt.json').write_text(json.dumps({'snapshotId':'old','state':'completed'}))
            (root/'latest.json').write_text(json.dumps({'snapshot':'snapshot-new','snapshotId':'new'}))
            with patch.object(soundlog,'SCENES',root):
                self.assertEqual(soundlog.selected_snapshot({'sourceSnapshot':'/former/path/snapshot-old','sourceSnapshotId':'old'}),old.resolve())
                with self.assertRaises(ValueError):
                    soundlog.selected_snapshot({'sourceSnapshot':'/former/path/snapshot-old','sourceSnapshotId':'other'})

    def test_rejects_snapshot_symlink_outside_root(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'scenes';root.mkdir();outside=Path(d)/'outside';outside.mkdir()
            (root/'snapshot-escape').symlink_to(outside, target_is_directory=True)
            with patch.object(soundlog,'SCENES',root):
                with self.assertRaises(ValueError):soundlog.selected_snapshot({'sourceSnapshot':'snapshot-escape','sourceSnapshotId':'x'})

if __name__=='__main__':unittest.main()
