import hashlib,json,sys
from pathlib import Path
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import test_pipeline
import test_hub
from soundlog_memory.voice_calibration import state,label,home,checksum,prepare,my_view
from soundlog_memory.voice_features import similarities,model_directory
from soundlog_memory.library_tools import library

class VoiceCalibrationTests(unittest.TestCase):
 def setUp(self):
  self.f=test_pipeline.PipelineTests();self.f.setUp();self.p=self.f.pipeline
  self.p.tick();r=self.p.ingest(self.f.envelope());self.p.publish(r['resultId'],self.f.screening(r['resultId']))
  expected=self.f.root/'产出/大模型分析素材/每日场景-v2'
  expected.parent.mkdir(parents=True,exist_ok=True);expected.symlink_to(self.p.scenes,target_is_directory=True)
  fs=library(self.p.delivery);self.samples=[]
  for i,f in enumerate(fs):
   e=f['evidence'][0];self.samples.append({'id':'sample-'+str(i)*24,'evidenceId':e['id'],'sourceSHA256':e['sourceSHA256'],'start':e['startOffsetSeconds'],'end':e['endOffsetSeconds'],'sourceFile':e['sourceFile']})
  self.batch={'schemaVersion':1,'samples':self.samples};self.batch['sha256']=checksum(self.batch)
  self.h=home(self.f.root);self.h.mkdir(parents=True);(self.h/'batch.json').write_text(json.dumps(self.batch))
 def tearDown(self):self.f.tearDown()
 def request(self,index=0,decision='self'):
  return {'batchSHA256':self.batch['sha256'],'sampleId':self.samples[index]['id'],'decision':decision}
 def test_explicit_labels_and_revoke_do_not_propagate(self):
  s=label(self.f.root,self.request());self.assertEqual(s['counts']['self'],1)
  self.assertEqual(len(s['labels']),1)
  self.assertEqual(my_view(self.f.root)['confirmedClips'],1)
  self.assertEqual(my_view(self.f.root)['records'][0]['attribution'],'user_confirmed_clip')
  self.assertFalse((self.f.root/'identity-scopes.json').exists())
  s=label(self.f.root,self.request(decision='revoke'));self.assertEqual(s['counts']['self'],0)
  self.assertEqual(len(json.loads((self.h/'labels.json').read_text())['history']),2)
 def test_version_and_source_mismatch_never_confirm(self):
  r=self.request();r['batchSHA256']='wrong'
  with self.assertRaises(ValueError):label(self.f.root,r)
  self.batch['samples'][0]['start']=99;self.batch['sha256']=checksum({k:v for k,v in self.batch.items() if k!='sha256'})
  (self.h/'batch.json').write_text(json.dumps(self.batch))
  with self.assertRaises(ValueError):label(self.f.root,self.request())
  self.assertFalse((self.h/'labels.json').exists())
 def test_cross_recording_scores_are_not_identity_confirmations(self):
  self.assertEqual(similarities(self.f.root)['status'],'awaiting_user_self_samples')
  label(self.f.root,self.request())
  (self.h/'features.json').write_text(json.dumps({s['id']:{'embedding':[1.0,0.0]} for s in self.samples}))
  result=similarities(self.f.root)
  self.assertIsNone(result['scores'][0]['score'])
  self.assertEqual(result['scores'][1]['score'],1.0)
  self.assertTrue(all(s['identity']=='unconfirmed' for s in result['scores']))
  self.assertEqual(result['confirmedIdentitiesCreated'],0)
 def test_missing_models_do_not_trigger_any_download_or_install(self):
  manifest=Path(__file__).resolve().parents[2]/'Sources/SoundlogCore/ModelManifests/speaker-diarization-coreml-v0.17.7.json'
  target=self.f.root/'Sources/SoundlogCore/ModelManifests'/manifest.name
  target.parent.mkdir(parents=True);target.write_bytes(manifest.read_bytes())
  with patch('soundlog_memory.voice_features.subprocess.run') as run:
   with patch.dict('os.environ',{'SOUNDLOG_FLUIDAUDIO_MODELS_DIR':str(self.f.root/'missing-models')}):
    with self.assertRaises(ValueError):model_directory(self.f.root)
   run.assert_not_called()

 def test_changed_labels_hide_stale_model_candidates(self):
  (self.h/'probe.json').write_text(json.dumps({'referenceBatchSHA256':self.batch['sha256'],'labelStateSHA256':'old','rows':[]}))
  result=my_view(self.f.root)
  self.assertTrue(result['matchingNeedsRefresh']);self.assertEqual(result['candidates'],[])

 def test_too_short_material_is_not_prepared_as_a_voice_sample(self):
  from unittest.mock import patch
  # The existing fixture consists entirely of two-second utterances.
  with patch('soundlog_memory.voice_calibration.evidence') as lookup:
   result=prepare(self.f.root)
  self.assertEqual(result['samples'],[]);lookup.assert_not_called()

class VoiceHTTPTests(unittest.TestCase):
 setUp=test_hub.HubTests.setUp
 tearDown=test_hub.HubTests.tearDown
 req=test_hub.HubTests.req
 def test_empty_voice_view_and_unapproved_or_wrong_version_label(self):
  self.assertEqual(self.req('/token/api/voice')[0],200)
  self.assertEqual(self.req('/token/api/me')[0],200)
  self.assertEqual(self.req('/token/api/voice/label','POST',{'decision':'self'},'https://evil.example')[0],404)
  self.assertEqual(self.req('/token/api/voice/label','POST',{'decision':'self','batchSHA256':'wrong'})[0],400)
  self.assertFalse((home(self.f.root)/'labels.json').exists())
