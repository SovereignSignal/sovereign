"""The client boundary in the producer exporters, tested against what it must do.

These two scripts decide what leaves a machine holding ENS and Uniswap Foundation
client material. Until 2026-09-21 they had no tests and lived only in `~/bin/` on
their VMs, so the only history was hand-made dated backups.

Two real failures drive most of what is asserted here:

  * a memory file named `project_retro_funding_rubric.md` reached the proposal
    stage naming a live SPP3 co-applicant and linking their handle to a prior
    one, because spp3 filtered on the source PATH and never read the body; and

  * the first filter written to fix that removed "Scoring scale: 1-5 per
    criterion" and "Score 5 - Exceptional" from the evaluation rubric, because a
    rubric IS a scoring scale and no pattern separates method from outcome.

Both directions are covered: what must never travel, and what must not be lost.
"""
import importlib.machinery
import importlib.util
import sys
import unittest
from pathlib import Path

PRODUCERS = Path(__file__).resolve().parents[1] / "connectors" / "producers"


def load(name):
    """Import an exporter by path; they are executables with no .py suffix."""
    path = PRODUCERS / name
    if not path.exists():                                  # pragma: no cover
        raise unittest.SkipTest(f"{name} is not vendored into the repo")
    spec = importlib.util.spec_from_loader(
        "producer_" + name.replace("-", "_"),
        importlib.machinery.SourceFileLoader("producer_" + name.replace("-", "_"), str(path)))
    module = importlib.util.module_from_spec(spec)
    saved, sys.argv = sys.argv, [name, "--dry"]            # never a capturing run
    try:
        spec.loader.exec_module(module)
    finally:
        sys.argv = saved
    return module


MARKER = "line withheld by the client boundary"


class Spp3Boundary(unittest.TestCase):
    """spp3 carries ENS program design. People here are named by handle."""

    @classmethod
    def setUpClass(cls):
        cls.m = load("spp3-brain-daily")

    def held(self, line):
        kept, _ = self.m.filter_lines([line])
        return MARKER in kept[0]

    # ---- what must never travel ----

    def test_a_co_applicant_handle_is_withheld(self):
        # The line that started this, near verbatim.
        self.assertTrue(self.held(
            'someapplicant.eth ("A Name", the otherhandle.eth SPP3 co-applicant, prior identity '
            'priorhandle.eth) is seeking retro funding'))

    def test_linking_a_handle_to_a_prior_handle_is_withheld(self):
        self.assertTrue(self.held("onehandle.eth, formerly anotherhandle.eth, favours a forum proposal"))

    def test_an_ethereum_address_is_withheld(self):
        self.assertTrue(self.held("send to 0x1234567890abcdef1234567890ABCDEF12345678 before Friday"))

    def test_a_forum_thread_pinning_a_position_to_a_person_is_withheld(self):
        self.assertTrue(self.held("see discuss.ens.domains/t/22086 for their objection"))

    def test_money_is_withheld(self):
        for line in ("the ask was $200,000 for the season",
                     "a 45,000 ENS grant",
                     "request >= $1.2M"):
            with self.subTest(line=line):
                self.assertTrue(self.held(line))

    def test_contact_details_are_withheld(self):
        for line in ("reach them at someone@example.org",
                     "ping @someprovider about the deadline"):
            with self.subTest(line=line):
                self.assertTrue(self.held(line))

    # ---- what must NOT be lost ----

    def test_a_scoring_rubric_survives_its_own_vocabulary(self):
        """The regression that deleted the rubric. A rubric IS a scoring scale."""
        for line in ("**Scoring scale:** 1-5 per criterion, in 0.5-point increments.",
                     "**Score 5 - Exceptional**",
                     "### Scoring Anchors",
                     "- Score applications independently (post-interview)",
                     "**Gate decision:** PASS or FAIL. Recorded by committee before scoring begins."):
            with self.subTest(line=line):
                self.assertFalse(self.held(line), f"method text must travel: {line!r}")

    def test_the_seated_committee_travels_by_name(self):
        """Owner decision 2026-09-21: a document about a committee may say who is on it."""
        for handle in self.m.PUBLIC_ROLES:
            with self.subTest(handle=handle):
                self.assertFalse(self.held(f"1. **{handle}** - Steward; grants experience"))

    def test_the_allow_list_fails_safe_for_everyone_else(self):
        self.assertTrue(self.held("aforumposter.eth posted once, objecting to the timeline"))
        self.assertTrue(self.held("a new member, someonenew.eth, joins the committee"))

    def test_a_public_role_beside_a_private_handle_still_goes(self):
        """One permitted name does not launder the rest of the line."""
        permitted = sorted(self.m.PUBLIC_ROLES)[0]
        self.assertTrue(self.held(f"{permitted} met someapplicant.eth about the retro ask"))

    # ---- the shape of a withheld line ----

    def test_a_dropped_line_leaves_a_visible_gap_and_keeps_its_indent(self):
        kept, dropped = self.m.filter_lines(["    the ask was $200,000"])
        self.assertTrue(kept[0].startswith("    ["), "indent is preserved")
        self.assertIn("money", kept[0])
        self.assertEqual(dropped, {"money": 1})

    def test_neighbours_are_never_spliced(self):
        kept, _ = self.m.filter_lines(["first half of a thought",
                                       "the ask was $200,000",
                                       "second half of a thought"])
        self.assertEqual(len(kept), 3, "a dropped line keeps its position")
        self.assertIn(MARKER, kept[1])


class Spp3Yield(unittest.TestCase):
    """The floor that refuses a capture with nothing left in it."""

    @classmethod
    def setUpClass(cls):
        cls.m = load("spp3-brain-daily")

    def test_scaffolding_is_not_counted_as_content(self):
        body = ("_Source: `~/x.md` on spp3, 4KB._\n"
                "\n---\nname: a-note\nmodified: 2026-08-13\n---\n"
                "a real sentence\n")
        content, markers, share = self.m.yield_of(body)
        self.assertEqual((content, markers), (1, 0), "frontmatter and header are not content")
        self.assertEqual(share, 0.0)

    def test_a_body_that_is_mostly_markers_is_measured_as_such(self):
        body = "\n".join([f"[… {MARKER}: identity …]"] * 4 + ["one surviving line"])
        content, markers, share = self.m.yield_of(body)
        self.assertEqual((content, markers), (1, 4))
        self.assertGreater(share, self.m.COLLAPSE_MARKER_SHARE)

    def test_the_floor_constants_are_a_floor(self):
        self.assertGreaterEqual(self.m.COLLAPSE_MIN_LINES, 1)
        self.assertLessEqual(self.m.COLLAPSE_MARKER_SHARE, 0.5)


class UniclaudeBoundary(unittest.TestCase):
    """uniclaude carries UF grants-ops method. The line here is money and identity."""

    @classmethod
    def setUpClass(cls):
        cls.m = load("uniclaude-brain-daily")

    def held(self, line, deny=frozenset()):
        kept, _ = self.m.filter_lines([line], deny)
        return MARKER in kept[0]

    def test_grant_amounts_are_withheld(self):
        for line in ("$70k confirmed 9/1", "297 UNI quarterly", "the ask was $1,200,000"):
            with self.subTest(line=line):
                self.assertTrue(self.held(line))

    def test_client_record_ids_are_withheld(self):
        self.assertTrue(self.held("base appFAKEBASE000001 holds the Grants table"))

    def test_contact_details_are_withheld(self):
        self.assertTrue(self.held("email them at someone@example.org"))

    def test_a_derived_deny_name_is_withheld(self):
        self.assertTrue(self.held("Some Grantee Org applied in August",
                                  deny={"Some Grantee Org"}))

    def test_method_prose_travels(self):
        for line in ("Independently verify the decisive claims.",
                     "Check recency, not just existence.",
                     "NEVER send. Drafts only."):
            with self.subTest(line=line):
                self.assertFalse(self.held(line))

    def test_a_dropped_line_leaves_a_visible_gap(self):
        kept, dropped = self.m.filter_lines(["  the ask was $70k"], frozenset())
        self.assertIn(MARKER, kept[0])
        self.assertTrue(kept[0].startswith("  "))
        self.assertEqual(dropped["money"], 1)

    def test_yield_ignores_the_source_header(self):
        content, markers, _ = self.m.yield_of("_Source: `~/x` on uniclaude, 4KB._\n\nreal line\n")
        self.assertEqual((content, markers), (1, 0))


class BothProducers(unittest.TestCase):
    """Invariants that must hold on every producer, so a new one inherits them."""

    def modules(self):
        return [("spp3", load("spp3-brain-daily")), ("uniclaude", load("uniclaude-brain-daily"))]

    def test_every_producer_has_a_floor_and_a_preflight(self):
        for name, m in self.modules():
            with self.subTest(producer=name):
                self.assertTrue(callable(m.yield_of))
                self.assertTrue(callable(m.preflight))
                self.assertTrue(callable(m.load_reference))
                self.assertLessEqual(m.COLLAPSE_MARKER_SHARE, 0.5)

    def test_secret_scanning_is_present_and_catches_a_key(self):
        for name, m in self.modules():
            with self.subTest(producer=name):
                self.assertTrue(m.secret_hits("ghp_" + "a" * 32))
                self.assertFalse(m.secret_hits("an ordinary sentence about method"))

    def test_an_empty_line_is_never_reported_as_withheld(self):
        for name, m in self.modules():
            with self.subTest(producer=name):
                kept, dropped = (m.filter_lines(["", "   "], frozenset())
                                 if name == "uniclaude" else m.filter_lines(["", "   "]))
                self.assertFalse(any(MARKER in k for k in kept))
                self.assertFalse(any(dropped.values()))


if __name__ == "__main__":                                 # pragma: no cover
    unittest.main()
