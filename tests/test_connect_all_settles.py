"""`sov connect all`, run twice.

A migration that never finishes is not a migration. The command is meant to be run again
and again - that is how a machine moves off a job per tool - so the second pass on an
unchanged machine has to select nothing. Two shapes broke that, and both are pinned here:

  * a cloud pull keeps a job of its own on a wall clock and never enters the connector
    manifest, so a manifest-membership test re-selects it forever, and every pass walks a
    live API that can block the run;
  * a machine that points at a hub must not install the hub's cloud pull at all - one
    account with two pullers writing one lane - and the guard that was supposed to stop
    that read a hub the command had deliberately not fetched, so it never fired.

Output order is checked too, because every one of these runs is piped: through `tee` on
the machine, or over ssh from another one. The plan has to arrive before the installers
it describes.

Same throwaway machine as the installer tests: fake HOME, a real-enough vault, stubbed
job control. Nothing loads a real job, nothing touches the network, nothing outside the
temp dir is written.
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_connectors_install import ROOT, Box

SOV = ROOT / "bin" / "sov"
# What `brain-mirror-notion --check` would say, so no test reaches Notion. Same seam the
# Notion harness test uses.
CHECK = ("bot: TestBot\nworkspace: Test WS\nitems: 1 (page 1)\nroots reachable:\n"
         "  %032x  Root A\nmissing roots: none\n" % 1)
CLOUD_PULL = "notion"                       # the harness with no detect paths: nothing local to find


def connect_all(b, extra_args=(), **envx):
    """Through `bin/sov`, the only way this repo tells anyone to run it."""
    return subprocess.run(["/bin/bash", str(SOV), "connect", "all",
                           "--vault", str(b.vault), "--host", "testbox", "--core", "me", "--apply"]
                          + list(extra_args),
                          capture_output=True, text=True, env=b.env(**envx), timeout=600)


def sections(out):
    """The tools a pass actually ran an installer for."""
    return [l[4:-4] for l in out.splitlines() if l.startswith("=== ") and l.endswith(" ===")]


def machine(tmp, hub=None):
    b = Box(tmp)
    (b.home / ".claude").mkdir()             # two tools to find, so a pass has real work
    (b.home / ".cursor").mkdir()
    if hub:
        (b.home / ".brain-hub").write_text(hub + ":/somewhere/vault\n")
    return b


class Settles(unittest.TestCase):
    def test_a_second_apply_pass_selects_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            env = {"NOTION_API_KEY": "ntn_test_token", "SOV_TEST_CHECK_OUTPUT": CHECK}
            first = connect_all(b, **env)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn(CLOUD_PULL, [s.lower() for s in sections(first.stdout)],
                          "the first pass never connected the cloud pull, so this proves nothing")
            second = connect_all(b, **env)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(sections(second.stdout), [],
                             "the second pass re-ran an installer with nothing left to do")
            self.assertIn("already connected", second.stdout)
            self.assertNotIn("re-running connect", second.stdout)

    def test_the_cloud_pull_that_keeps_its_own_job_is_named_not_silently_skipped(self):
        """It is connected here and it is not on the runner. A count that leaves it out is
        the wrong count, and this command exists to make that count honest."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            env = {"NOTION_API_KEY": "ntn_test_token", "SOV_TEST_CHECK_OUTPUT": CHECK}
            connect_all(b, **env)
            out = connect_all(b, **env).stdout
            self.assertIn("keeps its own job", out)
            self.assertIn("com.sovereign.connector.%s" % CLOUD_PULL, out)
            self.assertIn("com.sovereign.connector.%s.plist" % CLOUD_PULL, b.plists())


class HubCarriesTheCloudPull(unittest.TestCase):
    """~/.brain-hub names another machine: the pull belongs there, and this one leaves it
    alone rather than starting a second puller into the same lane."""

    def test_a_machine_that_points_at_a_hub_never_installs_the_cloud_pull(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp, hub="hubbox")
            # a token in the environment would be enough to install it, if anything tried
            r = connect_all(b, NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(CLOUD_PULL, [s.lower() for s in sections(r.stdout)])
            self.assertIn("runs on the hub (hubbox)", r.stdout)
            self.assertNotIn("com.sovereign.connector.%s.plist" % CLOUD_PULL, b.plists())
            self.assertFalse((b.home / ".notion-mirror").exists(),
                             "a machine that is not the hub wrote the cloud pull's instance state")
            second = connect_all(b, NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(sections(second.stdout), [])

    def test_the_hub_pointer_this_run_writes_counts_before_it_is_written(self):
        """First connect on a fresh client: --hub is on the command line and the pointer
        file does not exist yet. The cloud pull still belongs to the hub."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            r = connect_all(b, ["--hub", "hubbox:/somewhere/vault"],
                            NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertNotIn(CLOUD_PULL, [s.lower() for s in sections(r.stdout)])
            self.assertEqual((b.home / ".brain-hub").read_text().strip(), "hubbox:/somewhere/vault")

    def test_a_cloud_pull_already_installed_here_is_called_out_not_left_unsaid(self):
        """Skipping it quietly would leave two pullers writing one lane, and the pass that
        reported nothing would be the reason nobody noticed."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            env = {"NOTION_API_KEY": "ntn_test_token", "SOV_TEST_CHECK_OUTPUT": CHECK}
            connect_all(b, **env)                                    # installed here first
            (b.home / ".brain-hub").write_text("hubbox:/somewhere/vault\n")
            r = connect_all(b, **env)                                # ...then a hub appears
            self.assertEqual(sections(r.stdout), [])
            self.assertIn("also installed on this machine", r.stdout)
            self.assertIn("sov disconnect %s --apply" % CLOUD_PULL, r.stdout)

    def test_the_hub_itself_installs_it(self):
        """The same pointer, naming this machine, is not a reason to skip anything."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp, hub="testbox")
            r = connect_all(b, NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(CLOUD_PULL, [s.lower() for s in sections(r.stdout)])


class WithoutTheCredentialTheCloudPullNeeds(unittest.TestCase):
    """The machine most people run this on: no token for the cloud pull, and none coming.

    The pull declares a credential in its own harness.json. `connect all` can only hand an
    installer the environment it was started with, so on a machine without that credential
    the installer stops before it writes anything -- and stops the same way on every pass
    after it. Selected anyway, it made the command exit non-zero forever and never settle:
    the pull is never "connected", so every pass re-selects it, and the migration this
    command exists to perform can never report success. The rest of the machine connects
    perfectly the whole time.

    So it is named once, with the commands that end it, and left out of the selection.
    """

    def env(self):
        """No NOTION_API_KEY and no --secret: nothing here can connect that lane."""
        return {"SOV_TEST_CHECK_OUTPUT": CHECK}

    def test_the_pass_still_exits_zero_and_connects_the_rest_of_the_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            r = connect_all(b, **self.env())
            self.assertEqual(r.returncode, 0,
                             "a credential only the owner has failed the whole pass, and the "
                             "machine that runs this command is the one without it:\n"
                             + r.stdout + r.stderr)
            ran = [s.lower() for s in sections(r.stdout)]
            self.assertNotIn(CLOUD_PULL, ran,
                             "the pass ran an installer that cannot get past its own missing "
                             "credential, and will not on any later pass either")
            self.assertIn("claude code", ran,
                          "no local tool was connected either; this proves nothing")
            self.assertIn("claude-code", b.manifest()["harnesses"],
                          "the machine was left unmigrated by one lane it could never connect")

    def test_it_is_named_once_with_the_command_that_ends_it(self):
        """Skipping it quietly would leave a lane nobody mirrors and a run with nothing in
        it to say why."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            out = connect_all(b, **self.env()).stdout
            self.assertEqual(out.lower().count("needs a credential"), 1,
                             "the blocked pull is named more or less than once:\n" + out)
            self.assertIn("sov connect %s" % CLOUD_PULL, out,
                          "the run does not say how to connect it")
            self.assertIn("NOTION_API_KEY", out,
                          "the run does not name the credential this machine is missing")

    def test_a_second_pass_settles_on_exactly_the_same_answer(self):
        """Twice, unchanged: same exit code, no installer, same sentence. A pass that never
        settles is one nobody can tell has finished."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            first = connect_all(b, **self.env())
            second = connect_all(b, **self.env())
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertEqual(first.returncode, second.returncode)
            self.assertEqual(sections(second.stdout), [],
                             "the second pass re-ran an installer with nothing left to do:\n"
                             + second.stdout)
            self.assertIn("needs a credential", second.stdout,
                          "the second pass stopped saying why one lane is missing")
            self.assertNotIn("com.sovereign.connector.%s.plist" % CLOUD_PULL, b.plists(),
                             "a lane was scheduled without the credential its pull needs")

    def test_the_credential_in_the_environment_still_connects_it(self):
        """The other half: the guard is about what this machine carries, never about the
        harness. Given the token, the same pass installs it."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp)
            self.assertNotIn(CLOUD_PULL,
                             [s.lower() for s in sections(connect_all(b, **self.env()).stdout)])
            r = connect_all(b, NOTION_API_KEY="ntn_test_token", SOV_TEST_CHECK_OUTPUT=CHECK)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn(CLOUD_PULL, [s.lower() for s in sections(r.stdout)],
                          "the pull stayed blocked on a machine that now carries the token")
            self.assertIn("com.sovereign.connector.%s.plist" % CLOUD_PULL, b.plists())


class OutputOrder(unittest.TestCase):
    """stdout is a pipe here, exactly as it is under `tee` or over ssh."""

    def test_the_plan_prints_before_the_installers_it_describes(self):
        """This command's own prints and the installers' share one fd, and only one side
        of that is buffered. So the check is against an installer's first line, not
        against another print from here: those keep their order either way."""
        with tempfile.TemporaryDirectory() as tmp:
            b = machine(tmp, hub="hubbox")
            out = connect_all(b).stdout
            installer = out.index("Sovereign connector:")   # the first installer's own first line
            self.assertLess(out.index("connecting "), installer,
                            "the plan landed after the output it introduces: stdout is block "
                            "buffered while each installer writes straight to the same fd")
            self.assertLess(out.index("=== "), installer)
            self.assertLess(out.index("runs on the hub"), out.index("connecting "))


if __name__ == "__main__":
    unittest.main()
