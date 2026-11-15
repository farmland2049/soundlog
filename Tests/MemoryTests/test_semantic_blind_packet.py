import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from semantic_blind_packet import build_packet


class BlindPacketTests(unittest.TestCase):
    def test_packet_excludes_labels_and_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [{'caseId': str(i), 'date': '2026-11-14', 'function': 'journal', 'holdout': i < 8,
                      'evidenceIds': [str(i)], 'sourceRows': [{'id': str(i), 'text': 'source', 'secret': 'omit',
                          'start': '10:00', 'end': '10:01', 'sourceFile': 'source.mp3',
                          'startOffsetSeconds': 0, 'endOffsetSeconds': 60, 'speakers': []}],
                      'gold': {'answer': 'secret'}, 'goldReviewer': 'human'} for i in range(24)]
            frozen = root / 'frozen.json'
            frozen.write_text(json.dumps({'state': 'gold_frozen', 'frozenAt': '2026-11-14T00:00:00Z', 'cases': cases}))
            packet = root / 'packet.json'
            self.assertEqual(build_packet(frozen, packet)['cases'], 24)
            data = json.loads(packet.read_text())
            self.assertEqual(set(data['cases'][0]), {'caseId', 'date', 'function', 'sourceRows'})
            self.assertEqual(data['cases'][0]['sourceRows'][0]['startOffsetSeconds'], 0)
            self.assertEqual(data['cases'][0]['sourceRows'][0]['speakers'], [])
            self.assertNotIn('secret', packet.read_text())
            with self.assertRaises(ValueError):
                build_packet(frozen, packet)

    def test_draft_cannot_be_used(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'draft').write_text('{"state":"annotation_draft"}')
            with self.assertRaises(ValueError):
                build_packet(root / 'draft', root / 'packet')


if __name__ == '__main__':
    unittest.main()
