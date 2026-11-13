import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler,HTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.local_products import LocalOllama,RejectRedirect,extract_local
from soundlog_memory.products import export_request,load_request
from soundlog_memory.scenes import build_snapshot
from soundlog_memory.store import write_json


class LocalProductsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);runs=self.root/'runs';runs.mkdir()
        d={'sourceSHA256':'a'*64,'sourcePath':'/private/20261107100000.mp3','recordingStartLocal':'2026-11-07T10:00:00',
           'status':'completed_with_text','segments':[{'text':'我明天联系供应方','startOffsetSeconds':0,'endOffsetSeconds':2,'speakerCandidates':['S1']} ]}
        write_json(runs/'raw.json',d);write_json(runs/'speaker-aligned-transcript.json',d);write_json(runs/'sound-events.json',{**d,'events':[]})
        scenes=self.root/'scenes';build_snapshot(runs,scenes);self.store=self.root/'products'
        exp=export_request(scenes,self.store);self.req=load_request(self.store,exp['requestId']);self.item=self.req['items'][0]
        self.raw={'facts':[{'summary':'匿名发言承诺明天联系供应方，身份和是否完成未知。','functionUses':['actions'],
             'assertion':'explicit','taskState':'commitment','dueText':'明天','eventTimeText':None,'evidenceIds':['u0']}]}

    def tearDown(self):self.temp.cleanup()

    def fake(self):
        client=object.__new__(LocalOllama);client.model='test-local';client.model_digest='a'*64
        client.request=lambda *args,**kwargs:{'done':True,'done_reason':'stop','message':{'content':json.dumps(self.raw,ensure_ascii=False)},'eval_count':10}
        return client

    def test_maps_model_ids_to_exact_quotes_without_confirming(self):
        block,_=self.fake().generate(self.item)
        fact=block['facts'][0]
        self.assertIsNone(fact['subject']);self.assertEqual(fact['sourceMedium'],'unknown')
        self.assertEqual(fact['evidence'][0]['quote'],'我明天联系供应方')
        self.assertIn('程序据编号填入',block['coverage'][0]['reason'])

    def test_bad_ids_and_quoted_due_text_are_rejected(self):
        self.raw['facts'][0]['evidenceIds']=['fake']
        with self.assertRaises(ValueError):self.fake().generate(self.item)
        self.raw['facts'][0]['evidenceIds']=['u0'];self.raw['facts'][0]['dueText']='2026-11-08'
        with self.assertRaises(ValueError):self.fake().generate(self.item)

    def test_truncated_output_rejected(self):
        c=self.fake();c.request=lambda *args:{'done':True,'done_reason':'length'}
        with self.assertRaises(ValueError):c.generate(self.item)

    def test_drafts_resume_without_importing_or_marking_semantics_verified(self):
        first=extract_local(self.store,self.req['requestId'],self.fake())
        c=self.fake();c.generate=lambda *args:(_ for _ in ()).throw(AssertionError('should reuse'))
        second=extract_local(self.store,self.req['requestId'],c)
        self.assertEqual(first['result'],second['result']);self.assertEqual(second['completed'],1)
        self.assertEqual(second['semanticAssessment'],'unreviewed')
        self.assertFalse((self.store/'results').exists());self.assertFalse((self.store/'completed').exists())

    def test_failure_retries_once_and_not_counted_complete(self):
        c=self.fake();calls=[]
        def fail(*args):calls.append(1);raise ValueError('invalid')
        c.generate=fail
        result=extract_local(self.store,self.req['requestId'],c)
        self.assertEqual(len(calls),2);self.assertEqual(result['failed'],1);self.assertEqual(result['completed'],0)
        self.assertEqual(json.loads(Path(result['result']).read_text())['results'],[])

    def test_unknown_keys_rejected_before_inference(self):
        with self.assertRaises(ValueError):extract_local(self.store,self.req['requestId'],self.fake(),['bogus'])

    def test_redirects_and_cloud_names_rejected(self):
        with self.assertRaises(ValueError):RejectRedirect().redirect_request(None,None,302,None,None,'https://example.com')
        with self.assertRaises(ValueError):LocalOllama('anything:cloud')
        with self.assertRaises(ValueError):LocalOllama('local',port=-1)

    def test_only_existing_model_and_no_proxy(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body={'models':[{'name':'test-local','size':100,'digest':'b'*64}]}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
            def do_POST(self):
                data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.assertEqual(self.path,'/api/chat');owner.assertEqual(data['model'],'test-local')
                owner.assertFalse(data['think']);owner.assertNotIn('/private/',json.dumps(data))
                body={'done':True,'done_reason':'stop','message':{'content':json.dumps(owner.raw)}}
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(body).encode())
            def log_message(self,*args):pass
        server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.dict(os.environ,{'HTTP_PROXY':'http://invalid:1','http_proxy':'http://invalid:1'}):
                c=LocalOllama('test-local',server.server_port);block,_=c.generate(self.item)
                self.assertEqual(len(block['facts']),1)
                with self.assertRaises(ValueError):LocalOllama('not-installed',server.server_port)
        finally:server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
