import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class CaptureBoundary(unittest.TestCase):
 def test_cli_sanitizes_repeated_capture_and_rejects_escape(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);vault=root/'vault';home=root/'home';home.mkdir();vault.mkdir()
   env=dict(os.environ,HOME=str(home),BRAIN_ROOT=str(vault),BRAIN_LANE='fixture')
   token='gh'+'p_'+'A'*35
   def capture(*args):return subprocess.run([sys.executable,str(ROOT/'bin/brain-capture'),'note',*args],env=env,capture_output=True,text=True)
   for _ in range(3):self.assertEqual(capture('--note',token).returncode,0)
   files=list(vault.rglob('*.md'));self.assertEqual(len(files),3)
   self.assertTrue(all(token not in p.read_text() for p in files))
   self.assertNotEqual(capture('--lane','../../knowledge','--note','escape').returncode,0)
 def test_symlink_destination_preserves_external_directory(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);lane=root/'vault/raw/workspaces/fixture';lane.parent.mkdir(parents=True);external=root/'outside';external.mkdir();lane.symlink_to(external)
   env=dict(os.environ,HOME=str(root),BRAIN_ROOT=str(root/'vault'),BRAIN_LANE='fixture')
   r=subprocess.run([sys.executable,str(ROOT/'bin/brain-capture'),'note','--note','body'],env=env,capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0);self.assertEqual(list(external.iterdir()),[])
if __name__=='__main__':unittest.main()
