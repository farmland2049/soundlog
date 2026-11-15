import http.client
import json
import sys
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts'))
import soundlog_web
from soundlog_memory.scenes import digest_bytes


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.object(soundlog_web, 'selected', return_value=(
            {'resultId': 'product-test', 'dates': ['2026-11-13']}, {},
            [{'date': '2026-11-13', 'functionUses': ['journal'], 'summary': '<script>bad</script>'}]))
        self.patcher.start()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), soundlog_web.handler('test-token'))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.patcher.stop()

    def request(self, path, host=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        c.request('GET', path, headers={'Host': host or f'127.0.0.1:{self.server.server_port}'})
        r = c.getresponse(); body = r.read(); headers = dict(r.getheaders()); code = r.status; c.close()
        return code, headers, body

    def test_token_and_host_are_required(self):
        self.assertEqual(self.request('/wrong/api/status')[0], 404)
        self.assertEqual(self.request('/test-token/api/status', 'untrusted.example')[0], 404)
        self.assertEqual(self.request('/test-token/api/status')[0], 200)

    def test_items_validate_scope_and_page_uses_text_rendering(self):
        code, _, body = self.request('/test-token/api/items?day=2026-11-13&kind=journal')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['items'][0]['summary'], '<script>bad</script>')
        self.assertEqual(self.request('/test-token/api/items?day=1900-01-01&kind=journal')[0], 400)
        code, headers, page = self.request('/test-token/')
        self.assertEqual(code, 200)
        self.assertIn(b'textContent', page)
        self.assertIn('frame-ancestors', headers['Content-Security-Policy'])

    def test_search_uses_snapshot_of_selected_result(self):
        expected = Path('/selected/snapshot-old')
        response = {'rawEvidence': {'totalMatches': 0, 'matches': []},
                    'functionalCandidates': {'totalMatches': 0, 'matches': []}}
        with patch.object(soundlog_web, 'selected_snapshot', return_value=expected) as snapshot, \
             patch.object(soundlog_web, 'search_soundlog', return_value=response) as search:
            code, _, body = self.request('/test-token/api/search?day=2026-11-13&q=test')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), response)
        snapshot.assert_called_once_with({})
        self.assertEqual(search.call_args.args[0], expected)

    def test_search_all_dates_and_reject_unknown_date(self):
        response = {'rawEvidence': {'totalMatches': 0, 'matches': []},
                    'functionalCandidates': {'totalMatches': 0, 'matches': []}}
        with patch.object(soundlog_web, 'selected_snapshot', return_value=Path('/selected')), \
             patch.object(soundlog_web, 'search_soundlog', return_value=response) as search:
            self.assertEqual(self.request('/test-token/api/search?q=test')[0], 200)
            self.assertEqual(search.call_args.kwargs['day'], '2026-11-13')
            self.assertEqual(self.request('/test-token/api/search?day=1900-01-01&q=test')[0], 400)

    def test_topics_use_verified_outline_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); rid = 'reading-' + 'a' * 24; folder = root / 'reading' / rid
            folder.mkdir(parents=True)
            outline = {'sections': [{'date': '2026-11-13', 'function': 'journal', 'title': 'Topic',
                                     'summary': 'Summary', 'factIds': ['fact-1']}]}
            path = folder / 'outline.json'; path.write_text(json.dumps(outline))
            (folder / 'receipt.json').write_text(json.dumps({'readingId': rid, 'sourceResultId': 'product-test',
                                                             'artifacts': {'outline.json': digest_bytes(path)}}))
            selection = ({'resultId': 'product-test', 'readingId': rid, 'dates': ['2026-11-13']}, {},
                         [{'id': 'fact-1', 'date': '2026-11-13', 'functionUses': ['journal']}])
            with patch.object(soundlog_web, 'selected', return_value=selection), patch.object(soundlog_web, 'PRODUCTS', root):
                code, _, body = self.request('/test-token/api/topics?day=2026-11-13&kind=journal')
                self.assertEqual(code, 200)
                self.assertEqual(json.loads(body)['topics'][0]['items'][0]['id'], 'fact-1')
                path.write_text('{}')
                self.assertEqual(self.request('/test-token/api/topics?day=2026-11-13&kind=journal')[0], 400)

    def test_context_stays_within_source_and_checks_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp)
            ids = ['ev-' + str(i) * 24 for i in range(3)]
            rows = [{'id': ids[0], 'sourceSHA256': 'a', 'text': 'before'},
                    {'id': ids[1], 'sourceSHA256': 'a', 'text': 'focus'},
                    {'id': ids[2], 'sourceSHA256': 'b', 'text': 'different file'}]
            source = snapshot / '2026-11-13_utterances.json'
            source.write_text(json.dumps({'utterances': rows}))
            (snapshot / 'receipt.json').write_text(json.dumps({'artifacts': {source.name: digest_bytes(source)}}))
            with patch.object(soundlog_web, 'selected_snapshot', return_value=snapshot):
                path = '/test-token/api/context?day=2026-11-13&id=' + ids[1]
                code, _, body = self.request(path)
                self.assertEqual(code, 200)
                self.assertEqual([r['id'] for r in json.loads(body)['rows']], ids[:2])
                source.write_text('{}')
                self.assertEqual(self.request(path)[0], 400)


if __name__ == '__main__': unittest.main()
