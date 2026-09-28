"""The producers' lane refresh, against a real clone that a connector mirror shares.

On 2026-09-28 uniclaude skipped its daily run: a cron-started Claude Code session
at 11:30 appended a line to the harness's brain-load-usage.md, the mirror would
not commit it until 11:45:37, and the producer at 11:45:01 refused to run on any
dirty file. The mirror's folders are the mirror's business; anything else dirty
still stops the run, and the producer now takes the mirror's publish lock so the
two never share an index.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_producer_boundary import load

PRODUCERS = ["spp3-brain-daily", "uniclaude-brain-daily"]


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout


class LaneRefresh(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.clones = {}
        for name in PRODUCERS:
            m = load(name)
            lane = m.BRANCH.split("/", 1)[1]
            bare, clone = tmp / f"{lane}.git", tmp / lane
            git(tmp, "init", "-q", "--bare", "-b", "main", str(bare))
            git(tmp, "clone", "-q", str(bare), str(clone))
            git(clone, "config", "user.email", "t@example.invalid")
            git(clone, "config", "user.name", "t")
            lane_dir = clone / "raw" / "workspaces" / lane
            (lane_dir / "claude-code").mkdir(parents=True)
            (lane_dir / "LANE.md").write_text(
                f"---\nlane: {lane}\nwrite: git-branch\nmirror_harnesses: [claude-code]\n---\n")
            (lane_dir / "method.md").write_text("method\n")
            (lane_dir / "claude-code" / "brain-load-usage.md").write_text("- one\n")
            git(clone, "add", "-A")
            git(clone, "commit", "-qm", "seed")
            git(clone, "push", "-q", "origin", "main")
            git(clone, "switch", "-qc", m.BRANCH)
            m.BRAIN, m.LOG = str(clone), str(tmp / f"{lane}.log")
            self.clones[name] = (m, lane_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def each(self):
        return [(name, m, lane_dir) for name, (m, lane_dir) in self.clones.items()]

    def test_a_clean_lane_refreshes(self):
        for name, m, _ in self.each():
            with self.subTest(producer=name):
                self.assertTrue(m.refresh_lane())

    def test_a_pending_usage_line_does_not_skip_the_day(self):
        for name, m, lane_dir in self.each():
            with self.subTest(producer=name):
                with open(lane_dir / "claude-code" / "brain-load-usage.md", "a") as f:
                    f.write("- a cron session started\n")
                (lane_dir / "claude-code" / "new-memory.md").write_text("untracked\n")
                self.assertTrue(m.refresh_lane())

    def test_a_dirty_file_outside_the_mirror_still_stops_the_run(self):
        for name, m, lane_dir in self.each():
            with self.subTest(producer=name):
                (lane_dir / "method.md").write_text("edited by hand\n")
                self.assertFalse(m.refresh_lane())
                self.assertIn("method.md", Path(m.LOG).read_text())

    def test_a_lane_that_declares_no_mirror_owns_nothing(self):
        for name, m, lane_dir in self.each():
            with self.subTest(producer=name):
                (lane_dir / "LANE.md").write_text("---\nwrite: git-branch\n---\n")
                git(m.BRAIN, "commit", "-qam", "no mirror")
                with open(lane_dir / "claude-code" / "brain-load-usage.md", "a") as f:
                    f.write("- pending\n")
                self.assertFalse(m.refresh_lane())

    def test_a_rename_out_of_the_mirror_folder_is_not_owned(self):
        for name, m, lane_dir in self.each():
            with self.subTest(producer=name):
                git(m.BRAIN, "mv", str(lane_dir / "claude-code" / "brain-load-usage.md"),
                    str(lane_dir / "usage.md"))
                self.assertFalse(m.refresh_lane())

    def test_git_says_why_the_exchange_is_unreachable(self):
        for name, m, _ in self.each():
            with self.subTest(producer=name):
                git(m.BRAIN, "remote", "set-url", "origin", "/nonexistent/exchange.git")
                self.assertFalse(m.refresh_lane())
                last = Path(m.LOG).read_text().splitlines()[-1]
                self.assertIn("cannot reach the exchange: ", last)
                self.assertIn("nonexistent", last)

    def test_the_publish_lock_is_the_mirrors_lock(self):
        for name, m, _ in self.each():
            with self.subTest(producer=name):
                self.assertEqual(m.publish_lock(),
                                 os.path.join(m.BRAIN, ".git", "sov-publish.lock"))
                self.assertTrue(m.take_publish_lock())
                self.assertTrue(os.path.isdir(m.publish_lock()))
                os.rmdir(m.publish_lock())

    def test_a_held_lock_waits_then_gives_up(self):
        for name, m, _ in self.each():
            with self.subTest(producer=name):
                os.mkdir(m.publish_lock())
                sleeps = []
                real, m.time.sleep = m.time.sleep, sleeps.append
                try:
                    self.assertFalse(m.take_publish_lock())
                finally:
                    m.time.sleep = real
                    os.rmdir(m.publish_lock())
                self.assertEqual(sum(sleeps), 60)

    def test_a_dead_runs_lock_is_reclaimed(self):
        for name, m, _ in self.each():
            with self.subTest(producer=name):
                os.mkdir(m.publish_lock())
                old = m.time.time() - 11 * 60
                os.utime(m.publish_lock(), (old, old))
                self.assertTrue(m.take_publish_lock())
                os.rmdir(m.publish_lock())


if __name__ == "__main__":
    unittest.main()
