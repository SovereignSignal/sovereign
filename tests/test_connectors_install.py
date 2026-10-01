"""Connecting and disconnecting a tool: what the machine ends up carrying.

The point of the shared runner is a count. Connecting a third tool must not add a
third background item, and disconnecting the last one must leave nothing behind. Both
are asserted here against a fake home, with stub `launchctl`, `systemctl` and
`loginctl` on PATH and in SOV_LAUNCHCTL / SOV_SYSTEMCTL, so no test loads a real job;
SOV_PLATFORM runs the Linux half on a Mac (the same seam shape as
SOV_TEST_CHECK_OUTPUT in the Notion harness).
"""
import json
import os
import plistlib
import re
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
H = ROOT / "connectors" / "harness"
LIB = H / "_lib" / "install-common.sh"
# The mover's fence must equal SOV_EXCL in mirror-common.sh, exactly and in order.
EXCLUDES = ["--exclude=.DS_Store", "--exclude=.env", "--exclude=.secrets",
            "--exclude=.*.tmp", "--exclude=*.tmp", "--exclude=*.jsonl", "--exclude=.git/"]

STUB = '#!/bin/bash\nprintf "%s %s\\n" "$(basename "$0")" "$*" >> "$SOV_STUB_LOG"\nexit "${SOV_STUB_RC:-0}"\n'


def scheduled_tick(box, harness):
    """Stand in for the scheduler firing the shared job: the same runner, a strictly
    later tick than the one the installer ran by hand. Retiring a working per-tool job
    is licensed by a tick like this one, never by the installer's own."""
    time.sleep(1.1)                          # tick stamps are ISO seconds; make it strictly later
    r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-connectors-run"),
                        "--force", "--only", harness],
                       capture_output=True, text=True, env=box.env(), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def scheduled_tick_all(box):
    """The scheduler firing the shared job over EVERY declared lane, which is what it
    really does: no --only, so every lane gets a visit of its own, strictly later than
    any tick an installer ran by hand."""
    time.sleep(1.1)
    r = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-connectors-run"), "--force"],
                       capture_output=True, text=True, env=box.env(), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


class Box:
    """A throwaway machine: fake HOME, a real-enough vault, stubbed job control."""

    def __init__(self, tmp, platform="Darwin", staging=False):
        self.tmp = Path(tmp)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.state = self.tmp / "state"
        self.stub = self.tmp / "stub"
        self.platform = platform
        (self.home / "Library" / "LaunchAgents").mkdir(parents=True)
        (self.home / ".config" / "systemd" / "user").mkdir(parents=True)
        (self.vault / "knowledge" / "entities").mkdir(parents=True)
        (self.vault / "raw" / "tools").mkdir(parents=True)
        (self.vault / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n\nThe owner.\n")
        self.stub.mkdir()
        for name in ("launchctl", "systemctl", "loginctl", "prlctl"):
            p = self.stub / name
            p.write_text(STUB)
            p.chmod(0o755)
        # A python that is not the /usr/bin/python3 shim, which is what the shared job must be
        # pointed at on a Mac; stood in for by a script that hands off to the real interpreter.
        self.clt_python = self.stub / "clt-python3"
        self.clt_python.write_text('#!/bin/bash\nexec /usr/bin/python3 "$@"\n')
        self.clt_python.chmod(0o755)
        if staging:
            (self.home / ".vault-staging" / "raw" / "tools").mkdir(parents=True)
        self.log = self.tmp / "stub.log"
        self.log.write_text("")

    def env(self, **extra):
        e = {"HOME": str(self.home), "PATH": "%s:/usr/bin:/bin:/usr/sbin:/sbin" % self.stub,
             "SOV_STUB_LOG": str(self.log), "SOV_STATE_DIR": str(self.state),
             "SOV_MANIFEST": str(self.state / "connectors.json"),
             "SOV_LAUNCHCTL": str(self.stub / "launchctl"),
             "SOV_SYSTEMCTL": str(self.stub / "systemctl"),
             # Absolute Parallels discovery must never read the host's real guests.
             "PRLCTL": str(self.stub / "prlctl"),
             "SOV_PLATFORM": self.platform,
             "SOV_CLT_PYTHON": str(self.clt_python),
             "USER": os.environ.get("USER", "tester"), "LOGNAME": os.environ.get("USER", "tester")}
        e.update(extra)
        # A None value unsets the variable: `sov connect all` arrives over ssh, where USER
        # is often not in the environment at all.
        return {k: v for k, v in e.items() if v is not None}

    def connect(self, harness, args=(), vault=None, **envx):
        """`vault` names a DIFFERENT archive for this one call: the machine's vault moved
        and the same tool is connected again against the new one."""
        return subprocess.run(
            ["/bin/bash", str(H / harness / "install.sh"), "--vault", str(vault or self.vault),
             "--host", "testbox", "--core", "me", "--apply"] + list(args),
            capture_output=True, text=True, env=self.env(**envx), timeout=180)

    def disconnect(self, harness, args=(), **envx):
        return subprocess.run(
            ["/bin/bash", str(H / harness / "install.sh"), "--vault", str(self.vault),
             "--host", "testbox", "--disconnect", "--apply"] + list(args),
            capture_output=True, text=True, env=self.env(**envx), timeout=120)

    def relay(self, sub, args=(), **envx):
        """`sov relay`, through the front door. A shim that sources install-common.sh and
        calls sov_relay_add directly passes whether or not `bin/sov` routes the command,
        which is how a shipped `sov relay` that exited 64 stayed green through a suite."""
        return subprocess.run(["/bin/bash", str(ROOT / "bin" / "sov"), "relay", sub] + list(args),
                              capture_output=True, text=True, env=self.env(**envx), timeout=120)

    def plists(self):
        return sorted(p.name for p in (self.home / "Library" / "LaunchAgents").glob("*.plist"))

    def units(self):
        d = self.home / ".config" / "systemd" / "user"
        return sorted(p.name for p in d.iterdir() if p.is_file())

    def manifest(self):
        return json.loads((self.state / "connectors.json").read_text())

    def runner_plist(self):
        return plistlib.loads((self.home / "Library" / "LaunchAgents" /
                               "com.sovereign.connector.runner.plist").read_bytes())

    def relay_plist(self):
        return plistlib.loads((self.home / "Library" / "LaunchAgents" /
                               "com.sovereign.connector.relay.plist").read_bytes())


class Count(unittest.TestCase):
    """The complaint was a screen full of background items. This is the fix, measured."""

    def test_three_tools_declare_three_lanes_and_leave_one_background_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            for n, h in enumerate(("windsurf", "orca", "cowork"), start=1):
                r = b.connect(h)
                self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)
                self.assertEqual(len(b.manifest()["harnesses"]), n, h)
                self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                                 "connecting %s added a background item" % h)
            m = b.manifest()
            self.assertEqual(sorted(m["harnesses"]), ["cowork", "orca", "windsurf"])
            for h, ent in m["harnesses"].items():
                self.assertEqual(ent["label"], "com.sovereign.connector.%s" % h)
                self.assertTrue(ent["enabled"])
                self.assertTrue(ent["mirror"].endswith("connectors/harness/%s/mirror.sh" % h))
                self.assertLessEqual(ent["timeout_s"], m["runner"]["interval_s"])
            p = b.runner_plist()
            self.assertEqual(p["Label"], "com.sovereign.connector.runner")
            self.assertEqual(p["ProgramArguments"][0], str(b.clt_python), "the job named the Xcode shim")
            self.assertTrue(p["ProgramArguments"][1].endswith("bin/sov-connectors-run"))
            self.assertEqual(p["StartInterval"], m["runner"]["interval_s"])
            self.assertTrue(p["StandardErrorPath"], "StandardErrorPath is never omitted")

    def test_a_staged_machine_adds_exactly_one_mover_and_no_more(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            for h in ("windsurf", "orca", "cowork"):
                r = b.connect(h)
                self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)
                self.assertEqual(b.plists(), ["com.sovereign.connector.relay.plist",
                                              "com.sovereign.connector.runner.plist"], h)

    def test_connecting_the_same_tool_twice_is_one_lane_and_leaves_the_job_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            unit = b.home / "Library" / "LaunchAgents" / "com.sovereign.connector.runner.plist"
            before = (unit.stat().st_mtime_ns, unit.read_bytes())
            time.sleep(1.1)
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(list(b.manifest()["harnesses"]), ["windsurf"])
            self.assertEqual(unit.read_bytes(), before[1])
            self.assertEqual(unit.stat().st_mtime_ns, before[0],
                             "an unchanged job must not be rewritten: that boots out a tick in flight")


class Mover(unittest.TestCase):
    def test_the_movers_argv_is_rsync_with_no_delete_and_one_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            args = b.relay_plist()["ProgramArguments"]
            self.assertEqual(args[0], "/usr/bin/rsync")
            self.assertEqual(args[1], "-a")
            self.assertEqual(args[2:2 + len(EXCLUDES)], EXCLUDES)
            self.assertNotIn("--delete", args, "--delete removes every lane written by another machine")
            self.assertEqual(args[-1], str(b.vault / "raw" / "tools") + "/")
            src = args[2 + len(EXCLUDES)]
            self.assertEqual(src, str(b.home / ".vault-staging" / "raw" / "tools") + "/")
            self.assertEqual(b.manifest()["relay"]["dest"], str(b.vault / "raw" / "tools") + "/")

    def test_a_directory_source_never_carries_a_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            r = b.relay("add", [str(watched)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            args = b.relay_plist()["ProgramArguments"]
            sources = args[2 + len(EXCLUDES):-1]
            self.assertIn(str(watched), sources,
                          "a trailing slash here dumps the folder's children loose into raw/tools/, at exit 0")
            self.assertEqual([s for s in sources if s.endswith("/")],
                             [str(b.home / ".vault-staging" / "raw" / "tools") + "/"])
            self.assertNotIn("--delete", args)

    def test_two_sources_sharing_a_basename_are_refused_not_quietly_swapped(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            first, second = b.tmp / "a" / "Claude", b.tmp / "b" / "Claude"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.assertEqual(b.relay("add", [str(first)]).returncode, 0)
            r = b.relay("add", [str(second)])
            self.assertNotEqual(r.returncode, 0, "two sources sharing a basename merge into one destination at exit 0")
            self.assertIn(str(first), b.relay_plist()["ProgramArguments"],
                          "the first pipe must not be dropped by declaring a second one")

    def test_a_source_under_the_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            inside = b.vault / "raw" / "tools" / "loop"
            inside.mkdir(parents=True)
            self.assertNotEqual(b.relay("add", [str(inside)]).returncode, 0, "a source under the destination loops")

    def test_a_source_that_does_not_exist_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertNotEqual(b.relay("add", [str(b.tmp / "nope")]).returncode, 0)


class Refusals(unittest.TestCase):
    def test_a_lane_that_could_outlive_a_tick_is_refused_at_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("windsurf", ["--interval", "900", "--timeout", "1800"])
            self.assertEqual(r.returncode, 65)
            self.assertIn("own job", r.stdout + r.stderr)
            self.assertFalse((b.state / "connectors.json").exists())
            self.assertEqual(b.plists(), [])

    def test_a_lane_the_runner_will_refuse_is_never_left_declared(self):
        """The tick is the SHORTEST cadence on the machine, so connecting a fast tool
        shortens it under a slow one already declared. Checked against this lane's own
        cadence instead, the installer accepts a lane the runner then refuses to run:
        nothing mirrors it, and every job on the machine still reads green."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("windsurf", ["--interval", "3600", "--timeout", "1200"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            b.connect("orca", ["--interval", "900"])       # the tick is now 900s for everyone
            m = b.manifest()
            for h, ent in m["harnesses"].items():
                self.assertLessEqual(ent["timeout_s"], m["runner"]["interval_s"],
                                     "%s can outlive the tick the runner will use" % h)
            listing = subprocess.run(["/usr/bin/python3", str(ROOT / "bin" / "sov-connectors-run"), "--list"],
                                     capture_output=True, text=True, env=b.env(), timeout=120)
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            self.assertNotIn("timeout exceeds interval", listing.stdout,
                             "the installer left a lane the shipped runner refuses to run")

    def test_the_shared_jobs_own_names_are_not_available_to_a_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            shim = Path(tmp) / "reserved.sh"
            shim.write_text('#!/bin/bash\nTEMPLATE="%s"\nHARNESS="$1"; LANE_PREFIX=x\n'
                            '. "$TEMPLATE/connectors/harness/_lib/install-common.sh"\n'
                            'VAULT="%s"; HOST=testbox\nsov_resolve\n' % (ROOT, b.vault))
            shim.chmod(0o755)
            for bad in ("runner", "relay"):
                r = subprocess.run(["/bin/bash", str(shim), bad], capture_output=True, text=True, env=b.env())
                self.assertEqual(r.returncode, 64, bad)
                self.assertIn("reserved", r.stderr)


class HermesAbsent(unittest.TestCase):
    """`sov connect hermes` rewrites Hermes' own config. On a machine with no Hermes there is
    nothing to rewrite, and the 2026-09-30 rebuild rehearsal met that as a Python traceback
    after the pointers had already been written."""

    def test_no_hermes_is_a_sentence_not_a_traceback_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("hermes")
            self.assertNotEqual(r.returncode, 0, "a connector that cannot install must not exit clean")
            self.assertIn("Hermes is not installed", r.stdout + r.stderr)
            self.assertNotIn("Traceback", r.stdout + r.stderr)
            self.assertFalse((b.home / ".brain-root").exists(), "nothing may be written before the refusal")
            self.assertFalse((b.state / "connectors.json").exists(), "no lane may be declared")

    def test_with_hermes_present_it_installs_as_before(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            (b.home / ".hermes").mkdir()
            (b.home / ".hermes" / "config.yaml").write_text("model: local\n")
            r = b.connect("hermes")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("hermes", b.manifest()["harnesses"])


class Removal(unittest.TestCase):
    def test_disconnect_drops_the_lane_keeps_its_files_and_retires_its_error_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertEqual(b.connect("orca").returncode, 0)
            lane_dir = Path(b.manifest()["harnesses"]["windsurf"]["lane_dir"])
            (lane_dir).mkdir(parents=True, exist_ok=True)
            (lane_dir / "keep.md").write_text("provenance\n")
            err = b.state / "lanes" / "windsurf.error.log"
            self.assertTrue(err.exists(), "a connected lane always has an error log")
            r = b.disconnect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(list(b.manifest()["harnesses"]), ["orca"])
            self.assertEqual((lane_dir / "keep.md").read_text(), "provenance\n")
            self.assertFalse(err.exists())
            self.assertTrue((b.state / "lanes" / "windsurf.error.log.retired").exists())
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                             "one lane left, so the shared job stays")

    def test_disconnecting_the_last_lane_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertEqual(b.connect("orca").returncode, 0)
            self.assertEqual(b.disconnect("windsurf").returncode, 0)
            r = b.disconnect("orca")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})
            self.assertEqual(b.plists(), [])
            self.assertIn("com.sovereign.connector.runner", b.log.read_text())


class Migrate(unittest.TestCase):
    """Retiring the jobs the shared runner replaces.

    The old per-tool jobs are the rollback window: while they are still loaded the
    machine keeps mirroring whatever the new path fails to. So they go only on two
    proofs, and never on evidence the installer manufactured for itself: the shared job
    is really loaded by the scheduler, and it has run this lane on its own schedule.
    Booting a working job out while nothing is scheduled is the exact shape of the
    failure this whole change exists to remove."""

    LEGACY = ("claude-code", "codex", "cowork", "cursor", "hermes", "orca", "windsurf")

    def legacy(self, b):
        agents = b.home / "Library" / "LaunchAgents"
        for h in self.LEGACY:
            (agents / ("com.sovereign.connector.%s.plist" % h)).write_text("<plist/>\n")
        return agents

    def test_the_first_connect_keeps_the_job_it_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("com.sovereign.connector.windsurf.plist", b.plists(),
                          "the old job was retired on evidence this same install produced")
            self.assertFalse((agents / "sovereign-retired" / "com.sovereign.connector.windsurf.plist").exists())
            self.assertNotIn("bootout gui/%d/com.sovereign.connector.windsurf" % os.getuid(),
                             b.log.read_text())
            self.assertIn("com.sovereign.connector.runner.plist", b.plists())
            self.assertIn("kept", r.stdout, "a job left in place has to say so, and say what clears it")

    def test_it_goes_once_the_shared_job_has_run_the_lane_on_its_own_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            scheduled_tick(b, "windsurf")
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("com.sovereign.connector.windsurf.plist", b.plists())
            self.assertTrue((agents / "sovereign-retired" / "com.sovereign.connector.windsurf.plist").exists(),
                            "the parked plist is the restore path; it is never deleted")
            self.assertIn("bootout gui/%d/com.sovereign.connector.windsurf" % os.getuid(), b.log.read_text())
            self.assertIn("com.sovereign.connector.runner.plist", b.plists())
            self.assertIn("com.sovereign.connector.codex.plist", b.plists(),
                          "a lane this machine has not connected keeps its own job")

    def test_a_pass_that_connects_two_lanes_retires_both_of_their_jobs(self):
        """One `sov connect all --apply` runs one installer after another, in one pass.

        The evidence that licenses a retirement is per lane -- this lane has been mirrored
        by the shared job on its own schedule -- so the discount for the installer's own
        smoke tick has to be per lane too. Stamped once for the whole machine, the smoke
        tick of the FIRST installer in a pass discounts the scheduled tick for every
        installer after it: the pass retires exactly one legacy job and leaves the rest
        loaded forever, which is the ten-items-into-two the whole change is for."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            for h in ("windsurf", "orca"):
                self.assertEqual(b.connect(h).returncode, 0, h)
            scheduled_tick_all(b)              # one scheduled tick, every lane visited
            for h in ("windsurf", "orca"):     # the next pass: two installers, one run
                r = b.connect(h)
                self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)
            for h in ("windsurf", "orca"):
                self.assertNotIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                                 "%s kept its per-tool job: the pass retired only the lane it reached first" % h)
                self.assertTrue((agents / "sovereign-retired" / ("com.sovereign.connector.%s.plist" % h)).exists(),
                                "%s: the parked plist is the restore path" % h)
                self.assertIn("bootout gui/%d/com.sovereign.connector.%s" % (os.getuid(), h), b.log.read_text())
            self.assertIn("com.sovereign.connector.codex.plist", b.plists(),
                          "a lane this machine never connected keeps its own job")

    def test_a_first_pass_over_two_lanes_still_retires_nothing(self):
        """The mirror image, and the reason the discount exists at all. Two installers in
        one pass produce two hand-run ticks; neither is the scheduler, so neither lane may
        be retired on it -- least of all the second one, on the first one's evidence."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            for h in ("windsurf", "orca"):
                r = b.connect(h)
                self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)
                self.assertIn("kept", r.stdout, "%s: a job left in place has to say so" % h)
            for h in ("windsurf", "orca"):
                self.assertIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                              "%s was retired on a tick this same pass produced" % h)
            self.assertFalse((agents / "sovereign-retired").exists())

    def test_no_launchd_never_retires_anything_because_nothing_is_scheduled(self):
        """The plist is written and deliberately not bootstrapped, so the machine has no
        scheduled mirroring at all. Parking the working job here leaves it with none."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            r = b.connect("windsurf", ["--no-launchd"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("bootstrap", b.log.read_text(), "--no-launchd loaded a job")
            scheduled_tick(b, "windsurf")
            r = b.connect("windsurf", ["--no-launchd"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("com.sovereign.connector.windsurf.plist", b.plists(),
                          "the working per-tool job was parked while nothing was scheduled")
            self.assertFalse((agents / "sovereign-retired").exists())
            self.assertNotIn("bootout gui/%d/com.sovereign.connector.windsurf" % os.getuid(),
                             b.log.read_text())

    def test_a_shared_job_that_would_not_load_keeps_every_old_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            agents = self.legacy(b)
            r = b.connect("windsurf", SOV_STUB_RC="1")
            self.assertNotEqual(r.returncode, 0, "a failed bootstrap has to be loud")
            self.assertIn("com.sovereign.connector.windsurf.plist", b.plists())
            self.assertFalse((agents / "sovereign-retired").exists())

    def test_linux_keeps_its_timer_until_the_shared_timer_has_really_run_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            d = b.home / ".config" / "systemd" / "user"
            (d / "sovereign-connector-windsurf.service").write_text("[Service]\n")
            (d / "sovereign-connector-windsurf.timer").write_text("[Timer]\n")
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("sovereign-connector-windsurf.timer", b.units(),
                          "the old timer went on the installer's own tick")
            scheduled_tick(b, "windsurf")
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("sovereign-connector-windsurf.timer", b.units())
            self.assertIn("disable --now sovereign-connector-windsurf.timer", b.log.read_text())


class LaneContract(unittest.TestCase):
    """The LANE.md already in the vault.

    These files are synced to every device and tracked in git, and nothing but this
    installer ever re-renders them. A contract that still says the mirror runs "via
    `com.sovereign.connector.windsurf`" names a job that will exist on no machine, so
    the sentence has to be rewritten whatever shape it was written in. The four below
    are the shapes real lane contracts use, plus the systemd one for a Linux box; three
    fixed phrasings missed three of eight files.
    """

    LABEL = "com.sovereign.connector.windsurf"
    RUNNER = "com.sovereign.connector.runner"
    HEAD = ("---\ntype: capture\nsource: sov\ncreated: 2026-01-01\n---\n\n"
            "# windsurf-testbox\n\nread: sov-load (session-start hook)\n\n")
    SHAPES = {
        "as-label": "Rewired 2026-09-02 by `sov connect windsurf`: write wire "
                    "`connectors/harness/windsurf/mirror.sh` every 900s as `%s`. `MANIFEST.md` is the heartbeat.\n",
        "via-label": "Write wire: `connectors/harness/windsurf/mirror.sh` every 900s via `%s`,\n"
                     "memories folder to the lane.\n",
        "via-launchd-wrapped": "Write wire: `connectors/harness/windsurf/mirror.sh` every 900s via launchd\n"
                               "(`%s`), append-only. `MANIFEST.md` is the heartbeat.\n",
        "via-a-scheduled-job-wrapped": "Write wire: `connectors/harness/windsurf/mirror.sh` every 900s via a scheduled job\n"
                                       "(`%s`). It copies the store and renders one file per run.\n",
    }
    SYSTEMD = ("Write wire: `connectors/harness/windsurf/mirror.sh` every 900s "
               "via a systemd user timer (`sovereign-connector-windsurf`).\n")
    # Prose that only NAMES the lane id. None of it is a write wire, and all of it is the
    # owner's own words in a synced, git-tracked file, so all of it has to survive byte
    # for byte. A rule loose enough to take these rewrites any sentence the label appears
    # in, which is how a patcher meant for one line edits a vault.
    PASSING = {
        "no-cadence-at-all":
            "Filed as `%s` in the console, which is also the jump target.\n",
        "a-cadence-somewhere-else-in-the-sentence":
            "The mirror ran every 900s until 2026-08, and the row was filed under `%s`.\n",
        "the-trigger-word-far-from-the-label":
            "The gate log records who approved this lane by name, and the console row is `%s`.\n",
        # The narrow class a rule of "cadence, one of five words, then up to sixty
        # characters of anything, then the label" still eats: one unpunctuated clause
        # that happens to carry all three. None of these describes a write wire -- the
        # word after the cadence belongs to the sentence, not to a job -- and all three
        # are the owner's own words in a synced, git-tracked file.
        "as-that-is-not-a-job":
            "It syncs every 900s as long as the machine is awake and the console row is `%s` today.\n",
        "in-that-is-not-a-job":
            "The mirror runs every 900s in the shared job and the console still shows `%s` as its row.\n",
        "by-that-is-not-a-job":
            "Backfills ran every 900s by hand for a week before the console listed `%s` again.\n",
    }

    def patched(self, shape, platform="Darwin", label=None):
        label = label or self.LABEL
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform=platform)
            lane_dir = b.vault / "raw" / "tools" / "windsurf-testbox"
            lane_dir.mkdir(parents=True)
            (lane_dir / "LANE.md").write_text(self.HEAD + (shape % label if "%s" in shape else shape))
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return (lane_dir / "LANE.md").read_text()

    def assert_names_the_job_that_runs(self, text, shape_name, label=None, runner=None):
        label = label or self.LABEL
        runner = runner or self.RUNNER
        self.assertIn(runner, text, "%s: the contract does not name the job that will run it" % shape_name)
        for pat in (r"via\s+`%s`", r"as\s+`%s`", r"via\s+launchd\s*\(\s*`%s`",
                    r"via\s+a\s+scheduled\s+job\s*\(\s*`%s`",
                    r"via\s+a\s+systemd\s+user\s+timer\s*\(\s*`%s`"):
            self.assertIsNone(re.search(pat % re.escape(label), text),
                              "%s: the contract still names a per-tool job that exists nowhere" % shape_name)
        self.assertIn("lane id `%s`" % label, text,
                      "%s: the lane's own id is the console row and the jump target; it stays" % shape_name)

    def test_every_sentence_shape_on_disk_is_rewritten(self):
        for name, shape in sorted(self.SHAPES.items()):
            with self.subTest(shape=name):
                text = self.patched(shape)
                self.assert_names_the_job_that_runs(text, name)
                self.assertIn("read: instruction", text, "%s: the read wire line is still rewritten" % name)
                self.assertIn("every 900s", text, "%s: the cadence in front of the label is kept" % name)

    def test_the_systemd_phrasing_is_rewritten_too(self):
        text = self.patched(self.SYSTEMD, platform="Linux")
        self.assert_names_the_job_that_runs(text, "systemd", label="sovereign-connector-windsurf",
                                            runner="sovereign-connector-runner")

    def test_a_sentence_that_merely_mentions_the_lane_id_is_left_alone(self):
        """The write wire in the same file is rewritten; the prose beside it is not."""
        wire = self.SHAPES["via-label"] % self.LABEL
        for name, prose in sorted(self.PASSING.items()):
            with self.subTest(prose=name):
                sentence = prose % self.LABEL
                text = self.patched(wire + "\n" + sentence)
                self.assertIn(sentence, text,
                              "%s: the patcher rewrote a sentence that only names the lane" % name)
                self.assertNotIn("every 900s via `%s`" % self.LABEL, text,
                                 "%s: the write wire still names a per-tool job" % name)
                self.assertIn("every 900s via launchd (`%s`, lane id `%s`)" % (self.RUNNER, self.LABEL), text,
                              "%s: the write wire was not rewritten" % name)

    def test_a_contract_with_no_write_wire_keeps_every_word_of_its_prose(self):
        for name, prose in sorted(self.PASSING.items()):
            with self.subTest(prose=name):
                sentence = prose % self.LABEL
                text = self.patched(sentence)
                self.assertIn(sentence, text,
                              "%s: nothing in this contract is a write wire, and it was rewritten anyway" % name)
                self.assertIn("sov connect windsurf", text,
                              "%s: a contract with no write wire still gets the note that names the job" % name)

    def test_the_rewrite_does_not_swallow_the_word_after_the_label(self):
        """The tail of the rule takes the whitespace with the label, so a wire sentence
        that runs on into another clause comes back reading "lane id `...`)and it
        appends". These files are read by people, in a synced vault."""
        wire = ("Write wire: `connectors/harness/windsurf/mirror.sh` every 900s via `%s` "
                "and it appends to the lane.\n")
        text = self.patched(wire)
        self.assert_names_the_job_that_runs(text, "unpunctuated-tail")
        self.assertIn(" and it appends to the lane.", text,
                      "the rewrite ate the space in front of the word after the label")
        self.assertNotRegex(text, r"`\)\w",
                            "the rewritten span is glued to the next word")

    def test_the_previous_contract_is_kept_beside_the_patched_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            lane_dir = b.vault / "raw" / "tools" / "windsurf-testbox"
            lane_dir.mkdir(parents=True)
            (lane_dir / "LANE.md").write_text(self.HEAD + self.SHAPES["via-label"] % self.LABEL)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertTrue(list(lane_dir.glob(".LANE.md.bak-*")),
                            "a rewrite of an owner-visible file keeps the version it replaced")


class Linux(unittest.TestCase):
    def test_linux_gets_one_service_and_one_timer_and_gives_both_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            for h in ("windsurf", "orca"):
                r = b.connect(h)
                self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)
            self.assertEqual(b.units(), ["sovereign-connector-runner.service",
                                         "sovereign-connector-runner.timer"])
            timer = (b.home / ".config" / "systemd" / "user" / "sovereign-connector-runner.timer").read_text()
            self.assertIn("OnUnitInactiveSec=", timer, "measured from the end of a run, not the start")
            self.assertIn("Persistent=true", timer, "a laptop that slept must catch up")
            service = (b.home / ".config" / "systemd" / "user" / "sovereign-connector-runner.service").read_text()
            self.assertIn("/usr/bin/python3", service)
            self.assertIn("bin/sov-connectors-run", service)
            self.assertNotIn("relay", " ".join(b.units()), "no TCC on Linux, so no mover")
            self.assertEqual(b.disconnect("windsurf").returncode, 0)
            self.assertEqual(b.disconnect("orca").returncode, 0)
            self.assertEqual(b.units(), [])

    def test_a_legacy_linux_timer_is_disabled_not_merely_orphaned(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            d = b.home / ".config" / "systemd" / "user"
            (d / "sovereign-connector-windsurf.service").write_text("[Service]\n")
            (d / "sovereign-connector-windsurf.timer").write_text("[Timer]\n")
            wants = d / "timers.target.wants"
            wants.mkdir()
            (wants / "sovereign-connector-windsurf.timer").write_text("")
            self.assertEqual(b.connect("windsurf").returncode, 0)
            scheduled_tick(b, "windsurf")               # the old timer goes only after a real tick
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertFalse((wants / "sovereign-connector-windsurf.timer").exists(),
                             "an enabled timer keeps firing forever; the symlink has to go")
            self.assertFalse((d / "sovereign-connector-windsurf.timer").exists())
            self.assertIn("disable --now sovereign-connector-windsurf.timer", b.log.read_text())

    def test_a_user_manager_that_refuses_the_job_fails_the_install_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            r = b.connect("windsurf", SOV_STUB_RC="1")
            self.assertNotEqual(r.returncode, 0,
                                "a swallowed enable failure is the Linux twin of the silent TCC denial")


class Environment(unittest.TestCase):
    """What the installer may assume about the environment it lands in.

    `sov-host-add` runs `sov connect all --apply` over ssh, and a non-interactive ssh
    shell often has no USER at all. Under `set -euo pipefail` an unguarded $USER aborts
    the run, and the linger note is the first statement of the Linux branch, so it
    aborts before a single unit is written and no lane on that box ever runs."""

    def test_the_linux_install_survives_an_unset_USER(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            r = b.connect("windsurf", USER=None, LOGNAME=None)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("unbound variable", r.stderr)
            self.assertEqual(b.units(), ["sovereign-connector-runner.service",
                                         "sovereign-connector-runner.timer"],
                             "the install died before it wrote the units, so nothing runs here")

    def test_the_darwin_install_survives_an_unset_USER(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("windsurf", USER=None, LOGNAME=None)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("unbound variable", r.stderr)
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"])

    def test_a_calendar_lane_installs_with_an_unset_USER_too(self):
        """The second unguarded site: a lane with a job of its own takes the same
        linger note, and Notion is the harness that has one."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            r = subprocess.run(
                ["/bin/bash", str(H / "notion" / "install.sh"), "--vault", str(b.vault),
                 "--host", "testbox", "--secret", "ntn_test", "--apply"],
                capture_output=True, text=True, timeout=180,
                env=b.env(USER=None, LOGNAME=None,
                          SOV_TEST_CHECK_OUTPUT="bot: TestBot\nworkspace: Test WS\nitems: 0\n"
                                                "roots reachable:\nmissing roots: none\n"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("unbound variable", r.stderr)
            self.assertIn("sovereign-connector-notion.timer", b.units())


if __name__ == "__main__":
    unittest.main()


class Interpreter(unittest.TestCase):
    """What runs the shared job. /usr/bin/python3 on a Mac is an Xcode shim: after an Xcode
    update it exits 69 ("You have not agreed to the Xcode license agreements") until someone
    accepts the license, and a launchd job that names it fails every tick, silently, from
    then on (one laptop, 2026-09-14, seven hours of it). The Command Line Tools ship a real
    interpreter at a stable path; the job names that one when it exists."""

    def test_the_job_runs_on_a_python_an_xcode_update_cannot_revoke(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.runner_plist()["ProgramArguments"][0], str(b.clt_python))
            self.assertNotIn("xcodebuild", r.stdout + r.stderr, "no warning when the interpreter is safe")

    def test_a_mac_without_command_line_tools_falls_back_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            r = b.connect("windsurf", SOV_CLT_PYTHON=str(Path(tmp) / "no-such-python3"))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.runner_plist()["ProgramArguments"][0], "/usr/bin/python3")
            self.assertIn("xcodebuild -license accept", r.stdout + r.stderr,
                          "the fallback names its risk and the fix, or the next outage is silent again")

    def test_linux_keeps_the_system_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            unit = (b.home / ".config" / "systemd" / "user" / "sovereign-connector-runner.service").read_text()
            exec_line = next(l for l in unit.splitlines() if l.startswith("ExecStart="))
            self.assertTrue(exec_line.startswith("ExecStart=/usr/bin/python3 "), exec_line)
