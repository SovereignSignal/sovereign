import json
import os
from pathlib import Path
import subprocess
import unittest
import tempfile
ROOT = Path(__file__).resolve().parents[1]
LANE = "---\nlane: %s\nwrite: %s\ngear: ask-first\nstatus: onboarded\n---\n"
def run(tmp, lanes, stub_exit=0):
    """Run bin/hub/intake against a fixture vault, with `sov` stubbed so no real import happens."""
    root = Path(tmp); vault = root / "vault"; tpl = root / "tpl" / "bin"
    tpl.mkdir(parents=True)
    for name, write in lanes.items():
        d = vault / "raw/workspaces" / name; d.mkdir(parents=True)
        (d / "LANE.md").write_text(LANE % (name, write))
    # The stub stands in for sov-contribute: it records the client it was asked to import.
    (tpl / "sov").write_text(
        '#!/bin/bash\nif [ "$1" = "hub" ]; then exit 0; fi\n'
        'echo "$*" >> "%s"\n' % (root / "calls.txt") +
        'echo \'{"state":"imported","received":7,"imported_current":7,"rejections":[],"head":"abc123def456"}\'\n'
        'exit %d\n' % stub_exit)
    (tpl / "sov").chmod(0o755)
    (tpl / "_sov-python.sh").write_text("#!/bin/bash\necho /usr/bin/python3\n")
    (tpl / "_sov-python.sh").chmod(0o755)
    env = dict(os.environ, SOVS_VAULT=str(vault), SOV_TEMPLATE=str(root / "tpl"))
    cp = subprocess.run(["/bin/bash", str(ROOT / "bin/hub/intake")], env=env, capture_output=True, text=True)
    calls = (root / "calls.txt").read_text().splitlines() if (root / "calls.txt").exists() else []
    return cp, calls
class HubIntake(unittest.TestCase):
    def test_it_imports_only_lanes_declared_write_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp, calls = run(tmp, {"alpha": "intake", "beta": "git-branch",
                                  "curator": "local", "gamma": "rsync"})
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual(len(calls), 1, calls)
            self.assertIn("--client alpha", calls[0])
            self.assertIn("--apply", calls[0])
            for other in ("beta", "curator", "gamma"):
                self.assertNotIn(other, " ".join(calls))
    def test_it_reports_what_each_import_did(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp, _ = run(tmp, {"alpha": "intake"})
            self.assertIn("alpha", cp.stdout)
            self.assertIn("received 7", cp.stdout)
            self.assertIn("abc123def456", cp.stdout)
    def test_a_failing_lane_exits_nonzero_so_the_receipt_is_honest(self):
        # A clean exit that imported nothing is the failure this job exists to end.
        with tempfile.TemporaryDirectory() as tmp:
            cp, _ = run(tmp, {"alpha": "intake"}, stub_exit=1)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("FAILED", cp.stderr)
    def test_no_intake_lane_is_stated_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            cp, calls = run(tmp, {"beta": "git-branch"})
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual(calls, [])
            self.assertIn("nothing to import", cp.stdout)
    def test_it_is_declared_in_the_manifest_with_a_schedule(self):
        import sys
        sys.path.insert(0, str(ROOT / "lib"))
        from sovereign_hub.manifest import JOBS
        job = JOBS["intake"]
        self.assertEqual(job["program"], "hub/intake")
        self.assertTrue((ROOT / "bin" / job["program"]).is_file())
        self.assertTrue(os.access(ROOT / "bin" / job["program"], os.X_OK))
        self.assertEqual(sum(k in job for k in ("interval_s", "hour", "hours")), 1)
if __name__ == "__main__":
    unittest.main()
