import hashlib
import http.client
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.audio_access import byte_range,open_verified,interval
import test_hub

class AudioTests(unittest.TestCase):
 def test_ranges_reject_invalid_and_handle_seeking(self):
  self.assertEqual(byte_range('bytes=5-',10),(5,9,206))
  self.assertEqual(byte_range('bytes=-3',10),(7,9,206))
  self.assertEqual(byte_range('bytes=0-99',10),(0,9,206))
  self.assertEqual(byte_range(None,10),(0,9,200))
  for value in ['bytes=10-','bytes=8-2','bytes=-0','bytes=0-1,3-4','bytes=-']:
   with self.assertRaises(ValueError):byte_range(value,10)
  with self.assertRaises(ValueError):interval({'startOffsetSeconds':float('nan'),'endOffsetSeconds':4})
 def test_unchanged_source_required_and_symlink_archive_rejected(self):
  import tempfile
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);archive=root/'录音/已归档';archive.mkdir(parents=True);p=archive/'sample.mp3';p.write_bytes(b'original')
   row={'sourceFile':'sample.mp3','sourceSHA256':hashlib.sha256(b'original').hexdigest()}
   with patch('soundlog_memory.audio_access.evidence',return_value=row):
    f,_,size=open_verified(root,'ev-'+'a'*24);self.assertEqual(f.read(),b'original');f.close();self.assertEqual(size,8)
    p.write_bytes(b'changed!')
    with self.assertRaises(ValueError):open_verified(root,'ev-'+'a'*24)
    p.unlink();p.symlink_to(root/'outside.mp3');(root/'outside.mp3').write_bytes(b'original')
    with self.assertRaises(ValueError):open_verified(root,'ev-'+'a'*24)

class AudioHTTPTests(unittest.TestCase):
 setUp=test_hub.HubTests.setUp
 tearDown=test_hub.HubTests.tearDown
 req=test_hub.HubTests.req
 def test_audio_is_evidence_scoped_and_byte_range_streamed(self):
  day=json.loads((self.p.delivery/'catalog.json').read_text())['days']['2026-11-07']
  f=json.loads((self.p.delivery/day/'search.json').read_text())['facts'][0];e=f['evidence'][0]
  archive=self.f.root/'录音/已归档';archive.mkdir(parents=True)
  # Existing synthetic fixture provenance is replaced only in this isolated test.
  payload=b'0123456789'
  row={**e,'sourceFile':'sample.mp3','sourceSHA256':hashlib.sha256(payload).hexdigest()}
  (archive/'sample.mp3').write_bytes(payload)
  with patch('soundlog_memory.audio_access.evidence',return_value=row):
   c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
   c.request('GET','/token/audio/'+e['id'],headers={'Range':'bytes=2-5'})
   r=c.getresponse();self.assertEqual(r.status,206);self.assertEqual(r.getheader('Content-Range'),'bytes 2-5/10');self.assertEqual(r.read(),b'2345')
   c.request('HEAD','/token/audio/'+e['id']);r=c.getresponse();self.assertEqual(r.status,200);self.assertEqual(r.read(),b'')
   c.request('GET','/token/audio/'+e['id'],headers={'Range':'bytes=20-'})
   r=c.getresponse();self.assertEqual(r.status,416);r.read();c.close()
  self.assertNotEqual(self.req('/token/audio/../../etc/passwd')[0],200)
