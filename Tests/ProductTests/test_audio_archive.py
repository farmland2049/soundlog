import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.audio_archive import MODULES, publish
from soundlog_memory.store import write_json


class AudioArchiveTests(unittest.TestCase):
    def test_cross_midnight_archive_keeps_offsets_and_reuses_unchanged_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            originals = root / 'originals'
            originals.mkdir()
            original = originals / '20261127235950.wav'
            original.touch()
            output = root / 'days'
            run = root / 'runs' / 'one'
            source = {'sourcePath': str(original), 'sourceSHA256': 'a' * 64,
                      'recordingStartLocal': '2026-11-27T23:59:50'}
            segment = {'startOffsetSeconds': 8, 'endOffsetSeconds': 12, 'text': '跨天'}
            write_json(run / 'raw.json', {**source, 'status': 'completed_with_text', 'segments': [segment]})
            write_json(run / 'speaker-aligned-transcript.json',
                       {**source, 'segments': [{**segment, 'speakerCandidates': ['speaker-1']}]})
            write_json(run / 'speaker-timeline.json', {**source, 'segments': []})
            write_json(run / 'sound-events.json', {**source, 'events': []})
            write_json(run / 'run-manifest.json', {'inputPath': str(original), 'sourceSHA256': 'a' * 64,
                       'audioDurationSeconds': 20, 'modules': {name: {'state': 'completed'} for name in MODULES}})
            result = publish(root / 'runs', originals, output)
            self.assertEqual(result['updatedDates'], ['2026-11-27', '2026-11-28'])
            self.assertEqual(publish(root / 'runs', originals, output)['updatedDates'], [])
            first, second = [json.loads((output / item['path']).read_text()) for item in result['days'].values()]
            self.assertEqual(first['utterances'], second['utterances'])
            self.assertEqual(second['utterances'][0]['startOffsetSeconds'], 8)
            self.assertIn('speaker-timeline.json', second['sources']['a' * 64]['artifacts'])
            self.assertIn('speaker-aligned-transcript.json', second['sources']['a' * 64]['artifacts'])
            before = (output / 'latest.json').read_bytes()
            (run / 'speaker-timeline.json').unlink()
            with self.assertRaises(OSError):
                publish(root / 'runs', originals, output)
            self.assertEqual((output / 'latest.json').read_bytes(), before)
