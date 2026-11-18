import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory.pipeline import Pipeline
from soundlog_memory.processing_history import history,REQUIRED

class HistoryTests(unittest.TestCase):
 def test_history_reports_audio_processing_without_publication_status(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Pipeline(tmp);d=p.root/'产出/运行历史/test/hash-file';d.mkdir(parents=True)
   doc={'sourcePath':'/source/20261117100420.m4a','sourceSHA256':'abc','modules':{k:{'state':'completed'} for k in REQUIRED}}
   (d/'processing-status.json').write_text(json.dumps(doc));row=history(p)['files'][0]
   self.assertEqual(row['audioState'],'completed');self.assertNotIn('contentState',row)
   doc['modules']['runManifest']={'state':'failed','error':'rangeOutsideAudio'};(d/'processing-status.json').write_text(json.dumps(doc))
   self.assertEqual(history(p)['files'][0]['audioState'],'failed')
 def test_unprocessed_inbox_files_are_visible(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Pipeline(tmp);d=p.root/'录音/待处理';d.mkdir(parents=True);(d/'20261117100420.m4a').write_bytes(b'test')
   row=history(p)['files'][0];self.assertEqual(row['audioState'],'waiting');self.assertEqual(row['recordedTime'],'2026-11-17 10:04:20')
