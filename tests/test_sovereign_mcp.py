"""sov mcp serves trusted cards read-only: the same slice as sov load, fenced, hashed, gated per call."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import sovereign_mcp  # noqa: E402

CARD = "---\ntype: {kind}\nsource: owner\ncreated: 2026-10-20\ntitle: {title}\n---\n\n# {title}\n\n{body}\n"
TOKEN = "gh" + "p_" + "x" * 36  # a GitHub token shape, built so the repo's own scan never sees one


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def make_vault(base):
    v = base / "vault"
    write(v / "knowledge/concepts/garden-planner.md",
          CARD.format(kind="concept", title="Garden planner", body="Works offline. Grown for [[small-plots]]."))
    write(v / "knowledge/entities/small-plots.md",
          CARD.format(kind="entity", title="Small plots", body="Urban beds under four square metres. See [[garden-planner]] and [[watering]]."))
    write(v / "knowledge/concepts/watering.md", CARD.format(kind="concept", title="Watering", body="Drip lines."))
    write(v / "knowledge/entities/owner.md", CARD.format(kind="entity", title="Owner", body="Prefers plain language."))
    write(v / "knowledge/syntheses/leaky.md", CARD.format(kind="synthesis", title="Leaky", body=f"Pasted key {TOKEN} by mistake."))
    write(v / "knowledge/concepts/twin.md", CARD.format(kind="concept", title="Twin A", body="One."))
    write(v / "knowledge/syntheses/twin.md", CARD.format(kind="synthesis", title="Twin B", body="Two."))
    outside = base / "outside.md"
    write(outside, CARD.format(kind="concept", title="Outside", body="Not part of the archive."))
    os.symlink(outside, v / "knowledge/concepts/escape.md")
    write(v / "raw/tools/claude-code/memory.md", "untrusted raw capture: garden")
    (v / ".brain-aliases.json").write_text(json.dumps({"garden": "garden-planner"}))
    return v


def tree_state(root):
    return sorted((str(p.relative_to(root)), p.lstat().st_mtime_ns,
                   hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and not p.is_symlink() else "")
                  for p in root.rglob("*"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vault = make_vault(base)
        self.state = base / "state"
        self.state.mkdir()
        self.env = {"HOME": str(base / "home"), "BRAIN_ROOT": str(self.vault), "BRAIN_CORE": "owner",
                    "SOV_STATE_DIR": str(self.state), "PYTHONDONTWRITEBYTECODE": "1"}
        (base / "home").mkdir()
        patcher = mock.patch.dict(os.environ, self.env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)

    def config(self, value):
        (self.state / "connectors.json").write_text(json.dumps(value))

    def tool(self, name, **args):
        reply = sovereign_mcp.handle({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                                      "params": {"name": name, "arguments": args}})
        result = reply["result"]
        return result["content"][0]["text"], result["isError"]


class Tools(Base):
    def test_load_context_follows_links_adds_the_core_and_cites_each_card(self):
        text, failed = self.tool("load_context", topic="garden-planner")
        self.assertFalse(failed)
        for slug in ("garden-planner", "small-plots", "watering", "owner"):
            self.assertIn(f"/{slug}.md sha256:", text)
        self.assertEqual(text.count("# Garden planner"), 1)
        digest = hashlib.sha256((self.vault / "knowledge/concepts/garden-planner.md").read_bytes()).hexdigest()
        self.assertIn(f"<!-- knowledge/concepts/garden-planner.md sha256:{digest} -->", text)
        self.assertNotIn("untrusted raw capture", text)

    def test_depth_limits_the_walk_and_an_alias_resolves_once(self):
        text, _ = self.tool("load_context", topic="garden", depth=1)
        self.assertIn("small-plots.md", text)
        self.assertNotIn("watering.md", text)
        self.assertEqual(text.count("garden-planner.md sha256"), 1)

    def test_missing_topic_is_named_as_core_only(self):
        text, failed = self.tool("load_context", topic="nothing-here")
        self.assertFalse(failed)
        self.assertIn("always-on core only", text)
        self.assertIn("owner.md", text)

    def test_a_symlinked_card_and_an_ambiguous_slug_are_refused(self):
        text, failed = self.tool("read_card", slug="escape")
        self.assertTrue(failed)
        self.assertIn("unsafe_source", text)
        self.assertNotIn("Not part of the archive", text)
        text, failed = self.tool("read_card", slug="twin")
        self.assertTrue(failed)
        self.assertIn("ambiguous_card", text)
        listing, _ = self.tool("list_cards")
        self.assertNotIn("escape", listing)
        self.assertNotIn("twin", listing)
        self.assertIn("concepts/garden-planner: Garden planner", listing)

    def test_path_shaped_slugs_are_refused(self):
        for slug in ("../raw/tools/claude-code/memory", "/etc/hosts", "Garden-Planner"):
            text, failed = self.tool("read_card", slug=slug)
            self.assertTrue(failed, slug)
            self.assertIn("invalid_topic", text)

    def test_a_secret_pasted_into_a_card_is_redacted_on_the_way_out(self):
        text, failed = self.tool("read_card", slug="leaky")
        self.assertFalse(failed)
        self.assertNotIn(TOKEN, text)
        self.assertIn("Pasted key", text)

    def test_search_ranks_name_hits_first_and_needs_every_word(self):
        text, _ = self.tool("search_cards", query="garden")
        self.assertTrue(text.startswith("- garden-planner"), text)
        self.assertIn("small-plots", text)
        text, _ = self.tool("search_cards", query="garden zebra")
        self.assertEqual(text, "No trusted card matches.")
        _, failed = self.tool("search_cards", query="  ")
        self.assertTrue(failed)

    def test_bad_arguments_are_refused_not_raised(self):
        for name, args in (("load_context", {}), ("load_context", {"topic": "x", "depth": 9}),
                           ("load_context", {"topic": "x", "depth": True}), ("read_card", {"slug": 3}),
                           ("search_cards", {"query": "x", "limit": 0}), ("write_card", {})):
            _, failed = self.tool(name, **args)
            self.assertTrue(failed, (name, args))

    def test_an_archive_reached_through_a_symlink_is_served(self):
        link = self.vault.parent / "linked-archive"
        os.symlink(self.vault, link)
        with mock.patch.dict(os.environ, {"BRAIN_ROOT": str(link)}):
            text, failed = self.tool("read_card", slug="watering")
        self.assertFalse(failed, text)
        self.assertIn("Drip lines.", text)

    def test_an_oversized_card_is_truncated(self):
        write(self.vault / "knowledge/concepts/huge.md", CARD.format(kind="concept", title="Huge", body="x" * 100000))
        text, failed = self.tool("read_card", slug="huge")
        self.assertFalse(failed)
        self.assertLess(len(text), sovereign_mcp.MAX_CHARS + 100)
        self.assertIn("[card truncated", text)

    def test_an_unexpected_failure_is_an_error_result_not_a_dead_server(self):
        with mock.patch.object(sovereign_mcp, "call", side_effect=RuntimeError("boom")):
            text, failed = self.tool("list_cards")
        self.assertTrue(failed)
        self.assertNotIn("boom", text)

    def test_pack_budget_truncates_with_a_pointer_to_read_card(self):
        text = sovereign_mcp.Archive(self.vault).pack("garden-planner", max_chars=200)
        self.assertLess(len(text), 300)
        self.assertIn("read_card loads any card in full", text)


class Gate(Base):
    def test_contribute_only_client_reads_nothing(self):
        self.config({"machine": {"role": "client", "mode": "contribute-only"}})
        text, failed = self.tool("load_context", topic="garden-planner")
        self.assertTrue(failed)
        self.assertNotIn("Garden planner", text)

    def test_a_retired_mcp_harness_reads_nothing(self):
        self.config({"retired_harnesses": {"mcp": {"retired": "2026-10-20"}}})
        _, failed = self.tool("list_cards")
        self.assertTrue(failed)

    def test_invalid_role_configuration_fails_closed(self):
        self.config({"machine": {"role": "sideways"}})
        _, failed = self.tool("list_cards")
        self.assertTrue(failed)

    def test_no_archive_configured_is_explained(self):
        with mock.patch.dict(os.environ, {"BRAIN_ROOT": "", "SOVS_VAULT": ""}):
            text, failed = self.tool("list_cards")
        self.assertTrue(failed)
        self.assertIn("No archive is configured", text)


class Protocol(Base):
    def test_every_tool_is_declared_read_only(self):
        tools = sovereign_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"load_context", "read_card", "search_cards", "list_cards"})
        for t in tools:
            self.assertTrue(t["annotations"]["readOnlyHint"], t["name"])
            self.assertFalse(t["annotations"]["destructiveHint"], t["name"])

    def test_initialize_negotiates_a_known_protocol(self):
        reply = sovereign_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "2024-11-05"}})
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")
        reply = sovereign_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                      "params": {"protocolVersion": "1999-01-01"}})
        self.assertEqual(reply["result"]["protocolVersion"], sovereign_mcp.PROTOCOLS[0])

    def test_notifications_get_no_reply_and_errors_use_jsonrpc_codes(self):
        self.assertIsNone(sovereign_mcp.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(sovereign_mcp.handle({"jsonrpc": "2.0", "id": 2, "method": "resources/write"})["error"]["code"], -32601)
        self.assertEqual(sovereign_mcp.handle(["not", "an", "object"])["error"]["code"], -32600)

    def test_a_full_stdio_session_through_sov_leaves_the_archive_untouched(self):
        before = tree_state(self.vault)
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                 {"jsonrpc": "2.0", "method": "notifications/initialized"},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                 {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "load_context", "arguments": {"topic": "garden"}}},
                 {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_cards", "arguments": {"query": "plots"}}}]
        stdin = "\n".join(json.dumps(m) for m in lines) + "\n{not json\n"
        r = subprocess.run(["/bin/bash", str(ROOT / "bin/sov"), "mcp"], input=stdin, capture_output=True, text=True,
                           env={**os.environ, "PATH": "/usr/bin:/bin"}, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        replies = [json.loads(line) for line in r.stdout.splitlines()]
        self.assertEqual([m.get("id") for m in replies], [1, 2, 3, 4, None])
        self.assertIn("garden-planner.md sha256:", replies[2]["result"]["content"][0]["text"])
        self.assertEqual(replies[4]["error"]["code"], -32700)
        self.assertEqual(tree_state(self.vault), before)

    def test_the_router_refuses_to_start_for_a_contribute_only_client(self):
        self.config({"machine": {"role": "client", "mode": "contribute-only"}})
        r = subprocess.run(["/bin/bash", str(ROOT / "bin/sov"), "mcp"], input="", capture_output=True, text=True,
                           env={**os.environ, "PATH": "/usr/bin:/bin"}, timeout=60)
        self.assertEqual(r.returncode, 65)
        self.assertEqual(r.stdout, "")


if __name__ == "__main__":
    unittest.main()
