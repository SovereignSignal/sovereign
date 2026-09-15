"""bin/sov: the front door every recipe in this repo sends people to.

Nothing here reaches into `install-common.sh`. That is the whole point of the file. A
library function can exist, be covered by a test that sources it directly, and still be
unreachable from the shipped command, so a suite that calls `sov_relay_add` proves only
that a shim works. `sov relay add` is the only shipped way to declare a directory source
and `sov disconnect` is the only uninstall recipe the repo prints, so both are exercised
here exactly as a README spells them, through `bin/sov`.

The machine is the same throwaway box the installer tests use: fake HOME, a real-enough
vault, stubbed job control. Nothing loads a real job and nothing writes outside the temp
dir.
"""
import json
import os
import plistlib
import re
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_connectors_install import ROOT, Box, scheduled_tick_all

SOV = ROOT / "bin" / "sov"
# A stub that answers `launchctl list` as well as logging, so brain-status sees the
# machine this migration actually targets: every tool connected under its own old job.
LAUNCHCTL = """#!/bin/bash
printf "%s %s\\n" "$(basename "$0")" "$*" >> "$SOV_STUB_LOG"
case "$1" in
  list)  printf 'PID\\tStatus\\tLabel\\n'; for l in ${SOV_STUB_LABELS:-}; do printf -- '-\\t0\\t%s\\n' "$l"; done ;;
  print) echo "last exit code = 0" ;;
esac
exit "${SOV_STUB_RC:-0}"
"""


def mover_job(b):
    """This machine's mover: (the file it is declared in, what it would REALLY run), read
    off the installed job rather than off the manifest -- a plist's ProgramArguments on
    Darwin, the unit's ExecStart on Linux. (None, []) when no such job exists, which is
    the state `sov relay add` used to report as success: a pipe nothing carries."""
    if b.platform == "Darwin":
        for p in sorted((b.home / "Library" / "LaunchAgents").glob("*.plist")):
            try:
                argv = plistlib.loads(p.read_bytes()).get("ProgramArguments") or []
            except Exception:
                continue
            if argv and os.path.basename(argv[0]) == "rsync":
                return p, argv
        return None, []
    for p in sorted((b.home / ".config" / "systemd" / "user").glob("*.service")):
        for line in p.read_text().splitlines():
            if line.startswith("ExecStart=") and "rsync" in line:
                return p, shlex.split(line.split("=", 1)[1])
    return None, []


def mover_argv(b):
    return mover_job(b)[1]


def sov(args, env, cwd=None, timeout=180):
    return subprocess.run(["/bin/bash", str(SOV)] + list(args), capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=timeout)


def documented_commands():
    """Every `sov <word>` this repo instructs, read out of the docs themselves.

    Only code spans and fenced blocks count: prose says things like "sov not found",
    which is not an instruction to type anything."""
    found = set()
    for md in sorted(ROOT.rglob("*.md")):
        if "/.git/" in str(md):
            continue
        text = md.read_text(encoding="utf-8", errors="ignore")
        spans = re.findall(r"```.*?```", text, re.S) + re.findall(r"`[^`\n]+`", text)
        for span in spans:
            for word in re.findall(r"\bsov ([a-z][a-z-]*)", span):
                found.add(word)
    return found


class Routing(unittest.TestCase):
    """What the docs tell a person to type has to reach a branch of the router."""

    def bare(self, tmp):
        """No pointers, no vault: every command must still route, and say its own piece."""
        home = Path(tmp) / "home"
        home.mkdir()
        return {"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/sbin:/sbin"}

    def test_every_command_the_docs_instruct_is_routed_by_bin_sov(self):
        cmds = documented_commands()
        self.assertIn("relay", cmds, "the docs stopped instructing `sov relay`; this test is now blind")
        self.assertIn("disconnect", cmds)
        with tempfile.TemporaryDirectory() as tmp:
            env = self.bare(tmp)
            for c in sorted(cmds):
                r = sov([c], env, timeout=120)
                self.assertNotIn("unknown command", r.stdout + r.stderr,
                                 "the docs instruct `sov %s` and the router does not carry it" % c)

    def test_the_available_list_offers_only_harnesses_that_can_be_connected(self):
        """Both verbs answer a missing argument with a list of what to type. Built with a
        bare `ls`, that list also offers the catalog's own README.md, so the front door
        names a harness that does not exist and `sov connect README.md` is the answer."""
        catalog = ROOT / "connectors" / "harness"
        ids = sorted(p.name for p in catalog.iterdir()
                     if p.is_dir() and not p.name.startswith("_") and (p / "install.sh").exists())
        self.assertIn("README.md", [p.name for p in catalog.iterdir()],
                      "the catalog no longer holds a README; this test is now blind")
        with tempfile.TemporaryDirectory() as tmp:
            env = self.bare(tmp)
            for verb in ("connect", "disconnect"):
                r = sov([verb], env)
                self.assertEqual(r.returncode, 64, verb)
                out = r.stdout + r.stderr
                self.assertIn("available:", out, verb)
                offered = sorted(out.split("available:", 1)[1].split())
                self.assertEqual(offered, ids,
                                 "sov %s offers something that is not a connectable harness" % verb)

    def test_every_documented_command_is_in_the_front_doors_own_help(self):
        cmds = documented_commands()
        with tempfile.TemporaryDirectory() as tmp:
            help_text = sov(["help"], self.bare(tmp)).stdout
        for c in sorted(cmds):
            self.assertIn("sov %s" % c, help_text,
                          "`sov %s` is routed but `sov help` does not list it" % c)


class Relay(unittest.TestCase):
    """`sov relay add` is the replacement for the hand-installed watch-folder plists.
    Without it a client Mac floors at four background items instead of two."""

    def box(self, tmp):
        b = Box(tmp, staging=True)
        r = b.connect("windsurf")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return b

    def sources(self, b):
        args = b.relay_plist()["ProgramArguments"]
        return [a for a in args if not a.startswith("--") and a not in ("/usr/bin/rsync", "-a")]

    def test_add_list_and_remove_a_watch_folder_through_the_shipped_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            watched = b.tmp / "Claude"
            watched.mkdir()
            r = sov(["relay", "add", str(watched)], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(str(watched), self.sources(b),
                          "the mover does not carry the folder `sov relay add` declared")
            r = sov(["relay", "list"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("Claude", r.stdout)
            self.assertIn(str(watched), r.stdout)
            r = sov(["relay", "remove", "Claude"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(str(watched), self.sources(b))
            self.assertEqual(json.loads((b.state / "connectors.json").read_text())["relay"]["sources"],
                             [s for s in json.loads((b.state / "connectors.json").read_text())["relay"]["sources"]
                              if s["kind"] == "staging"], "removing a pipe must not take staging with it")

    def test_two_watch_folders_are_two_sources_on_one_job(self):
        """The count is the point of the change: pipes are sources, never jobs."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            for name in ("Claude", "Codex"):
                d = b.tmp / name
                d.mkdir()
                r = sov(["relay", "add", str(d)], b.env())
                self.assertEqual(r.returncode, 0, name + ": " + r.stdout + r.stderr)
            self.assertEqual(b.plists(), ["com.sovereign.connector.relay.plist",
                                          "com.sovereign.connector.runner.plist"],
                             "a watch folder added a background item")
            srcs = self.sources(b)
            self.assertIn(str(b.tmp / "Claude"), srcs)
            self.assertIn(str(b.tmp / "Codex"), srcs)

    def test_a_colliding_folder_is_refused_by_the_command_not_only_by_the_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            first, second = b.tmp / "a" / "Claude", b.tmp / "b" / "Claude"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            self.assertEqual(sov(["relay", "add", str(first)], b.env()).returncode, 0)
            r = sov(["relay", "add", str(second)], b.env())
            self.assertNotEqual(r.returncode, 0,
                                "two sources sharing a basename merge into one destination at exit 0")
            self.assertIn(str(first), self.sources(b), "the first pipe survived the refusal")
            self.assertNotIn(str(second), self.sources(b))


class RelayWithoutStaging(unittest.TestCase):
    """A machine with no staging hop still has watch folders.

    The staging hop exists for one reason: a vault inside a TCC-protected folder. A Linux
    box has no such thing, and neither does a Mac whose vault sits outside those folders,
    which is the hub's own shape. There is no permission reason either machine cannot
    carry a directory pipe, and `sov relay add` is the only shipped way to declare one.
    What it must never do is what it did: print the pipe, exit 0, install nothing, and
    leave `sov relay list` naming a job that exists on no machine while the folder is
    mirrored by nothing at all.
    """

    def declared(self, b):
        m = json.loads((b.state / "connectors.json").read_text()) if (b.state / "connectors.json").exists() else {}
        return [s.get("path") for s in ((m.get("relay") or {}).get("sources") or [])]

    def loaded(self, b, unit):
        """The scheduler was really handed this unit. A written job is not a running one,
        and an empty error log next to a job nobody loaded proves nothing at all."""
        want = ("bootstrap", str(unit)) if b.platform == "Darwin" else ("enable --now", unit.stem + ".timer")
        return [l for l in b.log.read_text().splitlines() if all(w in l for w in want)]

    def check(self, b, watched):
        r = sov(["relay", "add", str(watched)], b.env())
        listing = sov(["relay", "list"], b.env())
        if r.returncode == 0:
            unit, argv = mover_job(b)
            self.assertTrue(argv, "`sov relay add` reported success and installed no mover:\n" + r.stdout + r.stderr)
            self.assertEqual(os.path.basename(argv[0]), "rsync")
            self.assertIn(str(watched), argv, "the mover does not carry the folder that was declared")
            self.assertEqual(argv[-1], str(b.vault / "raw" / "tools") + "/", "the pipe lands in the vault")
            self.assertNotIn("--delete", argv, "--delete removes every lane no source covers")
            self.assertTrue(self.loaded(b, unit),
                            "the mover was written and never handed to the scheduler:\n" + b.log.read_text())
            self.assertIn(str(watched), listing.stdout, "`sov relay list` does not name the pipe it carries")
        else:
            # Loud is the other acceptable answer, and then nothing may stay declared: a
            # source in the manifest with no mover is the same lie in a quieter place.
            self.assertTrue((r.stderr + r.stdout).strip(), "a refusal has to say why")
            self.assertNotIn(str(watched), self.declared(b),
                             "the pipe was refused and left declared anyway")
            self.assertNotIn(str(watched), listing.stdout)

    def test_a_mac_whose_vault_is_not_behind_a_hop_carries_its_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)                                   # no ~/.vault-staging, vault outside Documents
            self.assertEqual(b.connect("windsurf").returncode, 0)
            self.assertFalse((b.home / ".vault-staging").exists(), "this box has no staging hop")
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"],
                             "one job so far: there is nothing to move yet")
            watched = b.tmp / "Claude"
            watched.mkdir()
            self.check(b, watched)

    def test_linux_carries_a_declared_pipe_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, platform="Linux")
            self.assertEqual(b.connect("windsurf").returncode, 0)
            watched = b.tmp / "Claude"
            watched.mkdir()
            self.check(b, watched)


class Disconnect(unittest.TestCase):
    """The only uninstall recipe this repo prints, run the way it is printed."""

    def test_the_readme_uninstall_recipe_undeclares_the_lane(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            for h in ("windsurf", "orca"):
                self.assertEqual(b.connect(h).returncode, 0, h)
            r = sov(["disconnect", "windsurf"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dry run", r.stdout.lower())
            self.assertEqual(sorted(b.manifest()["harnesses"]), ["orca", "windsurf"],
                             "a dry run changed the machine")
            r = sov(["disconnect", "windsurf", "--apply"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(list(b.manifest()["harnesses"]), ["orca"])
            self.assertTrue((b.state / "lanes" / "windsurf.error.log.retired").exists())
            self.assertEqual(b.plists(), ["com.sovereign.connector.runner.plist"])

    def test_disconnecting_the_last_tool_keeps_the_mover_that_carries_watch_folders(self):
        """The mover is not the runner's shadow.

        It also carries the directory pipes, and those belong to no tool: `sov relay add`
        declared them, not `sov connect`. Dropping the mover because the last LANE left
        stops every watch folder on the machine, at exit 0, with nothing said -- the exact
        silent stop this whole change exists to remove."""
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp, staging=True)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            pipes = []
            for name in ("Claude", "Codex"):
                d = b.tmp / name
                d.mkdir()
                self.assertEqual(sov(["relay", "add", str(d)], b.env()).returncode, 0, name)
                pipes.append(d)
            self.assertTrue(all(str(d) in mover_argv(b) for d in pipes))
            r = sov(["disconnect", "windsurf", "--apply"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {}, "that was the last lane")
            argv = mover_argv(b)
            if argv:
                for d in pipes:
                    self.assertIn(str(d), argv,
                                  "the mover stayed but stopped carrying a pipe no lane ever owned")
                self.assertEqual(argv[-1], str(b.vault / "raw" / "tools") + "/")
                said = [l for l in r.stdout.splitlines()
                        if re.search(r"\b2\b", l) and re.search(r"(?i)pipe|source|folder|director", l)]
                self.assertTrue(said or all(str(d) in r.stdout for d in pipes),
                                "the mover stays and the run never says what it still carries:\n" + r.stdout)
                self.assertIn(str(pipes[0]), sov(["relay", "list"], b.env()).stdout)
            else:
                # If it must go, the folders it stops mirroring are named, every one.
                for d in pipes:
                    self.assertIn(str(d), r.stdout,
                                  "the mover went and this watch folder stopped mirroring silently")

    def test_disconnecting_the_last_lane_through_the_front_door_leaves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            self.assertEqual(b.connect("windsurf").returncode, 0)
            r = sov(["disconnect", "windsurf", "--apply"], b.env())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.manifest()["harnesses"], {})
            self.assertEqual(b.plists(), [])


class ConnectAll(unittest.TestCase):
    """`sov connect all` is step one of the migration. On the machine it targets every
    tool is already connected, under its own old job: if "connected" excludes a tool from
    the run, the migration writes nothing and installs nothing, at exit 0."""

    def box(self, tmp):
        b = Box(tmp)
        (b.stub / "launchctl").write_text(LAUNCHCTL)
        (b.stub / "launchctl").chmod(0o755)
        # a machine mid-fleet: pointers written long ago by the per-tool installers
        (b.home / ".brain-root").write_text(str(b.vault))
        (b.home / ".brain-host").write_text("testbox")
        (b.home / ".brain-core").write_text("me")
        # the read wires, so brain-status can reach "connected" rather than "partial"
        (b.home / ".claude").mkdir()
        (b.home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"SessionStart": [
            {"matcher": "startup", "hooks": [{"type": "command", "command": str(
                ROOT / "connectors" / "harness" / "claude-code" / "session-start.py")}]}]}}))
        (b.home / ".orca").mkdir()
        # ...and the old per-tool jobs, which is why they read connected
        for h in ("claude-code", "orca"):
            (b.home / "Library" / "LaunchAgents" / ("com.sovereign.connector.%s.plist" % h)).write_text(
                "<?xml version=\"1.0\"?>\n<plist version=\"1.0\"><dict>\n"
                "<key>Label</key><string>com.sovereign.connector.%s</string>\n"
                "<key>StartInterval</key><integer>900</integer>\n</dict></plist>\n" % h)
        return b

    def calendar_box(self, tmp, hub=None):
        """A machine with one local tool and one cloud pull, and nothing legacy on it.

        `hub` makes it a client: the pointer names another machine, and the hub is stubbed
        so the run reaches the same answer whether it asks the hub or reads the pointer."""
        b = Box(tmp)
        (b.stub / "launchctl").write_text(LAUNCHCTL)
        (b.stub / "launchctl").chmod(0o755)
        (b.home / ".brain-root").write_text(str(b.vault))
        (b.home / ".brain-host").write_text("testbox")
        (b.home / ".brain-core").write_text("me")
        (b.home / ".claude").mkdir()
        if hub:
            (b.home / ".brain-hub").write_text("%s:/hub/vault" % hub)
            reply = json.dumps({"reachable": True, "hub_host": hub, "lanes": {}, "contrib": {},
                                "cloud_harnesses": [{"id": "notion", "name": "Notion", "lane": "Notion",
                                                     "label": "com.sovereign.connector.notion",
                                                     "job_loaded": True, "installed": True,
                                                     "state": "connected", "last_success": None,
                                                     "last_status": None}]})
            ssh = b.stub / "ssh"
            ssh.write_text("#!/bin/bash\ncat >/dev/null\nprintf '%%s' %s\n" % shlex.quote(reply))
            ssh.chmod(0o755)
        return b

    def calendar_env(self, b):
        """The pull's own token and its stubbed reachability check: a test never talks to
        a live API, and the point of the case is that a settled machine never does either."""
        return b.env(BRAIN_ROOT=str(b.vault), NOTION_API_KEY="ntn_test",
                     SOV_TEST_CHECK_OUTPUT="bot: TestBot\nworkspace: Test WS\nitems: 0\n"
                                           "roots reachable:\nmissing roots: none\n")

    def env(self, b):
        return b.env(SOV_STUB_LABELS="com.sovereign.connector.claude-code com.sovereign.connector.orca",
                     BRAIN_ROOT=str(b.vault))

    def test_a_tool_that_is_already_connected_is_still_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            self.assertFalse((b.state / "connectors.json").exists(), "the box has not migrated yet")
            state = json.loads(subprocess.run(
                ["/usr/bin/python3", str(ROOT / "bin" / "brain-status"), "--json", "--no-hub"],
                capture_output=True, text=True, env=self.env(b), timeout=180).stdout)
            by_id = {h["id"]: h for h in state["harnesses"]}
            self.assertEqual(by_id["claude-code"]["state"], "connected",
                             "the fixture no longer reproduces the machine this change targets")
            self.assertEqual(by_id["orca"]["state"], "connected")
            r = sov(["connect", "all"], self.env(b), timeout=300)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("already connected and runs", r.stdout,
                             "connect all treated a machine with no manifest as fully migrated")
            head = next((l for l in r.stdout.splitlines() if l.startswith("connecting ")), "")
            self.assertIn("Claude Code", head, "an already-connected tool was left out of the migration")
            self.assertIn("Orca", head)
            self.assertIn("=== Claude Code ===", r.stdout, "its installer never ran")

    def test_one_pass_retires_every_legacy_job_it_replaces_not_just_the_first(self):
        """The count is the whole point: ten background items become two.

        A pass runs one installer after another, and the evidence that licenses retiring
        a per-tool job is per lane. Discounted machine-wide, the first installer's own
        smoke tick makes every later installer in the same pass refuse: the pass retires
        exactly one job, the rest stay loaded, and the machine keeps its screenful."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            # neither pass asserts an exit code: a cloud pull with no token refuses on
            # purpose, and a machine-wide connect cannot invent one. What the jobs on this
            # machine end up being is the assertion.
            first = sov(["connect", "all", "--apply"], self.env(b), timeout=900)
            declared = b.manifest()["harnesses"]
            for h in ("claude-code", "orca"):
                self.assertIn(h, declared, first.stdout[-2000:])
                self.assertIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                              "%s was retired on a tick this same pass produced" % h)
            scheduled_tick_all(b)             # the scheduler fires the shared job, every lane
            second = sov(["connect", "all", "--apply"], self.env(b), timeout=900)
            for h, name in (("claude-code", "Claude Code"), ("orca", "Orca")):
                self.assertIn("=== %s ===" % name, second.stdout, "%s was not re-run at all" % h)
                self.assertNotIn("com.sovereign.connector.%s.plist" % h, b.plists(),
                                 "%s kept its per-tool job: the pass retired only the lane it reached first:\n%s"
                                 % (h, second.stdout[-3000:]))
                self.assertTrue((b.home / "Library" / "LaunchAgents" / "sovereign-retired" /
                                 ("com.sovereign.connector.%s.plist" % h)).exists(),
                                "%s: the parked plist is the restore path" % h)
            self.assertIn("com.sovereign.connector.runner.plist", b.plists(),
                          "the job that replaced them has to be the one left standing")

    def test_a_second_pass_settles_on_a_machine_that_carries_a_calendar_lane(self):
        """`sov connect all --apply` twice in a row must select nothing the second time.

        A cloud pull runs on a wall clock and keeps a job of its own, so it never joins
        the shared runner. It is declared all the same, as a lane the runner does not
        tick: `sov disconnect all` walks the manifest, and a lane that is not on it keeps
        its job loaded while the command reports a clean machine. So the pass has to read
        what the entry SAYS, not mere membership -- read as a tick lane the pull is
        re-selected on every pass forever, and every pass walks a live API, which can
        block the migration behind a network call."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.calendar_box(tmp)
            env = self.calendar_env(b)
            first = sov(["connect", "all", "--apply"], env, timeout=900)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn("=== Notion ===", first.stdout, "the fixture never connected the calendar lane")
            self.assertIn("com.sovereign.connector.notion.plist", b.plists(),
                          "a lane whose run can outlive a tick keeps its own job")
            entry = b.manifest()["harnesses"].get("notion")
            self.assertIsNotNone(entry, "`sov disconnect all` walks the manifest; a calendar lane "
                                        "missing from it keeps its own job and is never reported")
            self.assertIs(entry.get("tick"), False,
                          "the entry does not say the shared runner leaves this lane alone: %s" % entry)
            second = sov(["connect", "all", "--apply"], env, timeout=900)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertNotIn("=== Notion ===", second.stdout,
                             "the pull was walked again: this machine never settles")
            self.assertNotIn("=== ", second.stdout, "the second pass re-ran an installer:\n" + second.stdout)
            self.assertIn("already connected", second.stdout, second.stdout)
            self.assertIn("com.sovereign.connector.notion.plist", b.plists(),
                          "the settle must not cost the pull its job")

    def test_a_client_machine_never_installs_the_pull_its_hub_carries(self):
        """One cloud account, one puller. A machine that points at a hub gets the pull
        from the hub's lane; installing it here too gives one account two pullers writing
        one lane, and on a machine with no token it fails the whole migration."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.calendar_box(tmp, hub="hubbox")
            # deliberately no token in the environment: a pull attempted here refuses for
            # want of one and fails the whole pass, so exit 0 is itself part of the proof
            r = sov(["connect", "all", "--apply"], b.env(BRAIN_ROOT=str(b.vault)), timeout=900)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn("=== Notion ===", r.stdout, "a client machine ran the hub's cloud pull")
            self.assertNotIn("com.sovereign.connector.notion.plist", b.plists())
            self.assertFalse((b.home / ".notion-mirror").exists(), "the client wrote the pull's own state")
            self.assertIn("hubbox", r.stdout, "the run has to say where that lane does run")
            self.assertIn("sov connect notion", r.stdout, "and how to connect it there")
            self.assertIn("=== Claude Code ===", r.stdout, "the local tools are still connected here")

    def test_the_plan_is_printed_before_the_work_it_describes(self):
        """Every line here goes to one fd that the installers write to directly. Block
        buffered -- which is what stdout is through `tee` or over ssh, and a migration is
        always logged -- the header and the plan land after everything they introduce, so
        the log reads as if nothing was planned at all.

        What has to come first is the plan, not necessarily the first line: this command's
        own notices about lanes it is leaving alone (one the hub carries, one waiting on a
        credential this machine does not have) are printed before it, and they are printed
        by this command too. Nothing an INSTALLER writes may precede them."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            r = sov(["connect", "all"], self.env(b), timeout=300)      # a pipe, like tee or ssh
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            lines = [l for l in r.stdout.splitlines() if l.strip()]
            plan = next((i for i, l in enumerate(lines) if l.startswith("connecting ")), None)
            self.assertIsNotNone(plan, "no plan was printed at all:\n" + "\n".join(lines[:6]))
            self.assertEqual([l for l in lines[:plan] if l.startswith("=== ")
                              or l.startswith("Sovereign connector:")], [],
                             "the plan landed after the work it describes:\n"
                             + "\n".join(lines[:plan + 1]))
            self.assertLess(r.stdout.index("=== Claude Code ==="),
                            r.stdout.index("Sovereign connector: claude-code"),
                            "the section header landed after the section")

    def test_it_declares_every_connected_tool_when_applied(self):
        """Migration step one, applied. The exit code is not asserted: a cloud pull with
        no token refuses on purpose, and a machine-wide connect cannot invent one."""
        with tempfile.TemporaryDirectory() as tmp:
            b = self.box(tmp)
            r = sov(["connect", "all", "--apply"], self.env(b), timeout=900)
            declared = b.manifest()["harnesses"]
            for h in ("claude-code", "orca"):
                self.assertIn(h, declared,
                              "%s stayed on its old per-tool job forever: %s" % (h, r.stdout[-2000:]))
                self.assertEqual(declared[h]["label"], "com.sovereign.connector.%s" % h)
            self.assertIn("com.sovereign.connector.runner.plist", b.plists())


if __name__ == "__main__":
    unittest.main()


class Interpreter(unittest.TestCase):
    """bin/sov and the job it installs answer "which python" the same way. The front door
    runs the brain's own tools on its choice and hands it down, so on a Mac whose shim an
    Xcode update just revoked (exit 69) the status probe and the connector job survive
    together, or the console reads "not connected" with the tick still failing behind it."""

    def test_the_front_door_and_the_job_it_installs_pick_the_same_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Box(tmp)
            b.clt_python.write_text('#!/bin/bash\necho "clt-python3 $*" >> "$SOV_STUB_LOG"\nexec /usr/bin/python3 "$@"\n')
            r = sov(["connect", "windsurf", "--vault", str(b.vault), "--host", "testbox", "--core", "me", "--apply"],
                    b.env(BRAIN_ROOT=str(b.vault)))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertEqual(b.runner_plist()["ProgramArguments"][0], str(b.clt_python))
            used = [l for l in b.log.read_text().splitlines() if l.startswith("clt-python3 ")]
            self.assertTrue(used, "bin/sov ran none of its own tools on the interpreter it gave the job")
