"""The Sunday landed-review reports, per card type, how many cards the gear landed in
the trailing 30 days and how many of those the owner later reverted."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "hub" / "weekly-landed"


def card(kind):
    return "---\ntype: %s\nsource: test\ncreated: 2026-01-01\n---\n\n**Why this matters:** test card.\n" % kind


class RevertRate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        home = Path(self.tmp.name)
        vault = home / "vault"
        lane = vault / "raw" / "workspaces" / "archivist"
        (lane / "rejected").mkdir(parents=True)
        for sub in ("entities", "concepts", "syntheses"):
            (vault / "knowledge" / sub).mkdir(parents=True)
        (home / ".brain-root").write_text(str(vault))
        with mock.patch.dict(os.environ, {"HOME": str(home)}):
            loader = importlib.machinery.SourceFileLoader("weekly_landed_rate", str(SCRIPT))
            self.m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
            loader.exec_module(self.m)
        self.vault, self.lane = vault, lane

        now = datetime.now().astimezone()
        ts = lambda days: (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S%z")
        auto = lambda d, slug, sub: "%s\tapproved\t%s.md\tauto-gear\tknowledge/%s/%s.md: act-and-report: test" % (ts(d), slug, sub, slug)
        lines = [
            auto(45, "old-entity", "entities"),               # older than 30 days
            auto(40, "old-concept", "concepts"),              # older than 30 days, reverted
            "%s\tretired\told-concept.md\ttelegram-owner\ttelegram revert" % ts(39),
            auto(20, "concept-c", "concepts"),
            "%s\tretired\tconcept-c.md\towner-cli\tnot durable" % ts(15),
            auto(10, "concept-b", "concepts"),
            auto(5, "entity-e", "entities"),
            auto(3, "concept-a", "concepts"),
            "%s\tapproved\tsynthesis-f.md\towner-cli\tknowledge/syntheses/synthesis-f.md: owner" % ts(2),
            auto(2, "entity-d", "entities"),
            "%s\tretired\tsynthesis-f.md\ttelegram-owner\ttelegram revert" % ts(1),
            "%s\tretired\tconcept-a.md\ttelegram-owner\ttelegram revert: wrong" % ts(1),
        ]
        (lane / "decisions.log").write_text("\n".join(lines) + "\n")
        # Live cards sit in knowledge/; reverted ones now sit in the lane's rejected/.
        for slug, sub, kind in (("concept-b", "concepts", "concept"), ("entity-e", "entities", "entity"),
                                ("entity-d", "entities", "entity"), ("old-entity", "entities", "entity")):
            (vault / "knowledge" / sub / (slug + ".md")).write_text(card(kind))
        for slug, kind in (("concept-a", "concept"), ("concept-c", "concept"),
                           ("synthesis-f", "synthesis"), ("old-concept", "concept")):
            (lane / "rejected" / (slug + ".md")).write_text(card(kind))

    def rates(self):
        since = (datetime.now().astimezone() - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.m.revert_rates(self.m.read_decisions(since))

    def test_counts_per_type_over_thirty_days(self):
        # concept: a and c reverted, b kept; old-concept is outside the window.
        # entity: d and e kept; old-entity is outside the window.
        # synthesis: only an owner approval, so the type is omitted.
        self.assertEqual(self.rates(), [("concept", 3, 2), ("entity", 2, 0)])

    def test_section_lines_are_terse_and_omit_empty_types(self):
        self.assertEqual(self.m.revert_rate_lines(self.rates()),
                         ["concept: 3 landed, 2 reverted (67%)", "entity: 2 landed, 0 reverted (0%)"])

    def test_dry_run_prints_the_section_in_the_report(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(self.m.main(["--dry-run"]), 0)
        text = out.getvalue()
        self.assertIn("Revert rate, last 30 days", text)
        self.assertIn("concept: 3 landed, 2 reverted (67%)", text)
        self.assertIn("entity: 2 landed, 0 reverted (0%)", text)
        self.assertNotIn("synthesis:", text)
        # The weekly counts still cover only the 7-day window.
        self.assertIn("LANDED: 3", text)

    def test_notion_page_carries_the_section(self):
        since = datetime.now().astimezone() - timedelta(days=7)
        rep = self.m.build_report([], since, datetime.now().astimezone())
        rep["revert_rates"] = self.rates()
        texts = [b[b["type"]]["rich_text"][0]["text"]["content"] for b in self.m.notion_blocks(rep)
                 if b["type"] in ("heading_1", "bulleted_list_item")]
        i = texts.index("Revert rate, last 30 days")
        self.assertEqual(texts[i + 1:i + 3], ["concept: 3 landed, 2 reverted (67%)", "entity: 2 landed, 0 reverted (0%)"])

    def test_no_auto_landings_means_no_rows(self):
        self.assertEqual(self.m.revert_rates([]), [])
        self.assertEqual(self.m.revert_rate_lines([]), [])


if __name__ == "__main__":
    unittest.main()
