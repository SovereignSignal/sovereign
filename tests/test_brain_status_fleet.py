"""Which devices the status service says exist, and what each lane contract says.

A lane contract is a hand-written LANE.md, and owners annotate it the way they annotate
any YAML: `host: hubbox   # the hub, from 2026-10-03`. Read as part of the value, that
comment became a second device named after the whole comment, a contribute-only lane
read as one that reads, and a lane filed under a machine that does not exist.
"""
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

import tests.test_brain_status_jobs as base

loader = importlib.machinery.SourceFileLoader("brain_status_fleet_under_test", str(base.STATUS))
status = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(status)


class LaneContractComments(unittest.TestCase):
    def test_an_inline_comment_is_not_part_of_the_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "LANE.md"
            p.write_text("---\nhost: hubbox   # the hub, from 2026-10-03; staging stays valid\n"
                         "read: none                   # contribute-only\n"
                         "write: rsync (via staging)   # carried in by the runner\n"
                         "gear:   # not decided\n"
                         "link: https://example.org/page#section\n"
                         "producer: C# exporter\n---\n")
            fm = status.frontmatter(str(p))
        self.assertEqual(fm["host"], "hubbox")
        self.assertEqual(fm["read"], "none")
        self.assertEqual(fm["write"], "rsync (via staging)")
        self.assertEqual(fm["gear"], "")
        self.assertEqual(fm["link"], "https://example.org/page#section")
        self.assertEqual(fm["producer"], "C# exporter")

    def test_a_commented_host_files_the_lane_under_the_real_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = base.Box(tmp); b.declare({}); b.record({})
            lane = b.vault / "raw" / "tools" / "weekly-digest"
            lane.mkdir()
            (lane / "LANE.md").write_text("---\nlane: weekly-digest\nproducer: p\n"
                                          "host: hubbox   # the hub, from 2026-10-03\n"
                                          "write: rsync (via staging)   # note\n"
                                          "read: none                   # contribute-only\n"
                                          "status: onboarded\ngear: ask-first\n---\n")
            (lane / "note.md").write_text("x\n")
            d = b.status()
        names = [h["host"] for h in d["fleet"]["hosts"]]
        self.assertFalse([n for n in names if "#" in n], names)
        hub = next(h for h in d["fleet"]["hosts"] if h["host"] == "hubbox")
        self.assertEqual([l["lane"] for l in hub["lanes"]], ["weekly-digest"])
        row = next(l for l in d["lanes"] if l["lane"] == "weekly-digest")
        self.assertEqual((row["host"], row["read"], row["write"]), ("hubbox", "none", "rsync (via staging)"))


if __name__ == "__main__":
    unittest.main()
