import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
from soundlog_memory.evidence import build_evidence, chunks, digest
from soundlog_memory.store import Store, atomic, write_json, parse_note
from soundlog_memory.engine import MemoryEngine, validate_candidate
from soundlog_memory.workflow import Workflow
from soundlog_memory.protocol import ChatAPI, LocalModelAdapter


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = self.root / 'runs'
        self.store = Store(self.root / 'store')
        self.store.init()
        self.flow = Workflow(self.store, self.runs)
        self.source('a', 'a' * 64, '2026-11-07T10:00:00', ['我明天联系张三', '不买了', '建议先讨论', '项目甲决定下周交付'])

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name, sha, start, texts):
        folder = self.runs / name
        folder.mkdir(parents=True, exist_ok=True)
        segments = [{'startOffsetSeconds': n * 5, 'endOffsetSeconds': n * 5 + 2,
                     'text': text, 'speakerCandidates': ['S1']} for n, text in enumerate(texts)]
        doc = {'sourceSHA256': sha, 'sourcePath': '/private/source/' + name + '.mp3',
               'recordingStartLocal': start, 'status': 'completed_with_text', 'segments': segments}
        write_json(folder / 'raw.json', doc)
        write_json(folder / 'speaker-aligned-transcript.json', doc)
        write_json(folder / 'sound-events.json', {**doc, 'events': []})
        return folder

    def candidate(self, day='2026-11-07', index=0, content='联系张三', kind='todo'):
        package, _ = self.flow.prepare(day)
        ev = package['utterances'][index]
        return {'type': kind, 'content': content, 'assertion': 'explicit', 'subject': '我',
                'occurredAt': None, 'responsible': None, 'entities': [], 'dueText': None, 'dueDate': None,
                'evidence': [{'id': ev['id'], 'quote': ev['text']}]}

    def validated(self, **kwargs):
        raw = self.candidate(**kwargs)
        day = kwargs.get('day', '2026-11-07')
        package, _ = self.flow.prepare(day)
        return validate_candidate(raw, {e['id']: e for e in package['utterances']}, day)

    def add(self, c=None):
        return MemoryEngine(self.store).apply(c or self.validated(), {'model': 'test'}, {'action': 'ADD', 'reason': '新内容'})

    def test_evidence_stable_short_lines_scoped_speakers_and_duplicates(self):
        self.source('b', 'b'*64, '2026-11-07T11:00:00', ['嗯'])
        original = self.runs / 'a/raw.json'
        duplicate = self.runs / 'duplicate'
        duplicate.mkdir()
        write_json(duplicate / 'raw.json', json.loads(original.read_text()))
        p, manifest = build_evidence(self.runs, '2026-11-07')
        self.assertEqual(len(p['utterances']), 5)
        self.assertEqual(p['fingerprint'], build_evidence(self.runs, '2026-11-07')[0]['fingerprint'])
        self.assertNotEqual(p['utterances'][0]['speakers'], p['utterances'][-1]['speakers'])
        self.assertIn('嗯', [e['text'] for e in p['utterances']])

    def test_cross_midnight_keeps_whole_span(self):
        self.source('cross', 'c'*64, '2026-11-07T23:59:59', ['跨日'])
        a, _ = build_evidence(self.runs, '2026-11-07')
        b, _ = build_evidence(self.runs, '2026-11-08')
        ev = next(e for e in a['utterances'] if e['text'] == '跨日')
        self.assertEqual(ev, b['utterances'][0])

    def test_invalid_newer_artifact_does_not_hide_valid_old(self):
        folder = self.source('bad', 'a'*64, '2026-11-07T10:00:00', ['bad'])
        (folder / 'raw.json').write_text('{')
        (folder / 'speaker-aligned-transcript.json').write_text('{')
        p, m = build_evidence(self.runs, '2026-11-07')
        self.assertEqual(len(p['utterances']), 4)
        self.assertTrue(m['warnings'])

    def test_chunks_cover_all_evidence(self):
        p, _ = self.flow.prepare('2026-11-07')
        cs = chunks(p, max_chars=500)
        self.assertEqual({e['id'] for e in p['utterances']}, {e['id'] for c in cs for e in c['material']['utterances']})

    def test_subject_and_fake_evidence_rejected(self):
        p, _ = self.flow.prepare('2026-11-07')
        evs = {e['id']: e for e in p['utterances']}
        for change in [{'subject': '强哥'}, {'evidence': [{'id': 'fake', 'quote': '我'}]},
                       {'evidence': [{'id': p['utterances'][0]['id'], 'quote': '不是原话'}]},
                       {'assertion': 'negated'}, {'assertion': 'reported'}, {'assertion': 'suggestion'}]:
            c = self.candidate(); c.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_candidate(c, evs, '2026-11-07')

    def test_due_unknown_and_preference_stays_statement(self):
        c = self.validated()
        self.assertIsNone(c['dueDate'])
        self.assertEqual(self.validated(kind='preference_statement')['type'], 'preference_statement')

    def test_idempotent_replay(self):
        first = self.add()
        second = self.add()
        self.assertEqual(second['state'], 'reused')
        self.assertEqual(len(self.store.records()), 1)
        self.assertEqual(self.store.get(first['memoryId'])['status'], 'candidate')

    def test_same_content_different_date_not_merged(self):
        self.add()
        self.source('next', 'd'*64, '2026-11-08T10:00:00', ['我明天联系张三'])
        c = self.validated(day='2026-11-08')
        target = self.store.records()[0]['id']
        with self.assertRaises(ValueError):
            MemoryEngine(self.store).apply(c, {'model': 'test'}, {'action': 'NONE', 'target': target, 'reason': '重复'})
        self.add(c)
        self.assertEqual(len(self.store.records()), 2)

    def test_none_adds_new_evidence(self):
        first = self.add()
        self.source('a', 'a'*64, '2026-11-07T10:00:00', ['我明天联系张三', '我明天联系张三'])
        c = self.validated(index=1)
        MemoryEngine(self.store).apply(c, {'model': 'test'}, {'action': 'NONE', 'target': first['memoryId'], 'reason': '同一事实'})
        self.assertEqual(len(self.store.records()), 1)
        self.assertEqual(len(self.store.records()[0]['evidence']), 2)

    def proposal(self, action='UPDATE'):
        first = self.add()
        c = self.validated(content='联系张三，期限待定')
        result = MemoryEngine(self.store).apply(c, {'model': 'test'}, {'action': action, 'target': first['memoryId'], 'reason': '新的原话更正'}, {first['memoryId']})
        return first, result

    def test_update_review_undo(self):
        first, change = self.proposal()
        old = self.store.get(first['memoryId'])
        self.assertEqual(old['lifecycle'], 'active')
        op = MemoryEngine(self.store).review(change['changeId'], True)
        self.assertEqual(self.store.get(first['memoryId'])['lifecycle'], 'superseded')
        new = next(r for r in self.store.records() if r['lifecycle'] == 'active')
        self.assertEqual(new['status'], 'confirmed')
        self.store.undo(op)
        self.assertEqual(self.store.get(first['memoryId'])['lifecycle'], 'active')
        self.assertEqual(len(self.store.records()), 1)
        self.assertEqual(read_json(self.store.root/'审核'/ (change['changeId']+'.json'))['state'], 'pending')

    def test_delete_and_reject(self):
        first, change = self.proposal('DELETE')
        MemoryEngine(self.store).review(change['changeId'], False)
        self.assertEqual(self.store.get(first['memoryId'])['lifecycle'], 'active')
        with self.assertRaises(ValueError):
            MemoryEngine(self.store).review(change['changeId'], True)

    def test_delete_approval_retains_markdown(self):
        first, change = self.proposal('DELETE')
        MemoryEngine(self.store).review(change['changeId'], True)
        self.assertEqual(self.store.get(first['memoryId'])['lifecycle'], 'revoked')
        self.assertEqual(self.store.search(), [])
        self.assertEqual(len(self.store.search(include_inactive=True)), 1)

    def test_stale_review_is_rejected(self):
        first, change = self.proposal()
        MemoryEngine(self.store).confirm(first['memoryId'])
        with self.assertRaises(ValueError):
            MemoryEngine(self.store).review(change['changeId'], True)

    def test_undo_refuses_overwrite_later_edits(self):
        first = self.add()
        path = self.store.record_path(first['memoryId'])
        path.write_text(path.read_text().replace('[todo] 联系张三', '[todo] 人工编辑'))
        with self.assertRaises(ValueError):
            self.store.undo(first['operationId'])

    def test_markdown_authority_and_rebuild(self):
        first = self.add()
        path = self.store.record_path(first['memoryId'])
        path.write_text(path.read_text().replace('[todo] 联系张三', '[todo] 人工补充联系'))
        self.assertEqual(len(self.store.search('人工补充')), 1)
        (self.store.root / '索引/memory.sqlite3').unlink()
        self.assertEqual(len(self.store.search('人工补充', status='candidate')), 1)
        self.assertEqual(self.store.search('人工补充', status='confirmed'), [])

    def test_pending_transaction_recovers(self):
        first = self.add()
        path = self.store.record_path(first['memoryId'])
        old = path.read_text()
        path.write_text('partial')
        rel = str(path.relative_to(self.store.root))
        write_json(self.store.root/'运行/事务/crash.json', {'state': 'pending', 'before': {rel: old}})
        self.store.recover()
        self.assertEqual(path.read_text(), old)

    def envelope(self):
        req, _ = self.flow.request('2026-11-07')
        return {'schemaVersion': 1, 'requestId': req['requestId'], 'model': 'manual-test',
                'results': [{'chunkId': i['id'], 'candidates': [self.candidate()] if n == 0 else []} for n, i in enumerate(req['items'])]}

    def test_export_no_paths_and_import_replay(self):
        req, folder = self.flow.request('2026-11-07')
        public = (folder / 'materials.json').read_text()
        self.assertNotIn('/private/source', public)
        env = self.envelope()
        self.assertEqual(self.flow.import_result(env)['state'], 'completed')
        self.flow.import_result(env)
        self.assertEqual(len(self.store.records()), 1)

    def test_import_partial_error_and_missing_blocks(self):
        env = self.envelope()
        env['results'][0]['candidates'][0]['evidence'][0]['quote'] = '伪造'
        result = self.flow.import_result(env)
        self.assertEqual(result['state'], 'partial')
        self.assertTrue(result['errors'])
        self.assertEqual(self.store.records(), [])

    def test_resolution_export_import(self):
        self.flow.import_result(self.envelope())
        req, _ = self.flow.request('2026-11-07', resolve=True)
        env = {'schemaVersion': 1, 'requestId': req['requestId'], 'model': 'test',
               'results': [{'chunkId': i['id'], 'proposal': {'action': 'ADD', 'reason': '新内容', 'target': None}} for i in req['items']]}
        self.assertEqual(self.flow.import_result(env)['state'], 'completed')
        replay = self.flow.import_result(env)
        self.assertEqual(replay['state'], 'completed')
        self.assertEqual(replay['execution'], 'reuse')
        self.assertEqual(len(self.store.records()), 1)

    def test_api_resume_and_bad_json_retry(self):
        outer = self
        class Fake:
            identifier = 'fake-test'
            calls = 0
            def generate(self, prompt, material):
                self.calls += 1
                if self.calls == 1:
                    return {'broken': True}
                return {'candidates': [outer.candidate()]}
        api = Fake()
        first = self.flow.extract('2026-11-07', api)
        self.assertEqual(first['state'], 'completed')
        self.assertEqual(api.calls, 2)
        again = self.flow.extract('2026-11-07', api)
        self.assertEqual(api.calls, 2)
        self.assertEqual(next(iter(again['chunks'].values()))['execution'], 'reuse')

    def test_api_failure_recovers(self):
        outer = self
        class Fake:
            identifier = 'fake'
            fail = True
            def generate(self, prompt, material):
                if self.fail:
                    raise TimeoutError('test timeout')
                return {'candidates': [outer.candidate()]}
        api = Fake()
        self.assertEqual(self.flow.extract('2026-11-07', api)['state'], 'partial')
        api.fail = False
        self.assertEqual(self.flow.extract('2026-11-07', api)['state'], 'completed')

    def test_http_adapter_uses_chat_endpoint_and_no_local_paths(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                data = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((self.path, data))
                body = json.dumps({'choices': [{'message': {'content': '{"candidates":[]}'}}]}).encode()
                self.send_response(200); self.end_headers(); self.wfile.write(body)
            def log_message(self, *args):
                pass
        server = HTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            api = ChatAPI('http://127.0.0.1:' + str(server.server_port) + '/v1', 'fixture')
            self.assertEqual(self.flow.extract('2026-11-07', api)['state'], 'completed')
            self.assertEqual(received[0][0], '/v1/chat/completions')
            self.assertNotIn('/private/source', json.dumps(received))
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_undo_add_prevents_reimport_recreation(self):
        first = self.add()
        self.store.undo(first['operationId'])
        self.assertEqual(self.store.records(), [])
        replay = self.add()
        self.assertTrue(replay['undone'])
        self.assertEqual(self.store.records(), [])

    def test_long_single_utterance_is_bounded(self):
        self.source('long', 'f'*64, '2026-11-07T12:00:00', ['甲' * 40000])
        p, _ = self.flow.prepare('2026-11-07')
        cs = chunks(p)
        self.assertTrue(all(sum(len(json.dumps(e, ensure_ascii=False)) for e in c['material']['utterances']) < 12500 for c in cs))
        self.assertTrue(any('甲' in e['text'] for c in cs for e in c['material']['utterances']))

    def test_entity_backlinks_and_confirm(self):
        c = self.validated()
        c['entities'] = ['张三']
        result = self.add(c)
        MemoryEngine(self.store).confirm(result['memoryId'])
        self.assertEqual(len(self.store.search(entity='张三', status='confirmed')), 1)
        self.assertEqual(len(list((self.store.root/'笔记/实体').glob('*.md'))), 1)

    def test_stale_resolution_import_refused(self):
        self.add()
        req, _ = self.flow.request('2026-11-07', resolve=True)
        MemoryEngine(self.store).confirm(self.store.records()[0]['id'])
        env = {'schemaVersion': 1, 'model': 'test', 'requestId': req['requestId'],
               'results': [{'chunkId': i['id'], 'proposal': {'action': 'ADD', 'target': None, 'reason': '新内容'}} for i in req['items']]}
        self.assertEqual(self.flow.import_result(env)['state'], 'partial')

    def test_atomic_failure_rolls_back(self):
        from unittest.mock import patch
        import soundlog_memory.store as module
        original = module.atomic
        calls = []
        def fail_once(path, text):
            calls.append(str(path))
            if str(path).endswith('two.md') and len([p for p in calls if p.endswith('two.md')]) == 1:
                raise OSError('simulated disk failure')
            return original(path, text)
        atomic(self.store.root/'one.md', 'before')
        with patch.object(module, 'atomic', side_effect=fail_once), self.assertRaises(OSError):
            self.store.transaction({'one.md': 'changed', 'two.md': 'new'}, 'test-failure')
        self.assertEqual((self.store.root/'one.md').read_text(), 'before')
        self.assertFalse((self.store.root/'two.md').exists())

    def test_api_resolver_generates_review(self):
        old = self.add()
        outer = self
        class Fake:
            identifier = 'resolver-fixture'
            def generate(self, prompt, material):
                if 'existing' in material:
                    return {'action': 'UPDATE', 'target': old['memoryId'], 'reason': '补充期限线索'}
                return {'candidates': [outer.candidate(content='联系张三，期限未知')]}
        self.assertEqual(self.flow.extract('2026-11-07', Fake())['state'], 'completed')
        self.assertEqual(self.store.get(old['memoryId'])['lifecycle'], 'active')
        pending = list((self.store.root/'审核').glob('*.json'))
        self.assertEqual(len(pending), 1)
        self.assertEqual(read_json(pending[0])['action'], 'UPDATE')

    def test_resolve_import_update_existing_candidate(self):
        old = self.add()
        second = self.add(self.validated(content='联系张三，期限未知'))
        req, _ = self.flow.request('2026-11-07', resolve=True)
        item = next(i for i in req['items'] if i['candidate']['id'] == second['memoryId'])
        env = {'schemaVersion': 1, 'requestId': req['requestId'], 'model': 'resolver', 'results': [
            {'chunkId': item['id'], 'proposal': {'action': 'UPDATE', 'target': old['memoryId'], 'reason': '补充'}}]}
        result = self.flow.import_result(env)
        self.assertEqual(result['errors'], [])
        pid = result['results'][0]['changeId']
        MemoryEngine(self.store).review(pid, True)
        self.assertEqual(self.store.get(second['memoryId'])['status'], 'confirmed')
        self.assertEqual(self.store.get(old['memoryId'])['lifecycle'], 'superseded')

    def test_incomplete_import_can_resume(self):
        self.source('late', 'e'*64, '2026-11-07T19:00:00', ['我明天联系张三'])
        req, _ = self.flow.request('2026-11-07')
        env = {'schemaVersion': 1, 'requestId': req['requestId'], 'model': 'manual', 'results': []}
        result = self.flow.import_result(env)
        self.assertEqual(result['state'], 'partial')
        self.assertEqual(len(result['missingChunks']), len(req['items']))
        env['results'] = [{'chunkId': i['id'], 'candidates': []} for i in req['items']]
        self.assertEqual(self.flow.import_result(env)['state'], 'completed')

    def test_secondary_none_marks_imported_duplicate_and_can_undo(self):
        first = self.add()
        c = self.validated(content='明天联系张三')
        second = self.add(c)
        result = MemoryEngine(self.store).apply(c, {'model': 'resolver'},
                    {'action': 'NONE', 'target': first['memoryId'], 'reason': '同一原话的同一承诺'}, {first['memoryId']})
        self.assertEqual(self.store.get(second['memoryId'])['lifecycle'], 'merged')
        self.assertEqual(len(self.store.search()), 1)
        self.store.undo(result['operationId'])
        self.assertEqual(len(self.store.search()), 2)

    def test_secondary_add_records_resolution_without_duplicate(self):
        self.add()
        c = self.validated()
        MemoryEngine(self.store).apply(c, {'model': 'resolver'}, {'action': 'ADD', 'target': None, 'reason': '已核对为新增'}, set())
        self.assertEqual(len(self.store.records()), 1)
        self.assertEqual(self.store.records()[0]['resolution']['action'], 'ADD')

    def test_local_adapter_is_explicit_placeholder(self):
        with self.assertRaises(NotImplementedError):
            LocalModelAdapter().generate('', {})


from soundlog_memory.evidence import read_json
if __name__ == '__main__':
    unittest.main()
