"""A producer box: the mirror writes under the box's git lane and pushes the lane branch.

Builds a bare "exchange" repo, clones it as the box's scoped archive, puts the box on its
lane branch with a LANE.md that says write: git-branch, points HOME/BRAIN_ROOT/BRAIN_LANE
at it, runs the Claude Code mirror, and checks the commit arrived on the bare repo's
lane branch under raw/workspaces/<lane>/claude-code/.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "connectors" / "harness" / "claude-code" / "mirror.sh"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class GitLaneMirror(unittest.TestCase):
    def test_mirror_commits_and_pushes_on_the_lane_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bare = tmp / "exchange.git"; subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
            seed = tmp / "seed"; subprocess.run(["git", "clone", "-q", str(bare), str(seed)], check=True)
            git("config", "user.email", "t@t", cwd=seed); git("config", "user.name", "t", cwd=seed)
            (seed / "knowledge").mkdir(); (seed / "knowledge" / "x.md").write_text("x\n")
            lane = seed / "raw" / "workspaces" / "testbox"; lane.mkdir(parents=True)
            (lane / "LANE.md").write_text("---\nlane: testbox\nwrite: git-branch\nmirror_harnesses: [claude-code]\nread: git\nstatus: onboarded\n---\n")
            git("add", "-A", cwd=seed); git("commit", "-q", "-m", "seed", cwd=seed); git("push", "-q", "origin", "main", cwd=seed)
            archive = tmp / "archive"; subprocess.run(["git", "clone", "-q", str(bare), str(archive)], check=True)
            git("config", "user.email", "box@t", cwd=archive); git("config", "user.name", "box", cwd=archive)
            git("checkout", "-q", "-b", "lane/testbox", cwd=archive)
            home = tmp / "home"; home.mkdir()
            (home / ".brain-root").write_text(str(archive)); (home / ".brain-lane").write_text("testbox"); (home / ".brain-host").write_text("testbox")
            mem = home / ".claude" / "projects" / "-home-box-proj" / "memory"; mem.mkdir(parents=True)
            (mem / "MEMORY.md").write_text("# remembered\n")
            env = dict(os.environ); env.update({"HOME": str(home)})
            env.pop("BRAIN_STAGE", None); env.pop("BRAIN_ROOT", None); env.pop("BRAIN_LANE", None); env.pop("BRAIN_HOST", None)
            res = subprocess.run(["/bin/bash", str(MIRROR)], capture_output=True, text=True, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            dest = archive / "raw" / "workspaces" / "testbox" / "claude-code"
            self.assertTrue((dest / "memory" / "-home-box-proj" / "MEMORY.md").exists(), res.stderr)
            self.assertTrue((dest / "MANIFEST.md").exists())
            log = git("log", "--oneline", "lane/testbox", cwd=bare)
            self.assertIn("capture: Claude Code memory mirror", log)
            files = git("ls-tree", "-r", "--name-only", "lane/testbox", cwd=bare)
            self.assertIn("raw/workspaces/testbox/claude-code/memory/-home-box-proj/MEMORY.md", files)
            self.assertNotIn("raw/tools", files)
            # the read wire's receipt goes inside the lane as well, never under raw/tools/
            hook = ROOT / "connectors" / "harness" / "claude-code" / "session-start.py"
            (archive / "knowledge" / "me.md").write_text("---\ntype: entity\nsource: o\ncreated: 2026-01-01\n---\n# Me\n")
            env["BRAIN_CORE"] = "me"
            r = subprocess.run([sys.executable, str(hook)], input='{"cwd": "%s", "session_id": "s1", "source": "startup"}' % archive,
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue((dest / "brain-load-usage.md").exists(), r.stderr)
            self.assertFalse((archive / "raw" / "tools").exists())


if __name__ == "__main__":
    unittest.main()
