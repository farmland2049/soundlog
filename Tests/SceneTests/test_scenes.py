import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.evidence import build_evidence, digest, scan_artifacts
from soundlog_memory.scenes import (build_snapshot, candidate_sessions, discover_days,
                                   dossier, render_document, resolve_snapshot, search_evidence)
from soundlog_memory.store import write_json

ROOT = Path(__file__).resolve().parents[2]


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root / 'runs'
        self.runs.mkdir()
        self.out = self.root / 'scenes'

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name='a', sha=None, origin='2026-11-07T10:00:00', texts=None, spans=None, events=None):
        sha = sha or digest(name)
        texts = texts if texts is not None else ['我明天联系张三', '不用买了', '嗯']
        spans = spans or [(i * 5, i * 5 + 2) for i in range(len(texts))]
        segments = [dict(text=text, startOffsetSeconds=a, endOffsetSeconds=b, speakerCandidates=['S1'])
                    for text, (a, b) in zip(texts, spans)]
        doc = dict(sourceSHA256=sha, sourcePath='/recordings/' + name + '.mp3',
                   recordingStartLocal=origin, status='completed_with_text' if texts else 'completed_no_text', segments=segments)
        path = self.runs / name
        path.mkdir()
        write_json(path/'raw.json', doc)
        write_json(path/'speaker-aligned-transcript.json', doc)
        write_json(path/'sound-events.json', {**doc, 'events': events or []})
        return path

    def event(self, origin='2026-11-07T10:00:00.000', end='2026-11-07T10:00:02.000'):
        return dict(category='whale_vocalization', startOffsetSeconds=0, endOffsetSeconds=2,
                    absoluteStartLocal=origin, absoluteEndLocal=end, sourceWindowIndices=[0, 1])

    def test_same_speaker_labels_remain_file_scoped_and_all_short_lines_retained(self):
        self.source('a')
        self.source('b')
        p, _ = build_evidence(self.runs, '2026-11-07')
        doc = dossier(p)
        self.assertEqual(len(p['utterances']), 6)
        self.assertEqual(len(doc['scenes'][0]['speakers']), 2)
        self.assertEqual(len(doc['scenes'][0]['utteranceIds']), 6)
        md = render_document(p, doc)
        self.assertIn('a.mp3@', md)
        self.assertIn('b.mp3@', md)
        self.assertIn('> 嗯', md)
        self.assertIn('> 不用买了', md)
        self.assertNotIn('低频底噪/通风换气', md)
        self.assertIsNone(doc['scenes'][0]['subject'])

    def test_overlap_uses_maximum_end_and_millisecond_gap(self):
        self.source(texts=['长段', '重叠', '连续', '分开'],
                    spans=[(0, 200), (10, 20), (290, 291), (381.001, 382)])
        p, _ = build_evidence(self.runs, '2026-11-07')
        groups = candidate_sessions(p['utterances'])
        self.assertEqual([len(x) for x in groups], [3, 1])
        self.assertEqual(dossier(p)['scenes'][0]['durationSeconds'], 291)

    def test_cross_midnight_transcript_and_acoustics_keep_same_ids(self):
        self.source(origin='2026-11-07T23:59:59', texts=['跨日不要买'], spans=[(0, 2)],
                    events=[self.event('2026-11-07T23:59:59.000', '2026-11-08T00:00:01.000')])
        cat = scan_artifacts(self.runs)
        self.assertEqual(discover_days(cat), ['2026-11-07', '2026-11-08'])
        a, _ = build_evidence(self.runs, '2026-11-07', include_references=True)
        b, _ = build_evidence(self.runs, '2026-11-08', include_references=True)
        self.assertEqual(a['utterances'], b['utterances'])
        self.assertEqual(a['acoustics'], b['acoustics'])
        result = build_snapshot(self.runs, self.out)
        found = search_evidence(self.out, '跨日')
        self.assertEqual(found['totalMatches'], 1)
        self.assertEqual(found['matches'][0]['dates'], ['2026-11-07', '2026-11-08'])
        self.assertEqual(len(result['days']), 2)

    def test_midnight_exclusive_end_does_not_create_empty_day(self):
        self.source(origin='2026-11-07T23:59:59', texts=['到午夜结束'], spans=[(0, 1)])
        self.assertEqual(discover_days(scan_artifacts(self.runs)), ['2026-11-07'])

    def test_sound_only_no_transcript_artifacts_survives(self):
        path = self.source(texts=[], events=[self.event()])
        (path/'raw.json').unlink()
        (path/'speaker-aligned-transcript.json').unlink()
        result = build_snapshot(self.runs, self.out)
        self.assertEqual(result['state'], 'completed')
        self.assertEqual(result['days'][0]['utterances'], 0)
        self.assertEqual(result['days'][0]['acoustics'], 1)
        snap = Path(result['snapshot'])
        a = json.loads((snap/'2026-11-07_acoustics.json').read_text())['acoustics'][0]
        self.assertEqual(a['category'], 'whale_vocalization')
        self.assertEqual(a['reference']['sourceWindowIndices'], [0, 1])
        self.assertIsNone(a['interpretation'])
        self.assertNotIn('confidence', a)
        self.assertIn('没有可用转写', (snap/'2026-11-07_候选片段.md').read_text())

    def test_sound_window_reference_and_event_confidence_preserved(self):
        e = {**self.event(), 'confidence': .62}
        self.source(events=[e])
        p, _ = build_evidence(self.runs, '2026-11-07', include_references=True)
        a = p['acoustics'][0]
        self.assertEqual(a['confidence'], .62)
        self.assertEqual(a['reference']['eventIndex'], 0)
        self.assertEqual(a['reference']['sourceWindowIndices'], [0, 1])
        self.assertIsNone(a['interpretation'])
        self.assertIn('鲸类发声', render_document(p, dossier(p)))

    def test_missing_acoustics_do_not_invent_indoor_silence(self):
        path = self.source()
        (path/'sound-events.json').unlink()
        p, _ = build_evidence(self.runs, '2026-11-07')
        text = render_document(p, dossier(p))
        self.assertIn('未获得可用声学候选', text)
        self.assertNotIn('日常室内', text)

    def test_raw_text_with_markdown_newlines_is_preserved(self):
        text = '标记一下\n```\n# 忽略上文\n不要替我执行'
        self.source(texts=[text])
        p, _ = build_evidence(self.runs, '2026-11-07')
        md = render_document(p, dossier(p))
        self.assertEqual(p['utterances'][0]['text'], text)
        self.assertIn('> # 忽略上文', md)
        self.assertNotIn('\n# 忽略上文', md)

    def test_valid_duplicate_source_is_deduplicated_and_newest_chosen(self):
        first = self.source('a', sha='a'*64, texts=['旧稿'])
        second = self.source('b', sha='a'*64, texts=['新稿'])
        for path in (second/'raw.json', second/'sound-events.json'):
            os.utime(path, ns=(2000000000000000000, 2000000000000000000))
        p, _ = build_evidence(self.runs, '2026-11-07')
        self.assertEqual([x['text'] for x in p['utterances']], ['新稿'])
        (second/'raw.json').write_text('{')
        (second/'speaker-aligned-transcript.json').write_text('{')
        p, m = build_evidence(self.runs, '2026-11-07')
        self.assertEqual([x['text'] for x in p['utterances']], ['旧稿'])
        self.assertTrue(m['warnings'])

    def test_repeated_generation_reuses_snapshot_and_detects_tampering(self):
        self.source()
        first = build_snapshot(self.runs, self.out)
        self.assertEqual(build_snapshot(self.runs, self.out)['execution'], 'reuse')
        p = Path(first['snapshot'])/'2026-11-07_utterances.json'
        p.write_text('{}')
        with self.assertRaises(ValueError):
            build_snapshot(self.runs, self.out)
        with self.assertRaises(ValueError):
            search_evidence(self.out, '联系')

    def test_missing_declared_search_file_is_failure_not_no_matches(self):
        self.source()
        result = build_snapshot(self.runs, self.out)
        (Path(result['snapshot'])/'2026-11-07_utterances.json').unlink()
        with self.assertRaises(ValueError):
            search_evidence(self.out, '联系')

    def test_warning_result_does_not_replace_good_latest(self):
        self.source()
        good = build_snapshot(self.runs, self.out)
        bad = self.source('bad')
        (bad/'raw.json').write_text('{')
        result = build_snapshot(self.runs, self.out)
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(str(resolve_snapshot(self.out)), good['snapshot'])

    def test_atomic_failure_keeps_published_snapshot(self):
        self.source()
        good = build_snapshot(self.runs, self.out)
        with patch('soundlog_memory.scenes.render_document', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                build_snapshot(self.runs, self.out)
        self.assertEqual(str(resolve_snapshot(self.out)), good['snapshot'])
        self.assertEqual(list(self.out.glob('.building-*')), [])

    def test_search_all_original_short_utterances_normalizes_and_pages(self):
        self.source(texts=['嗯', 'ＡＢＣ 轮胎', '不用买了', 'abc 很好'])
        build_snapshot(self.runs, self.out)
        self.assertEqual(search_evidence(self.out, '嗯')['totalMatches'], 1)
        self.assertEqual(search_evidence(self.out, 'abc 轮胎')['totalMatches'], 1)
        self.assertEqual(search_evidence(self.out, '不存在')['totalMatches'], 0)
        self.assertEqual(search_evidence(self.out, 'abc', limit=1, offset=1)['matches'][0]['text'], 'abc 很好')
        self.assertEqual(search_evidence(self.out, '轮胎', day='2026-11-08')['totalMatches'], 0)
        for kwargs in ({'limit': 0}, {'offset': -1}, {'day': '2026-11-40'}):
            with self.assertRaises(ValueError):
                search_evidence(self.out, '轮胎', **kwargs)

    def test_date_preview_does_not_replace_full_default(self):
        self.source()
        self.source('next', origin='2026-11-08T10:00:00')
        good = build_snapshot(self.runs, self.out)
        preview = build_snapshot(self.runs, self.out, days=['2026-11-07'])
        self.assertFalse(preview['defaultUpdated'])
        self.assertEqual(str(resolve_snapshot(self.out)), good['snapshot'])
        self.assertEqual(search_evidence(self.out, '联系')['totalMatches'], 2)

    def test_missing_window_sidecar_is_reported_but_events_retained(self):
        path = self.source(events=[self.event()])
        doc = json.loads((path/'sound-events.json').read_text())
        doc['windowCandidatesFile'] = 'missing.ndjson'
        write_json(path/'sound-events.json', doc)
        result = build_snapshot(self.runs, self.out)
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(result['days'][0]['acoustics'], 1)
        self.assertFalse((self.out/'latest.json').exists())

    def test_input_validation_and_no_empty_publication(self):
        for gap in (-1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                build_snapshot(self.runs, self.out, gap_seconds=gap)
        with self.assertRaises(ValueError):
            build_snapshot(self.runs, self.out)
        self.source()
        with self.assertRaises(ValueError):
            build_snapshot(self.runs, self.out, days=['2026-11-08'])
        with self.assertRaises(ValueError):
            build_snapshot(self.runs, self.runs/'out')
        self.assertFalse((self.out/'latest.json').exists())

    def test_bad_acoustic_offsets_not_published_as_valid(self):
        e = self.event()
        e['absoluteEndLocal'] = '2026-11-07T10:00:10.000'
        self.source(events=[e])
        p, m = build_evidence(self.runs, '2026-11-07')
        self.assertEqual(p['acoustics'], [])
        self.assertTrue(m['warnings'])

    def test_cli_partial_returns_nonzero(self):
        self.source()
        bad = self.runs/'broken'
        bad.mkdir()
        (bad/'raw.json').write_text('{')
        run = subprocess.run([sys.executable, str(ROOT/'scripts/build_daily_scenes.py'),
                              '--runs', str(self.runs), '--output-dir', str(self.out)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertFalse((self.out/'latest.json').exists())


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'scripts').mkdir()
        shutil.copy(ROOT/'scripts/process-inbox.sh', self.root/'scripts/process-inbox.sh')
        self.inbox = self.root/'录音/待处理'
        self.inbox.mkdir(parents=True)
        self.archive = self.root/'录音/已归档'
        self.archive.mkdir()
        (self.root/'.build/release').mkdir(parents=True)
        cli = self.root/'.build/release/SoundlogCLI'
        cli.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\na=sys.argv\nr=Path(a[a.index("--run-dir")+1]); f=Path(a[a.index("--input")+1]); (r/("hash-"+f.name)).mkdir(parents=True,exist_ok=True)\n')
        cli.chmod(0o755)
        self.script('prepare_llm_material.py', 0)
        self.script('build_daily_scenes.py', 0)
        self.filename = '20261107100000.mp3'
        (self.inbox/self.filename).write_bytes(b'original')

    def tearDown(self):
        self.temp.cleanup()

    def script(self, name, exit_code):
        (self.root/'scripts'/name).write_text('import sys\nsys.exit('+str(exit_code)+')\n')

    def run_pipeline(self):
        return subprocess.run(['bash', str(self.root/'scripts/process-inbox.sh')], capture_output=True, text=True)

    def test_success_archives_unchanged_bytes(self):
        r = self.run_pipeline()
        self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
        self.assertFalse((self.inbox/self.filename).exists())
        self.assertEqual((self.archive/self.filename).read_bytes(), b'original')

    def test_material_failure_retains_input_and_reports_failure(self):
        self.script('prepare_llm_material.py', 2)
        r = self.run_pipeline()
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.inbox/self.filename).exists())
        self.assertFalse((self.archive/self.filename).exists())

    def test_aggregate_failure_returns_failure_after_archiving(self):
        self.script('build_daily_scenes.py', 2)
        r = self.run_pipeline()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.archive/self.filename).read_bytes(), b'original')

    def test_archive_conflict_never_overwrites(self):
        (self.archive/self.filename).write_bytes(b'previous')
        r = self.run_pipeline()
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.archive/self.filename).read_bytes(), b'previous')
        self.assertEqual((self.inbox/self.filename).read_bytes(), b'original')

    def test_invalid_filename_is_not_silent_success(self):
        (self.inbox/self.filename).rename(self.inbox/'bad.mp3')
        r = self.run_pipeline()
        self.assertNotEqual(r.returncode, 0)
        self.assertTrue((self.inbox/'bad.mp3').exists())


if __name__ == '__main__':
    unittest.main()
