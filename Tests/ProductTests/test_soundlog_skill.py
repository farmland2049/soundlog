"""Check project routing from a discoverable skill without starting audio jobs."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT/'skills/soundlog/scripts/locate_project.py'


class SoundlogSkillTests(unittest.TestCase):
 def run_locator(self, helper=HELPER, args=(), env=None, cwd=None):
  environ=dict(os.environ);environ.pop('SOUNDLOG_ROOT',None);environ.update(env or {})
  return subprocess.run([sys.executable,str(helper),*map(str,args)],cwd=cwd,env=environ,capture_output=True,text=True)

 def test_installed_symlink_locates_checkout_from_unrelated_directory(self):
  with tempfile.TemporaryDirectory(prefix='skill routing ') as temporary:
   folder=Path(temporary);link=folder/'soundlog';link.symlink_to(ROOT/'skills/soundlog',target_is_directory=True)
   r=self.run_locator(link/'scripts/locate_project.py',cwd=folder)
   self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(Path(r.stdout.strip()),ROOT)
   self.assertFalse((folder/'记忆库').exists())

 def test_explicit_wrong_root_never_falls_back_to_real_recordings(self):
  with tempfile.TemporaryDirectory() as temporary:
   r=self.run_locator(args=['--root',temporary],cwd=ROOT)
   self.assertEqual(r.returncode,2);self.assertEqual(r.stdout,'')
   self.assertFalse(list(Path(temporary).iterdir()))

 def test_environment_override_and_explicit_precedence_with_spaces(self):
  with tempfile.TemporaryDirectory(prefix='Soundlog checkout ') as temporary:
   folder=Path(temporary)
   # A clean checkout may not contain this machine's ignored AGENTS.md.
   markers=['README.md','需求说明.md','PROJECT_STATUS.md','scripts/pipeline-agent.md','scripts/soundlog_pipeline.py','scripts/soundlog_memory/pipeline.py']
   for name in markers:
    p=folder/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('synthetic marker')
   r=self.run_locator(env={'SOUNDLOG_ROOT':str(folder)})
   self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(Path(r.stdout.strip()),folder.resolve())
   r=self.run_locator(args=['--root',ROOT],env={'SOUNDLOG_ROOT':str(folder/'missing')})
   self.assertEqual(r.returncode,0,r.stderr);self.assertEqual(Path(r.stdout.strip()),ROOT)
