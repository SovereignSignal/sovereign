import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from brain_redact import redact_file, redact_paths, redact_text  # noqa: E402

GH = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
SK = "sk-proj-" + "abcDEF123456abcDEF123456abcDEF123456"
TG = "123456789:AA" + "H3jK9lM2nO5pQ8rS1tU4vW7xY0zA3bC6d"


class Shapes(unittest.TestCase):
    def test_vendor_tokens_are_replaced_by_kind(self):
        text = "token %s and key %s and bot %s" % (GH, SK, TG)
        out, hits = redact_text(text)
        self.assertEqual(out, "token [redacted github token] and key [redacted api key] and bot [redacted telegram bot token]")
        self.assertEqual(hits, ["api key", "github token", "telegram bot token"])

    def test_private_key_block_goes_whole(self):
        text = ('before\n-' + '----BEGI' + 'N RSA PR' + 'IVATE KE' + 'Y-----\nM' + 'IIEow\nAA' + 'AA\n-----' + 'END RSA ' + 'PRIVATE ' + 'KEY-----' + '\nafter')
        out, hits = redact_text(text)
        self.assertEqual(out, "before\n[redacted private key]\nafter")
        self.assertEqual(hits, ["private key"])

    def test_connection_url_keeps_user_and_host(self):
        out, hits = redact_text(('DATABASE' + '_URL=pos' + 'tgres://' + 'app:Xy9$' + 'kLm2pQ@d' + 'b.intern' + 'al:5432/' + 'wire'))
        self.assertEqual(out, "DATABASE_URL=postgres://app:[redacted password]@db.internal:5432/wire")
        self.assertEqual(hits, ["password"])
        out, hits = redact_text("postgres://user:password@host/db and postgres://u:${PASS}@h/d")
        self.assertEqual(hits, [])

    def test_labeled_values_that_look_like_secrets(self):
        out, hits = redact_text(('Password' + ': P@ssw0' + 'rd!2024\n' + 'API key ' + '= qZ8xL2' + 'mN4vB7cD' + '1eF3gH\nc' + 'lient se' + 'cret: GO' + 'CSPX-abc' + 'defghijk' + 'lmnopqrs' + 'tuv'))
        self.assertIn("Password: [redacted value]", out)
        self.assertIn("API key = [redacted value]", out)
        self.assertIn("client secret: [redacted oauth secret]", out)
        self.assertEqual(sorted(hits), ["api key", "oauth secret", "password"])

    def test_prose_addresses_and_hashes_pass_through(self):
        keep = [
            "The token launched at 0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984 on mainnet.",
            "commit 8488dca2f0b1c3d4e5f6a7b8c9d0e1f2a3b4c5d6 fixed it",
            "password: hunter2",
            "secret: the sauce is paprika",
            "api key: <paste yours here>",
            "password = ${DB_PASSWORD}",
            "password: same-word",
            "See https://example.com/docs/api-key-rotation for the policy.",
            "cross-prime-risk-announcement-path",
            "The Book of Secret Knowledge, sk-ip this one",
        ]
        for line in keep:
            out, hits = redact_text(line)
            self.assertEqual(out, line, line)
            self.assertEqual(hits, [], line)

    def test_code_after_a_label_is_not_a_secret(self):
        keep = [
            "apiKey: process.env.CURSOR_API_KEY,",
            "const apiKey = ENV.forgeApiUrl;",
            "secret: ENV.cookieSecret,",
            "secretKey: this.sessionSecretKey,",
            "refresh_token=creds.refresh_token",
            "API key: ~/.config/notion/api-key",
            "password = getPassword(user)",
            "access_token: tokens[0].value",
            "const API_KEY = import.meta.env.VITE_GOOGLE_KEY;",
        ]
        for line in keep:
            out, hits = redact_text(line)
            self.assertEqual(out, line, line)

    def test_labeled_vendor_keys_without_a_known_shape_are_caught(self):
        out, hits = redact_text(('Tavily A' + 'PI Key: ' + 'tvly-dev' + '-Ab3dEf6' + 'gH9jKl2M' + 'nOp5qRs8' + 'tUv1wXy4' + 'zAb7cDe0' + 'fGh'))
        self.assertEqual(out, "Tavily API Key: [redacted value]")

    def test_sk_hynix_slugs_are_not_api_keys(self):
        for line in ("see sk-hynix-q2-memory-demand-outlook-2026-07-31 for the note",
                     "https://example.com/sk-hynix-hbm4-capacity-expansion-plan-analysis",
                     "sk-hynix-samsung-micron-hbm-pricing-comparison-2026"):
            out, hits = redact_text(line)
            self.assertEqual(out, line, line)
        out, _ = redact_text(('key sk-a' + 'nt-api03' + '-Ab3dEf6' + 'gH9jKl2M' + 'nOp5qRs8' + 'tUv1wXy4' + 'z-Ab7cDe' + '0fGh_ij'))
        self.assertEqual(out, "key [redacted api key]")

    def test_long_two_class_passphrase_after_a_label_is_caught(self):
        out, hits = redact_text(('password' + ': correc' + 't-horse-' + 'battery-' + 'staple-9'))
        self.assertEqual(out, "password: [redacted value]")

    def test_idempotent(self):
        once, _ = redact_text("key %s" % SK)
        twice, hits = redact_text(once)
        self.assertEqual(once, twice)
        self.assertEqual(hits, [])

    def test_csv_cells(self):
        out, hits = redact_text("Name,Token,Note\nGrok,%s,rotate me\nPlain,none,ok\n" % ("xai-" + "a" * 48))
        self.assertEqual(out, "Name,Token,Note\nGrok,[redacted xai key],rotate me\nPlain,none,ok\n")


class Files(unittest.TestCase):
    def test_redacts_in_place_only_when_needed_and_skips_binaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            lane = Path(tmp) / "lane"
            (lane / "sub").mkdir(parents=True)
            (lane / ".git").mkdir()
            secret = lane / "sub" / "creds.md"
            secret.write_text("gh token: %s\n" % GH)
            clean = lane / "note.md"
            clean.write_text("nothing here\n")
            before = clean.stat().st_mtime_ns
            binary = lane / "shot.png"
            binary.write_bytes(b"\x89PNG\x00\x00" + GH.encode())
            ingit = lane / ".git" / "config"
            ingit.write_text(GH)
            report = redact_paths([lane])
            self.assertEqual([(str(p.relative_to(lane)), h) for p, h in report], [("sub/creds.md", ["github token"])])
            self.assertEqual(secret.read_text(), "gh token: [redacted github token]\n")
            self.assertEqual(clean.stat().st_mtime_ns, before)
            self.assertIn(GH.encode(), binary.read_bytes())
            self.assertEqual(ingit.read_text(), GH)
            self.assertFalse(list(lane.rglob("*.part")))

    def test_non_utf8_bytes_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "latin.md"
            f.write_bytes(b"caf\xe9 " + SK.encode() + b"\n")
            self.assertEqual(redact_file(f), ["api key"])
            self.assertEqual(f.read_bytes(), b"caf\xe9 [redacted api key]\n")


class Cli(unittest.TestCase):
    def run_cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(ROOT / "bin" / "sov-redact"), *args], capture_output=True, text=True, cwd=cwd)

    def test_check_reports_and_exits_1_then_redact_exits_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.md"
            f.write_text("k %s\n" % SK)
            r = self.run_cli("--check", tmp)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("would be redacted (api key)", r.stdout)
            self.assertIn(SK, f.read_text())
            r = self.run_cli(tmp)
            self.assertEqual(r.returncode, 0)
            self.assertIn("redacted: 1 value(s) in 1 file(s)", r.stdout)
            self.assertNotIn(SK, f.read_text())
            r = self.run_cli("--check", tmp)
            self.assertEqual(r.returncode, 0)

    def test_list_file_relative_to_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "raw").mkdir()
            (Path(tmp) / "raw" / "x.md").write_text(GH)
            (Path(tmp) / "list.txt").write_text("raw/x.md\n")
            r = self.run_cli("--list", "list.txt", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((Path(tmp) / "raw" / "x.md").read_text(), "[redacted github token]")

    def test_no_args_is_usage(self):
        self.assertEqual(self.run_cli().returncode, 64)


if __name__ == "__main__":
    unittest.main()
