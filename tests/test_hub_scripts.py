"""The hub scripts ship in the template with their settings read from sov hub env, and
none of them names an owner. The runner and jobs table point at these files."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import manifest  # noqa: E402


def hub_scripts():
    return [p for p in sorted((ROOT / "bin" / "hub").iterdir()) if p.is_file()]


class Scripts(unittest.TestCase):
    def test_every_manifest_program_exists_and_is_executable(self):
        for job_id, spec in manifest.JOBS.items():
            p = ROOT / "bin" / spec["program"]
            self.assertTrue(p.is_file(), job_id); self.assertTrue(p.stat().st_mode & 0o111, job_id)

    def test_hub_scripts_read_their_settings_from_the_environment_not_from_exports(self):
        for p in hub_scripts():
            text = p.read_text()
            self.assertNotRegex(text, r'(?m)^\s*export (SOVS_VAULT|CURATOR_MODEL|CURATOR_AUDIT_MODEL|CURATOR_ENDPOINT|CURATOR_LANE|CURATOR_EXCLUDE)=', p.name)
            self.assertNotRegex(text, r'Obsidian/|/Users/|private-host.example.invalid|qwen|sovsarchive|sovs-cron', p.name)

    def test_shell_scripts_parse_and_python_scripts_compile(self):
        for p in hub_scripts():
            head = p.read_text().splitlines()[0] if p.read_text() else ""
            if "python" in head:
                # compile in memory: py_compile writes bin/hub/__pycache__, which the next run trips on
                r = subprocess.run(["/usr/bin/python3", "-c", "import sys; compile(open(sys.argv[1]).read(), sys.argv[1], 'exec')", str(p)],
                                   capture_output=True, text=True)
            else:
                r = subprocess.run(["/bin/bash", "-n", str(p)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, p.name + ": " + r.stderr)


if __name__ == "__main__":
    unittest.main()
