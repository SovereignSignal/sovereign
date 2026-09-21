"""The template ships to other people, so nothing in it may name the machine it was
written on.

Four rounds of review found the author's own machine name and archive name sitting in
seven harness usage comments: `sov connect <tool> --host <their machine> --vault
"<their archive>" --apply`. A guard that greps for those two literal strings would keep
exactly that pair out and let the next one in -- and it would have to carry them, so the
guard itself would ship the leak it exists to stop.

So it is built the other way round. It asks THIS machine who it is -- its home
directory, its login name, `~/.brain-host`, `~/.brain-root` -- and then refuses to find
any of that in a shipped file. Whoever edits the template next is checked against their
own machine, not against the author's, and the guard names nobody.

Two rules sit beside it, and neither needs a machine to check:

  * no shipped file carries an absolute home path (`/Users/<somebody>/`), placeholders
    excepted: the template writes `~` or `$HOME` and resolves it at run time;
  * every harness usage example passes a placeholder to --host and --vault, which is the
    exact line the leak was found on.

"Shipped" is what git carries -- tracked files plus new ones that are not ignored -- with
the scratch dot-directories (`.git`, the pytest cache, agent notes) left out.
"""
import os
import re
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A probe built from one of these would search for an ordinary English word, or for one of
# the template's own. A machine whose owner called it "archive" cannot be looked for -- and
# does not need to be, because that name gives nothing away. Everything else is fair game.
GENERIC = {
    "", "admin", "box", "archive", "default", "desktop", "example", "home", "host", "hub",
    "laptop", "local", "localhost", "machine", "main", "me", "my archive", "name", "notes",
    "obsidian", "owner", "raw", "relay", "root", "runner", "sample", "sov", "sovereign",
    "test", "tests", "tools", "user", "username", "users", "vault", "you", "your",
}

# What may stand in for a person's own login in a written-out path. Anything else in that
# position is somebody's real home directory.
PLACEHOLDER_USER = {
    "you", "your", "user", "username", "name", "me", "someone", "somebody", "owner",
}

# What an example command may pass to --host or --vault.
PLACEHOLDER_ARG = re.compile(r"^<[^<>]+>$")

# An absolute home directory, whoever it belongs to.
HOME_PATH = re.compile(r"(?:/Users|/home)/([A-Za-z0-9._${}<>-]+)")


def shipped():
    """Every file the template hands to somebody else."""
    names = []
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--cached", "--others",
                            "--exclude-standard"], capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            names = r.stdout.splitlines()
    except OSError:
        names = []
    if not names:                                # not a checkout: walk it instead
        names = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*") if p.is_file()]
    out = []
    for n in names:
        n = n.strip()
        # a leading dot is scratch: .git, the pytest cache, worktrees, agent notes
        if not n or n.startswith("."):
            continue
        p = ROOT / n
        if p.is_file():
            out.append(p)
    return sorted(set(out))


def lines_of(path):
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []                                # a binary asset carries no usage comment
    return list(enumerate(text.splitlines(), 1))


def pointer(name):
    try:
        return (Path.home() / name).read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def probeable(value):
    v = (value or "").strip()
    return len(v) >= 2 and v.lower() not in GENERIC


def usage_header(path):
    """The comment block at the top of an installer: its usage line lives there."""
    head = []
    for _, line in lines_of(path):
        if line.startswith("#"):
            head.append(line)
        elif head:
            break
    return head


class NothingNamesThisMachine(unittest.TestCase):
    """The leak, checked against whoever is holding the template."""

    def hits(self, pattern):
        rx = re.compile(pattern, re.IGNORECASE)
        found = []
        for p in shipped():
            for n, line in lines_of(p):
                if rx.search(line):
                    found.append("%s:%d: %s" % (p.relative_to(ROOT), n, line.strip()[:120]))
        return found

    def word(self, value):
        return r"(?<![A-Za-z0-9_-])%s(?![A-Za-z0-9_-])" % re.escape(value)

    def test_no_shipped_file_names_the_home_directory_it_was_written_in(self):
        home = str(Path.home())
        self.assertTrue(home.startswith("/"), "no home directory to check against")
        self.assertEqual(self.hits(self.word(home)), [],
                         "a shipped file carries this machine's home directory (%s). The "
                         "template resolves ~ and $HOME at run time; an absolute one is "
                         "somebody's own disk." % home)

    def test_no_shipped_file_names_this_machine(self):
        probes = [v for v in (pointer(".brain-host"), os.environ.get("USER", ""),
                              Path.home().name, socket.gethostname(),
                              socket.gethostname().split(".")[0]) if probeable(v)]
        if not probes:
            self.skipTest("this machine has no name that is not a generic word")
        for probe in sorted(set(probes)):
            with self.subTest(machine=probe):
                self.assertEqual(self.hits(self.word(probe)), [],
                                 "a shipped file names this machine (%r). The template is "
                                 "copied onto other people's machines, where that name is "
                                 "wrong." % probe)

    def test_no_shipped_file_names_the_hub_this_machine_points_at(self):
        """A client cannot catch a hub's name by asking who IT is.

        Every probe above is built from this machine, so a client passes while
        carrying the hub's hostname in plain sight and only the hub itself fails.
        That happened on 2026-09-21: two vendored scripts described the wire as
        "fenced and merged by <hub>", the laptop's run was green, and the guard
        only went red once the commit reached the hub - after it was published.

        The hub is the machine the kit publishes from, so its name is the one that
        must not ship. Read it from the pointer `sov status` uses, take the alias
        before the colon, and skip in silence when this machine points at no hub:
        a standalone instance has no hub name to leak, and a guard that fails for
        every unwired machine is a guard nobody reads.
        """
        hub = pointer(".brain-hub").split(":", 1)[0].strip()
        if not probeable(hub):
            self.skipTest("this machine points at no hub, or its name is a generic word")
        found = self.hits(self.word(hub))
        self.assertEqual(found, [],
                         "a shipped file names the hub this machine points at "
                         "(hub name %r matched). The hub is where the kit publishes "
                         "from, so its name must not ship. If this is a coincidence - "
                         "a variable or an ordinary word that happens to match - rename "
                         "it rather than leaving the guard red, because a check that "
                         "always fails is one nobody reads." % hub)

    def test_no_shipped_file_names_this_machines_brain(self):
        root = pointer(".brain-root")
        if not root:
            self.skipTest("this machine points at no archive (~/.brain-root)")
        probes = [os.path.expanduser(root)]
        if probeable(Path(root).name):
            probes.append(Path(root).name)
        for probe in probes:
            with self.subTest(archive=probe):
                self.assertEqual(self.hits(re.escape(probe)), [],
                                 "a shipped file names this machine's archive (%r). A vault "
                                 "name is the owner's, never the template's." % probe)


class NoAbsoluteHomePaths(unittest.TestCase):
    """The same rule with nobody's machine in it, so it holds on a fresh checkout too."""

    def test_a_written_out_home_path_names_a_placeholder_or_nobody(self):
        found = []
        for p in shipped():
            for n, line in lines_of(p):
                for who in HOME_PATH.findall(line):
                    # `<you>`, `$USER` and `${USER}` all stand for the reader
                    if who.strip("<>${}").lower() not in PLACEHOLDER_USER:
                        found.append("%s:%d: %s" % (p.relative_to(ROOT), n, line.strip()[:120]))
        self.assertEqual(found, [],
                         "a shipped file writes out somebody's home directory. Use ~ or "
                         "$HOME, or a placeholder login (%s)."
                         % ", ".join(sorted(PLACEHOLDER_USER)))


class SelfCheckFixturesAreNobodysSubjectMatter(unittest.TestCase):
    """A worked example is instance data too.

    The judge-brief module carries its own self-check, and its fixture slugs were the
    author's real card names. Shipped, they read as the shape an archive is supposed to have
    -- and a reader can tell from them what the machine that wrote the template works on,
    which is the leak this file exists to stop, one layer in.

    It is checked the same way round as everything else here: against the cards on THIS
    machine, so whoever edits it next is measured against their own archive and the guard
    names nobody. The self-check is run too, because a fixture nobody exercises drifts.
    """

    MODULE = ROOT / "bin" / "_curator_brief.py"
    KEBAB = re.compile(r'"([a-z][a-z0-9]*(?:-[a-z0-9]+){1,5})"')

    def test_the_self_check_still_passes(self):
        self.assertTrue(self.MODULE.exists(), "the module this guard checks is gone")
        r = subprocess.run([sys.executable, str(self.MODULE)], capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0,
                         "the self-check no longer passes, so its fixtures exercise nothing:\n"
                         + r.stdout + r.stderr)
        self.assertIn("ok", r.stdout)

    def test_no_fixture_slug_is_a_card_in_this_machines_brain(self):
        root = pointer(".brain-root")
        if not root:
            self.skipTest("this machine points at no archive (~/.brain-root)")
        cards = {p.stem for p in Path(os.path.expanduser(root)).glob("knowledge/**/*.md")}
        if not cards:
            self.skipTest("this machine's archive has no cards to check against")
        hits = sorted(set(self.KEBAB.findall(self.MODULE.read_text(encoding="utf-8"))) & cards)
        self.assertEqual(hits, [],
                         "%s uses this machine's own cards as worked examples (%s). A fixture "
                         "reads as the shape an archive should have, and it tells every reader "
                         "what this machine works on: use a subject nobody's archive holds."
                         % (self.MODULE.relative_to(ROOT), ", ".join(hits)))


class UsageExamplesArePlaceholders(unittest.TestCase):
    """The line the leak was found on, in all seven of them: a harness usage comment.

    An example that passes a real host or a real vault is the whole defect -- it reads as
    an instruction, and the reader who copies it is connecting a machine that is not
    theirs to an archive that is not theirs.
    """

    def installers(self):
        found = sorted((ROOT / "connectors" / "harness").glob("*/install.sh"))
        self.assertTrue(found, "no harness installer found; this guard is blind")
        return found

    def test_every_harness_usage_example_passes_a_placeholder_host_and_vault(self):
        checked = 0
        for install in self.installers():
            head = "\n".join(usage_header(install))
            self.assertIn("sov connect", head,
                          "%s: no usage line in its header comment, so nothing is checked here"
                          % install.relative_to(ROOT))
            for flag, value in re.findall(r"--(host|vault)[= ]+(\S+)", head):
                checked += 1
                self.assertRegex(
                    value, PLACEHOLDER_ARG,
                    "%s: the usage example passes --%s %s. Every reader of this file is on "
                    "a different machine with a differently named archive; the example has to "
                    "be a placeholder." % (install.relative_to(ROOT), flag, value))
        self.assertGreaterEqual(checked, 2 * len(self.installers()),
                                "the usage lines were not read: each installer names both "
                                "--host and --vault")


if __name__ == "__main__":
    unittest.main()
