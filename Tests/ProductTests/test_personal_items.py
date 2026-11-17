import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory import personal_items as personal
from soundlog_memory.voice_calibration import home as voice_home
from soundlog_memory.store import write_json


class PersonalItemsTests(unittest.TestCase):
 def setUp(self):
  self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
  self.rows = {
   'self': {'id': 'self', 'text': '我回头发给你。', 'sourceSHA256': 'audio', 'sourceFile': 'audio.mp3', 'start': '2026-11-12T10:00:10', 'startOffsetSeconds': 10, 'endOffsetSeconds': 12},
   'other': {'id': 'other', 'text': '你能发给我吗？', 'sourceSHA256': 'audio', 'sourceFile': 'audio.mp3', 'start': '2026-11-12T10:00:05', 'startOffsetSeconds': 5, 'endOffsetSeconds': 8}}
  self.labels = {'labels': {k: {'evidenceId': k, 'sourceSHA256': 'audio', 'start': r['startOffsetSeconds'], 'end': r['endOffsetSeconds'], 'decision': k} for k,r in self.rows.items()}}
  self.save_labels()
  self.lookup = patch.object(personal, 'evidence', side_effect=lambda root,key: copy.deepcopy(self.rows[key])); self.lookup.start()
  self.item = {'id': 'send-document', 'kind': 'commitment', 'summary': '我当时承诺发送资料', 'reason': '本人明确作出未来发送承诺；尚无完成证据', 'selfEvidenceId': 'self', 'evidence': [{'id': 'self', 'quote': '我回头发给你。'}]}
 def tearDown(self): self.lookup.stop(); self.temp.cleanup()
 def save_labels(self): write_json(voice_home(self.root)/'labels.json', self.labels)
 def spec(self): return {'schemaVersion': 1, 'reviewer': 'synthetic test reviewer', 'decisions': [copy.deepcopy(self.item)]}
 def test_published_commitment_remains_historical_and_repeat_is_idempotent(self):
  a=personal.publish(self.root,self.spec()); b=personal.publish(self.root,self.spec())
  self.assertEqual(a['version'],b['version']); self.assertEqual(a['counts']['commitment'],1)
  self.assertEqual(a['items'][0]['currentState'],'unknown');self.assertIsNone(a['items'][0]['due'])
  self.assertEqual(len(list(personal.home(self.root).glob('personal-*'))),1)
 def test_revocation_hides_item_without_destroying_history(self):
  a=personal.publish(self.root,self.spec());self.labels['labels'].pop('self');self.save_labels()
  b=personal.view(self.root);self.assertEqual(b['items'],[]);self.assertEqual(len(b['stale']),1)
  self.assertTrue((personal.home(self.root)/a['version']/'review.json').exists())
 def test_similarity_or_other_voice_cannot_be_claimed_as_self(self):
  self.labels['labels']['self']['decision']='possible_self';self.save_labels()
  with self.assertRaises(ValueError):personal.publish(self.root,self.spec())
  self.assertFalse((personal.home(self.root)/'latest.json').exists())
 def test_fabricated_quote_and_duplicate_id_are_rejected(self):
  s=self.spec();s['decisions'][0]['evidence'][0]['quote']='我已经发了'
  with self.assertRaises(ValueError):personal.publish(self.root,s)
  s=self.spec();s['decisions']*=2
  with self.assertRaises(ValueError):personal.publish(self.root,s)
 def test_request_needs_reviewed_recipient_relationship_and_continuous_reply(self):
  s=self.spec();i=s['decisions'][0];i['kind']='request_to_me';i['requestEvidenceId']='other';i['evidence'].append({'id':'other','quote':self.rows['other']['text']})
  with self.assertRaises(ValueError):personal.publish(self.root,s)
  i['recipientProof']={'reason':'紧接请求，本人回应答应发送；由审阅者判断收件关系','quote':self.rows['self']['text']}
  a=personal.publish(self.root,s);self.assertEqual(a['counts']['request_to_me'],1)
  self.rows['self']['startOffsetSeconds']=200
  self.labels['labels']['self']['start']=200;self.save_labels()
  with self.assertRaises(ValueError):personal.publish(self.root,s)
 def test_tampered_output_and_changed_original_fail_closed(self):
  a=personal.publish(self.root,self.spec());self.rows['self']['text']='不同的原话'
  with self.assertRaises(ValueError):personal.view(self.root)
  self.rows['self']['text']='我回头发给你。'
  (personal.home(self.root)/a['version']/'personal.md').write_text('changed')
  with self.assertRaises(ValueError):personal.view(self.root)
 def test_ignored_clip_is_reviewed_but_never_becomes_a_task(self):
  s=self.spec();s['decisions'][0]['kind']='ignore'
  r=personal.publish(self.root,s);self.assertEqual(r['items'],[]);self.assertEqual(len(r['ignored']),1)


class PersonalHTTPTests(unittest.TestCase):
 def test_empty_personal_endpoint_is_read_only(self):
  from test_hub import HubTests
  f=HubTests();f.setUp()
  try:
   status,body=f.req('/token/api/personal');self.assertEqual(status,200)
   self.assertEqual(json.loads(body)['items'],[])
   self.assertEqual(f.req('/token/api/personal','POST',{})[0],404)
   self.assertEqual(f.req('/token/api/personal',origin='https://evil.example')[0],404)
  finally:f.tearDown()
