import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "bin/sov-signing-identity"
def run(*args, env=None):
    cp = subprocess.run([sys.executable, str(CMD), *args], capture_output=True, text=True,
                        env=dict(os.environ, **(env or {})))
    try:
        return cp.returncode, json.loads(cp.stdout or "{}"), cp.stderr
    except json.JSONDecodeError:
        return cp.returncode, {"raw": cp.stdout}, cp.stderr
class SigningIdentity(unittest.TestCase):
    def test_preview_writes_nothing_and_explains_why_it_matters(self):
        code, out, _ = run("--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["state"], "preview")
        self.assertEqual(out["identity"], "Sovereign Local Signing")
        # A person must be told what it costs and what changes, not just that it is missing.
        self.assertIn("login password once", out["effects"])
        self.assertIn("no existing certificate is touched", out["effects"])
        self.assertIn("build.sh finds the identity", out["afterwards"])
    def test_it_names_the_consequence_of_not_having_one(self):
        _, out, _ = run("--json")
        summary = out["summary"]
        if out["present"]:
            self.assertIn("survives a rebuild", summary)
        else:
            # The symptom the owner actually sees, in his words, not "ad-hoc signature".
            self.assertIn("asks for Documents access again", summary)
    def test_the_human_output_leads_with_the_consequence(self):
        cp = subprocess.run([sys.executable, str(CMD)], capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        first = cp.stdout.strip().splitlines()[0]
        self.assertNotIn("ad-hoc", first.lower().split("so")[0],
                         "the first clause should be the consequence, not the mechanism")
        self.assertIn("--apply", cp.stdout)
    def test_it_is_reachable_through_the_front_door(self):
        cp = subprocess.run(["/bin/bash", str(ROOT / "bin/sov")], capture_output=True, text=True)
        self.assertIn("sov signing-identity", cp.stdout)
    def test_the_build_script_points_at_it_rather_than_degrading_in_silence(self):
        build = (ROOT / "apps/console/build.sh").read_text()
        self.assertIn("sov signing-identity --apply", build)
        self.assertIn("re-ask for permissions", build)
if __name__ == "__main__":
    unittest.main()
