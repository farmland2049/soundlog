import http.client,json,sys,threading,unittest
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import soundlog_hub
import test_pipeline

class HubTests(unittest.TestCase):
 def setUp(self):
  self.f=test_pipeline.PipelineTests();self.f.setUp();self.p=self.f.pipeline
  self.p.tick();r=self.p.ingest(self.f.envelope());self.p.publish(r['resultId'],self.f.screening(r['resultId']))
  self.server=ThreadingHTTPServer(('127.0.0.1',0),soundlog_hub.handler(self.f.root,'token'))
  self.t=threading.Thread(target=self.server.serve_forever,daemon=True);self.t.start()
 def tearDown(self):self.server.shutdown();self.server.server_close();self.t.join();self.f.tearDown()
 def req(self,path,method='GET',data=None,origin=None):
  c=http.client.HTTPConnection('127.0.0.1',self.server.server_port);headers={}
  if origin:headers['Origin']=origin
  body=json.dumps(data).encode() if data is not None else None
  if body:headers['Content-Type']='application/json'
  c.request(method,path,body=body,headers=headers);r=c.getresponse();d=r.read();status=r.status;c.close();return status,d
 def test_question_queue_and_origin_scope(self):
  status,body=self.req('/token/api/questions','POST',{'question':'充电约定？','queries':['充电']});self.assertEqual(status,201)
  status,body=self.req('/token/api/questions');self.assertEqual(json.loads(body)[0]['state'],'awaiting_agent')
  self.assertEqual(self.req('/token/api/questions','POST',{'question':'x','queries':['x']},'https://evil.example')[0],404)
  self.assertEqual(self.req('/wrong/')[0],404)
 def test_browse_and_readable_markdown_links(self):
  self.assertEqual(self.req('/token/api/overview')[0],200)
  from soundlog_memory.period_review import publish_period_review
  review=publish_period_review(self.p.delivery,'2026-11-07','2026-11-09')
  overview=json.loads(self.req('/token/api/overview')[1])
  self.assertIn('reviews/README.md',[r['path'] for r in overview['links']])
  self.assertEqual(self.req('/token/files/reviews/'+review['id']+'/README.md')[0],200)
  status,body=self.req('/token/files/README.md');self.assertEqual(status,200);self.assertIn(b'<a href=',body)
  self.assertNotEqual(self.req('/token/files/%2e%2e/%2e%2e/README.md')[0],200)
 def test_renderer_escapes_untrusted_html(self):
  s=soundlog_hub.markdown_html('<script>evil</script>\n[x](javascript:bad)\n[ok](sources.md#ev-a)')
  self.assertNotIn('<script>',s);self.assertNotIn('href="javascript:',s);self.assertIn('href="sources.md#ev-a"',s)
