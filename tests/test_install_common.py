"""install-common.sh: the shared library behind every `sov connect`.

Things that only show themselves on a real machine, reproduced here on the same
throwaway box the installer tests use (fake HOME, stub launchctl/systemctl/loginctl,
SOV_PLATFORM to run the Linux half on a Mac):

  * a migration pass that connects more than one lane retires EVERY legacy job it
    replaces, not just the first one;
  * a scheduled run that was killed, or that failed, or that the runner refused, is not
    evidence for retiring the working job it would replace;
  * a machine with no staging hop still carries the directory pipes `sov relay add`
    declares, on either platform, to the destination the installer says it does;
  * the mover outlives the last lane while it still carries pipes of its own, and a
    mover that will not load says what really stops;
  * the LANE.md patcher rewrites the write-wire sentence and leaves the owner's prose
    exactly as it found it.

The box helper is imported by module, never by name: pulling a TestCase into this
namespace would collect and re-run the installer suite here.
"""
import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import tests.test_connectors_install as ti

RUNNER = ti.ROOT / "bin" / "sov-connectors-run"


def machine_tick(box, force=True):
    """Stand in for the scheduler firing the shared job for the whole machine: the same
    runner, every lane, strictly later than any tick an installer ran by hand.

    `force=False` is the tick as it really arrives. Every fifteen minutes the runner
    visits every lane and rewrites every lane's record, and the cadence gate passes over
    the ones that ran recently -- which is most ticks, for most lanes."""
    time.sleep(1.1)                          # tick stamps are ISO seconds; make it strictly later
    argv = ["/usr/bin/python3", str(RUNNER)] + (["--force"] if force else [])
    r = subprocess.run(argv, capture_output=True, text=True, env=box.env(), timeout=300)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def record(box, harness):
    """One lane's row in runs.json, as the runner last left it."""
    return json.loads((box.state / "runs.json").read_text())["lanes"][harness]


def scheduled_run(box, harness, mirror=None, timeout_s=None):
    """One scheduled visit to one lane, run by the SHIPPED runner, and the record it
    left. `mirror` swaps in a stand-in script for this tick: the manifest is the runner's
    whole input, so pointing a lane at a script that hangs or fails is how a kill or a
    failure is reproduced without waiting hours for a real one. The next `sov connect`
    puts the harness's own mirror back, which is exactly what happens on a real machine.
    """
    path = box.state / "connectors.json"
    m = json.loads(path.read_text())
    if mirror is not None:
        m["harnesses"][harness]["mirror"] = str(mirror)
    if timeout_s is not None:
        m["harnesses"][harness]["timeout_s"] = timeout_s
    path.write_text(json.dumps(m, indent=1, sort_keys=True))
    time.sleep(1.1)                          # strictly later than the installer's own tick
    r = subprocess.run(["/usr/bin/python3", str(RUNNER), "--force", "--only", harness],
                       capture_output=True, text=True, env=box.env(), timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads((box.state / "runs.json").read_text())["lanes"][harness]


def stand_in(box, name, body):
    p = box.tmp / name
    p.write_text(body)
    p.chmod(0o755)
    return p


class MigrationPass(unittest.TestCase):
    """`sov connect all --apply` is one invocation and many installers, run back to back.

    The evidence that licenses retiring a per-tool job is per lane: this lane has been
    mirrored by the shared job on its own schedule. Kept as one machine-wide stamp, every
    installer after the first in a pass discounted the hand tick the one before it had
    just run, so a pass retired exactly one old job and left the rest loaded forever."""

    LANES = ("windsurf", "orca")

    def legacy(self, b):
        agents = b.home / "Library" / "LaunchAgents"
        for h in self.LANES:
            (agents / ("com.sovereign.connector.%s.plist" % h)).write_text("<plist/>\n")
        return agents

    def one_pass(self, b):
        for h in self.LANES:
            r = b.connect(h)
            self.assertEqual(r.returncode, 0, h + ": " + r.stdout + r.stderr)

    def test_one_pass_retires_every_legacy_job_it_replaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            agents = self.legacy(b)
            self.one_pass(b)                     # nothing has run on a schedule yet
            for h in self.LANES:
                self.assertIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                              "%s went before the shared job had ever run it" % h)
            machine_tick(b)                      # the scheduler fires and runs both lanes
            self.one_pass(b)                     # the same one invocation, second time
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                             "the pass retired one legacy job and left the rest: ten background "
                             "items never become two")
            for h in self.LANES:
                self.assertTrue((agents / "sovereign-retired" /
                                 ("com.sovereign.connector.%s.plist" % h)).exists(),
                                "%s: the parked plist is the restore path" % h)

    def test_no_lane_is_retired_on_a_tick_its_own_installer_ran(self):
        """The other half of the same rule. Per lane must not mean per lane sometimes:
        with no scheduled tick anywhere in between, both jobs stay."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            agents = self.legacy(b)
            self.one_pass(b)
            self.one_pass(b)
            for h in self.LANES:
                self.assertIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                              "%s was retired on evidence its own installer produced" % h)
            self.assertFalse((agents / "sovereign-retired").exists())


class RetirementGate(unittest.TestCase):
    """What licenses parking a working per-tool job.

    The old job had no time bound at all; the shared runner imposes one. So a lane that
    now times out on every tick, or fails on every tick, is exactly the lane whose old
    job must NOT go: the gate would swap something that mirrors for something that does
    not, and the machine would look migrated. A visit is only evidence when it worked:
    exit 0, not killed, not refused.
    """

    LANE = "windsurf"
    LEGACY = "com.sovereign.connector.windsurf.plist"

    def machine(self, tmp):
        """A box with the old per-tool job installed and the lane freshly declared. The
        first connect never retires anything: nothing has run on a schedule yet."""
        b = ti.Box(tmp)
        (b.home / "Library" / "LaunchAgents" / self.LEGACY).write_text("<plist/>\n")
        r = b.connect(self.LANE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(self.LEGACY, b.plists(), "the legacy job went before anything scheduled ran")
        return b

    def reconnect(self, b):
        r = b.connect(self.LANE)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_a_scheduled_run_that_succeeded_is_what_retires_the_old_job(self):
        """The control. Without it every test below could pass because nothing is ever
        retired at all."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            rec = scheduled_run(b, self.LANE)
            self.assertEqual(rec["last_exit"], 0, rec)
            self.assertFalse(rec["timed_out"], rec)
            self.reconnect(b)
            self.assertNotIn(self.LEGACY, b.plists(),
                             "a clean scheduled run is the evidence this gate exists to wait for")

    def test_a_run_the_runner_killed_does_not_retire_the_old_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            hang = stand_in(b, "hangs.sh", "#!/bin/bash\nsleep 30\n")
            rec = scheduled_run(b, self.LANE, mirror=hang, timeout_s=1)
            self.assertTrue(rec["timed_out"], "the stand-in was not killed; this proves nothing: %s" % rec)
            self.assertNotEqual(rec["last_exit"], 0, rec)
            r = self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "a lane that times out on every tick had its working job parked: "
                          "the machine now mirrors nothing and reads as migrated")
            self.assertIn("[migrate]", r.stdout, "the job was kept and the run said nothing about it")

    def test_a_run_that_failed_does_not_retire_the_old_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            bad = stand_in(b, "fails.sh", "#!/bin/bash\nexit 3\n")
            rec = scheduled_run(b, self.LANE, mirror=bad)
            self.assertEqual(rec["last_exit"], 3, rec)
            self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "an exit 3 on every tick licensed retiring the job that still worked")

    def test_a_clean_run_still_retires_the_old_job_after_the_gate_passes_it_over(self):
        """The stall that kept the migration from ever finishing.

        The runner rewrites every lane's record on every tick, and the ordinary cadence
        gate stamps `skipped: not due` on a lane that ran a moment ago -- with the clean
        run it just had still standing in the same row. Read as "the runner declined to
        run it", that benign stamp made the installer refuse to retire the legacy job,
        and it refused again on every tick after: the machine never left the additive
        window, and the run blamed a tick that had in fact succeeded.

        A visit is not an outcome, and neither is a stamp. The outcome is."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            good = scheduled_run(b, self.LANE)
            self.assertEqual(good["last_exit"], 0, good)
            machine_tick(b, force=False)         # the very next tick: nothing is due yet
            rec = record(b, self.LANE)
            self.assertEqual(rec["skipped"], "not due",
                             "the cadence gate did not pass the lane over; this proves nothing: %s" % rec)
            self.assertIsNone(rec["refused"], "nothing refused this lane: %s" % rec)
            self.assertEqual(rec["last_exit"], 0, "the clean run is still the outcome on record")
            self.assertEqual(rec["attempted_at"], good["attempted_at"],
                             "a skipped tick must not move the stamp of the run that happened")
            r = self.reconnect(b)
            self.assertNotIn(self.LEGACY, b.plists(),
                             "the shared job mirrored this lane cleanly and the next tick "
                             "passed it over, so the legacy job was kept -- and will be kept "
                             "on every tick after: this machine never leaves the additive "
                             "window.\n" + r.stdout)

    def test_a_killed_run_the_gate_then_passes_over_still_keeps_the_old_job(self):
        """Why the gate cannot simply stop reading `skipped`. One tick later the same
        benign "not due" sits on a record whose last real outcome was a kill: judging the
        stamp instead of the outcome would park a working job on the strength of a run
        that mirrored nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            hang = stand_in(b, "hangs.sh", "#!/bin/bash\nsleep 30\n")
            killed = scheduled_run(b, self.LANE, mirror=hang, timeout_s=1)
            self.assertTrue(killed["timed_out"], "the stand-in was not killed: %s" % killed)
            machine_tick(b, force=False)
            rec = record(b, self.LANE)
            self.assertEqual(rec["skipped"], "not due", "the gate did not pass it over: %s" % rec)
            self.assertTrue(rec["timed_out"], "the kill is still the outcome on record: %s" % rec)
            self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "a lane that is killed on every tick had its working job parked "
                          "because the tick after the kill said only 'not due'")

    def test_a_failed_run_the_gate_then_passes_over_still_keeps_the_old_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            bad = stand_in(b, "fails.sh", "#!/bin/bash\nexit 3\n")
            self.assertEqual(scheduled_run(b, self.LANE, mirror=bad)["last_exit"], 3)
            machine_tick(b, force=False)
            rec = record(b, self.LANE)
            self.assertEqual(rec["skipped"], "not due", "the gate did not pass it over: %s" % rec)
            self.assertEqual(rec["last_exit"], 3, "the failure is still the outcome on record: %s" % rec)
            self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "an exit 3, then a tick that passed the lane over, licensed "
                          "retiring the job that still worked")

    def test_a_tick_that_passes_the_lane_over_is_not_itself_the_evidence(self):
        """Ignoring the benign stamp must not turn the TICK into the proof. The only run
        on this lane's record is the one its own installer ran by hand; a scheduled tick
        that arrives, finds nothing due and passes it over adds no evidence at all."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)                # connecting ran the lane by hand
            machine_tick(b, force=False)         # the scheduler arrives, nothing is due
            rec = record(b, self.LANE)
            self.assertEqual(rec["skipped"], "not due", "the gate did not pass it over: %s" % rec)
            self.assertEqual(rec["last_exit"], 0, "the hand run was clean; that is the trap here")
            self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "the shared job has never mirrored this lane on its own schedule, "
                          "and a tick that passed it over was counted as one that did")

    def test_a_visit_the_runner_refused_does_not_retire_the_old_job(self):
        """A refused lane is not run at all, so its attempted_at is history carried
        forward from the last real run. Read on its own it says the shared job has been
        here; the record says in the same breath that nothing was mirrored."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.machine(tmp)
            good = scheduled_run(b, self.LANE)
            self.assertEqual(good["last_exit"], 0, good)
            rec = scheduled_run(b, self.LANE, mirror=b.tmp / "gone" / "mirror.sh")
            self.assertEqual(rec["refused"], "mirror missing", rec)
            self.assertIsNone(rec["last_exit"], "a refused lane must not keep a green exit code")
            self.assertTrue(rec["attempted_at"], "the carried stamp is the whole trap here")
            self.reconnect(b)
            self.assertIn(self.LEGACY, b.plists(),
                          "the last scheduled visit mirrored nothing and the old job went anyway")


class MoverWithoutAStagingHop(unittest.TestCase):
    """A directory pipe belongs to no lane, and no permission rule stops a machine
    without a staging hop from carrying one. `sov relay add` used to declare the source,
    print it, exit 0 and install nothing at all there -- which is every Linux box, and
    every Mac whose vault is not inside a protected folder."""

    def test_a_mac_with_an_unprotected_vault_carries_its_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)                      # no ~/.vault-staging, vault outside Documents
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                             "a machine with nothing to drain must not carry a mover for nothing")
            watched = b.tmp / "Claude"
            watched.mkdir()
            r = b.relay("add", [str(watched)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("com.sovereign.connector.relay.plist", b.plists(),
                          "`sov relay add` reported a pipe that nothing on this machine carries")
            args = b.relay_plist()["ProgramArguments"]
            self.assertEqual(args[0], "/usr/bin/rsync")
            self.assertEqual(args[1], "-a")
            self.assertEqual(args[2:2 + len(ti.EXCLUDES)], ti.EXCLUDES)
            self.assertEqual(args[2 + len(ti.EXCLUDES):-1], [str(watched)],
                             "with no staging hop the mover carries the declared pipes and nothing else")
            self.assertEqual(args[-1], str(b.vault / "raw" / "tools") + "/")
            self.assertNotIn("--delete", args)
            log = b.log.read_text()
            self.assertIn("bootstrap", log)
            self.assertIn("com.sovereign.connector.relay.plist", log,
                          "the mover was written and never loaded")
            listing = b.relay("list")
            self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
            self.assertIn("com.sovereign.connector.relay", listing.stdout)
            self.assertIn(str(watched), listing.stdout)

    def test_removing_the_last_pipe_takes_the_mover_with_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            self.assertEqual(b.relay("add", [str(watched)]).returncode, 0)
            self.assertIn("com.sovereign.connector.relay.plist", b.plists(),
                          "the pipe was declared and nothing was installed to carry it")
            r = b.relay("remove", ["Claude"])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                             "the mover stayed behind rsyncing a source nothing declares any more")

    def test_linux_carries_its_pipes_on_a_systemd_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, platform="Linux")
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertNotIn("sovereign-connector-relay.timer", b.units(),
                             "no pipe is declared, so nothing to carry")
            watched = b.tmp / "Claude"
            watched.mkdir()
            r = b.relay("add", [str(watched)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("sovereign-connector-relay.service", b.units())
            self.assertIn("sovereign-connector-relay.timer", b.units())
            svc = (b.home / ".config" / "systemd" / "user" /
                   "sovereign-connector-relay.service").read_text()
            self.assertIn("/usr/bin/rsync", svc)
            self.assertIn('"%s"' % watched, svc, "every argument is quoted: systemd splits on whitespace")
            self.assertIn('"%s/"' % (b.vault / "raw" / "tools"), svc)
            self.assertNotIn("--delete", svc)
            self.assertIn("enable --now sovereign-connector-relay.timer", b.log.read_text(),
                          "the unit was written and never enabled")


class MoverDestination(unittest.TestCase):
    """Where the mover really writes, and where the installer says it writes.

    Behind a staging hop the destination is re-declared on every connect. Off that path
    it is declared once, by `sov relay add`, and never again -- while the sentence the
    install prints is built from the vault THIS run was given. Move the vault and the two
    part company: the line says the new brain, the argv still carries into the old one,
    and a person reading the install has no way to tell.
    """

    def other_brain(self, b):
        # never a name the first vault's path is a prefix of: the check below asks which
        # of the two a sentence names, and a prefix would answer "both"
        v = b.tmp / "second-brain"
        (v / "knowledge" / "entities").mkdir(parents=True)
        (v / "raw" / "tools").mkdir(parents=True)
        (v / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n")
        return v

    def relay_line(self, out):
        line = [l for l in out.splitlines() if "connector.relay" in l and " into " in l]
        self.assertTrue(line, "the install said nothing about where the mover carries to:\n" + out)
        return line[-1]

    def test_the_sentence_and_the_argv_name_the_same_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)                                  # no staging hop
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            self.assertEqual(b.relay("add", [str(watched)]).returncode, 0)
            moved = self.other_brain(b)
            r = b.connect("windsurf", vault=moved)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            dest = b.relay_plist()["ProgramArguments"][-1]
            line = self.relay_line(r.stdout)
            named = [str(v) for v in (b.vault, moved) if str(v) in line]
            self.assertEqual(len(named), 1, "the line names both brains, or neither: %r" % line)
            self.assertTrue(dest.startswith(named[0]),
                            "the install says the mover carries into %s; its argv carries into %s"
                            % (named[0], dest))

    def test_the_pipe_still_lands_inside_a_brain(self):
        """Whichever way the two are made to agree, the destination has to stay a real
        vault: an rsync into a path with no raw/tools/ is a pipe that mirrors nowhere."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            self.assertEqual(b.relay("add", [str(watched)]).returncode, 0)
            self.assertEqual(b.connect("windsurf", vault=self.other_brain(b)).returncode, 0)
            dest = Path(b.relay_plist()["ProgramArguments"][-1])
            self.assertEqual((dest.parent.name, dest.name), ("raw", "tools"),
                             "the mover carries into %s, which is not a lane root" % dest)
            self.assertTrue(dest.is_dir(), "the mover carries into %s, which is not there" % dest)
            self.assertTrue((dest.parent.parent / "knowledge").is_dir(),
                            "the mover carries into %s, which is not inside a brain" % dest)


class MoverBootstrapFailure(unittest.TestCase):
    """A mover that will not load is loud -- and it has its own thing to say. Borrowing
    the runner's sentence tells the owner every lane on the machine has stopped, which is
    false and sends them looking in the wrong place; what actually stopped is the
    directory pipes, which no lane owns and nothing else carries."""

    RUNNERS_SENTENCE = "No lane on this Mac will run"

    def test_the_movers_failure_does_not_claim_the_lanes_stopped(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            r = b.relay("add", [str(watched)], SOV_STUB_RC="1")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 70, "a pipe nothing carries has to be loud:\n" + out)
            self.assertIn("com.sovereign.connector.relay", out,
                          "the failure does not name the job that would not load")
            self.assertNotIn(self.RUNNERS_SENTENCE, out,
                             "the mover printed the runner's sentence: no lane stopped here, "
                             "the declared directory pipe did")

    def test_the_runner_keeps_its_own_sentence(self):
        """The other half: the two failures must stay tellable apart."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            r = b.connect("windsurf", SOV_STUB_RC="1")
            self.assertEqual(r.returncode, 70, r.stdout + r.stderr)
            self.assertIn(self.RUNNERS_SENTENCE, r.stdout + r.stderr)


class DocsMatchTheMover(unittest.TestCase):
    """`MoverWithoutAStagingHop` proves a machine off the staging path installs a mover
    the moment a directory pipe is declared, on either platform. A doc that still says
    there is none there sends a reader looking for a background job the machine has."""

    STALE = "no mover at all"

    def test_no_doc_still_says_a_machine_off_the_staging_path_has_none(self):
        for md in sorted(ti.ROOT.rglob("*.md")):
            if "/.git/" in str(md):
                continue
            text = md.read_text(encoding="utf-8", errors="ignore").lower()
            self.assertNotIn(self.STALE, text,
                             "%s says %r; `sov relay add` installs one there" %
                             (md.relative_to(ti.ROOT), self.STALE))

    def test_the_connector_readme_still_documents_the_command_that_installs_one(self):
        text = (ti.ROOT / "connectors" / "README.md").read_text(encoding="utf-8")
        self.assertIn("sov relay add", text, "this test is blind if the recipe is gone")


class MoverAfterTheLastLane(unittest.TestCase):
    """Disconnecting the last tool drops the runner. The mover is not the runner's
    shadow: it also carries the watch folders, which no lane owns."""

    def test_the_pipes_it_still_carries_keep_it_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            folders = []
            for name in ("Claude", "Codex"):
                d = b.tmp / name
                d.mkdir()
                folders.append(d)
                self.assertEqual(b.relay("add", [str(d)]).returncode, 0, name)
            r = b.disconnect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})
            self.assertNotIn("com.sovereign.connector.runner.plist", b.plists(),
                             "the last lane went, so the runner goes")
            self.assertIn("com.sovereign.connector.relay.plist", b.plists(),
                          "two watch folders stopped mirroring with the last lane, silently")
            args = b.relay_plist()["ProgramArguments"]
            for d in folders:
                self.assertIn(str(d), args, "the mover was rebuilt without a pipe it still carries")
            self.assertIn("2 directory pipe(s)", r.stdout,
                          "a mover that stays has to say how much it still carries")

    def test_the_listing_stops_naming_a_mover_that_was_removed(self):
        """`sov relay list` is built from the manifest, and the staging source is the
        mover's own declaration -- written by the job that carries it, not by the owner.
        Left standing after the mover went, the listing went on describing a background
        job that is not installed, and the reader had no way to tell."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            before = b.relay("list")
            self.assertEqual(before.returncode, 0, before.stdout + before.stderr)
            self.assertIn("com.sovereign.connector.relay", before.stdout,
                          "nothing was listed while a mover was installed; this proves nothing")
            self.assertEqual(b.disconnect("windsurf").returncode, 0)
            self.assertEqual(b.plists(), [], "the mover is still installed; this proves nothing")
            after = b.relay("list")
            self.assertEqual(after.returncode, 0, after.stdout + after.stderr)
            self.assertNotIn("com.sovereign.connector.relay", after.stdout,
                             "the listing names a mover this machine no longer carries:\n"
                             + after.stdout)

    def test_a_mover_with_nothing_left_goes_and_names_what_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            r = b.disconnect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.plists(), [])
            self.assertIn("[relay]", r.stdout, "the mover went without a word")
            report = r.stdout.split("[relay]", 1)[1].split("[lane]")[0]
            self.assertIn(str(b.home / ".vault-staging" / "raw" / "tools"), report,
                          "a mover that goes has to name what it stops carrying")


class StagingTreeAndWhatCarriesIt(unittest.TestCase):
    """Creating ~/.vault-staging is not a local act.

    mirror-common.sh's sov_dest redirects EVERY mirror on the machine into that tree the
    moment it exists -- it is checked before the vault, precisely so no lane can write
    into a protected folder from a script-program job. So the tree and the mover that
    drains it are one decision. A tree with no mover is every lane on the box mirroring
    into a dead end, and nothing says a word: exactly the silent stall this whole change
    exists to end.

    The installer made the tree first and installed the job that carries it two calls
    later, with an exit 70 in between.
    """

    RELAY = "com.sovereign.connector.relay.plist"

    def brain_inside_documents(self, b):
        """What puts a Mac behind the staging hop: a vault under ~/Documents. The folder
        is TCC-protected, a job whose program is a script host cannot write there, and
        the denial is silent."""
        v = b.home / "Documents" / "brain"
        (v / "knowledge" / "entities").mkdir(parents=True)
        (v / "raw" / "tools").mkdir(parents=True)
        (v / "knowledge" / "entities" / "me.md").write_text(
            "---\ntype: entity\nsource: owner\ncreated: 2026-01-01\n---\n# Me\n")
        return v

    def test_the_control_a_protected_vault_gets_both_the_tree_and_the_mover(self):
        """Without this every test below could pass on a machine that never staged."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)                      # no ~/.vault-staging yet
            r = b.connect("windsurf", vault=self.brain_inside_documents(b))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertTrue((b.home / ".vault-staging" / "raw" / "tools").is_dir(),
                            "this box never went behind a staging hop; the tests below are blind")
            self.assertIn(self.RELAY, b.plists(), "the tree is there and nothing drains it")
            self.assertIn("bootstrap", b.log.read_text())

    def test_a_failed_install_leaves_no_tree_for_nothing_to_carry(self):
        """The runner will not load, so the install stops at exit 70 -- and every lane on
        this machine has already been redirected into a tree that no mover will ever
        drain."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            r = b.connect("windsurf", vault=self.brain_inside_documents(b), SOV_STUB_RC="1")
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 70, "the install was supposed to fail here:\n" + out)
            self.assertNotIn(self.RELAY, b.plists(),
                             "the mover was installed after all; this proves nothing")
            self.assertFalse((b.home / ".vault-staging").exists(),
                             "the install failed and left ~/.vault-staging behind. sov_dest "
                             "sends every mirror on this machine into that tree as soon as it "
                             "exists, and nothing here carries it into the vault: every lane "
                             "on the box now writes into a dead end, silently.\n" + out)

    def test_a_mover_that_will_not_load_leaves_no_tree_either(self):
        """The same rule at the other failure point. The runner comes up, the tree is
        made, and the one job that drains it will not start -- which is the worse half:
        the lanes now run on a schedule, into staging, forever."""
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp)
            stub = b.stub / "launchctl"
            stub.write_text('#!/bin/bash\n'
                            'printf "%s %s\\n" "$(basename "$0")" "$*" >> "$SOV_STUB_LOG"\n'
                            'case "$*" in *bootstrap*connector.relay*) exit 1;; esac\n'
                            'exit 0\n')
            stub.chmod(0o755)
            r = b.connect("windsurf", vault=self.brain_inside_documents(b))
            out = r.stdout + r.stderr
            self.assertEqual(r.returncode, 70, "the mover was supposed to fail to load:\n" + out)
            self.assertIn("com.sovereign.connector.relay", out, "the failure names no job")
            self.assertFalse((b.home / ".vault-staging").exists(),
                             "nothing on this machine carries staging into the vault, and the "
                             "tree that redirects every mirror into it was left behind.\n" + out)


class LaneContractProse(unittest.TestCase):
    """The LANE.md patcher, from the other side.

    These files live in the owner's synced, git-tracked vault, so the rewrite has to be
    exactly as wide as the write-wire sentence. What marks that sentence is the cadence
    sitting immediately in front of the connector word; prose that merely names the lane
    id has no cadence there and must come back untouched.
    """

    LABEL = "com.sovereign.connector.windsurf"
    # three real ways a contract names its lane without describing the write wire
    PASSING = ("The console row for this lane is filed under `%(l)s`.\n"
               "It runs every 900s, and the console still shows it as `%(l)s` in the lane list.\n"
               "Everything the mirror writes lands in `%(l)s`, under raw/tools/ in the vault.\n")

    def patch(self, body, platform="Darwin"):
        with tempfile.TemporaryDirectory() as tmp:
            b = ti.Box(tmp, platform=platform)
            lane_dir = b.vault / "raw" / "tools" / "windsurf-testbox"
            lane_dir.mkdir(parents=True)
            (lane_dir / "LANE.md").write_text(body)
            r = b.connect("windsurf")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            return (lane_dir / "LANE.md").read_text()

    def check(self, name, out, passing, label, runner):
        self.assertIn(runner, out, "%s: the write-wire sentence still names no live job" % name)
        self.assertIn("lane id `%s`" % label, out, "%s: the lane's own id is the console row" % name)
        self.assertIn(passing.strip(), out,
                      "%s: a sentence that only mentions the lane id was rewritten too" % name)

    def test_each_real_shape_is_rewritten_and_the_prose_beside_it_is_not(self):
        passing = self.PASSING % {"l": self.LABEL}
        for name, shape in sorted(ti.LaneContract.SHAPES.items()):
            with self.subTest(shape=name):
                out = self.patch(ti.LaneContract.HEAD + (shape % self.LABEL) + "\n" + passing)
                self.check(name, out, passing, self.LABEL, ti.LaneContract.RUNNER)
                self.assertIn("every 900s", out, "%s: the cadence in front of the label is kept" % name)

    def test_the_systemd_shape_too(self):
        label = "sovereign-connector-windsurf"
        passing = self.PASSING % {"l": label}
        out = self.patch(ti.LaneContract.HEAD + ti.LaneContract.SYSTEMD + "\n" + passing,
                         platform="Linux")
        self.check("systemd", out, passing, label, "sovereign-connector-runner")


if __name__ == "__main__":
    unittest.main()
