import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_evidence.cards import bind_overlay_reference, bind_topic, load_aliases


CARD = b"---\ntype: concept\nsource: owner\ncreated: 2026-01-01\n---\n# Test Card\n\nTrusted statement.\n"


class CardBindingTests(unittest.TestCase):
    def test_unique_topic_binds_exact_relative_path_and_raw_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card_path = root / "knowledge" / "concepts" / "test-card.md"
            card_path.parent.mkdir(parents=True)
            card_path.write_bytes(CARD)

            card = bind_topic(root, "test-card", aliases={})

            self.assertEqual(card.slug, "test-card")
            self.assertEqual(card.relative_path, "knowledge/concepts/test-card.md")
            self.assertEqual(card.content_sha256, hashlib.sha256(CARD).hexdigest())
            self.assertEqual(card.raw, CARD)

    def test_duplicate_slug_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for kind in ("concepts", "entities"):
                card_path = root / "knowledge" / kind / "test-card.md"
                card_path.parent.mkdir(parents=True, exist_ok=True)
                card_path.write_bytes(CARD)

            with self.assertRaisesRegex(Exception, "ambiguous_card"):
                bind_topic(root, "test-card", aliases={})

    def test_opaque_reference_binds_declared_path_slug_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card_path = root / "knowledge" / "concepts" / "test-card.md"
            card_path.parent.mkdir(parents=True)
            card_path.write_bytes(CARD)
            overlay = {
                "opaque-1": {
                    "slug": "test-card",
                    "relative_path": "knowledge/concepts/test-card.md",
                    "content_sha256": hashlib.sha256(CARD).hexdigest(),
                }
            }

            card = bind_overlay_reference(root, overlay, "opaque-1")

            self.assertEqual(card.relative_path, overlay["opaque-1"]["relative_path"])
            self.assertEqual(card.content_sha256, overlay["opaque-1"]["content_sha256"])

    def test_opaque_reference_rejects_stale_source_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card_path = root / "knowledge" / "concepts" / "test-card.md"
            card_path.parent.mkdir(parents=True)
            card_path.write_bytes(CARD)
            overlay = {
                "opaque-1": {
                    "slug": "test-card",
                    "relative_path": "knowledge/concepts/test-card.md",
                    "content_sha256": "0" * 64,
                }
            }

            with self.assertRaisesRegex(Exception, "stale_binding"):
                bind_overlay_reference(root, overlay, "opaque-1")

    def test_topic_rejects_symlinked_trusted_parent(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside_tmp:
            root = Path(tmp)
            outside = Path(outside_tmp)
            card_path = outside / "concepts" / "test-card.md"
            card_path.parent.mkdir(parents=True)
            card_path.write_bytes(CARD)
            (root / "knowledge").symlink_to(outside, target_is_directory=True)

            with self.assertRaisesRegex(Exception, "unsafe_source"):
                bind_topic(root, "test-card", aliases={})

    def test_alias_loader_reads_one_level_mapping_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".brain-aliases.json").write_text(json.dumps({"short": "test-card"}))

            aliases = load_aliases(root, user_alias_path=root / "missing-aliases.json")

            self.assertEqual(aliases, {"short": "test-card"})

        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            target = Path(other) / "aliases.json"
            target.write_text(json.dumps({"short": "test-card"}))
            (root / ".brain-aliases.json").symlink_to(target)

            with self.assertRaisesRegex(Exception, "unsafe_aliases"):
                load_aliases(root, user_alias_path=root / "missing-aliases.json")

    def test_user_alias_file_overrides_vault_alias_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault_alias = root / ".brain-aliases.json"
            user_alias = root / "user-aliases.json"
            vault_alias.write_text(json.dumps({"spoken": "vault-card", "vault-only": "vault-card"}))
            user_alias.write_text(json.dumps({"spoken": "user-card"}))

            aliases = load_aliases(root, user_alias_path=user_alias)

            self.assertEqual(
                aliases,
                {"spoken": "user-card", "vault-only": "vault-card"},
            )

    def test_user_alias_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            root = Path(tmp)
            target = Path(other) / "aliases.json"
            target.write_text(json.dumps({"spoken": "test-card"}))
            linked = root / "user-aliases.json"
            linked.symlink_to(target)

            with self.assertRaisesRegex(Exception, "unsafe_aliases"):
                load_aliases(root, user_alias_path=linked)

    def test_alias_resolution_is_single_hop(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for lane, slug in (("concepts", "second"), ("entities", "third")):
                card_path = root / "knowledge" / lane / f"{slug}.md"
                card_path.parent.mkdir(parents=True)
                card_path.write_bytes(CARD)

            card = bind_topic(root, "first", aliases={"first": "second", "second": "third"})

            self.assertEqual(card.slug, "second")
            self.assertEqual(card.relative_path, "knowledge/concepts/second.md")

    def test_overlay_rejects_path_traversal_before_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            overlay = {
                "opaque-1": {
                    "slug": "test-card",
                    "relative_path": "knowledge/../outside/test-card.md",
                    "content_sha256": "0" * 64,
                }
            }

            with self.assertRaisesRegex(Exception, "invalid_overlay_path"):
                bind_overlay_reference(root, overlay, "opaque-1")

    def test_invalid_utf8_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            card_path = root / "knowledge" / "concepts" / "test-card.md"
            card_path.parent.mkdir(parents=True)
            raw = b"\xff\xfe"
            card_path.write_bytes(raw)

            with self.assertRaisesRegex(Exception, "invalid_utf8"):
                bind_topic(root, "test-card", aliases={})

    def test_topic_scan_maps_directory_listing_failure_to_stable_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "knowledge").mkdir()

            with patch("archive_evidence.cards.os.listdir", side_effect=OSError("synthetic failure")):
                with self.assertRaisesRegex(Exception, "source_scan_failed"):
                    bind_topic(root, "test-card", aliases={})


if __name__ == "__main__":
    unittest.main()
