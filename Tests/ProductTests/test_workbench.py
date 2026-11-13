import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.workbench import compile_review, prepare, create_only

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.item={'key':'a','date':'2026-11-07','material':{'utterances':[
            {'id':'e0','text':'明天联系供应商','speakers':[],'start':'2026-11-07T10:00:00','end':'2026-11-07T10:00:01'},
            {'id':'e1','text':'嗯','speakers':[],'start':'2026-11-07T10:00:02','end':'2026-11-07T10:00:03'}]}}
        self.request={'requestId':'r','items':[self.item]}
        self.patcher=patch('soundlog_memory.workbench.load_request',return_value=self.request);self.patcher.start();self.addCleanup(self.patcher.stop)
        self.patcher2=patch('soundlog_memory.products.load_request',return_value=self.request);self.patcher2.start();self.addCleanup(self.patcher2.stop)
        self.review={'requestId':'r','processor':'agent reviewed','blocks':[{'key':'a','facts':[{
            'summary':'匿名发言提出明天联系供应商的安排','functionUses':['actions'],'assertion':'uncertain','taskState':'unknown','rows':[0]}],
            'coverage':[{'rows':[0],'disposition':'used','reason':'安排原话'},{'rows':[1],'disposition':'context','reason':'应答'}]}]}
    def test_exact_source_quote_and_no_import(self):
        got=compile_review('.',self.review)
        self.assertEqual(got['results'][0]['facts'][0]['evidence'],[{'id':'e0','quote':'明天联系供应商'}])
    def test_missing_coverage_rejected(self):
        self.review['blocks'][0]['coverage'].pop()
        with self.assertRaises(ValueError):compile_review('.',self.review)
    def test_duplicate_coverage_rejected(self):
        self.review['blocks'][0]['coverage'][1]['rows']=[0]
        with self.assertRaises(ValueError):compile_review('.',self.review)
    def test_out_of_bounds_and_boolean_indices_rejected(self):
        for value in [-1,2,True]:
            self.review['blocks'][0]['facts'][0]['rows']=[value]
            with self.assertRaises(ValueError):compile_review('.',self.review)
    def test_conflicting_supplied_quote_rejected(self):
        self.review['blocks'][0]['facts'][0]['evidence']=[]
        with self.assertRaises(ValueError):compile_review('.',self.review)
    def test_prepare_never_marks_unread_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'packet.json';prepare('.','r',p,count=1)
            import json
            self.assertEqual(json.loads(p.read_text())['blocks'][0]['coverage'],[])
    def test_create_only_protects_existing_review(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'review.json';create_only(p,{'first':True})
            with self.assertRaises(FileExistsError):create_only(p,{'second':True})
if __name__=='__main__':unittest.main()
