"""The pre-filter and the privacy gate: which sessions a distiller may ever see.

Every skip happens without a model and carries a named reason. The privacy gate refuses
a session that ran inside an archive, the vault or any folder shaped like one, and the
allow list cannot override that; a PermissionError while probing counts as an archive,
which is the macOS protected-folder case.
"""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402
import brain_local  # noqa: E402
from session_ingest import claude_code, prefilter, privacy, state  # noqa: E402

BLAND = ["please tidy the readme", "run the tests again", "looks good, ship it"]


class PreFilter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home, self.vault, self.state = fx.make_home(self.tmp.name)
        self.cwd = Path(self.tmp.name, "work", "proj")
        self.cwd.mkdir(parents=True)
        self.cfg = state.default_config()
        self.floor = time.time() - 86400
        self.n = 0

    def session(self, prompts, **kw):
        self.n += 1
        path = fx.transcript(self.home, "-work-proj", "%08d-aaaa" % self.n, self.cwd, prompts, **kw)
        return claude_code.scan(path)

    def check(self, s, stems=()):
        return prefilter.check(s, self.cfg, self.floor, stems)

    def test_one_prompt_is_few_prompts(self):
        self.assertEqual(self.check(self.session(["remember this forever"]))[0], "skipped:few-prompts")

    def test_sdk_entrypoint_skipped(self):
        s = self.session(["remember one", "two", "three"], entrypoint="sdk-py")
        self.assertEqual(self.check(s)[0], "skipped:entrypoint")

    def test_sidechain_skipped(self):
        s = self.session(["remember one", "two", "three"], sidechain=True)
        self.assertEqual(self.check(s)[0], "skipped:sidechain")

    def test_order_entrypoint_before_sidechain_before_prompts(self):
        s = self.session(["one"], entrypoint="sdk-cli", sidechain=True)
        self.assertEqual(self.check(s)[0], "skipped:entrypoint")
        s = self.session(["one"], sidechain=True)
        self.assertEqual(self.check(s)[0], "skipped:sidechain")

    def test_fresh_file_is_not_quiet(self):
        s = self.session(BLAND, age_s=60)
        now = time.time()
        self.assertFalse(prefilter.quiet(s["size"], s["mtime"], None, now, 45))
        old = self.session(BLAND, age_s=3600)
        self.assertTrue(prefilter.quiet(old["size"], old["mtime"], None, now, 45))
        self.assertTrue(prefilter.quiet(old["size"], old["mtime"], {"size": old["size"]}, now, 45))
        self.assertFalse(prefilter.quiet(old["size"], old["mtime"], {"size": old["size"] - 1}, now, 45))

    def test_remember_session_passes(self):
        s = self.session(["remember that the deploy runs nightly", "run the tests", "thanks"])
        verdict, score, hits = self.check(s)
        self.assertIsNone(verdict)
        self.assertEqual(score, 1)
        self.assertEqual(hits, frozenset({1}))

    def test_correction_plus_decision_scores_two(self):
        s = self.session(["set up the job", "no, that's wrong, the port is different",
                          "ok let's go with the second option"])
        verdict, score, hits = self.check(s)
        self.assertIsNone(verdict)
        self.assertEqual(score, 2)
        self.assertEqual(hits, frozenset({2, 3}))

    def test_bland_session_is_low_signal(self):
        self.assertEqual(self.check(self.session(BLAND))[:2], ("skipped:low-signal", 0))

    def test_word_boundary_and_case(self):
        s = self.session(["I remembered the plan", "factually fine", "ACTUALLY no, we DECIDED otherwise"])
        verdict, score, hits = self.check(s)
        self.assertEqual((verdict, score, hits), (None, 2, frozenset({3})))

    def test_one_point_per_turn_per_category(self):
        s = self.session(["actually, that's wrong, actually", "fine", "ok"])
        self.assertEqual(self.check(s)[:2], ("skipped:low-signal", 1))

    def test_curly_apostrophe_matches(self):
        s = self.session(["that’s wrong", "we decided on it", "ok"])
        self.assertEqual(self.check(s)[:2], (None, 2))

    def test_instance_phrases_extend_defaults(self):
        self.cfg["phrases"]["memory"] = ["park this"]
        s = self.session(["park this for later", "fine", "ok"])
        self.assertEqual(self.check(s)[0], None)
        s = self.session(["remember the rule", "fine", "ok"])
        self.assertEqual(self.check(s)[0], None)

    def test_new_names_add_at_most_one_point(self):
        prompts = ["ask the team about Zorblax and Quintessa", "we decided it", "ok"]
        self.assertEqual(self.check(self.session(prompts))[:2], (None, 2))
        # A name with a matching card is known; a sentence-initial word and "I" are not names.
        s = self.session(["ask the team about Zorblax. Today I decided it", "fine", "ok"])
        self.assertEqual(self.check(s, stems={"zorblax"})[:2], ("skipped:low-signal", 1))
        s = self.session(["ask about Zorblax", "we decided it", "ok"])
        self.assertEqual(self.check(s, stems={"zorblax-labs"})[:2], ("skipped:low-signal", 1))

    def test_before_enable(self):
        s = self.session(["remember one", "two", "three"], age_s=3600)
        self.assertEqual(prefilter.check(s, self.cfg, time.time() - 60, ())[0], "skipped:before-enable")
        self.assertEqual(prefilter.check(s, self.cfg, None, ())[0], "skipped:before-enable")
        self.assertIsNone(prefilter.check(s, self.cfg, time.time() - 7200, ())[0])

    def test_denied_project_stops_with_reason(self):
        cfg = dict(self.cfg, allow=[self.tmp.name], deny=[str(Path(self.tmp.name, "work"))])
        path = fx.transcript(self.home, "-work-proj", "deny-aaaa", self.cwd, ["remember one", "two", "three"])
        s = claude_code.scan(path, privacy.make_cwd_check(self.vault, cfg))
        self.assertEqual(s["stopped"], "denied")
        self.assertEqual(prefilter.check(s, self.cfg, self.floor, ()), ("denied", 0, frozenset()))

    def test_card_stems(self):
        (self.vault / "knowledge" / "entities" / "acme-county.md").write_text("x")
        (self.vault / "knowledge" / "concepts" / "Gate-Rules.md").write_text("x")
        self.assertEqual(prefilter.card_stems(self.vault), {"acme-county", "gate-rules"})


class Privacy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home, self.vault, self.state = fx.make_home(self.tmp.name)
        self.base = Path(os.path.realpath(self.tmp.name))
        self.other = Path(brain_local.create(self.base / "other", ROOT)["root"])
        self.work = self.base / "work" / "proj"
        self.work.mkdir(parents=True)
        self.link = self.base / "link"
        os.symlink(self.vault / "workstreams", self.link)
        self.link2 = self.base / "link2"
        os.symlink(self.other / "raw", self.link2)
        everywhere = [str(self.base), str(self.vault), str(self.other)]
        self.cfg = dict(state.default_config(), allow=everywhere)

    def gate(self, cfg=None):
        return privacy.make_cwd_check(self.vault, cfg or self.cfg)

    def test_archive_like(self):
        self.assertTrue(privacy.archive_like(str(self.vault)))
        self.assertTrue(privacy.archive_like(str(self.other / "knowledge" / "concepts")))
        self.assertFalse(privacy.archive_like(str(self.work)))
        self.assertFalse(privacy.archive_like("/definitely-not-here/x"))

    def test_archive_cwds_refused_even_when_allowed(self):
        gate = self.gate()
        for cwd in (self.vault, self.vault / "raw", self.other, self.other / "workstreams"):
            self.assertEqual(gate(os.path.realpath(str(cwd))), "refused-archive", cwd)
        for cwd in (self.link, self.link2):
            self.assertEqual(gate(os.path.realpath(str(cwd))), "refused-archive", cwd)
            self.assertEqual(gate(str(cwd)), "refused-archive", cwd)
        self.assertIsNone(gate(str(self.work)))

    def test_vault_refused_without_its_shape(self):
        os.unlink(self.vault / "CLAUDE.md")
        self.assertFalse(privacy.archive_like(str(self.vault)))
        self.assertEqual(self.gate()(str(self.vault / "workstreams")), "refused-archive")

    def test_permission_error_fails_closed(self):
        gate = self.gate()
        with mock.patch.object(privacy.os, "stat", side_effect=PermissionError("TCC")):
            self.assertTrue(privacy.archive_like(str(self.work)))
            self.assertEqual(gate(str(self.work)), "refused-archive")

    def test_scan_stops_at_archive_cwd(self):
        path = fx.transcript(self.home, "-link", "link-aaaa", self.link, ["remember one", "two", "three"])
        s = claude_code.scan(path, self.gate())
        self.assertEqual((s["stopped"], s["turns"]), ("refused-archive", []))

    def test_deny_prefix(self):
        cfg = dict(self.cfg, deny=[str(self.base / "work")])
        gate = self.gate(cfg)
        self.assertEqual(gate(str(self.work)), "denied")
        self.assertEqual(gate(str(self.base / "work")), "denied")
        shop = self.base / "workshop"
        shop.mkdir()
        self.assertIsNone(gate(str(shop)))

    def test_temporary_roots_off_unless_allowed(self):
        cfg = dict(self.cfg, allow=[])
        self.assertEqual(self.gate(cfg)("/private/tmp/x"), "denied")
        self.assertEqual(self.gate(cfg)(str(self.work)), "denied")  # under $TMPDIR / var/folders
        self.assertIsNone(self.gate(dict(cfg, allow=["/private/tmp"]))("/private/tmp/x"))
        self.assertIsNone(self.gate(dict(cfg, allow=["/tmp"]))("/private/tmp/x"))
        self.assertIsNone(self.gate(cfg)("/not-a-temp-root-xyz/proj"))

    def test_policy_hash(self):
        a = privacy.policy_hash(dict(self.cfg, allow=["/a", "/b"], deny=["/c"]))
        b = privacy.policy_hash(dict(self.cfg, allow=["/b", "/a"], deny=["/c"]))
        c = privacy.policy_hash(dict(self.cfg, allow=["/a", "/b"], deny=[]))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertRegex(a, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
