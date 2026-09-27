"""The Parallels harness: the host pulls each running guest through a fake prlctl.

prlctl exec re-splits its arguments and reads its own stdin, so the mirror drives every
guest command as a script on stdin and collects the guest list before it loops. The shim
here behaves the same way: `list` prints a fixture, `exec <vm> sh` runs the stdin script
against a fake guest root with /home rewritten, exactly as a Linux guest would answer.
"""
import os, stat, subprocess, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "connectors/harness/parallels/mirror.sh"

SHIM = r'''#!/bin/bash
# fake prlctl: fixtures under $FAKE_PRL
case "$1" in
  list) if [ "$2" = "-i" ]; then root="$FAKE_PRL/guests/${3// /_}"; printf 'OS: %s\n' "$(cat "$root/.os" 2>/dev/null || echo ubuntu)"; exit 0; fi
        [ -f "$FAKE_PRL/.list_failure" ] && { echo 'guest inventory unavailable' >&2; exit 1; }
        printf 'NAME                             STATUS\n'; cat "$FAKE_PRL/list.txt";;
  exec) vm="$2"; shift 2
        root="$FAKE_PRL/guests/${vm// /_}"
        [ -d "$root" ] || { echo "no such guest" >&2; exit 1; }
        # a Windows guest has no sh: answer nothing, like prlctl does for a foreign guest
        [ -f "$root/.windows" ] && exit 1
        # a guest marked flaky answers "Invalid argument" every time, like prlctl on a bad day
        [ -f "$root/.flaky" ] && { echo "PrlJob_GetResult: Invalid argument." >&2; exit 255; }
        script="$(cat)"
        if [[ "$script" == *'tar -cf'* ]]; then
          if [ -f "$root/.partial_once" ]; then
            rm "$root/.partial_once"; printf 'partial archive'; echo 'transient transfer failure' >&2; exit 255
          fi
          [ -f "$root/.bad_archive" ] && { printf 'invalid archive'; exit 0; }
        fi
        # a guest answer already carries $root; undo before rewriting so nothing doubles.
        # No escaped slashes: bash keeps a backslash literally in the replacement text.
        h=/home/; script="${script//$root$h/$h}"; script="${script//$h/$root$h}"
        exec sh -c "$script";;
  *) exit 2;;
esac
'''


def guest(root, vm, memory=None, outputs=None, windows=False):
    g = root / "guests" / vm.replace(" ", "_")
    (g / "home/parallels").mkdir(parents=True)
    if windows:
        (g / ".windows").write_text(""); (g / ".os").write_text("win-11")
    for project, files in (memory or {}).items():
        m = g / "home/parallels/.claude/projects" / project / "memory"
        m.mkdir(parents=True)
        for name, text in files.items():
            (m / name).write_text(text)
        (g / "home/parallels/.claude/projects" / project / "session.jsonl").write_text("{}")
    if memory:
        (g / "home/parallels/.claude/.credentials.json").write_text('{"token":"SECRET"}')
        (g / "home/parallels/.claude.json").write_text('{"oauth":"SECRET"}')
    for name, text in (outputs or {}).items():
        o = g / "home/parallels/Claude"; o.mkdir(parents=True, exist_ok=True)
        (o / name).write_text(text)


class ParallelsMirror(unittest.TestCase):
    def run_mirror(self, fake, stage, home):
        shim = fake / "prlctl"; shim.write_text(SHIM); shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ, HOME=str(home), PRLCTL=str(shim), FAKE_PRL=str(fake),
                   BRAIN_STAGE=str(stage), BRAIN_HOST="testbox", BRAIN_ROOT=str(home / "vault"))
        cp = subprocess.run(["/bin/bash", str(MIRROR)], env=env, capture_output=True, text=True, timeout=60)
        lane = stage / "raw/tools/parallels-testbox"
        return cp, lane

    def test_running_guests_are_pulled_and_others_named_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("Alpha Ubuntu VM                  running\nBeta Box                         suspended\nWindows 11                       running\n")
            guest(fake, "Alpha Ubuntu VM", memory={"-home-parallels": {"MEMORY.md": "- [x](x.md)\n", "x.md": "fact\n"}},
                  outputs={"report.md": "deliverable\n"})
            guest(fake, "Beta Box", memory={"-home-parallels": {"MEMORY.md": "never read\n"}})
            guest(fake, "Windows 11", windows=True)
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual((lane / "alpha-ubuntu-vm/claude-code/memory/-home-parallels/x.md").read_text(), "fact\n")
            self.assertEqual((lane / "alpha-ubuntu-vm/claude/report.md").read_text(), "deliverable\n")
            self.assertFalse((lane / "beta-box").exists(), "a suspended guest is skipped, never invented")
            self.assertFalse((lane / "windows-11").exists(), "a guest that cannot answer is skipped")
            manifest = (lane / "MANIFEST.md").read_text()
            self.assertIn("`alpha-ubuntu-vm` (Alpha Ubuntu VM): running, 1 project memory folder(s) mirrored", manifest)
            self.assertIn("`beta-box` (Beta Box): suspended, skipped", manifest)
            self.assertIn("`windows-11` (Windows 11): running, win-11, not a Linux guest, skipped", manifest)
            self.assertIn("Items mirrored: 1. Failed: 0.", manifest)

    def test_credentials_and_transcripts_never_cross(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("Alpha Ubuntu VM                  running\n")
            guest(fake, "Alpha Ubuntu VM", memory={"-home-parallels": {"MEMORY.md": "index\n"}})
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            names = {p.name for p in lane.rglob("*") if p.is_file()}
            self.assertIn("MEMORY.md", names)
            self.assertNotIn(".credentials.json", names); self.assertNotIn(".claude.json", names)
            self.assertFalse(any(n.endswith(".jsonl") for n in names))
            self.assertNotIn("SECRET", "".join(p.read_text() for p in lane.rglob("*") if p.is_file()))

    def test_partial_archive_retry_publishes_only_the_successful_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("Alpha VM                         running\n")
            guest(fake, "Alpha VM", memory={"project": {"MEMORY.md": "complete capture\n"}})
            (fake / "guests/Alpha_VM/.partial_once").touch()
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual((lane / "alpha-vm/claude-code/memory/project/MEMORY.md").read_text(), "complete capture\n")
            self.assertNotIn("transient transfer failure", cp.stderr)

    def test_failed_inventory_retains_the_previous_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / ".list_failure").touch()
            old = tmp / "stage/raw/tools/parallels-testbox/MANIFEST.md"
            old.parent.mkdir(parents=True); old.write_text("previous successful capture\n")
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("guest inventory unavailable", cp.stderr)
            self.assertEqual(old.read_text(), "previous successful capture\n")

    def test_invalid_archive_reports_extraction_error_and_retains_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("Alpha VM                         running\n")
            guest(fake, "Alpha VM", memory={"project": {"MEMORY.md": "new\n"}})
            (fake / "guests/Alpha_VM/.bad_archive").touch()
            old = tmp / "stage/raw/tools/parallels-testbox/MANIFEST.md"
            old.parent.mkdir(parents=True); old.write_text("previous capture\n")
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertNotEqual(cp.returncode, 0)
            self.assertIn("tar:", cp.stderr)
            self.assertEqual(old.read_text(), "previous capture\n")

    def test_no_prlctl_means_nothing_to_do_not_a_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            env = dict(os.environ, HOME=str(home), PRLCTL=str(tmp / "absent"), BRAIN_STAGE=str(tmp / "stage"),
                       BRAIN_HOST="testbox", BRAIN_ROOT=str(home / "vault"))
            cp = subprocess.run(["/bin/bash", str(MIRROR)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertFalse((tmp / "stage").exists())

    def test_the_second_guest_is_still_pulled_after_the_first(self):
        # prlctl reads stdin: a loop streaming the guest list into commands that also run
        # prlctl loses every guest after the first. That is the bug the first draft had.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("One VM                           running\nTwo VM                           running\n")
            for vm in ("One VM", "Two VM"):
                guest(fake, vm, memory={"-home-parallels": {"MEMORY.md": vm + "\n"}})
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertEqual(cp.returncode, 0, cp.stderr)
            self.assertEqual((lane / "two-vm/claude-code/memory/-home-parallels/MEMORY.md").read_text(), "Two VM\n")
            self.assertIn("Items mirrored: 2.", (lane / "MANIFEST.md").read_text())

    def test_an_exec_that_keeps_failing_marks_the_guest_failed_not_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); fake = tmp / "fake"; fake.mkdir(); home = tmp / "home"; (home / "vault/raw/tools").mkdir(parents=True)
            (fake / "list.txt").write_text("Flaky VM                         running\nGood VM                          running\n")
            guest(fake, "Flaky VM", memory={"-home-parallels": {"MEMORY.md": "unreachable\n"}})
            (fake / "guests/Flaky_VM/.flaky").write_text("")
            guest(fake, "Good VM", memory={"-home-parallels": {"MEMORY.md": "fine\n"}})
            cp, lane = self.run_mirror(fake, tmp / "stage", home)
            self.assertNotEqual(cp.returncode, 0, "a guest that cannot be read is a failed run, not a quiet zero")
            self.assertIn("prlctl exec failed", cp.stderr)
            self.assertIn("PrlJob_GetResult: Invalid argument.", cp.stderr)
            self.assertFalse(lane.exists(), "a failed run publishes nothing; the prior capture is what stands")


if __name__ == "__main__":
    unittest.main()
