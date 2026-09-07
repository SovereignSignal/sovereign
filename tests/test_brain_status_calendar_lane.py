"""brain-status and the two jobs that are NOT the shared runner: the mover, and a lane that
keeps a calendar job of its own.

Both are read here through the same lens the console uses, because both fail the same silent
way. The mover writes relay.error.log, not <label>.error.log, so a Linux row built from the
generic name points at a file nothing ever creates and a mover failing every tick renders as
"no log file" - the exact signature the shared-runner change exists to remove. And a
calendar-cadence lane is now DECLARED in the manifest (with "tick": false) so
`sov disconnect all` can reach it; the runner never runs it, never counts it due and never
stamps it, so every runner-shaped reading has to skip it or the console grows a second,
bogus row for the lane and then calls it silent for not ticking.

The Linux half runs in-process with sys.platform patched, because that platform's answer
comes from a code path a Mac never takes; `systemctl` is stubbed on PATH and HOME is a temp
dir, so no real job is ever read. The rest runs the shipped script as a subprocess against a
stubbed `launchctl`, which is how the other status tests prove things.
"""
import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "bin" / "brain-status"
RUNNER = "com.sovereign.connector.runner"
RELAY = "com.sovereign.connector.relay"
NOTION = "com.sovereign.connector.notion"

LAUNCHCTL = """#!/bin/bash
case "$1" in
  list)  printf 'PID\\tStatus\\tLabel\\n'
         for l in $SOV_STUB_LABELS; do printf -- '-\\t0\\t%s\\n' "$l"; done ;;
  print) echo "last exit code = 0" ;;
esac
exit 0
"""

SYSTEMCTL = """#!/bin/bash
if [ "$2" = "list-timers" ]; then
  for l in $SOV_STUB_TIMERS; do
    echo "Mon 2026-09-07 10:00:00 UTC 1min left n/a n/a $l.timer $l.service"
  done
  exit 0
fi
if [ "$2" = "show" ]; then
  lbl="${3%.service}"; code=0
  for pair in ${SOV_STUB_EXITS:-}; do
    [ "${pair%%=*}" = "$lbl" ] && code="${pair#*=}"
  done
  echo "$code"; exit 0
fi
exit 0
"""


def iso(seconds_ago=0):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_status_module():
    """The shipped script, imported. It has no .py suffix, so it needs its loader named."""
    loader = importlib.machinery.SourceFileLoader("brain_status_under_test", str(STATUS))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Box:
    """One whole machine in a temp dir: HOME, vault, state dir, and a stub scheduler."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.state = self.tmp / "state"
        self.stub = self.tmp / "stub"
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        (self.home / ".config" / "systemd" / "user").mkdir(parents=True)
        (self.vault / "knowledge" / "entities").mkdir(parents=True)
        (self.vault / "raw" / "tools").mkdir(parents=True)
        (self.vault / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n\nThe owner.\n")
        (self.home / ".brain-root").write_text(str(self.vault))
        (self.home / ".brain-host").write_text("testbox")
        (self.state / "lanes").mkdir(parents=True)
        self.stub.mkdir()
        for name, body in (("launchctl", LAUNCHCTL), ("systemctl", SYSTEMCTL)):
            p = self.stub / name
            p.write_text(body)
            p.chmod(0o755)
        self.labels = RUNNER          # what launchctl/systemd say is loaded
        self.exits = ""               # "<label>=<code> ..." for the systemd stub

    # ---- declarations ----
    def plist(self, label, daily=False):
        sched = ('<key>StartCalendarInterval</key><dict><key>Hour</key><integer>3</integer>'
                 '<key>Minute</key><integer>45</integer></dict>' if daily
                 else '<key>StartInterval</key><integer>900</integer>')
        (self.home / "Library" / "LaunchAgents" / (label + ".plist")).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0"><dict>\n'
            '<key>Label</key><string>%s</string>\n'
            '<key>ProgramArguments</key><array><string>/usr/bin/python3</string></array>\n'
            '%s\n'
            '<key>StandardErrorPath</key><string>%s</string>\n'
            '</dict></plist>\n' % (label, sched,
                                   self.state / ("relay.error.log" if label == RELAY else label + ".error.log")))

    def unit(self, label):
        (self.home / ".config" / "systemd" / "user" / (label + ".service")).write_text("[Service]\n")

    def manifest(self, harnesses, relay=None, interval_s=900):
        m = {"version": 1,
             "runner": {"label": RUNNER, "interval_s": interval_s,
                        "state_dir": str(self.state), "log_dir": str(self.state / "lanes")},
             "harnesses": harnesses}
        if relay is not None:
            m["relay"] = relay
        (self.state / "connectors.json").write_text(json.dumps(m, indent=2))
        return m

    def tick_lane(self, hid, cadence_s=900):
        """A lane the shared runner serves: it declares no `tick`, so it defaults to true."""
        (self.state / "lanes" / (hid + ".log")).write_text("")
        (self.state / "lanes" / (hid + ".error.log")).write_text("")
        return {"label": "com.sovereign.connector.%s" % hid,
                "mirror": str(ROOT / "connectors" / "harness" / hid / "mirror.sh"),
                "lane": "%s-testbox" % hid, "lane_dir": str(self.vault / "raw" / "tools" / ("%s-testbox" % hid)),
                "cadence_s": cadence_s, "timeout_s": 300, "enabled": True, "env": {}, "registered": "2026-01-01"}

    def calendar_lane(self, hid="notion", label=NOTION, cadence_s=86400):
        """The one interface change this round: a cloud pull that keeps its own job is in the
        manifest (so `sov disconnect all` reaches it) and declares that it does not tick."""
        return {"label": label, "lane": "Notion", "lane_dir": str(self.vault / "raw" / "tools" / "Notion"),
                "cadence_s": cadence_s, "enabled": True, "tick": False, "registered": "2026-01-01"}

    def runs(self, lanes, **runner):
        r = {"label": RUNNER, "host": "testbox", "interval_s": 900, "pid": 41231,
             "tick_started": iso(8), "tick_finished": iso(1), "lanes_declared": len(lanes),
             "lanes_due": len(lanes), "lanes_ran": len(lanes), "lanes_failed": 0,
             "lanes_timed_out": 0, "skipped_overlap": False, "reclaimed_lock": False}
        r.update(runner)
        (self.state / "runs.json").write_text(json.dumps({"version": 1, "runner": r, "lanes": lanes}, indent=2))

    def lane_run(self, cadence_s=900, checked_ago=60, **over):
        rec = {"enabled": True, "cadence_s": cadence_s, "timeout_s": 300, "checked_at": iso(checked_ago),
               "attempted_at": iso(checked_ago), "finished_at": iso(max(0, checked_ago - 2)),
               "duration_s": 2.14, "last_exit": 0, "timed_out": False, "in_flight": False,
               "skipped": None, "mirror_missing": False}
        rec.update(over)
        return rec

    # ---- readings ----
    def env(self):
        return {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.stub,
                "TMPDIR": tempfile.gettempdir(), "BRAIN_ROOT": str(self.vault), "BRAIN_HOST": "testbox",
                "SOV_STATE_DIR": str(self.state), "SOV_MANIFEST": str(self.state / "connectors.json"),
                "SOV_STUB_LABELS": self.labels, "SOV_STUB_TIMERS": self.labels, "SOV_STUB_EXITS": self.exits}

    def status(self):
        """The shipped script as a subprocess, on this machine's real platform."""
        r = subprocess.run([sys.executable, str(STATUS), "--json", "--no-hub"],
                           capture_output=True, text=True, env=self.env(), timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    def status_as_linux(self):
        """The same script in-process with sys.platform patched, so the systemd half of the
        read side is exercised from a Mac. Nothing here touches the developer's machine: HOME,
        PATH and the state dir are all inside the temp dir."""
        mod = load_status_module()
        buf = io.StringIO()
        with mock.patch.object(sys, "platform", "linux"), \
             mock.patch.object(sys, "argv", ["brain-status", "--json", "--no-hub"]), \
             mock.patch.dict(os.environ, self.env(), clear=True), \
             contextlib.redirect_stdout(buf):
            mod.main()
        return json.loads(buf.getvalue())


def row(d, label):
    return next((j for j in d["jobs"] if j["label"] == label), None)


class Mover(unittest.TestCase):
    """S3: the mover's row must point at the log the installer really writes."""

    def box(self, tmp, relay_exit=0, err_lines=0, label="sovereign-connector-relay"):
        b = Box(tmp)
        # The installer records the mover's real label, which is platform-shaped: this box is
        # read as a Linux machine unless a test says otherwise.
        b.manifest({"orca": b.tick_lane("orca")},
                   relay={"label": label, "enabled": True, "interval_s": 900,
                          "dest": str(b.vault / "raw" / "tools") + "/", "excludes": [],
                          "sources": [{"path": str(b.tmp) + "/", "kind": "dir", "name": "Claude",
                                       "trailing_slash": True}]})
        b.runs({"orca": b.lane_run()})
        # the Linux mover's real name and the real name of the file its unit appends to
        b.labels = "sovereign-connector-runner sovereign-connector-relay"
        b.exits = "sovereign-connector-relay=%d" % relay_exit
        b.unit("sovereign-connector-runner")
        b.unit("sovereign-connector-relay")
        if err_lines:
            (b.state / "relay.error.log").write_text("rsync: link_stat failed\n" * err_lines)
        return b

    def test_a_failing_mover_reads_as_failing_not_as_a_job_with_no_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, relay_exit=23, err_lines=3)
            d = b.status_as_linux()
            r = row(d, "sovereign-connector-relay")
            self.assertIsNotNone(r, "the mover's own unit must have a row: %s" % [j["label"] for j in d["jobs"]])
            self.assertEqual(r["stderr"], str(b.state / "relay.error.log"),
                             "the row must name the file the installer appends the mover's stderr to")
            self.assertEqual(r["stderr_lines"], 3, "a mover writing errors reads as 0 lines, or as none at all")
            self.assertEqual(r["last_exit"], 23)
            self.assertFalse((b.state / "sovereign-connector-relay.error.log").exists(),
                             "the generic <label>.error.log is the name nothing writes; that is the bug")
            texts = [n["text"] for n in d["needs_you"] if n.get("kind") == "job"]
            self.assertTrue(any("relay" in t for t in texts), "a mover exiting 23 must be loud: %s" % d["needs_you"])
            self.assertTrue(any(str(b.state / "relay.error.log") in t for t in texts),
                            "the row sends the owner to the log that exists: %s" % texts)

    def test_a_clean_mover_reports_its_log_rather_than_no_log_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, err_lines=0)
            (b.state / "relay.error.log").write_text("")
            r = row(b.status_as_linux(), "sovereign-connector-relay")
            self.assertEqual(r["stderr"], str(b.state / "relay.error.log"))
            self.assertEqual(r["stderr_lines"], 0, "a clean mover reports 0, never null")
            self.assertRegex(r["schedule"], r"^every \d+s$", "the mover runs on the same interval as the runner")

    def test_the_mac_row_already_reads_its_log_from_the_plist(self):
        """The other platform of the same rule: nothing here changes, and this pins it."""
        if sys.platform != "darwin":
            self.skipTest("the launchd half only exists on a Mac")
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp, label=RELAY)
            b.labels = "%s %s" % (RUNNER, RELAY)
            b.plist(RUNNER)
            b.plist(RELAY)
            (b.state / "relay.error.log").write_text("rsync: link_stat failed\n")
            r = row(b.status(), RELAY)
            self.assertEqual(r["stderr"], str(b.state / "relay.error.log"))
            self.assertEqual(r["stderr_lines"], 1)

    def test_a_unit_that_is_neither_runner_nor_mover_keeps_the_generic_log_name(self):
        """The fallback is right for everything else: a calendar job's systemd unit really
        does append to <label>.error.log, so the mover's special case must not swallow it."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            b.labels += " sovereign-connector-notion"
            b.unit("sovereign-connector-notion")
            (b.state / "sovereign-connector-notion.error.log").write_text("boom\n")
            r = row(b.status_as_linux(), "sovereign-connector-notion")
            self.assertEqual(r["stderr"], str(b.state / "sovereign-connector-notion.error.log"))
            self.assertEqual(r["stderr_lines"], 1)

    def test_the_movers_label_can_never_become_a_lane_row(self):
        """A synthetic lane row is labelled sovereign-connector-<harness>, so only a lane
        called "relay" could collide - and both write paths refuse that name (install-common
        `sov_resolve` and the manifest upsert), which tests/test_connectors_install.py pins.
        This is the read side of the same promise: one row, and it is the real unit."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status_as_linux()
            rows = [j for j in d["jobs"] if j["label"].endswith("-relay")]
            self.assertEqual(len(rows), 1, "the mover must appear exactly once: %s" % rows)
            self.assertIsNone(rows[0].get("harness"), "the mover is a real unit, never a lane")
            self.assertEqual(d["relay"]["label"], "sovereign-connector-relay")


class CalendarLane(unittest.TestCase):
    """The manifest now declares a lane the runner does not serve. It must change nothing
    about how that lane is reported: its own job answers for it, exactly as before."""

    def box(self, tmp, with_job=True, runner_ticked=True):
        b = Box(tmp)
        b.manifest({"orca": b.tick_lane("orca"), "notion": b.calendar_lane()})
        if runner_ticked:
            b.runs({"orca": b.lane_run()})
        b.labels = RUNNER
        b.plist(RUNNER)
        if with_job:
            b.labels += " " + NOTION
            b.plist(NOTION, daily=True)
        return b

    def needs_for(self, d, hid):
        return [n for n in d["needs_you"] if n.get("harness") == hid]

    def test_its_own_job_row_is_not_doubled_by_the_manifest_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            labels = [j["label"] for j in d["jobs"]]
            self.assertEqual(labels.count(NOTION), 1, "one lane, two rows: %s" % labels)
            r = row(d, NOTION)
            self.assertIsNone(r.get("harness"), "the real job row, not a synthetic lane row")
            self.assertEqual(r["stderr"], str(Path(tmp) / "state" / (NOTION + ".error.log")),
                             "its log is the one its own job writes, not a lane log of the runner's")

    def test_a_calendar_lane_whose_job_is_gone_grows_no_runner_shaped_row(self):
        """The bogus row: with no job of its own there is nothing to double, and a synthetic
        row would invent a lane log under the runner that nothing will ever write."""
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp, with_job=False).status()
            self.assertIsNone(row(d, NOTION), "rows: %s" % [j["label"] for j in d["jobs"]])
            self.assertFalse((Path(tmp) / "state" / "lanes" / "notion.error.log").exists())

    def test_it_is_never_reported_as_silent_for_not_ticking(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            self.assertEqual(self.needs_for(d, "notion"), [],
                             "the runner was never going to visit this lane, so silence is not news")
            kinds = {n.get("kind") for n in d["needs_you"]}
            self.assertNotIn("lane-silent", kinds)
            self.assertNotIn("mirror-missing", kinds)
            self.assertNotIn("lane-refused", kinds)

    def test_it_reports_from_its_own_job_and_its_own_cadence(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp).status()
            h = next(x for x in d["harnesses"] if x["id"] == "notion")
            self.assertEqual(h["kick"], NOTION, "the runner does not kick it")
            self.assertEqual(h["runs_in"], NOTION)
            self.assertTrue(h["job_loaded"])
            self.assertEqual(h["cadence_s"], 86400, "a daily pull judged against the 15-minute tick reads red forever")

    def test_a_loaded_runner_does_not_make_its_job_look_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self.box(tmp, with_job=False).status()
            h = next(x for x in d["harnesses"] if x["id"] == "notion")
            self.assertFalse(h["job_loaded"], "the shared runner never runs it, so it cannot vouch for it")
            self.assertEqual(h["state"], "not connected")
            self.assertEqual(h["cadence_s"], 86400, "the declaration is the only cadence left to report")

    def test_a_machine_carrying_only_a_calendar_lane_is_not_a_stalled_runner(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            b.manifest({"notion": b.calendar_lane()})
            b.plist(NOTION, daily=True)
            b.labels = NOTION
            d = b.status()
            self.assertEqual([n for n in d["needs_you"] if n.get("kind") == "runner-stalled"], [],
                             "no lane here needs the runner, so it not ticking is not a fault")


class TickField(unittest.TestCase):
    """The manifest field itself, read the way the runner reads it."""

    def setUp(self):
        self.bs = load_status_module()

    def test_a_lane_that_declares_nothing_still_ticks(self):
        self.assertTrue(self.bs.lane_ticks({"cadence_s": 900}))
        self.assertTrue(self.bs.lane_ticks({"tick": True}))
        self.assertFalse(self.bs.lane_ticks({"tick": False}))
        self.assertFalse(self.bs.lane_ticks(None))

    def test_a_lane_that_does_not_tick_cannot_shorten_the_tick(self):
        m = {"runner": {"label": RUNNER},
             "harnesses": {"orca": {"cadence_s": 900, "enabled": True},
                           "notion": {"cadence_s": 60, "enabled": True, "tick": False}}}
        self.assertEqual(self.bs.runner_interval(m), 900,
                         "a lane the runner never runs must not set the interval it judges the others by")

    def test_the_runner_view_of_a_calendar_lane_is_nobody(self):
        m = {"runner": {"label": RUNNER, "interval_s": 900},
             "harnesses": {"notion": {"cadence_s": 86400, "enabled": True, "tick": False, "mirror": None}}}
        self.assertIsNone(self.bs.runner_lane("notion", m, {}),
                          "a lane with its own job has no runner record, and inventing one calls it refused")


if __name__ == "__main__":
    unittest.main()
