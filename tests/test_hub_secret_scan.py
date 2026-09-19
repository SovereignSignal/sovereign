"""The commit gate distinguishes document slugs from credentials without leaking hits."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SecretScan(unittest.TestCase):
    def scan(self, content, name="note.md"):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / name).write_text(content)
            listing = root / "files"
            listing.write_text(name + "\nmissing.md\n")
            return subprocess.run([str(ROOT / "bin/hub/secret-scan"), str(listing)],
                                  cwd=root, text=True, capture_output=True)

    def test_document_title_ending_in_sk_is_not_a_key(self):
        result = self.scan("https://app.notion.com/MetaMask-" + "a1b2" * 8)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_real_keys_remain_blocked_in_prose_and_urls(self):
        for prefix in ("", "key=", '"', "https://example.com/?key=", "Bearer ", "("):
            for vendor in ("sk-", "sk-proj-", "sk-ant-", "sk-svcacct-", "sk-or-"):
                key = vendor + "Test7Value" * 4
                with self.subTest(prefix=prefix, vendor=vendor):
                    result = self.scan(prefix + key)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("[redacted]", result.stdout)
                    self.assertNotIn(key, result.stdout + result.stderr)

    def test_document_url_does_not_hide_another_key_on_the_same_line(self):
        key = "ghp_" + "Test7Value" * 4
        result = self.scan("https://app.notion.com/MetaMask-" + "a1b2" * 8 + " " + key)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(key, result.stdout + result.stderr)

    def test_filename_gate_still_blocks_credential_files(self):
        self.assertEqual(self.scan("ordinary text", ".env").returncode, 1)

    def test_unreadable_content_cannot_pass_the_commit_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); document=root/'note.md'; listing=root/'files'
            key='sk-'+'Test7Value'*4
            document.write_text(key); listing.write_text('note.md\n'); document.chmod(0)
            try:
                result=subprocess.run([str(ROOT/'bin/hub/secret-scan'),str(listing)],cwd=root,text=True,capture_output=True)
                self.assertNotEqual(result.returncode,0)
                self.assertNotIn(key,result.stdout+result.stderr)
            finally:
                document.chmod(0o600)

    def test_scanner_read_error_cannot_be_reported_as_zero_hits(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'note.md').write_text('ordinary text')
            listing=root/'files';listing.write_text('note.md\n')
            fake=root/'bin';fake.mkdir();grep=fake/'grep'
            grep.write_text('#!/bin/bash\nif [ "$1" = "-aoEn" ]; then exit 2; fi\nexec /usr/bin/grep "$@"\n')
            grep.chmod(0o755)
            result=subprocess.run([str(ROOT/'bin/hub/secret-scan'),str(listing)],cwd=root,text=True,capture_output=True,
                                  env=dict(os.environ,PATH=str(fake)+os.pathsep+os.environ.get('PATH','')))
            self.assertNotEqual(result.returncode,0)
            self.assertIn('cannot scan',result.stderr)


if __name__ == "__main__":
    unittest.main()
