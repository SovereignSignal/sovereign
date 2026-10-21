"""What sov-status says about session capture: the lane's week from sessions/MANIFEST.md,
and, for a proposal drawn from a session capture, where it came from.

The capture's frontmatter is read only when its real path is inside the vault: a source
that leads out of it (a link planted in the lane) gives no session at all. `local` says
whether this machine holds the transcript, so the console offers Open session only here.
The whole machine is a temp dir, as in the other status tests.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

import tests.test_brain_status_jobs as base

sys.path.insert(0, str(base.ROOT / "lib"))
from session_ingest import run, state  # noqa: E402

SID = "0b4f7c9e-2d1a-4c3b-9e8f-1a2b3c4d5e6f"
LANE = "claude-code-testbox"
MANIFEST = ("---\ntype: capture\nsource: %s\ncreated: 2026-10-21\ntitle: Claude Code session capture manifest\n---\n\n"
            "Last run: 2026-10-21T14:20:00Z on testbox. Items mirrored: 2. Failed: 0.\n\n"
            "Sessions this week: distilled 3, captures 2, skipped 41, waiting 1, failed 0, refused 0.\n" % LANE)
CAPTURE = ("---\ntype: capture\nsource: %s\ncreated: 2026-10-21\ntitle: Pick the judge by bake-off\n"
           "origin: claude-code-session:%s\nsession_title: \"Judge: bake-off rerun\"\nproject: sovereign\n"
           "span: 2026-10-21T09:02Z..2026-10-21T10:40Z\ndistiller: anthropic/some-model\nprompt: session-distill/v1\n"
           "kind: decision\nconfidence: high\nevidence: [T4, T9]\n---\n\nThe owner picks judges by bake-off.\n" % (LANE, SID))


class Box(base.Box):
    def lane(self):
        d = self.vault / "raw" / "tools" / LANE / "sessions"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def hub(self, source):
        """A hub lane on this machine with one proposal drawn from `source`."""
        lane = self.vault / "raw" / "workspaces" / "archivist"
        (lane / "proposals").mkdir(parents=True, exist_ok=True)
        (lane / "status.json").write_text(json.dumps({"generated_at": "2026-10-21T15:00:00Z"}))
        (lane / "proposals" / "judge-bake-off.md").write_text(
            "---\ntype: concept\nsource: %s\ncreated: 2026-10-21\ntitle: Judge bake-off\n---\n\nPick by bake-off.\n" % source)

    def run(self, hub=True):
        args = ["/usr/bin/python3", str(base.STATUS), "--json"] + ([] if hub else ["--no-hub"])
        r = subprocess.run(args, capture_output=True, text=True, env=self.env(), timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)


def claude_row(d):
    return next(h for h in d["harnesses"] if h["id"] == "claude-code")


class SessionsCount(unittest.TestCase):
    def test_the_lane_row_carries_the_weeks_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.lane() / "MANIFEST.md").write_text(MANIFEST)
            s = claude_row(b.run(hub=False))["sessions"]
        self.assertEqual(s, {"distilled": 3, "captures": 2, "skipped": 41, "waiting": 1, "failed": 0,
                             "refused": 0, "waiting_reason": None})

    def test_a_waiting_line_gives_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.lane() / "MANIFEST.md").write_text(MANIFEST + "Waiting: model unreachable since 2026-10-21T14:05Z.\n")
            s = claude_row(b.run(hub=False))["sessions"]
        self.assertEqual(s["waiting_reason"], "model unreachable since 2026-10-21T14:05Z")

    def test_reads_what_the_tick_writes(self):
        """The writer is lib/session_ingest/run.py; a change to its wording must break here."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            now = time.time()
            wm = state.Watermark(b.state, "claude-code")
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 60))
            wm.stage("a", {"verdict": "distilled", "captures": 2, "at": stamp}, write=False)
            wm.stage("b", {"verdict": "skipped:few-prompts", "at": stamp}, write=False)
            wm.stage_waiting({"reason": run.UNREACHABLE, "since": "2026-10-21T14:05:00Z"})
            run.write_manifest(b.lane(), LANE, wm, now, host="testbox", waiting=1)
            s = claude_row(b.run(hub=False))["sessions"]
        self.assertEqual(s, {"distilled": 1, "captures": 2, "skipped": 1, "waiting": 1, "failed": 0,
                             "refused": 0, "waiting_reason": "model unreachable since 2026-10-21T14:05Z"})

    def test_no_manifest_gives_null(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            b.lane()
            self.assertIsNone(claude_row(b.run(hub=False))["sessions"])
            other = [h for h in b.run(hub=False)["harnesses"] if h["id"] != "claude-code"]
        self.assertTrue(all(h.get("sessions") is None for h in other))


class SessionProvenance(unittest.TestCase):
    def proposal(self, d):
        return next(p for p in d["hub"]["proposals"] if p["slug"] == "judge-bake-off")

    def test_a_session_capture_source_gives_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.lane() / "judge.md").write_text(CAPTURE)
            b.hub("raw/tools/%s/sessions/judge.md" % LANE)
            p = self.proposal(b.run())
        self.assertEqual(p["session"], {"id": SID, "title": "Judge: bake-off rerun", "project": "sovereign",
                                        "span": "2026-10-21T09:02Z..2026-10-21T10:40Z", "evidence": ["T4", "T9"],
                                        "local": False})

    def test_local_when_this_machine_holds_the_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.lane() / "judge.md").write_text(CAPTURE)
            b.hub("raw/tools/%s/sessions/judge.md" % LANE)
            proj = b.home / ".claude" / "projects" / "-work-sovereign"
            proj.mkdir(parents=True)
            (proj / (SID + ".jsonl")).write_text("{}\n")
            self.assertTrue(self.proposal(b.run())["session"]["local"])

    def test_no_evidence_gives_an_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.lane() / "judge.md").write_text(CAPTURE.replace("evidence: [T4, T9]\n", ""))
            b.hub("raw/tools/%s/sessions/judge.md" % LANE)
            self.assertEqual(self.proposal(b.run())["session"]["evidence"], [])

    def test_a_source_that_leads_out_of_the_vault_gives_no_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            outside = b.tmp / "elsewhere.md"
            outside.write_text(CAPTURE)
            os.symlink(str(outside), str(b.lane() / "judge.md"))
            b.hub("raw/tools/%s/sessions/judge.md" % LANE)
            p = self.proposal(b.run())
        self.assertNotIn("session", p)

    def test_a_source_outside_the_sessions_folders_gives_no_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.vault / "raw" / "tools" / LANE / "memory").mkdir(parents=True)
            (b.vault / "raw" / "tools" / LANE / "memory" / "judge.md").write_text(CAPTURE)
            b.hub("raw/tools/%s/memory/judge.md" % LANE)
            self.assertNotIn("session", self.proposal(b.run()))


class ChildWireReportsUnderItsParent(unittest.TestCase):
    def test_a_missing_sessions_script_names_the_parent_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            ent = b.lane_entry("claude-code-sessions")
            ent.update(mirror=str(b.tmp / "not-here" / "sessions.sh"), parent="claude-code", lane=LANE,
                       lane_dir=str(b.vault / "raw" / "tools" / LANE / "sessions"))
            b.declare({"claude-code-sessions": ent})
            b.record({"claude-code-sessions": b.lane_run(mirror_missing=True)})
            rows = [n for n in b.run(hub=False)["needs_you"] if n.get("kind") == "mirror-missing"]
        self.assertTrue(rows)
        self.assertEqual(rows[0]["harness"], "claude-code")
        self.assertIn("sov connect claude-code --apply", rows[0]["text"])
        self.assertNotIn("sov connect claude-code-sessions", rows[0]["text"])
        self.assertTrue(rows[0]["text"].startswith("Claude Code:"), rows[0]["text"])


if __name__ == "__main__":
    unittest.main()
