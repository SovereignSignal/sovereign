"""sov-capture: the staging root, the sessions folder and the allow-listed --meta labels.

A session capture arrives with labels only this tool may write, in the spec's order, each
checked by its own pattern. On a machine with a stage the tool lane is written there, the
same order every mirror wire uses; a workspace lane always stays in the vault. The fence
holds on whichever root was chosen: a --subdir other than sessions, a linked sessions/
folder, or a linked lane is refused with exit 64 and nothing is written.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "bin/sov-capture"
LANE = "claude-code-testhost"

try:
    import yaml
except ImportError:  # PyYAML is a test-only dependency (docs/release-checks.md)
    yaml = None

META = [("session_title", "Fix the [staging] relay: retry"), ("project", "garden-planner"),
        ("span", "2026-10-21T14:02Z..2026-10-21T15:40Z"), ("distiller", "ollama/qwen3.8:27b"),
        ("prompt", "session-distill/v1"), ("kind", "decision"), ("confidence", "med"),
        ("evidence", "T4,T9")]
ORDER = ["type", "source", "created", "title", "origin", "session_title", "project", "span",
         "distiller", "prompt", "kind", "confidence", "evidence"]


def meta_args(pairs):
    out = []
    for k, v in pairs:
        out += ["--meta", "%s=%s" % (k, v)]
    return out


class CaptureMeta(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home, self.vault, self.stage = base / "home", base / "vault", base / "stage"
        self.home.mkdir()
        (self.vault / "knowledge").mkdir(parents=True)
        (self.vault / "raw/tools").mkdir(parents=True)
        self.stage.mkdir()

    def run_capture(self, *args, stage=True, extra_env=None, body="A decision worth keeping.", slug="s1"):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "BRAIN_ROOT": str(self.vault),
               "PYTHONDONTWRITEBYTECODE": "1"}
        if stage:
            env["BRAIN_STAGE"] = str(self.stage)
        env.update(extra_env or {})
        return subprocess.run([sys.executable, str(CAPTURE), slug, *args, "--from", "-"], input=body,
                              capture_output=True, text=True, timeout=60, env=env)

    def session(self, *extra, lane=LANE, **kw):
        return self.run_capture("--lane", lane, "--subdir", "sessions", "--title", "Tests run against the staging copy",
                                "--origin", "claude-code-session:0b9e-synthetic", *meta_args(META), *extra, **kw)

    def files(self, root):
        return sorted(p for p in root.rglob("*") if p.is_file())

    def assert_refused(self, r):
        self.assertEqual(r.returncode, 64, r.stdout + r.stderr)
        self.assertEqual(self.files(self.stage), [])
        self.assertEqual(self.files(self.vault), [])

    def test_meta_written_in_order(self):
        r = self.session()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.stage / "raw/tools" / LANE / "sessions/s1.md"
        self.assertEqual(self.files(self.stage), [out])
        self.assertEqual(self.files(self.vault), [], "the vault is untouched when a stage is set")
        self.assertIn("captured: raw/tools/%s/sessions/s1.md" % LANE, r.stdout)
        fm = out.read_text().split("---\n")[1]
        self.assertEqual([line.split(":", 1)[0] for line in fm.splitlines()], ORDER)
        self.assertIn("\nsource: %s\n" % LANE, fm)
        self.assertIn("\nspan: 2026-10-21T14:02Z..2026-10-21T15:40Z\n", fm)
        self.assertIn("\ndistiller: ollama/qwen3.8:27b\n", fm)
        self.assertIn("\nprompt: session-distill/v1\n", fm)
        self.assertIn("\nkind: decision\n", fm)
        self.assertIn("\nconfidence: med\n", fm)
        self.assertTrue(fm.endswith("\nevidence: [T4, T9]\n"), fm)
        if yaml is not None:
            data = yaml.safe_load(fm)
            self.assertEqual(data["evidence"], ["T4", "T9"])
            for k, v in META[:-1]:
                self.assertEqual(data[k], v, k)
            self.assertEqual(data["origin"], "claude-code-session:0b9e-synthetic")

    def test_bad_meta_refused(self):
        cases = [
            ["--meta", "owner=me"],                       # not an allowed key
            ["--meta", "kind=decision"],                  # a key given twice, even with the same value
            ["--meta", "nokey"],                          # no "="
        ]
        for extra in cases:
            self.assert_refused(self.session(*extra))
        bad_values = [("kind", "opinion"), ("confidence", "certain"), ("span", "2026-10-21..2026-10-22"),
                      ("distiller", "Ollama/qwen"), ("prompt", "session-distill/1"), ("evidence", "T4, T9"),
                      ("evidence", "[T4]"), ("project", "two\nlines"), ("session_title", "x" * 201),
                      ("project", "")]
        for key, value in bad_values:
            pairs = [(k, value if k == key else v) for k, v in META]
            r = self.run_capture("--lane", LANE, "--subdir", "sessions", *meta_args(pairs))
            self.assertEqual(r.returncode, 64, "%s=%r was accepted" % (key, value))
            self.assertEqual(self.files(self.stage) + self.files(self.vault), [])

    def test_subdir_other_than_sessions_refused(self):
        for sub in ("../x", "memory", "sessions/..", "/tmp", ""):
            self.assert_refused(self.run_capture("--lane", LANE, "--subdir", sub))

    def test_linked_sessions_folder_refused(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        lane = self.stage / "raw/tools" / LANE
        lane.mkdir(parents=True)
        (lane / "sessions").symlink_to(outside)
        r = self.session()
        self.assertEqual(r.returncode, 64, r.stderr)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(self.files(self.stage), [])

    def test_linked_lane_in_stage_refused(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.stage / "raw/tools").mkdir(parents=True)
        (self.stage / "raw/tools" / LANE).symlink_to(outside)
        r = self.session()
        self.assertEqual(r.returncode, 64, r.stderr)
        self.assertEqual(list(outside.iterdir()), [])

    def test_workspace_lane_ignores_the_stage(self):
        ws = self.vault / "raw/workspaces" / LANE
        ws.mkdir(parents=True)
        r = self.session()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.files(self.stage), [])
        self.assertTrue((ws / "sessions/s1.md").is_file())

    def test_stage_order_matches_sov_dest(self):
        other = Path(self.tmp.name) / "other-stage"
        other.mkdir()
        (self.home / ".vault-staging").mkdir()
        # BRAIN_STAGE beats SOVEREIGN_STAGE
        r = self.session(extra_env={"SOVEREIGN_STAGE": str(other)}, slug="a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.stage / "raw/tools" / LANE / "sessions/a.md").is_file())
        # SOVEREIGN_STAGE beats ~/.vault-staging
        r = self.session(stage=False, extra_env={"SOVEREIGN_STAGE": str(other)}, slug="b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((other / "raw/tools" / LANE / "sessions/b.md").is_file())
        # ~/.vault-staging when it is a directory
        r = self.session(stage=False, slug="c")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / ".vault-staging/raw/tools" / LANE / "sessions/c.md").is_file())
        self.assertEqual(self.files(self.vault), [])

    def test_no_stage_writes_the_vault(self):
        r = self.session(stage=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.files(self.vault), [self.vault / "raw/tools" / LANE / "sessions/s1.md"])

    def test_dry_writes_nothing(self):
        r = self.session("--dry")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("evidence: [T4, T9]", r.stdout)
        self.assertEqual(self.files(self.stage) + self.files(self.vault), [])


if __name__ == "__main__":
    unittest.main()
