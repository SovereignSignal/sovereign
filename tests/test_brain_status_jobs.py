"""sov-status after the connector jobs collapse into one.

The danger in this change is not the data path, it is the monitoring. Every tool used
to be "connected" because a launchd job carried its name; now one job carries them all.
If the status keeps asking launchd for a per-tool label, every tool reads "not
connected" while the mirrors keep working perfectly: the console goes red across the
board and `sov connect all` reinstalls everything on every run. So this file pins the
replacement signal (the manifest plus the run record), the synthetic job rows the
console renders, the five needs_you rules that make a silent lane loud, and the error log
each kind of job row points at -- a row aimed at a file nothing writes reports a failing
job as one with no log, which reads as "never ran".

launchctl is stubbed on PATH and the whole machine is a temp dir: without that, the run
picks up the developer's real jobs and passes for the wrong reason.
"""
import contextlib
import datetime
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests.test_calendar_lane as cal
import tests.test_connectors_install as ti

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "connectors" / "harness"
STATUS = ROOT / "bin" / "sov-status"
RUNNER_LABEL = "com.sovereign.connector.runner"

LAUNCHCTL = """#!/bin/bash
case "$1" in
  list)  printf 'PID\\tStatus\\tLabel\\n-\\t0\\t%s\\n' "$SOV_STUB_LABELS" ;;
  print) echo "last exit code = 0" ;;
esac
exit 0
"""


def iso(seconds_ago=0):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Box:
    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.state = self.tmp / "state"
        self.stub = self.tmp / "stub"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        (self.vault / "knowledge" / "entities").mkdir(parents=True)
        (self.vault / "raw" / "tools").mkdir(parents=True)
        (self.vault / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n\nThe owner.\n")
        (self.home / ".brain-root").write_text(str(self.vault))
        (self.home / ".brain-host").write_text("testbox")
        (self.state / "lanes").mkdir(parents=True)
        self.stub.mkdir()
        p = self.stub / "launchctl"
        p.write_text(LAUNCHCTL)
        p.chmod(0o755)
        self.labels = RUNNER_LABEL
        self.plist(RUNNER_LABEL)

    def plist(self, label, program="/usr/bin/python3"):
        (self.home / "Library" / "LaunchAgents" / (label + ".plist")).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '<key>Label</key><string>%s</string>\n'
            '<key>ProgramArguments</key><array><string>%s</string></array>\n'
            '<key>StartInterval</key><integer>900</integer>\n'
            '<key>StandardErrorPath</key><string>%s/%s.error.log</string>\n'
            '</dict></plist>\n' % (label, program, self.state, label))

    def read_wires(self):
        """The read half of each harness this file declares, so state can reach 'connected'."""
        (self.home / ".claude").mkdir(exist_ok=True)
        (self.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"matcher": "startup", "hooks": [{"type": "command", "command": str(H / "claude-code" / "session-start.py")}]}]}}))
        (self.home / ".cursor").mkdir(exist_ok=True)
        (self.home / ".cursor" / "hooks.json").write_text(json.dumps({"version": 1, "hooks": {"sessionStart": [
            {"command": str(H / "cursor" / "session-start.py"), "timeout": 30}]}}))

    def declare(self, harnesses, interval_s=900):
        (self.state / "connectors.json").write_text(json.dumps({
            "version": 1,
            "runner": {"label": RUNNER_LABEL, "interval_s": interval_s,
                       "state_dir": str(self.state), "log_dir": str(self.state / "lanes")},
            "harnesses": harnesses}, indent=2))

    def record(self, lanes, **runner):
        r = {"label": RUNNER_LABEL, "host": "testbox", "interval_s": 900, "pid": 41231,
             "tick_started": iso(8), "tick_finished": iso(1),
             "lanes_declared": len(lanes), "lanes_due": len(lanes), "lanes_ran": len(lanes),
             "lanes_failed": 0, "lanes_timed_out": 0,
             "skipped_overlap": False, "reclaimed_lock": False}
        r.update(runner)
        (self.state / "runs.json").write_text(json.dumps({"version": 1, "runner": r, "lanes": lanes}, indent=2))

    def lane_entry(self, hid, cadence_s=900):
        (self.state / "lanes" / (hid + ".log")).write_text("")
        (self.state / "lanes" / (hid + ".error.log")).write_text("")
        return {"label": "com.sovereign.connector.%s" % hid,
                "mirror": str(H / hid / "mirror.sh"), "lane": "%s-testbox" % hid,
                "lane_dir": str(self.vault / "raw" / "tools" / ("%s-testbox" % hid)),
                "cadence_s": cadence_s, "timeout_s": 300, "enabled": True,
                "env": {}, "registered": "2026-01-01"}

    def lane_run(self, cadence_s=900, checked_ago=60, **over):
        rec = {"enabled": True, "cadence_s": cadence_s, "timeout_s": 300,
               "checked_at": iso(checked_ago), "attempted_at": iso(checked_ago),
               "finished_at": iso(checked_ago - 2 if checked_ago > 2 else 0),
               "duration_s": 2.14, "last_exit": 0, "timed_out": False, "in_flight": False,
               "skipped": None, "mirror_missing": False}
        rec.update(over)
        return rec

    def env(self):
        return {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.stub,
                "BRAIN_ROOT": str(self.vault), "SOV_STATE_DIR": str(self.state),
                "SOV_MANIFEST": str(self.state / "connectors.json"),
                "SOV_STUB_LABELS": self.labels}

    def status(self):
        r = subprocess.run(["/usr/bin/python3", str(STATUS), "--json", "--no-hub"],
                           capture_output=True, text=True, env=self.env(), timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    def tick(self, args=()):
        """The real runner over this machine's real manifest. A hand-written runs.json
        can only prove what the console does with a record; a record the shipped runner
        actually wrote is what proves the two halves agree."""
        return subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-connectors-run")] + list(args),
                              capture_output=True, text=True, env=self.env(), timeout=180)


class Connected(unittest.TestCase):
    IDS = ("claude-code", "cursor", "orca")

    def box(self, tmp, cadences=(900, 900, 1800)):
        b = Box(tmp)
        b.read_wires()
        b.declare({h: b.lane_entry(h, c) for h, c in zip(self.IDS, cadences)})
        b.record({h: b.lane_run(c) for h, c in zip(self.IDS, cadences)})
        return b

    def test_exit_zero_keeps_recent_errors_visible_without_claiming_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
            (b.state / "lanes/claude-code.error.log").write_text("capture failed " + token + "\n")
            d = b.status()
            issue = next(n for n in d["needs_you"] if n.get("harness") == "claude-code")
            self.assertIn("last run exited 0", issue["text"])
            self.assertIn("skipped source does not verify recovery", issue["verify"])
            self.assertIn("capture failed", issue["failure_output"])
            self.assertNotIn(token, issue["failure_output"])
            self.assertIn("[redacted", issue["failure_output"])

    def test_one_launchd_row_still_reports_every_tool_connected(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            by_id = {h["id"]: h for h in d["harnesses"]}
            for h in self.IDS:
                self.assertTrue(by_id[h]["job_loaded"], h)
                self.assertEqual(by_id[h]["state"], "connected", h)
                self.assertEqual(by_id[h]["label"], "com.sovereign.connector.%s" % h,
                                 "the logical lane id keeps its exact old value")

    def test_claude_hook_is_validated_as_a_command_not_a_substring(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            memory = b.home / ".claude" / "projects" / "-tmp-demo" / "memory"
            memory.mkdir(parents=True)
            (memory / "preference.md").write_text("---\ntype: preference\nsource: owner\n---\nRemember this.\n")
            hook = str(H / "claude-code" / "session-start.py")
            (b.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
                {"matcher": "startup|resume", "hooks": [{
                    "type": "command",
                    "command": "PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 %s" % hook,
                }]}]}}))
            got = next(h for h in b.status()["harnesses"] if h["id"] == "claude-code")
            self.assertEqual(got["state"], "connected")
            self.assertIsNone(got["hook_issue"])
            checks = {x["label"]: x for x in got["diagnostics"]}
            self.assertEqual(checks["Read hook"]["state"], "ok")
            self.assertEqual(checks["Memory source"]["state"], "ok")
            self.assertIn("1 project memory", checks["Memory source"]["detail"])

    def test_claude_settings_can_look_registered_and_still_never_run(self):
        cases = (
            ("malformed JSON", "{not json " + str(H / "claude-code" / "session-start.py"), "not valid JSON"),
            ("matcher drift", json.dumps({"hooks": {"SessionStart": [
                {"matcher": "resume", "hooks": [{"type": "command", "command": str(H / "claude-code" / "session-start.py")}]}]}}),
             "no longer runs at session startup"),
            ("missing interpreter", json.dumps({"hooks": {"SessionStart": [
                {"matcher": "startup", "hooks": [{"type": "command",
                    "command": "/missing/python %s" % (H / "claude-code" / "session-start.py")}]}]}}),
             "Python named by the Sovereign hook is missing"),
        )
        for name, settings, issue in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                b = self.box(tmp)
                (b.home / ".claude" / "settings.json").write_text(settings)
                d = b.status()
                got = next(h for h in d["harnesses"] if h["id"] == "claude-code")
                self.assertEqual(got["state"], "partial")
                self.assertFalse(got["hook_registered"])
                self.assertIn(issue, got["hook_issue"])
                checks = {x["label"]: x for x in got["diagnostics"]}
                self.assertEqual(checks["Read hook"]["state"], "bad")
                need = next(n for n in d["needs_you"] if n.get("harness") == "claude-code")
                self.assertIn("Reinstall", need["action"])
                self.assertIn("fresh Muse session", need["verify"])

    def test_every_harness_names_the_job_that_actually_runs_it_and_its_own_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            by_id = {h["id"]: h for h in d["harnesses"]}
            for h, cad in zip(self.IDS, (900, 900, 1800)):
                self.assertEqual(by_id[h]["kick"], RUNNER_LABEL, h)
                self.assertEqual(by_id[h]["runs_in"], RUNNER_LABEL, h)
                self.assertEqual(by_id[h]["cadence_s"], cad, h)

    def test_the_console_gets_a_row_per_lane_and_can_parse_every_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            labels = [j["label"] for j in d["jobs"]]
            self.assertEqual(len(labels), len(set(labels)), "duplicate job rows: %s" % labels)
            self.assertIn(RUNNER_LABEL, labels)
            for h in self.IDS:
                row = next(j for j in d["jobs"] if j["label"] == "com.sovereign.connector.%s" % h)
                self.assertEqual(row["kick"], RUNNER_LABEL, h)
                self.assertEqual(row["harness"], h)
                self.assertTrue(row["stderr"].endswith("lanes/%s.error.log" % h), h)
                self.assertEqual(row["stderr_lines"], 0, "a clean lane reports 0, never null")
                self.assertRegex(row["schedule"], r"^every \d+s$")
            for h in self.IDS:
                info = next(x for x in d["harnesses"] if x["id"] == h)["plist"]
                self.assertRegex(info["schedule"], r"every (\d+)s", h)
                self.assertEqual(int(re.search(r"every (\d+)s", info["schedule"]).group(1)),
                                 next(x for x in d["harnesses"] if x["id"] == h)["cadence_s"])

    def test_the_mover_reports_each_source_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            gone = b.tmp / "Codex"
            here = b.tmp / "Claude"
            here.mkdir()
            m = json.loads((b.state / "connectors.json").read_text())
            m["relay"] = {"label": "com.sovereign.connector.relay", "enabled": True, "interval_s": 900,
                          "dest": str(b.vault / "raw" / "tools") + "/", "excludes": [],
                          "sources": [{"path": str(b.home / ".vault-staging" / "raw" / "tools") + "/",
                                       "kind": "staging", "name": "(contents)", "trailing_slash": True},
                                      {"path": str(here), "kind": "dir", "name": "Claude", "trailing_slash": False},
                                      {"path": str(gone), "kind": "dir", "name": "Codex", "trailing_slash": False}]}
            (b.state / "connectors.json").write_text(json.dumps(m, indent=2))
            d = b.status()
            by_name = {s["name"]: s for s in d["relay"]["sources"]}
            self.assertTrue(by_name["Claude"]["exists"])
            self.assertFalse(by_name["Codex"]["exists"])
            need = [n for n in d["needs_you"] if n["kind"] == "relay"]
            self.assertTrue(need, "a declared source that vanished is a problem, and the row must name it")
            self.assertIn("Codex", " ".join(n["text"] for n in need))


class Loudness(unittest.TestCase):
    """The one failure mode consolidation could invent: a lane quietly dropped from the
    loop, with the shared job still green. Each of these must produce a row a human sees."""

    def one(self, tmp, run_over=None, runner_over=None, cadence_s=900):
        b = Box(tmp)
        b.read_wires()
        b.declare({"orca": b.lane_entry("orca", cadence_s)})
        b.record({"orca": b.lane_run(cadence_s, **(run_over or {}))}, **(runner_over or {}))
        return b

    def kinds(self, d, kind):
        return [n for n in d["needs_you"] if n.get("kind") == kind]

    def test_a_lane_the_runner_stopped_visiting_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.one(tmp, run_over={"checked_at": iso(3 * 900)}).status()
            rows = self.kinds(d, "lane-silent")
            self.assertTrue(rows, "an enabled lane not visited for twice its cadence must be loud")
            self.assertEqual(rows[0]["harness"], "orca", "the console routes a need with .harness to Tools")

    def test_a_hung_mirror_is_told_apart_from_a_failing_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.one(tmp, run_over={"timed_out": True, "last_exit": 124}).status()
            rows = self.kinds(d, "lane-timeout")
            self.assertTrue(rows)
            self.assertEqual(rows[0]["harness"], "orca")

    def test_a_runner_that_stopped_finishing_ticks_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.one(tmp, runner_over={"tick_finished": iso(3 * 900)}).status()
            self.assertTrue(self.kinds(d, "runner-stalled"))

    def test_a_declared_mirror_that_is_gone_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.one(tmp, run_over={"mirror_missing": True})
            m = json.loads((b.state / "connectors.json").read_text())
            m["harnesses"]["orca"]["mirror"] = str(b.tmp / "not-here" / "mirror.sh")
            (b.state / "connectors.json").write_text(json.dumps(m, indent=2))
            rows = self.kinds(b.status(), "mirror-missing")
            self.assertTrue(rows)
            self.assertEqual(rows[0]["harness"], "orca")

    def test_a_failing_lane_keeps_its_own_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.one(tmp, run_over={"last_exit": 7}).status()
            row = next(j for j in d["jobs"] if j["label"] == "com.sovereign.connector.orca")
            self.assertEqual(row["last_exit"], 7, "a lane failure keeps DOWN severity in the console")
            self.assertTrue([n for n in d["needs_you"] if "orca" in n.get("text", "")])


class Refused(unittest.TestCase):
    """A lane the runner will not run at all, end to end: the shipped runner writes the
    record, the shipped status reads it.

    This is the quietest failure the shared job can produce and the one the whole change
    exists to remove. The tick finishes, the job exits 0, the lane's error log stays
    empty, the last exit code from the last good run is still 0, and nothing mirrors.
    Both halves are run for real here because each is green on its own: the runner
    stamping "I visited this lane" is exactly what stops the console noticing.
    """

    def box(self, tmp, timeout_s=300, mirror_ok=True):
        b = Box(tmp)
        b.read_wires()
        out = b.tmp / "out"
        out.mkdir()
        m = b.tmp / "mirror.sh"
        m.write_text('#!/bin/bash\nset -uo pipefail\necho ran >> "%s/orca"\nexit 0\n' % out)
        m.chmod(0o755)
        ent = b.lane_entry("orca")
        ent.update({"mirror": str(m) if mirror_ok else str(b.tmp / "gone" / "mirror.sh"),
                    "timeout_s": timeout_s})
        b.declare({"orca": ent})
        b.out = out
        return b

    def refuse(self, b, **over):
        m = json.loads((b.state / "connectors.json").read_text())
        m["harnesses"]["orca"].update(over)
        (b.state / "connectors.json").write_text(json.dumps(m, indent=2))

    def needs_for(self, d, hid):
        return [n for n in d["needs_you"] if n.get("harness") == hid]

    def test_a_lane_whose_timeout_outgrew_the_tick_stops_reading_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            r = b.tick()
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual((b.out / "orca").read_text().count("\n"), 1, "the healthy tick ran the mirror")
            self.assertFalse(self.needs_for(b.status(), "orca"), "a healthy lane needs nobody")
            # the tick did not change; this lane's declared bound outgrew it
            self.refuse(b, timeout_s=1800)
            r = b.tick(["--force"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("orca", r.stderr, "the runner names the lane it refuses")
            self.assertEqual((b.out / "orca").read_text().count("\n"), 1, "the mirror did not run")
            d = b.status()
            lane = json.loads((b.state / "runs.json").read_text())["lanes"]["orca"]
            self.assertEqual(lane["skipped"], "timeout exceeds interval")
            self.assertNotEqual(lane.get("last_exit"), 0,
                                "the last good run's exit code carried forward reads as a lane that just succeeded")
            rows = self.needs_for(d, "orca")
            self.assertTrue(rows, "the lane mirrors nothing and the console says nothing at all")
            self.assertEqual(rows[0]["kind"], "lane-refused")
            self.assertIn("1800", rows[0]["text"], "the row says what is wrong with the declaration")

    def test_a_lane_whose_mirror_is_gone_stops_reading_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            self.assertEqual(b.tick().returncode, 0)
            self.refuse(b, mirror=str(b.tmp / "gone" / "mirror.sh"))
            r = b.tick(["--force"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("orca", r.stderr)
            rows = self.needs_for(b.status(), "orca")
            self.assertTrue(rows, "a declared mirror that is gone mirrors nothing, quietly")
            self.assertEqual(rows[0]["kind"], "mirror-missing")

    def test_a_refusal_cured_on_disk_clears_without_waiting_for_a_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, timeout_s=1800)
            self.assertEqual(b.tick().returncode, 0)
            self.assertTrue(self.needs_for(b.status(), "orca"), "refused from the very first tick")
            self.refuse(b, timeout_s=300)
            rows = self.needs_for(b.status(), "orca")
            self.assertFalse(rows, "the declaration is fixed; the console must not stay red "
                                   "until a tick proves it: %s" % rows)

    def test_a_missing_mirror_restored_on_disk_clears_without_waiting_for_a_tick(self):
        """The other half of the same rule, and the reason a copied verdict cannot be
        trusted at all: both refusals are recomputed from the current declaration and the
        current disk, so a row built on the stale one carries a reason its own text then
        contradicts."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, mirror_ok=False)
            self.assertEqual(b.tick().returncode, 0)
            rows = self.needs_for(b.status(), "orca")
            self.assertTrue(rows, "a declared mirror that is gone mirrors nothing, quietly")
            self.assertEqual(rows[0]["kind"], "mirror-missing")
            gone = Path(json.loads((b.state / "connectors.json").read_text())["harnesses"]["orca"]["mirror"])
            gone.parent.mkdir(parents=True, exist_ok=True)
            gone.write_text("#!/bin/bash\nexit 0\n")
            gone.chmod(0o755)
            rows = self.needs_for(b.status(), "orca")
            self.assertFalse(rows, "the mirror is back on disk and the console still says it is gone: %s" % rows)


class Migration(unittest.TestCase):
    def test_a_machine_still_running_its_old_per_tool_job_reports_from_that_row(self):
        """The fleet moves one machine at a time, so the legacy label is checked first."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            b.read_wires()
            b.plist("com.sovereign.connector.orca", program="/bin/bash")
            b.labels = "com.sovereign.connector.orca"          # the runner is not loaded here
            b.declare({"orca": b.lane_entry("orca")})
            b.record({"orca": b.lane_run()})
            d = b.status()
            orca = next(h for h in d["harnesses"] if h["id"] == "orca")
            self.assertTrue(orca["job_loaded"])
            self.assertEqual(orca["state"], "connected")
            labels = [j["label"] for j in d["jobs"]]
            self.assertEqual(labels.count("com.sovereign.connector.orca"), 1,
                             "the real row and a synthetic row for the same lane would double-count it")


class MoverRowOnAMac(unittest.TestCase):
    """The same question on the other platform, asked of the shipped command.

    A Mac row reads its error log out of the plist, so the row and the job cannot disagree
    about the path -- but only if the mover gets a row at all, and only if the log the
    plist names is the one the mover really writes."""

    def machine(self, tmp):
        b = ti.Box(tmp)
        r = b.connect("windsurf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        watched = b.tmp / "Claude"
        watched.mkdir()
        r = b.relay("add", [str(watched)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return b

    def test_the_movers_row_counts_the_lines_in_the_log_it_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            written = b.relay_plist()["StandardErrorPath"]
            Path(written).parent.mkdir(parents=True, exist_ok=True)
            Path(written).write_text("rsync error: some files could not be transferred (code 23)\n")
            r = subprocess.run(["/usr/bin/python3", str(STATUS), "--json", "--no-hub"],
                               capture_output=True, text=True, env=b.env(), timeout=180)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            d = json.loads(r.stdout)
            rows = [j for j in d["jobs"] if j["label"] == "com.sovereign.connector.relay"]
            self.assertEqual(len(rows), 1, "the mover has no row, or two: %s" % [j["label"] for j in d["jobs"]])
            self.assertEqual(rows[0]["stderr"], written)
            self.assertEqual(rows[0]["stderr_lines"], 1,
                             "a mover failing every tick reads as one with no log at all")
            self.assertIsNone(rows[0].get("harness"),
                              "the mover was given a LANE row: no lane owns it and the runner "
                              "never carries it, so there is no run record behind that row")


class LinuxJobLogs(unittest.TestCase):
    """Where a Linux job row looks for its error log.

    Every unit is named `<label>.error.log` except one: the mover writes `relay.error.log`.
    A row pointed at a file the installer never creates reports `stderr_lines: null`, which
    the console renders as "no log file" and a reader takes as "never ran" -- so a mover
    failing on every tick reads as a mover nobody has to look at. That is the exact silent
    failure this whole change exists to remove.

    On a Mac `sys.platform` sends every row through `plist_info`, which reads the path out
    of the plist and cannot disagree with it. The systemd half is therefore unreachable
    from a subprocess here, and this is the one place in the file that calls the reader's
    functions directly rather than running the command.
    """

    def reader(self):
        # the command has no .py extension, so the loader is named rather than guessed
        loader = importlib.machinery.SourceFileLoader("brain_status_under_test", str(STATUS))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(mod)
        return mod

    @contextlib.contextmanager
    def as_machine(self, b):
        """The reader resolves ~ and the state directory from the environment, so the
        throwaway box has to be the environment for the length of the call."""
        old = dict(os.environ)
        os.environ["HOME"] = str(b.home)
        os.environ["SOV_STATE_DIR"] = str(b.state)
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(old)

    def stderr_of(self, unit):
        """The file that unit really writes its stderr to."""
        for line in Path(unit).read_text().splitlines():
            if line.startswith("StandardError="):
                return line.split("=", 1)[1].split(":", 1)[1]
        self.fail("%s sets no StandardError: a job whose failures go nowhere is the "
                  "failure mode every mirror agent must not have" % unit)

    def units_dir(self, b):
        return b.home / ".config" / "systemd" / "user"

    def machine(self, tmp):
        """A Linux box carrying all three kinds of job: the shared runner, a mover for a
        declared directory pipe, and a calendar lane with a job of its own."""
        b = ti.Box(tmp, platform="Linux")
        r = b.connect("windsurf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        watched = b.tmp / "Claude"
        watched.mkdir()
        r = b.relay("add", [str(watched)])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = cal.connect_calendar(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return b

    def test_the_movers_row_points_at_the_log_its_unit_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            written = self.stderr_of(self.units_dir(b) / "sovereign-connector-relay.service")
            Path(written).parent.mkdir(parents=True, exist_ok=True)
            Path(written).write_text("rsync error: some files could not be transferred (code 23)\n")
            manifest = json.loads((b.state / "connectors.json").read_text())
            mod = self.reader()
            with self.as_machine(b):
                row = mod.unit_info(mod.relay_label(manifest), manifest)
            self.assertEqual(row["stderr"], written,
                             "a mover failing every tick reads as one with no log at all")
            self.assertEqual(row["stderr_lines"], 1,
                             "the console counted no lines in a log that has one")
            self.assertTrue(row["plist"], "the row does not name the unit the mover is declared in")

    def test_the_runner_and_a_calendar_lane_keep_their_own_names(self):
        """The mover is the one exception. A fix that generalized would point the runner's
        row, or a calendar lane's, at a file nothing writes -- the same blindness moved."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            manifest = json.loads((b.state / "connectors.json").read_text())
            mod = self.reader()
            calendar_label = "sovereign-connector-%s" % cal.CALENDAR
            with self.as_machine(b):
                runner_row = mod.unit_info(mod.runner_label(manifest), manifest)
                calendar_row = mod.unit_info(calendar_label, manifest)
            self.assertEqual(runner_row["stderr"],
                             self.stderr_of(self.units_dir(b) / "sovereign-connector-runner.service"))
            self.assertEqual(calendar_row["stderr"],
                             self.stderr_of(self.units_dir(b) / (calendar_label + ".service")))
            self.assertNotEqual(runner_row["stderr"], calendar_row["stderr"])

    def test_the_movers_label_can_never_become_a_lane_row(self):
        """A job row for the mover is right; a LANE row for it would be invented from a run
        record that does not exist, because the runner never carries the mover. The only
        source of lane rows is the manifest's harnesses, and both shared names are refused
        there -- so the two can never collide."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            manifest = json.loads((b.state / "connectors.json").read_text())
            self.assertEqual(manifest["relay"]["label"], "sovereign-connector-relay")
            for reserved in ("relay", "runner"):
                self.assertNotIn(reserved, manifest["harnesses"])
            shim = Path(tmp) / "reserve.sh"
            shim.write_text('#!/bin/bash\nTEMPLATE="%s"\nHARNESS="$1"; LANE_PREFIX=x\n'
                            '. "$TEMPLATE/connectors/harness/_lib/install-common.sh"\n'
                            'VAULT="%s"; HOST=testbox\nsov_resolve\n' % (ROOT, b.vault))
            shim.chmod(0o755)
            for reserved in ("relay", "runner"):
                r = subprocess.run(["/bin/bash", str(shim), reserved], capture_output=True,
                                   text=True, env=b.env(), timeout=60)
                self.assertEqual(r.returncode, 64, reserved)
                self.assertIn("reserved", r.stderr, reserved)


class OneBadPlistIsOneBadRow(unittest.TestCase):
    """~/Library/LaunchAgents is a shared folder: whatever else the owner has installed
    sits in it beside these jobs, and a plist is not always a dict.

    An array or a bare string at the root parses perfectly well and has no `.get`, so the
    reader that pulled a schedule out of one died on an AttributeError -- and it is one
    command producing one document, so the console lost every row it has, not the row for
    the odd file. A machine mirroring perfectly then reads as no machine at all.
    """

    LABEL = "com.sovereign.connector.strayjob"       # the prefix is what makes it looked at

    def machine(self, tmp):
        b = Box(tmp)
        b.read_wires()
        b.declare({"orca": b.lane_entry("orca")})
        b.record({"orca": b.lane_run()})
        return b

    def write_plist(self, b, body):
        p = b.home / "Library" / "LaunchAgents" / (self.LABEL + ".plist")
        p.write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
                     '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                     '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                     '<plist version="1.0">%s</plist>\n' % body)
        return p

    def status(self, b):
        return subprocess.run(["/usr/bin/python3", str(STATUS), "--json", "--no-hub"],
                              capture_output=True, text=True, env=b.env(), timeout=180)

    def test_a_plist_that_is_not_a_dict_costs_one_row_its_schedule_and_nothing_else(self):
        for shape, body in (("an array", "<array><string>x</string></array>"),
                            ("a bare string", "<string>x</string>"),
                            ("not a plist at all", "")):
            with self.subTest(plist=shape):
                with tempfile.TemporaryDirectory() as tmp:
                    b = self.machine(tmp)
                    self.write_plist(b, body)
                    b.labels = "%s\n-\t0\t%s" % (RUNNER_LABEL, self.LABEL)
                    r = self.status(b)
                    self.assertEqual(r.returncode, 0,
                                     "one plist in the LaunchAgents folder that is %s took the "
                                     "whole console down:\n%s" % (shape, r.stderr[-800:]))
                    d = json.loads(r.stdout)
                    self.assertTrue(d["jobs"], "the console lost every job row")
                    self.assertIn("orca", [h["id"] for h in d["harnesses"]])
                    row = next((j for j in d["jobs"] if j["label"] == self.LABEL), None)
                    self.assertIsNotNone(row, "the odd job lost its row entirely: %s"
                                              % [j["label"] for j in d["jobs"]])
                    self.assertIsNone(row["schedule"],
                                      "a schedule was read out of a plist that has none")

    def test_the_control_a_well_formed_plist_beside_it_still_reads(self):
        """Otherwise a guard that returned early on everything would pass this file."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            b.plist(self.LABEL)
            b.labels = "%s\n-\t0\t%s" % (RUNNER_LABEL, self.LABEL)
            d = json.loads(self.status(b).stdout)
            row = next(j for j in d["jobs"] if j["label"] == self.LABEL)
            self.assertEqual(row["schedule"], "every 900s")


if __name__ == "__main__":
    unittest.main()


class XcodeLicense(unittest.TestCase):
    """A launchd job whose program is /usr/bin/python3 stops after an Xcode update: the shim
    exits 69 with "You have not agreed to the Xcode license agreements" until someone accepts
    it. The console already says "last exited 69" and points at a log; this rule reads the
    log and names the fix instead, once, in place of that row."""

    LAUNCHCTL = """#!/bin/bash
case "$1" in
  list)  printf 'PID\\tStatus\\tLabel\\n-\\t69\\t%s\\n' "$SOV_STUB_LABELS" ;;
  print) echo "last exit code = 69" ;;
esac
exit 0
"""
    LINE = ("You have not agreed to the Xcode license agreements. Please run 'sudo xcodebuild -license' "
            "from within a Terminal window to review and agree to the Xcode and Apple SDKs license.\n")

    def box(self, tmp, lines):
        b = Box(tmp)
        (b.stub / "launchctl").write_text(self.LAUNCHCTL)
        b.declare({"orca": b.lane_entry("orca")})
        b.record({"orca": b.lane_run()})
        (b.state / (RUNNER_LABEL + ".error.log")).write_text(lines)
        return b

    def test_a_job_the_xcode_license_stopped_is_named_with_its_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, self.LINE * 29)
            d = b.status()
            rows = [n for n in d["needs_you"] if n.get("kind") == "xcode-license"]
            self.assertEqual(len(rows), 1, d["needs_you"])
            n = rows[0]
            self.assertIn(RUNNER_LABEL, n["text"])
            self.assertIn("sudo xcodebuild -license accept", n["action"])
            self.assertIn("launchctl kickstart", n["action"])
            self.assertFalse(n.get("legacy"), "the rule ships its own why / action / verify")
            self.assertFalse([x for x in d["needs_you"] if x.get("kind") == "job" and RUNNER_LABEL in x.get("text", "")],
                             "the generic exit-code row named the same job a second time")

    def test_a_job_that_failed_for_another_reason_keeps_the_generic_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, "Traceback (most recent call last):\n  boom\n")
            d = b.status()
            self.assertFalse([n for n in d["needs_you"] if n.get("kind") == "xcode-license"])
            self.assertTrue([n for n in d["needs_you"] if n.get("kind") == "job" and RUNNER_LABEL in n.get("text", "")])


class HubReceipts(unittest.TestCase):
    """A hub job row reads the runner's receipts, so a job that has never exited in
    launchd's eyes still shows its last run and last exit, and its log is the runner's."""

    def test_hub_failure_points_at_the_captured_program_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); label = "com.sovereign.hub.autocommit"
            b.plist(label); b.labels = label
            hub = b.state / "hub"; hub.mkdir()
            (hub / "autocommit.last-run").write_text("1700000000\n")
            (hub / "autocommit.last-exit").write_text("1\n")
            output = hub / "autocommit.last-output"
            output.write_text("Credential scan blocked the commit.\n")
            (hub / "autocommit.error.log").write_text("")
            d = b.status()
            row = next(j for j in d["jobs"] if j["label"] == label)
            self.assertEqual(row["last_exit"], 1)
            self.assertEqual(row["last_output"], str(output))
            self.assertEqual(row["stderr"], str(hub / "autocommit.error.log"))
            need = next(n for n in d["needs_you"] if n.get("kind") == "job" and n["text"].startswith(label + " last exited 1"))
            self.assertIn(str(output), need["text"])
            self.assertIn("Credential scan blocked the commit.", need["failure_output"])

    def test_a_hub_job_that_succeeded_and_printed_is_not_an_error(self):
        """The runner writes every job's stdout and stderr to <job>.last-output, so a kit
        receipt or "updates=0" is normal output. It is not an error log: it raised a
        Today alert and an "N err" on every healthy hub job, and offered to clear a file
        the nightly reads back. launchd's own stderr for the job is the error log."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); label = "com.sovereign.hub.kit"
            b.plist(label); b.labels = label
            hub = b.state / "hub"; hub.mkdir()
            (hub / "kit.last-run").write_text("1700000000\n"); (hub / "kit.last-exit").write_text("0\n")
            (hub / "kit.last-output").write_text('{\n  "applied": true\n}\n')
            (hub / "kit.error.log").write_text("")
            d = b.status()
            row = next(j for j in d["jobs"] if j["label"] == label)
            self.assertEqual((row["stderr"], row["stderr_lines"]), (str(hub / "kit.error.log"), 0))
            self.assertFalse([n for n in d["needs_you"] if label in n.get("text", "")])
            (hub / "kit.error.log").write_text("could not start the runner\n")
            d = b.status()
            self.assertTrue([n for n in d["needs_you"] if n.get("kind") == "job" and label in n.get("text", "")],
                            "output launchd itself recorded is still an error log")

    def test_a_hub_job_row_carries_the_runner_receipts(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp); b.plist("com.sovereign.hub.nightly"); b.labels = "com.sovereign.hub.nightly"
            hub = b.state / "hub"; hub.mkdir()
            (hub / "nightly.last-run").write_text("1700000000\n"); (hub / "nightly.last-ok").write_text("1699990000\n"); (hub / "nightly.last-exit").write_text("2\n")
            d = b.status()
            row = next(j for j in d["jobs"] if j["label"] == "com.sovereign.hub.nightly")
            self.assertEqual(row["last_exit"], 2); self.assertEqual(row["last_run"], 1700000000); self.assertEqual(row["last_ok"], 1699990000)
            self.assertTrue(row["stderr"].endswith("hub/nightly.error.log"))
