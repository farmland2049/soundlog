import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_products as fixtures
from soundlog_memory.product_search import search_products
from soundlog_memory.products import import_result


class ProductSearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ProductTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.products
        envelope = self.fixture.envelope()
        for block in envelope['results']:
            block['facts'][0]['summary'] = '设备取回充电的状态仍待核对。'
        self.envelope = envelope
        self.result = import_result(self.root, envelope)
        self.rid = self.result['resultId']

    def search(self, query, **kwargs):
        return search_products(self.root, [self.rid], query, **kwargs)

    def test_summary_only_hit_is_explicit_and_quotes_unchanged(self):
        result = self.search('设备')
        self.assertEqual(result['totalMatches'], 2)
        hit = result['matches'][0]
        self.assertEqual(hit['matchFields'], ['summary'])
        self.assertEqual(hit['matchedEvidenceIds'], [])
        self.assertNotIn('设备', hit['fact']['evidence'][0]['quote'])
        self.assertIsNone(hit['fact']['subject'])
        self.assertEqual(hit['fact']['sourceMedium'], 'unknown')

    def test_raw_quote_search_and_normalized_multi_term(self):
        hit = self.search('明天 留家里')['matches'][0]
        self.assertEqual(hit['matchFields'], ['evidenceQuote'])
        self.assertEqual(len(hit['matchedEvidenceIds']), 1)

    def test_filters_paging_and_empty_match(self):
        self.assertEqual(self.search('充电', day='2026-11-07')['totalMatches'], 1)
        self.assertEqual(self.search('充电', function='learning')['totalMatches'], 0)
        self.assertEqual(self.search('不存在')['matches'], [])
        hit = self.search('充电', limit=1, offset=1)['matches'][0]
        self.assertEqual(hit['fact']['date'], '2026-11-08')

    def test_invalid_inputs_rejected(self):
        for kwargs in [{'limit': True}, {'offset': -1}, {'limit': 0},
                       {'day': 'not-date'}, {'function': 'health'}]:
            with self.subTest(kwargs=kwargs), self.assertRaises((ValueError, TypeError)):
                self.search('充电', **kwargs)
        for query in ['', '   ', None]:
            with self.assertRaises(ValueError): self.search(query)
        for ids in [[], [self.rid, self.rid], self.rid, [None]]:
            with self.assertRaises(ValueError):
                search_products(self.root, ids, '充电')

    def test_changed_source_rejected_not_silently_ignored(self):
        path = Path(self.result['directory']) / 'facts.json'
        path.write_text('{}')
        with self.assertRaises(ValueError): self.search('充电')

    def test_multiple_revisions_of_same_request_rejected(self):
        envelope = copy.deepcopy(self.envelope)
        envelope['results'][0]['facts'][0]['summary'] = '不同的历史修订。'
        revised = import_result(self.root, envelope)
        with self.assertRaisesRegex(ValueError, '修订'):
            search_products(self.root, [self.rid, revised['resultId']], '充电')

    def test_cli_readonly_output_and_error_exit(self):
        script = Path(__file__).resolve().parents[2] / 'scripts/search_products.py'
        args = [sys.executable, str(script), '设备', '--root', str(self.root),
                '--result', self.rid]
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['totalMatches'], 2)
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))
        result = subprocess.run(args + ['--limit', '0'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
