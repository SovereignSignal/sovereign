"""A producer box that stops running a tool's mirror leaves the mirror's folder in its lane
(raw is provenance, never deleted). The hub must not keep reading that folder as a live
mirror that is late: a HARNESS.md marked `status: retired` drops out of the host's
mirror rows and is listed as retired instead."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import tests.test_brain_status_jobs as base

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "bin" / "sov-status"


def harness_md(status=None):
    fm = "---\ntype: capture\nsource: box1\ncreated: 2026-09-03\ntitle: t\n" + ("status: %s\n" % status if status else "") + "---\n\nConnected.\n"
    return fm


class RetiredHarness(unittest.TestCase):
    def test_a_retired_harness_leaves_the_mirror_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            lane = b.vault / "raw" / "workspaces" / "boxlane"
            (lane / "claude-code").mkdir(parents=True); (lane / "codex").mkdir()
            (lane / "LANE.md").write_text("---\nlane: boxlane\nproducer: p\nhost: box1\nwrite: git\nread: none\nstatus: onboarded\n---\n")
            (lane / "claude-code" / "HARNESS.md").write_text(harness_md("retired"))
            (lane / "codex" / "HARNESS.md").write_text(harness_md())
            d = b.status()
            host = next(h for h in d["fleet"]["hosts"] if h["host"] == "box1")
            self.assertEqual([t["harness"] for t in host["harnesses"]], ["codex"])
            self.assertEqual([t["harness"] for t in host.get("retired", [])], ["claude-code"])


if __name__ == "__main__":
    unittest.main()
