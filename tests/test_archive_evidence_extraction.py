import hashlib
import unittest

from archive_evidence.cards import BoundCard
from archive_evidence.evidence import build_evidence


class EvidenceTests(unittest.TestCase):
    def test_preamble_becomes_overview_and_retains_bound_identity(self):
        raw = b"---\nsource: owner\nas_of: 2026-07-01\nverified_at: 2026-07-30\nfreshness_class: operational\n---\n# Card Title\n\nCurrent trusted statement.\n"
        card = BoundCard(
            slug="test-card",
            relative_path="knowledge/concepts/test-card.md",
            content_sha256=hashlib.sha256(raw).hexdigest(),
            raw=raw,
            text=raw.decode(),
        )

        result = build_evidence(card, max_sections=4)

        self.assertEqual(result["relative_path"], card.relative_path)
        self.assertEqual(result["content_sha256"], card.content_sha256)
        self.assertEqual(result["records"][0]["section"], "Overview")
        self.assertEqual(result["records"][0]["anchor"], "overview")
        self.assertEqual(result["records"][0]["text"], "Current trusted statement.")
        self.assertEqual(result["records"][0]["source"], "owner")
        self.assertEqual(result["records"][0]["as_of"], "2026-07-01")

    def test_section_limit_declares_truncation_and_total_count(self):
        raw = b"---\nsource: owner\n---\n# Card\n\nIntro.\n\n## First\n\nOne.\n\n## Second\n\nTwo.\n"
        card = BoundCard(
            slug="test-card",
            relative_path="knowledge/concepts/test-card.md",
            content_sha256=hashlib.sha256(raw).hexdigest(),
            raw=raw,
            text=raw.decode(),
        )

        result = build_evidence(card, max_sections=2)

        self.assertEqual(result["total_section_count"], 3)
        self.assertEqual(result["returned_section_count"], 2)
        self.assertTrue(result["truncated"])

    def test_heading_only_card_rejects_zero_records(self):
        raw = b"---\nsource: owner\n---\n# Card\n"
        card = BoundCard(
            slug="test-card",
            relative_path="knowledge/concepts/test-card.md",
            content_sha256=hashlib.sha256(raw).hexdigest(),
            raw=raw,
            text=raw.decode(),
        )

        with self.assertRaisesRegex(Exception, "zero_records"):
            build_evidence(card)

    def test_malformed_frontmatter_fails_closed(self):
        raw = b"---\nsource: [unterminated\n---\n# Card\n\nText.\n"
        card = BoundCard(
            slug="test-card",
            relative_path="knowledge/concepts/test-card.md",
            content_sha256=hashlib.sha256(raw).hexdigest(),
            raw=raw,
            text=raw.decode(),
        )

        with self.assertRaisesRegex(Exception, "invalid_frontmatter"):
            build_evidence(card)

    def test_duplicate_headings_receive_stable_distinct_anchors(self):
        raw = b"# Card\n\n## Same\n\nOne.\n\n## Same\n\nTwo.\n"
        card = BoundCard(
            slug="test-card",
            relative_path="knowledge/concepts/test-card.md",
            content_sha256=hashlib.sha256(raw).hexdigest(),
            raw=raw,
            text=raw.decode(),
        )

        result = build_evidence(card)

        self.assertEqual([record["anchor"] for record in result["records"]], ["same", "same-2"])


if __name__ == "__main__":
    unittest.main()
