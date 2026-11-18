import json,os,sqlite3,sys,tempfile,time,unittest
from pathlib import Path
from datetime import datetime,timezone,date
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from soundlog_memory import audio_sources as src

class AudioSourceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.root=self.base/'project';self.root.mkdir();self.external=self.base/'recorder';self.external.mkdir();self.memo=self.base/'memos';self.memo.mkdir()
  src.save_settings(self.root,{'voiceMemos':False,'directories':[str(self.external)]})
 def tearDown(self):self.tmp.cleanup()
 def audio(self,folder,name,content=b'audio',stable=True):
  p=folder/name;p.write_bytes(content)
  if stable:os.utime(p,(time.time()-120,time.time()-120))
  return p
 def test_normalizes_copy_preserves_original_and_deduplicates_after_archive(self):
  p=self.audio(self.external,'20261117 100420-title.m4a');before=p.read_bytes()
  r=src.collect(self.root,memo_directory=self.memo);self.assertEqual(r['copied'],1)
  target=self.root/'录音/待处理/20261117100420.m4a';self.assertEqual(target.read_bytes(),before);self.assertEqual(p.read_bytes(),before)
  archive=self.root/'录音/已归档';archive.mkdir();target.rename(archive/target.name)
  r=src.collect(self.root,memo_directory=self.memo);self.assertEqual(r['copied'],0);self.assertEqual(r['duplicates'],1)
 def test_collision_keeps_both_originals_and_does_not_overwrite(self):
  a=self.audio(self.external,'20261117100420.mp3',b'one')
  src.collect(self.root,memo_directory=self.memo);a.write_bytes(b'two');os.utime(a,(time.time()-120,time.time()-120))
  r=src.collect(self.root,memo_directory=self.memo);self.assertEqual(r['skipped'],1);self.assertEqual((self.root/'录音/待处理'/a.name).read_bytes(),b'one');self.assertEqual(a.read_bytes(),b'two')
 def test_unstable_symlink_and_unknown_time_are_skipped(self):
  self.audio(self.external,'20261117100420.mp3',stable=False)
  self.audio(self.external,'not-a-clock.mp3');target=self.audio(self.base,'20261117120420.mp3');(self.external/target.name).symlink_to(target)
  r=src.collect(self.root,memo_directory=self.memo);self.assertEqual(r['copied'],0);self.assertEqual(r['skipped'],3)
 def test_missing_source_does_not_block_other_source(self):
  src.save_settings(self.root,{'voiceMemos':True,'directories':[str(self.external),str(self.base/'missing')]})
  self.audio(self.external,'20261117100420.mp3')
  r=src.collect(self.root,memo_directory=self.base/'missing-memos');self.assertEqual(r['copied'],1);self.assertEqual(r['skipped'],2)
 def test_voice_metadata_filters_shanghai_day_and_checks_filename(self):
  c=sqlite3.connect(self.memo/'CloudRecordings.db');c.execute('create table ZCLOUDRECORDING (ZDATE real,ZPATH text)')
  for when,name in [('2026-11-17T02:04:20+00:00','20261117 100420.m4a'),('2026-11-16T02:04:20+00:00','20261116 100420.m4a'),('2026-11-17T03:04:20+00:00','20261117 120420.m4a')]:
   n=(datetime.fromisoformat(when)-datetime(2001,1,1,tzinfo=timezone.utc)).total_seconds();c.execute('insert into ZCLOUDRECORDING values (?,?)',(n,name));self.audio(self.memo,name)
  c.commit();c.close();src.save_settings(self.root,{'voiceMemos':True,'directories':[]})
  r=src.collect(self.root,memo_directory=self.memo,today=date(2026,11,17));self.assertEqual(r['copied'],1);self.assertEqual(r['skipped'],1);self.assertEqual(r['outcomes'][0]['name'],'20261117100420.m4a')
 def test_two_sources_identical_content_copied_once(self):
  second=self.base/'second';second.mkdir();src.save_settings(self.root,{'voiceMemos':False,'directories':[str(self.external),str(second)]})
  self.audio(self.external,'20261117100420.mp3');self.audio(second,'20261117110420.mp3')
  r=src.collect(self.root);self.assertEqual(r['copied'],1);self.assertEqual(r['duplicates'],1)
 def test_source_changes_during_copy_leaves_no_partial_input(self):
  p=self.audio(self.external,'20261117100420.mp3')
  original=Path.stat;count=[0]
  def stat(path,*args,**kwargs):
   result=original(path,*args,**kwargs)
   if path==p:
    count[0]+=1
    if count[0]==3:p.write_bytes(b'changed');return original(path,*args,**kwargs)
   return result
  with patch.object(Path,'stat',stat):
   r=src.collect(self.root)
  self.assertEqual(r['copied'],0);self.assertFalse(list((self.root/'录音/待处理').glob('*.mp3')))
 def test_settings_reject_project_and_relative_paths(self):
  for p in ['relative',str(self.root),str(self.root/'录音/待处理'),'/']:
   with self.assertRaises(ValueError):src.save_settings(self.root,{'voiceMemos':True,'directories':[p]})
