"""A backup retry must keep failed remote pushes visible even without new files."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class AutocommitRetry(unittest.TestCase):
    def test_no_new_files_does_not_turn_a_failed_push_into_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);vault=base/'vault';vault.mkdir();(vault/'.git').mkdir()
            stub=base/'bin';stub.mkdir()
            git=stub/'git';git.write_text('''#!/bin/sh
case "$1 $2" in
  'rev-parse --git-dir') echo .git;;
  'rev-parse --abbrev-ref') echo main;;
  'push -q') exit 7;;
esac
exit 0
''');git.chmod(0o755)
            pgrep=stub/'pgrep';pgrep.write_text('#!/bin/sh\nexit 1\n');pgrep.chmod(0o755)
            result=subprocess.run(['/bin/bash',str(ROOT/'bin/hub/autocommit')],capture_output=True,text=True,
                env=dict(os.environ,PATH=str(stub)+':/usr/bin:/bin',SOVS_VAULT=str(vault),VAULT=str(vault),SOV_STATE_DIR=str(base/'state'),SOV_HUB_REMOTES='fixture'),timeout=10)
            self.assertEqual(result.returncode,1,result.stdout+result.stderr)
            self.assertIn('push fixture failed',result.stderr)
            self.assertFalse((base/'state/hub/autocommit.lock').exists())


if __name__=='__main__':unittest.main()
