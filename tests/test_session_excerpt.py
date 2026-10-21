"""The transcript reader and the excerpt it builds: what a session distiller may see.

A Claude Code transcript carries far more than the conversation: the archive's own
session-start pack (hook_success), thinking, tool inputs and results, request copies,
file snapshots. The reader keeps typed prompts, assistant text and tool names only, the
excerpt numbers and caps them, and the clean step redacts credentials. The fixture
plants one marker in every dropped kind, so "no MARK- in the excerpt" is the boundary.
"""
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import session_fixtures as fx  # noqa: E402
import session_ingest  # noqa: E402
from session_ingest import claude_code, excerpt  # noqa: E402


class SessionExcerpt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home, self.vault, self.state = fx.make_home(self.tmp.name)
        self.cwd = Path(self.tmp.name, "work", "proj")
        self.cwd.mkdir(parents=True)

    def write(self, prompts, **kw):
        return fx.transcript(self.home, "-work-proj", kw.pop("sid", "11111111-aaaa"), self.cwd, prompts, **kw)

    def test_readers_seam(self):
        self.assertIs(session_ingest.READERS["claude-code"], claude_code)
        self.assertEqual(claude_code.TOOL, "claude-code")
        self.assertEqual(claude_code.LANE_PREFIX, "claude-code")

    def test_lists_top_level_only(self):
        a = self.write(["one", "two", "three"])
        b = fx.transcript(self.home, "-other", "22222222-bbbb", self.cwd, ["hi"])
        projects = self.home / ".claude" / "projects"
        (projects / "-work-proj" / "workflows").mkdir()
        (projects / "-work-proj" / "workflows" / "w.jsonl").write_text("{}\n")
        os.symlink(a, projects / "-other" / "linked.jsonl")
        os.symlink(projects / "-work-proj", projects / "-linked-dir")
        found = claude_code.list_transcripts(self.home)
        self.assertEqual(sorted(found), sorted([a, b]))
        for p in found:
            self.assertNotIn("subagents", p)
            self.assertNotIn("tool-results", p)

    def test_no_marker_survives(self):
        path = self.write(["first prompt", "second prompt", "third prompt"])
        planted = Path(path).read_text() + "".join(
            p.read_text() for p in Path(path).with_suffix("").rglob("*.jsonl"))
        for mark in fx.MARKERS:
            self.assertIn(mark, planted, "the fixture plants " + mark)
        s = claude_code.scan(path)
        text, ids = excerpt.build(s["turns"])
        self.assertEqual(ids, [1, 2, 3])
        for mark in fx.MARKERS:
            self.assertNotIn(mark, text, mark)
        self.assertNotIn("MARK-", text)
        self.assertIn("T1 user: first prompt", text)

    def test_keys_redacted(self):
        path = self.write(["one", "two", "three"])
        self.assertTrue(all(k in Path(path).read_text() for k in fx.KEYS), "the fixture plants keys")
        s = claude_code.scan(path)
        self.assertTrue(any(k in b for t in s["turns"] for b in t["assistant"] for k in fx.KEYS))
        raw, _ = excerpt.build(s["turns"])
        for k in fx.KEYS:
            self.assertNotIn(k, raw, "build redacts before it cuts")
        clean, dropped = excerpt.clean(raw)
        for k in fx.KEYS:
            self.assertNotIn(k, clean)
        self.assertIn("[redacted", clean)
        self.assertIsInstance(dropped, int)
        self.assertEqual(excerpt.clean(clean), (clean, 0), "clean is idempotent")

    def _excerpt(self, prompt="typed", assistant=()):
        text, _ = excerpt.build([{"n": 1, "prompt": prompt, "assistant": list(assistant), "tools": []}])
        return text, excerpt.clean(text)[0]

    def test_pem_past_the_cut(self):
        body = ["".join(chr(65 + (i * 7 + j) % 26) for j in range(60)) + "%04d" % i for i in range(60)]
        pem = "-----BEGIN " + "PRIVATE KEY-----\n" + "\n".join(body) + "\n-----END " + "PRIVATE KEY-----"
        self.assertGreater(len(pem), excerpt.PROMPT_CUT)
        for text in self._excerpt("here is the key\n" + pem + "\nthanks"):
            for line in body:
                self.assertNotIn(line, text)
            self.assertNotIn("BEGIN " + "PRIVATE", text)

    def test_key_straddling_the_cut(self):
        key = "gh" + "p_" + "B" * 36
        for text in self._excerpt("x" * 1480 + " " + key):
            self.assertNotIn("gh" + "p_", text)
            self.assertNotIn("B" * 10, text)

    def test_key_past_the_assistant_cut(self):
        key = "gh" + "p_" + "C" * 36
        for text in self._excerpt(assistant=["y " * 290 + key + " tail"]):
            self.assertNotIn("gh" + "p_", text)
            self.assertNotIn("C" * 10, text)
        for text in self._excerpt(assistant=["z " * 400 + key]):
            self.assertNotIn("gh" + "p_", text)

    def test_cut_backs_off_to_whitespace(self):
        text, _ = self._excerpt(("word " * 400).strip())
        line = text.splitlines()[0]
        self.assertTrue(line.endswith("word…"), line[-20:])
        self.assertLessEqual(len(line) - len("T1 user: "), excerpt.PROMPT_CUT + 1)

    def test_embedded_reminder_stripped(self):
        path = self.write(["one", "two", "three"])
        with open(path, "a") as fh:
            fh.write(json.dumps({"type": "user", "sessionId": "11111111-aaaa", "message": {"content": [
                {"type": "text", "text": "keep this typed text <system-reminder>MARK-PACK card text\nmore</system-reminder> and this"}]}}) + "\n")
            fh.write(json.dumps({"type": "user", "sessionId": "11111111-aaaa",
                                 "message": {"content": "second typed <system-reminder>MARK-PACK unclosed"}}) + "\n")
        s = claude_code.scan(path)
        self.assertEqual(s["turns"][3]["prompt"], "keep this typed text  and this")
        self.assertEqual(s["turns"][4]["prompt"], "second typed")
        text, _ = excerpt.build(s["turns"])
        self.assertNotIn("MARK-PACK", text)
        self.assertNotIn("system-reminder", text)

    def test_nul_cwd_line_skipped(self):
        path = self.write(["one", "two", "three"])
        with open(path) as fh:
            lines = fh.readlines()
        lines.insert(8, json.dumps({"type": "user", "cwd": "a\u0000b", "message": {"content": "MARK-NUL"}}) + "\n")
        lines.insert(9, json.dumps({"type": "user", "cwd": 7, "message": {"content": "MARK-NUL"}}) + "\n")
        with open(path, "w") as fh:
            fh.writelines(lines)
        s = claude_code.scan(path, cwd_check=lambda real: None)
        self.assertEqual([t["prompt"] for t in s["turns"]], ["one", "two", "three"])
        self.assertEqual(s["cwds"], [os.path.realpath(self.cwd)])

    def test_clean_drops_tripped_line(self):
        # redact_text leaves this label-shaped value, secret_hits still sees it
        line = "T2 user: password: " + "abcdefgh" + "ijklmnop1"
        text, dropped = excerpt.clean("T1 user: fine\n" + line + "\nT3 user: also fine")
        self.assertEqual(text.splitlines()[1], "[line dropped]")
        self.assertEqual(dropped, 1)
        self.assertIn("T1 user: fine", text)
        self.assertIn("T3 user: also fine", text)

    def test_cuts(self):
        s = claude_code.scan(self.write(["p" * 2000, "two", "three"], assistant="a" * 900))
        text, _ = excerpt.build(s["turns"])
        lines = text.splitlines()
        self.assertIn("T1 user: " + "p" * 1500 + "…", lines)
        self.assertNotIn("p" * 1501, text)
        self.assertIn("T1 assistant: " + "a" * 600 + "…", lines)
        self.assertNotIn("a" * 601, text)

    def test_numbering_and_tools(self):
        turns = [
            {"n": 1, "prompt": "fix it", "assistant": ["Looking.", "Fixed."], "tools": ["Read", "Edit", "Edit", "Edit", "Bash"]},
            {"n": 2, "prompt": "line one\nline two", "assistant": [], "tools": []},
        ]
        text, ids = excerpt.build(turns)
        self.assertEqual(text.splitlines(), [
            "T1 user: fix it",
            "T1 assistant: Looking.",
            "T1 assistant: Fixed.",
            "[tool: Read]",
            "[tool: Edit] x3",
            "[tool: Bash]",
            "T2 user: line one",
            "  line two",
        ])
        self.assertEqual(ids, [1, 2])
        s = claude_code.scan(self.write(["one", "two", "three"]))
        self.assertEqual([t["n"] for t in s["turns"]], [1, 2, 3])
        self.assertEqual([t["prompt"] for t in s["turns"]], ["one", "two", "three"])
        self.assertEqual(s["turns"][0]["tools"], ["Edit"])
        self.assertEqual(s["turns"][2]["assistant"], ["Done."])

    def test_cap(self):
        turns = [{"n": i, "prompt": "q%d " % i + "x" * 900, "assistant": ["ok"], "tools": ["Edit"]} for i in range(1, 41)]
        text, ids = excerpt.build(turns, hit_turns=frozenset({20}))
        self.assertLessEqual(len(text), 24000)
        self.assertLessEqual(len(excerpt.clean(text)[0]), 24000)
        for n in (1, 2, 3, 20, 40):
            self.assertIn(n, ids)
            self.assertTrue(("T%d user: q%d " % (n, n)) in text, n)
        self.assertNotIn(10, ids)
        self.assertTrue(re.search(r"^\[T4\.\.T\d+ omitted\]$", text, re.M), "one line for the gap after T3")
        self.assertEqual(text.count("omitted]"), 1)
        self.assertEqual(ids, sorted(ids))
        small, all_ids = excerpt.build(turns[:5])
        self.assertEqual(all_ids, [1, 2, 3, 4, 5])
        self.assertNotIn("omitted", small)

    def test_metadata(self):
        path = self.write(["one", "two", "three"], sid="33333333-cccc", entrypoint="sdk-py", sidechain=True,
                          extra_cwds=[str(self.tmp.name) + "/work"])
        s = claude_code.scan(path)
        self.assertEqual(s["id"], "33333333-cccc")
        self.assertEqual(s["path"], path)
        self.assertEqual(s["size"], os.path.getsize(path))
        self.assertEqual(s["mtime"], os.path.getmtime(path))
        self.assertEqual(s["cwds"], [os.path.realpath(self.cwd), os.path.realpath(self.tmp.name + "/work")])
        self.assertEqual(s["entrypoint"], "sdk-py")
        self.assertTrue(s["sidechain"])
        self.assertEqual(s["title"], "Synthetic session")
        self.assertTrue(s["first_ts"] < s["last_ts"])
        self.assertTrue(s["last_ts"].endswith("Z"))
        self.assertIsNone(s["stopped"])
        plain = claude_code.scan(self.write(["one"], sid="44444444-dddd"))
        self.assertFalse(plain["sidechain"])
        self.assertEqual(plain["entrypoint"], "cli")

    def test_id_falls_back_to_stem(self):
        path = self.home / ".claude" / "projects" / "-work-proj" / "55555555-eeee.jsonl"
        path.parent.mkdir()
        path.write_text('{"type": "user", "message": {"content": "hello"}}\n')
        s = claude_code.scan(str(path))
        self.assertEqual(s["id"], "55555555-eeee")
        self.assertEqual(len(s["turns"]), 1)

    def test_cwd_check_stops(self):
        bad = os.path.realpath(self.tmp.name + "/work")
        path = self.write(["one", "two", "three"], extra_cwds=[bad])
        seen = []

        def check(real):
            seen.append(real)
            return "refused-archive" if real == bad else None

        s = claude_code.scan(path, cwd_check=check)
        self.assertEqual(s["stopped"], "refused-archive")
        self.assertEqual(s["turns"], [])
        self.assertEqual(seen, [os.path.realpath(self.cwd), bad])
        ok = claude_code.scan(path, cwd_check=lambda real: None)
        self.assertIsNone(ok["stopped"])
        self.assertEqual(len(ok["turns"]), 3)

    def test_malformed_line_skipped(self):
        path = self.write(["one", "two", "three"])
        with open(path) as fh:
            lines = fh.readlines()
        lines.insert(8, "{not json\n")
        lines.insert(9, "[1, 2]\n")
        lines.insert(10, "\n")
        with open(path, "w") as fh:
            fh.writelines(lines)
        with open(path, "ab") as fh:
            fh.write(b'{"type": "user", "message": {"content": "cut off')
        s = claude_code.scan(path)
        self.assertEqual([t["prompt"] for t in s["turns"]], ["one", "two", "three"])

    def test_model_stub(self):
        replies = iter([500, '{"captures": []}'])
        with fx.ModelStub(lambda body: next(replies)) as stub:
            req = lambda: urllib.request.Request(stub.url, json.dumps({"messages": []}).encode(),
                                                 {"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(req(), timeout=5)
            out = json.load(urllib.request.urlopen(req(), timeout=5))
            self.assertEqual(out["choices"][0]["message"]["content"], '{"captures": []}')
            self.assertEqual(stub.calls, 2)
            self.assertEqual(stub.requests[0], {"messages": []})
            self.assertTrue(stub.url.startswith("http://127.0.0.1:"))


if __name__ == "__main__":
    unittest.main()
