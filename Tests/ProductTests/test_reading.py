import copy
import json
from pathlib import Path
import unittest
import test_products as fixtures
from soundlog_memory.products import import_result
from soundlog_memory.reading import publish_reading

class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.ProductTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.root=self.fixture.products
        self.result=import_result(self.root,self.fixture.envelope())
        self.source=Path(self.result['directory'])
        self.facts=json.loads((self.source/'facts.json').read_text())['facts']
        first=self.facts[0]
        self.outline={'schemaVersion':1,'resultId':self.result['resultId'],'reviewer':'reviewer',
                      'sections':[{'date':first['date'],'function':'actions','title':'条件安排',
                                   'summary':'明天取回并按需提供，未确认完成。','factIds':[first['id']]}]}
    def test_reading_has_all_days_all_functions_and_remaining_facts(self):
        report=publish_reading(self.root,self.outline);dest=Path(report['directory'])
        self.assertEqual(len(list(dest.glob('2026-*.md'))),8)
        self.assertIn('其他候选条目（1条', (dest/'2026-11-08_actions.md').read_text())
        self.assertIn('未确认完成', (dest/'2026-11-07_actions.md').read_text())
        self.assertTrue((dest/'../../results'/self.result['resultId']/'2026-11-07_actions.md').resolve().is_file())
    def test_unknown_fact_rejected(self):
        self.outline['sections'][0]['factIds']=['fake']
        with self.assertRaises(ValueError):publish_reading(self.root,self.outline)
    def test_cross_date_or_function_rejected(self):
        for field,value in [('date','2026-11-08'),('function','learning')]:
            outline=copy.deepcopy(self.outline);outline['sections'][0][field]=value
            with self.assertRaises(ValueError):publish_reading(self.root,outline)
    def test_duplicate_assignment_rejected(self):
        self.outline['sections'].append(copy.deepcopy(self.outline['sections'][0]))
        with self.assertRaises(ValueError):publish_reading(self.root,self.outline)
    def test_source_tampering_rejected_before_publish(self):
        (self.source/'facts.json').write_text('{}')
        with self.assertRaises(ValueError):publish_reading(self.root,self.outline)
    def test_reuse_and_changed_output_protected(self):
        first=publish_reading(self.root,self.outline);second=publish_reading(self.root,self.outline)
        self.assertEqual(first['directory'],second['directory'])
        (Path(first['directory'])/'README.md').write_text('changed')
        with self.assertRaises(ValueError):publish_reading(self.root,self.outline)
    def test_empty_fact_day_still_has_four_outputs(self):
        env=self.fixture.envelope();env['results'][1]=self.fixture.block(self.fixture.request['items'][1],facts=[])
        result=import_result(self.root,env);self.outline['resultId']=result['resultId']
        report=publish_reading(self.root,self.outline)
        self.assertTrue((Path(report['directory'])/'2026-11-08_learning.md').is_file())
if __name__=='__main__':unittest.main()
