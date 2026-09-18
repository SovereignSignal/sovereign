"""A calendar-cadence lane: declared in the manifest, run by a job of its own.

One kind of connector pulls from a cloud account, and one of its runs can take hours. It
cannot share the fifteen-minute tick -- neither launchd StartInterval nor a systemd
oneshot starts a second run while one is in flight -- so it keeps a wall-clock job. The
first answer was to keep it out of the connector manifest entirely, and that left
`sov disconnect all --apply` walking a list the lane was not on: the command exited 0
saying the machine was clean while the lane's job stayed loaded and kept pulling.

So it is declared like every other lane and carries `"tick": false`. That one field has
to hold four things together, and each is pinned here:

  * the shared runner never runs it, never counts it due, never stamps it, and never
    takes its wall-clock cadence for the tick every other lane shares;
  * `sov connect all --apply` still settles on the second pass, without a live API walk;
  * `sov disconnect all --apply` reaches it and takes its own job with it;
  * the console shows it once, from that job, and the manifest entry does not double it.

The machine is the throwaway box the installer tests use: fake HOME, a real-enough
vault, stub launchctl/systemctl. Nothing loads a real job and nothing reaches the network
-- the harness's own `--check` seam answers instead.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import tests.test_connectors_install as ti

SOV = ti.ROOT / "bin" / "sov"
RUNNER_BIN = ti.ROOT / "bin" / "sov-connectors-run"
CALENDAR = "notion"                  # the one harness whose single run can outlive a tick
TICK_LANE = "windsurf"               # an ordinary lane beside it, so "declared" is never "the only one"
RUNNER_LABEL = "com.sovereign.connector.runner"
# What `sov-mirror-notion --check` would say. The same seam the Notion harness test
# uses, so no test here touches Notion.
CHECK = ("bot: TestBot\nworkspace: Test WS\nitems: 1 (page 1)\nroots reachable:\n"
         "  %032x  Root A\nmissing roots: none\n" % 1)


def label(b, harness):
    return ("com.sovereign.connector.%s" if b.platform == "Darwin" else "sovereign-connector-%s") % harness


def sov(b, args, **envx):
    """Through `bin/sov`: the only uninstall recipe this repo prints."""
    return subprocess.run(["/bin/bash", str(SOV)] + list(args),
                          capture_output=True, text=True, env=b.env(**envx), timeout=600)


def runner(b, args=()):
    return subprocess.run(["/usr/bin/python3", str(RUNNER_BIN)] + list(args),
                          capture_output=True, text=True, env=b.env(), timeout=180)


def connect_calendar(b, args=()):
    return b.connect(CALENDAR, ["--secret", "ntn_test_token"] + list(args),
                     SOV_TEST_CHECK_OUTPUT=CHECK)


def both_kinds(tmp, platform="Darwin"):
    """A machine carrying one lane of each kind."""
    b = ti.Box(tmp, platform=platform)
    r = b.connect(TICK_LANE)
    assert r.returncode == 0, r.stdout + r.stderr
    r = connect_calendar(b)
    assert r.returncode == 0, r.stdout + r.stderr
    return b


def sections(out):
    """The lanes a `sov ... all` pass actually ran an installer for."""
    return [l[4:-4] for l in out.splitlines() if l.startswith("=== ") and l.endswith(" ===")]


class Declared(unittest.TestCase):
    """It is in the manifest, and the manifest says what it is."""

    def test_the_calendar_lane_declares_itself_as_one_the_runner_does_not_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            h = b.manifest()["harnesses"]
            self.assertIn(CALENDAR, h, "`sov disconnect all` walks the manifest; a lane that is "
                                       "not on it keeps its job and is never reported")
            self.assertIs(h[CALENDAR].get("tick"), False,
                          "the entry does not say the runner leaves it alone: %s" % h[CALENDAR])
            self.assertEqual(h[CALENDAR].get("label"), label(b, CALENDAR),
                             "the entry has to name the job that really runs it")
            self.assertIsNot(h[TICK_LANE].get("tick"), False,
                             "an ordinary lane must not inherit the exemption")

    def test_its_wall_clock_cadence_never_becomes_the_shared_tick(self):
        """The runner's tick is the smallest cadence declared. Counting a daily lane in
        that would stretch the tick every other lane shares -- and on a machine where it
        is the only declared lane, stretch the mover's schedule with it."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.assertEqual(connect_calendar(b).returncode, 0)
            self.assertEqual(b.manifest()["runner"]["interval_s"], 900,
                             "a lane the runner never ticks set the tick for the ones it does")
            self.assertEqual(b.connect(TICK_LANE).returncode, 0)
            self.assertEqual(b.manifest()["runner"]["interval_s"], 900)
            self.assertEqual(b.runner_plist()["StartInterval"], 900)

    def test_it_adds_no_second_background_item_beyond_its_own_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            self.assertEqual(b.plists(), [label(b, CALENDAR) + ".plist", RUNNER_LABEL + ".plist"],
                             "one shared job plus the calendar lane's own, and nothing else")


class RunnerLeavesItAlone(unittest.TestCase):
    """"Declared" must not leak into "run". The runner reads the same manifest, and a
    lane it started ticking would take hours inside a fifteen-minute job and starve every
    other lane behind it."""

    def test_it_is_not_listed_not_due_not_run_and_not_stamped(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)

            listing = runner(b, ["--list"])
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            self.assertIn(TICK_LANE, listing.stdout, "this listing shows no lane at all; it proves nothing")
            self.assertNotIn(CALENDAR, listing.stdout, "the runner lists a lane it will never run")

            dry = runner(b, ["--dry-run"])
            self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
            self.assertIn("1 lane(s) declared", dry.stdout,
                          "the calendar lane was counted as one of the runner's own")
            self.assertNotIn(CALENDAR, dry.stdout)

            only = runner(b, ["--only", CALENDAR])
            self.assertEqual(only.returncode, 64,
                             "the runner accepted a hand-run of a lane that has its own job")
            self.assertIn(CALENDAR, only.stderr, "the refusal does not say which lane it refused")

            tick = runner(b, ["--force"])
            self.assertEqual(tick.returncode, 0, tick.stdout + tick.stderr)
            runs = json.loads((b.state / "runs.json").read_text())
            self.assertIn(TICK_LANE, runs["lanes"], "the tick ran nothing; this proves nothing")
            self.assertNotIn(CALENDAR, runs["lanes"],
                             "the runner stamped a lane it never ran: the console will read that "
                             "record as the lane's liveness and call a dead pull healthy")
            self.assertEqual(runs["runner"]["lanes_declared"], 1)
            self.assertEqual(runs["runner"]["lanes_due"], 1)

    def test_a_record_left_from_a_downgrade_is_dropped_rather_than_kept(self):
        """A record for a lane the runner does not serve is the same false liveness
        whether this tick wrote it or an older build did."""
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            runs_path = b.state / "runs.json"
            runs = json.loads(runs_path.read_text())
            runs["lanes"][CALENDAR] = dict(runs["lanes"][TICK_LANE])
            runs_path.write_text(json.dumps(runs, indent=2))
            r = runner(b, ["--force"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(CALENDAR, json.loads(runs_path.read_text())["lanes"])


class ConnectAllStillSettles(unittest.TestCase):
    """The manifest entry is exactly what `sov connect all` reads to decide whether a
    tool has migrated. Read without the `tick` field it says this lane is on the runner
    and is not being carried, so every pass re-runs its installer -- and that installer
    walks a live API."""

    def machine(self, tmp):
        b = ti.Box(tmp)
        (b.home / ".claude").mkdir()          # a local tool to find, so a pass has real work
        return b

    def connect_all(self, b):
        return sov(b, ["connect", "all", "--vault", str(b.vault), "--host", "testbox",
                       "--core", "me", "--apply"],
                   NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)

    def test_a_second_pass_selects_nothing_with_a_calendar_lane_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            first = self.connect_all(b)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn(CALENDAR, [s.lower() for s in sections(first.stdout)],
                          "the first pass never connected the calendar lane; this proves nothing")
            self.assertIs(b.manifest()["harnesses"][CALENDAR].get("tick"), False)
            second = self.connect_all(b)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(sections(second.stdout), [],
                             "a declared calendar lane made the pass re-run an installer with "
                             "nothing to do, and that installer walks a live API")
            self.assertIn("keeps its own job", second.stdout,
                          "a lane this machine carries outside the runner has to be named, or the "
                          "count of what runs here is wrong")


class DisconnectAllReachesIt(unittest.TestCase):
    """`sov disconnect all --apply` walks the manifest. Before the lane was declared
    there, the command left the job loaded and still exited 0 reporting a clean machine
    -- three reviewers reproduced exactly that."""

    def test_it_takes_the_calendar_lanes_own_job_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            plist = label(b, CALENDAR) + ".plist"
            self.assertIn(plist, b.plists(), "the calendar job was never installed; this proves nothing")
            r = sov(b, ["disconnect", "all", "--apply"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(CALENDAR, sections(r.stdout),
                          "the command never visited the calendar lane and reported success anyway")
            self.assertEqual(b.manifest()["harnesses"], {})
            self.assertEqual(b.plists(), [],
                             "the machine is reported clean and still carries a background job")
            self.assertTrue((b.home / "Library" / "LaunchAgents" / "sovereign-retired" / plist).exists(),
                            "the parked plist is the restore path")
            self.assertTrue(any("bootout" in l and label(b, CALENDAR) in l
                                for l in b.log.read_text().splitlines()),
                            "the plist was moved and the job was never booted out: it is still "
                            "loaded and still pulling")

    def test_the_same_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp, platform="Linux")
            unit = label(b, CALENDAR) + ".service"
            self.assertIn(unit, b.units())
            r = sov(b, ["disconnect", "all", "--apply"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.units(), [],
                             "an enabled timer keeps firing forever, and this one was left behind")
            retired = b.state / "retired-units"
            self.assertTrue((retired / unit).exists())
            self.assertIn("disable --now %s.timer" % label(b, CALENDAR), b.log.read_text())

    def test_it_needs_no_token_to_take_a_lane_away(self):
        """Disconnecting is the one path that must work when the credential is long gone."""
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            r = sov(b, ["disconnect", "all", "--apply"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("no token", (r.stdout + r.stderr).lower())


class DisconnectNamesTheRealLane(unittest.TestCase):
    """`sov disconnect <calendar lane>` prints the lane it is leaving in place, because
    `raw/` is provenance and the owner has to know what stays. A cloud pull's lane is not
    the host-suffixed one the shared resolver computes: one workspace has one lane, named
    once. Printing the computed name sends the owner to a directory that never existed."""

    def lane_dir(self, b):
        return b.vault / "raw" / "tools" / "Notion"

    def test_apply_prints_the_directory_that_is_really_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            lane = self.lane_dir(b)
            self.assertTrue(lane.is_dir(), "the calendar lane's own directory is missing; this is blind")
            r = b.disconnect(CALENDAR)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(str(lane), r.stdout,
                          "disconnect named a lane directory that does not exist on this machine")
            self.assertNotIn("%s-testbox" % CALENDAR, r.stdout)
            self.assertTrue(lane.is_dir(), "raw/ is provenance, never cache")

    def test_the_dry_run_names_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            r = subprocess.run(["/bin/bash", str(ti.H / CALENDAR / "install.sh"),
                                "--vault", str(b.vault), "--host", "testbox", "--disconnect"],
                               capture_output=True, text=True, env=b.env(), timeout=120)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dry run", r.stdout)
            self.assertIn(str(self.lane_dir(b)), r.stdout)
            self.assertNotIn("%s-testbox" % CALENDAR, r.stdout)


class OneContractForTheTickFlag(unittest.TestCase):
    """`tick` is read by four things, and this file is hand-editable.

    `sov connect` writes a JSON boolean, but the manifest is plain text in a state
    directory and a person fixing one lane writes `"tick": "false"`. A string is truthy
    everywhere it is read naively, so one reader saying "off the tick" while another says
    "on it" is how a lane nobody counts gets run every quarter hour anyway -- or how the
    console reports a lane as failing to tick that nothing was ever going to tick.

    One contract, pinned across all four readers at once.
    """

    def hand_edited(self, tmp):
        """The manifest as a person left it: the flag written as a string."""
        b = both_kinds(tmp)
        path = b.state / "connectors.json"
        m = json.loads(path.read_text())
        m["harnesses"][CALENDAR]["tick"] = "false"
        path.write_text(json.dumps(m, indent=1, sort_keys=True))
        self.assertIsInstance(b.manifest()["harnesses"][CALENDAR]["tick"], str,
                              "the flag was not left as a string; this proves nothing")
        return b

    def status(self, b):
        r = subprocess.run(["/usr/bin/python3", str(ti.ROOT / "bin" / "sov-status"),
                            "--json", "--no-hub"],
                           capture_output=True, text=True, env=b.env(), timeout=180)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_the_runner_the_installer_and_the_console_all_read_it_as_off_the_tick(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.hand_edited(tmp)

            listing = runner(b, ["--list"])
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            self.assertIn(TICK_LANE, listing.stdout, "this listing shows no lane at all")
            self.assertNotIn(CALENDAR, listing.stdout,
                             "the runner reads a hand-written \"false\" as true and will run a "
                             "lane whose single run can outlive the whole tick")

            dry = runner(b, ["--dry-run"])
            self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
            self.assertIn("1 lane(s) declared", dry.stdout, dry.stdout)

            d = self.status(b)
            lane_rows = [j for j in d["jobs"] if j.get("kick")]
            self.assertEqual([j["harness"] for j in lane_rows], [TICK_LANE],
                             "the console credits the shared job with a lane it never ticks")
            self.assertEqual([j["label"] for j in d["jobs"]].count(label(b, CALENDAR)), 1,
                             "the console shows the calendar lane twice")

            r = b.connect(TICK_LANE)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("(1 lane(s)", r.stdout,
                          "the installer counts the calendar lane among the ones the shared "
                          "job carries:\n" + r.stdout)
            self.assertNotIn("(2 lane(s)", r.stdout, r.stdout)

    def test_a_pass_over_the_machine_still_settles_on_it(self):
        """The fourth reader. `sov connect all` decides from this same field whether a tool
        has migrated: read as "on the tick and not being carried", every pass re-runs the
        calendar lane's installer -- and that installer walks a live API."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.hand_edited(tmp)
            r = sov(b, ["connect", "all", "--vault", str(b.vault), "--host", "testbox",
                        "--core", "me", "--apply"],
                    NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(CALENDAR, [x.lower() for x in sections(r.stdout)],
                             "the pass re-ran the calendar lane's installer, which walks a live "
                             "API, because it read a hand-written \"false\" as true")


class TheMoverAndTheLastTickingLane(unittest.TestCase):
    """Behind a staging hop a calendar lane stages like every other one, and the same one
    mover carries it in.

    Two counts were being taken from one number. `lane-count` was narrowed to the lanes the
    RUNNER ticks, which is right for the runner and wrong for the question disconnect asks
    with it -- "was that the last lane on this machine" -- and the mover's own fate was
    decided from the directory pipes alone, which deliberately leave the staging source
    out. So on a staged Mac carrying one ticking lane beside a calendar one, disconnecting
    the ticking lane dropped the mover: the calendar lane kept pulling into
    ~/.vault-staging on its own daily job, and nothing carried a byte of it into the vault
    again. Nothing said so.
    """

    RELAY = "com.sovereign.connector.relay.plist"

    def staged_machine(self, tmp):
        b = ti.Box(tmp, staging=True)
        r = b.connect(TICK_LANE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = connect_calendar(b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return b

    def staged_lane(self, b):
        return b.home / ".vault-staging" / "raw" / "tools" / "Notion"

    def test_the_calendar_lane_keeps_the_mover_when_the_last_ticking_lane_goes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.staged_machine(tmp)
            self.assertTrue(self.staged_lane(b).is_dir(),
                            "the calendar lane does not stage on this box; this proves nothing")
            self.assertIn(self.RELAY, b.plists(), "no mover was installed; this proves nothing")

            r = b.disconnect(TICK_LANE)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(list(b.manifest()["harnesses"]), [CALENDAR],
                             "the calendar lane is still declared and still pulling")
            self.assertIn(self.RELAY, b.plists(),
                          "the mover went with the last TICKING lane while the calendar lane "
                          "still stages: its daily pull stops reaching the vault, silently.\n"
                          + r.stdout)
            args = b.relay_plist()["ProgramArguments"]
            self.assertIn(str(b.home / ".vault-staging" / "raw" / "tools") + "/", args,
                          "the mover was rebuilt without the staging source it still has to carry")
            self.assertEqual(args[-1], str(b.vault / "raw" / "tools") + "/")
            self.assertIn(label(b, CALENDAR) + ".plist", b.plists(),
                          "the calendar lane's own job went with a lane that is not it")
            self.assertNotIn("last lane on this machine", r.stdout,
                             "a lane that still mirrors from here is a lane on this machine: "
                             "the run says the opposite, so nobody goes looking.\n" + r.stdout)

    def test_the_same_holds_when_the_calendar_lane_was_connected_first(self):
        """Declaration order is not evidence of anything. It decided this once."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, staging=True)
            self.assertEqual(connect_calendar(b).returncode, 0)
            self.assertEqual(b.connect(TICK_LANE).returncode, 0)
            r = b.disconnect(TICK_LANE)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(self.RELAY, b.plists(),
                          "the staged calendar lane stopped reaching the vault.\n" + r.stdout)

    def test_the_mover_goes_when_the_calendar_lane_goes_too(self):
        """The other half of the same rule: nothing is kept alive for a lane that left."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.staged_machine(tmp)
            self.assertEqual(b.disconnect(TICK_LANE).returncode, 0)
            r = b.disconnect(CALENDAR)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})
            self.assertEqual(b.plists(), [],
                             "this machine carries no lane at all and still carries jobs")
            self.assertIn("[relay]", r.stdout, "the mover went without a word")
            report = r.stdout.split("[relay]", 1)[1]
            self.assertIn(str(b.home / ".vault-staging" / "raw" / "tools"), report,
                          "a mover that goes has to name what it stops carrying")

    def test_a_directory_pipe_is_still_reason_enough_on_its_own(self):
        """The staging hop is one reason to keep the mover, never the only one: a watch
        folder belongs to no lane and outlives every one of them."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.staged_machine(tmp)
            watched = b.tmp / "Inbox"
            watched.mkdir()
            self.assertEqual(b.relay("add", [str(watched)]).returncode, 0)
            self.assertEqual(b.disconnect(TICK_LANE).returncode, 0)
            r = b.disconnect(CALENDAR)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(self.RELAY, b.plists(),
                          "the last lane went and took a watch folder nobody owns with it")
            args = b.relay_plist()["ProgramArguments"]
            self.assertIn(str(watched), args,
                          "the mover was rebuilt without the pipe that is keeping it alive")
            self.assertEqual(args[-1], str(b.vault / "raw" / "tools") + "/")


class ConsoleShowsItOnce(unittest.TestCase):
    """The console already had a row for this lane, from its own job. The manifest entry
    must not add a second: a doubled row makes one lane look like two, and the synthetic
    one is built from a run record the runner never writes for it."""

    def status(self, b):
        r = subprocess.run(["/usr/bin/python3", str(ti.ROOT / "bin" / "sov-status"),
                            "--json", "--no-hub"],
                           capture_output=True, text=True, env=b.env(), timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr
        return json.loads(r.stdout)

    def test_the_manifest_entry_does_not_double_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            d = self.status(b)
            labels = [j["label"] for j in d["jobs"]]
            self.assertEqual(labels.count(label(b, CALENDAR)), 1,
                             "the calendar lane has two rows: %s" % labels)
            self.assertIn(RUNNER_LABEL, labels)
            row = next(j for j in d["jobs"] if j["label"] == label(b, CALENDAR))
            self.assertIsNone(row.get("kick"),
                              "the row is a synthetic lane row: it says the shared job runs this "
                              "lane, and the shared job never will")
            self.assertTrue(row.get("plist"), "the row does not name the job's own unit")
            self.assertEqual(Path(row["plist"]).name, label(b, CALENDAR) + ".plist")

    def test_the_shared_jobs_own_count_leaves_it_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = both_kinds(tmp)
            d = self.status(b)
            lane_rows = [j for j in d["jobs"] if j.get("kick")]
            self.assertEqual([j["harness"] for j in lane_rows], [TICK_LANE],
                             "the runner is credited with a lane it never ticks")


class ARefusedCalendarJobIsAsLoudAsARefusedTick(unittest.TestCase):
    """This job is the ONLY thing that runs this lane. The shared runner skips it by
    declaration, so a scheduler that refuses to load it leaves a lane that will never
    mirror again -- and the installer used to print one line about it and exit 0, over a
    machine it had just reported as connected. The tick path exits 70 at the same point.
    """

    def refuse(self, b, name, pattern):
        """A stub scheduler that loads everything except the one job under test, so the
        failure being measured is this lane's own and not the shared runner's."""
        stub = b.stub / name
        stub.write_text(ti.STUB.replace('exit "${SOV_STUB_RC:-0}"',
                                        'case "$*" in %s) exit 1;; esac\nexit 0' % pattern))
        stub.chmod(0o755)

    def refuse_bootstrap(self, b):
        self.refuse(b, "launchctl", "*bootstrap*connector.%s*" % CALENDAR)

    def test_a_scheduler_that_refuses_the_job_fails_the_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.refuse_bootstrap(b)
            r = connect_calendar(b)
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 70,
                             "the scheduler refused the only job that runs this lane and the "
                             "install still reported success:\n" + out)
            self.assertIn(label(b, CALENDAR), r.stderr,
                          "the failure does not name the job that would not load")
            self.assertIn("launchctl bootstrap", r.stderr,
                          "the failure does not say how to load it by hand")
            self.assertTrue((b.home / "Library" / "LaunchAgents" /
                             (label(b, CALENDAR) + ".plist")).exists(),
                            "the plist the recovery line names was never written")

    def test_it_says_this_lane_stopped_and_not_that_the_machine_did(self):
        """The tick path's sentence is 'No lane on this Mac will run'. Here every ticking
        lane is untouched, and borrowing that sentence sends the reader to the wrong job."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.assertEqual(b.connect(TICK_LANE).returncode, 0)
            self.refuse_bootstrap(b)
            r = connect_calendar(b)
            self.assertEqual(r.returncode, 70, r.stdout + r.stderr)
            self.assertNotIn("No lane on this Mac will run", r.stdout + r.stderr)
            self.assertIn(CALENDAR, r.stderr, "the failure does not name the lane that stopped")
            self.assertIn(RUNNER_LABEL + ".plist", b.plists(),
                          "the machine's ticking lanes were taken down with it")

    def test_the_same_refusal_on_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, platform="Linux")
            self.refuse(b, "systemctl", "*enable*--now*")
            r = connect_calendar(b)
            self.assertEqual(r.returncode, 70,
                             "systemd refused the timer and the install reported success:\n"
                             + r.stdout + r.stderr)
            self.assertIn(label(b, CALENDAR), r.stderr,
                          "the failure does not name the timer that would not enable")
            self.assertIn(label(b, CALENDAR) + ".timer", b.units(),
                          "the unit a hand-enable would name was never written")

    def test_no_launchd_is_still_the_quiet_deliberate_way(self):
        """The other half. --no-launchd is how a plist is written without being loaded --
        on a box with no GUI session, or in a test -- and it must stay silent and exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            r = connect_calendar(b, ["--no-launchd"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(r.stderr, "", "writing without loading is not a failure")
            self.assertIn(label(b, CALENDAR) + ".plist", b.plists())
            self.assertIn("not loaded", r.stdout)


class TheCalendarLaneStagesLikeAnyOther(unittest.TestCase):
    """Behind a staging hop, making ~/.vault-staging is not a local act: mirror-common's
    sov_dest sends EVERY mirror on the machine into that tree the moment it exists. So the
    tree and the job that drains it are one decision, and an install that fails in between
    leaves every lane on the box writing into a dead end, silently.

    The tick path closed this by ordering: the job first, the tree after. This lane's
    contract directory sits inside that tree, so writing it before the job reopened the
    same hole on the calendar path.
    """

    RELAY = "com.sovereign.connector.relay.plist"

    def brain_inside_documents(self, b):
        """What puts a Mac behind the staging hop: a vault under ~/Documents, a
        TCC-protected folder where a job whose program is a script host is denied."""
        v = b.home / "Documents" / "archive"
        (v / "knowledge" / "entities").mkdir(parents=True)
        (v / "raw" / "tools").mkdir(parents=True)
        (v / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n")
        return v

    def connect_staged(self, b, **envx):
        return b.connect(CALENDAR, ["--secret", "ntn_test_token"],
                         vault=self.brain_inside_documents(b),
                         SOV_TEST_CHECK_OUTPUT=CHECK, **envx)

    def test_the_control_a_protected_vault_gets_the_tree_the_mover_and_the_lane(self):
        """Without this the two tests below could pass on a box that never staged."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            r = self.connect_staged(b)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            staged = b.home / ".vault-staging" / "raw" / "tools"
            self.assertTrue(staged.is_dir(), "this box never went behind a staging hop")
            self.assertIn(self.RELAY, b.plists(), "the tree is there and nothing drains it")
            self.assertTrue((staged / "Notion" / "LANE.md").exists(),
                            "the lane contract is not in the tree the mover carries")

    def test_a_failed_install_leaves_no_tree_for_nothing_to_carry(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            r = self.connect_staged(b, SOV_STUB_RC="1")
            out = r.stdout + r.stderr
            self.assertNotEqual(r.returncode, 0, "the install was supposed to fail here:\n" + out)
            self.assertNotIn("bootstrap", [l.split()[1] for l in b.log.read_text().splitlines()
                                           if l.startswith("launchctl ") and len(l.split()) > 1
                                           and "connector.notion" in l],
                             "the calendar job loaded after all; this proves nothing")
            self.assertFalse((b.home / ".vault-staging").exists(),
                             "the install failed and left ~/.vault-staging behind. sov_dest "
                             "sends every mirror on this Mac into that tree as soon as it "
                             "exists, and nothing here carries it into the vault: every lane "
                             "on the box now writes into a dead end, silently.\n" + out)

    def test_a_mover_that_will_not_load_leaves_no_tree_either(self):
        """The worse half of the same rule: the tree is made, and the one job that drains
        it will not start."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            stub = b.stub / "launchctl"
            stub.write_text('#!/bin/bash\n'
                            'printf "%s %s\\n" "$(basename "$0")" "$*" >> "$SOV_STUB_LOG"\n'
                            'case "$*" in *bootstrap*connector.relay*) exit 1;; esac\n'
                            'exit 0\n')
            stub.chmod(0o755)
            r = self.connect_staged(b)
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 70, "the mover was supposed to fail to load:\n" + out)
            self.assertIn("com.sovereign.connector.relay", out, "the failure names no job")
            self.assertFalse((b.home / ".vault-staging").exists(),
                             "nothing on this machine carries staging into the vault, and the "
                             "tree that redirects every mirror into it was left behind.\n" + out)


if __name__ == "__main__":
    unittest.main()
