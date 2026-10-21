import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from brain_redact import SHAPES, redact_file, redact_paths, redact_text  # noqa: E402
from sovereign_intake.selection import DETECTOR, detector_hits, secret_hits  # noqa: E402

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


# Key shapes for the glued cases, assembled so no fixture reads as a real credential. A glued
# token must look random (mixed classes and a digit), so the bodies mix them.
MIX = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6"
GH36 = "gh" + "p_" + MIX[:36]
SLACK = "xo" + "xb-" + "1234567890" + "-" + "1234567890123" + "-" + MIX[:24]
AWS = "AK" + "IA" + "B" * 16
HEX36 = "3f9a8b7c6d5e" * 3

PEM = ("-----BEGIN " + "PRIVATE KEY-----\n" + "MIIEv" + MIX[:40] + "\n" + MIX[:40]
       + "\n-----END " + "PRIVATE KEY-----")

# One fixture per redactor shape kind, with whether it may be glued onto a word (the shapes
# that keep a leading \b may not). redact_text must redact it and the strict detector must
# see it in every context, and neither may find anything left in what redact_text wrote.
TOKEN_CORPUS = [
    (PEM, True), (GH36, True), (SLACK, True), (AWS, True), (TG, True), (SK, True),
    ("github" + "_pat_" + MIX[:40], True),
    ("gl" + "pat-" + MIX[:20], True),
    ("nt" + "n_" + MIX[:40], True),
    ("AI" + "za" + MIX[:35], True),
    ("GOC" + "SPX-" + MIX[:28], True),
    ("xa" + "i-" + MIX[:48], True),
    ("pp" + "lx-" + MIX[:48], True),
    ("h" + "f_" + MIX[:34], True),
    ("ey" + "J" + MIX[:20] + ".ey" + "J" + MIX[:20] + "." + MIX[:16], True),
    ("sk" + "_live_" + MIX[:24], False),
    ("SG" + "." + MIX[:22] + "." + MIX[:43], False),
    ("f" + "c-" + "0123456789abcdef" * 2, False),
]

class GluedTokens(unittest.TestCase):
    """A token is recognised by its own shape, not by a word boundary in front of it."""

    def test_github_token_glued_onto_a_word(self):
        for text in ("word" + GH36, "x" * 1480 + GH36, "key_" + GH36, "1234" + GH36):
            out, hits = redact_text(text)
            self.assertNotIn("gh" + "p_", out, text[-60:])
            self.assertEqual(hits, ["github token"])
        self.assertEqual(redact_text("word" + GH36)[0], "word[redacted github token]")

    def test_slack_token_glued_onto_a_word(self):
        out, hits = redact_text("word" + SLACK + " tail")
        self.assertEqual(out, "word[redacted slack token] tail")
        self.assertEqual(hits, ["slack token"])

    def test_aws_key_id_glued_onto_a_word(self):
        for glue in ("word", "id_", "key-"):
            out, hits = redact_text(glue + AWS + "\n")
            self.assertEqual(out, glue + "[redacted aws key]\n")
        out, hits = redact_text("word" + AWS + "trailing")
        self.assertEqual(out, "word[redacted aws key]trailing")

    def test_token_at_end_of_line(self):
        out, hits = redact_text("first line\nthe key is word" + GH36)
        self.assertEqual(out, "first line\nthe key is word[redacted github token]")
        out, hits = redact_text("| row | value" + SLACK + "\n| next | ok |")
        self.assertEqual(out, "| row | value[redacted slack token]\n| next | ok |")

    def test_token_inside_a_url(self):
        out, hits = redact_text("https://api.example.com/v1/items?access=" + GH36 + "&page=2")
        self.assertEqual(out, "https://api.example.com/v1/items?access=[redacted github token]&page=2")
        out, hits = redact_text("https://api.telegram.org/bot" + TG + "/sendMessage")
        self.assertEqual(out, "https://api.telegram.org/bot[redacted telegram bot token]/sendMessage")

    def test_unglued_single_class_fixtures_still_redact(self):
        for text in ("key " + "gh" + "p_" + "B" * 36, "Grok," + "xai-" + "a" * 48):
            out, hits = redact_text(text)
            self.assertEqual(len(hits), 1, text)

    def test_underscore_joined_labels_count(self):
        out, hits = redact_text("DB_PASS" + "WORD=" + "Xy9kLm2pQ7rT4vW8")
        self.assertEqual(out, "DB_PASSWORD=[redacted value]")
        out, hits = redact_text("OPENAI_API" + "_KEY=" + "qZ8xL2mN4vB7cD1eF3gH")
        self.assertEqual(out, "OPENAI_API_KEY=[redacted value]")
        out, hits = redact_text('print("api' + '_key=' + 'Zx9QwErTy7UiOp3AsDfGh2JkL\\n")')
        self.assertEqual(out, 'print("api_key=[redacted value]\\n")')
        for keep in ("API_KEY_ID=" + "Ab3dEf6gH9jKl2Mn", "mypassword: " + "Xy9kLm2pQ7rT4vW8",
                     'write_text("NOTION_API' + '_KEY=k\\nBRAIN_ROOT=%s\\n" % root)',
                     "API_KEY=k\\nROOT=" + "Ab3dEf6gH9jKl2Mn"):
            self.assertEqual(redact_text(keep), (keep, []), keep)

    def test_a_password_holding_backslash_n_stays_whole(self):
        out, hits = redact_text("pass" + "word=" + "Gx7\\nQ2pL9vR4tW")
        self.assertEqual(out, "password=[redacted value]")
        out, hits = redact_text("passphrase: " + "Rt5\\tKw8mZ2qPx")
        self.assertEqual(out, "passphrase: [redacted value]")

    def test_database_url_with_a_driver_suffix(self):
        out, hits = redact_text("postgresql+psycopg2://app:" + "Xy9kLm2pQ" + "@db.internal/wire")
        self.assertEqual(out, "postgresql+psycopg2://app:[redacted password]@db.internal/wire")
        self.assertEqual(detector_hits("postgresql+psycopg2://user:" + "pw" + "@host"), ["database url with password"])

    def test_ordinary_text_still_passes(self):
        keep = [
            "The crowd laughs at the joke and laughs_loudly_at_the_end.",
            "That was sk-ill, not a key, and the desk-ill-advised plan stays.",
            "sought_after_feature_flag_for_the_new_release",
            "task-" + HEX36 + " and risk-" + HEX36,
            "id " + HEX36 + " and " + HEX36.upper(),
            "| name | id | note |\n|---|---|---|\n| laughs | " + HEX36 + " | sk-ill |",
            "SOUTHEAST ASIA PACIFIC REGION 2026",
            "MSG.connectionTimeoutHandler.retryWithBackoff",
            "benchmark_test_HashFunctionPerformanceSuite",
        ]
        for line in keep:
            self.assertEqual(redact_text(line), (line, []), line)
            self.assertEqual(secret_hits(line), [], line)

    def test_identifiers_ending_in_a_prefix_are_kept_in_prose_but_still_detected(self):
        """The redactor leaves a glued identifier alone; the detector, the fail-closed gate,
        still sees the shape, so the line is dropped where secret_hits gates it."""
        lenient = [
            "laughs_LoudlyAtTheEndOfTheJokeEveryTime",
            "EURASIAFUNDINGROUND2026",
            "PAIzaSyntheticComponentRendererFactoryXy",
            "top_secret_ProjectCodenameRegistryEntriesForTheWholeTeam",
            "slackxoxb-IntegrationSettings-ChannelNotificationPreferences",
            "task-proj-roadmap-q3-planning-notes-for-the-team",
            "desk-ant-colony-field-notes-and-observations",
        ]
        for line in lenient:
            self.assertEqual(redact_text(line), (line, []), line)
            self.assertTrue(detector_hits(line), line)
            self.assertTrue(secret_hits(line), line)
        for line in ("task-proj-roadmap-q3", "desk-ant-colony-notes"):
            self.assertEqual(redact_text(line), (line, []), line)
            self.assertEqual(secret_hits(line), [], line)
        # a digit makes a glued body look random, so this one is a token to both sides
        self.assertEqual(redact_text("laughs_LoudlyAtTheEndOfTheJokeEveryTime2")[1], ["github token"])

    def test_a_value_that_runs_on_into_code_is_judged_before_the_escape(self):
        out, hits = redact_text("api" + "_key=" + "Zx9QwErTy7UiOp3AsDfGh2JkL" + "\\nprint(x)")
        self.assertEqual(out, "api_key=[redacted value]\\nprint(x)")
        out, hits = redact_text('echo -e "sec' + 'ret=' + 'Zx9QwErTy7UiOp3AsDfGh2JkL' + '\\n./run.sh"')
        self.assertEqual(out, 'echo -e "secret=[redacted value]\\n./run.sh"')

    def test_database_url_password_with_a_slash(self):
        out, hits = redact_text("postgres://app:" + "Xy9/kLm2pQ" + "@db.internal/wire")
        self.assertEqual(out, "postgres://app:[redacted password]@db.internal/wire")
        self.assertEqual(detector_hits("postgres://u:" + "p/wd" + "@h"), ["database url with password"])

    def test_long_slash_free_url_password_is_redacted(self):
        out, hits = redact_text("postgres://app:" + "Q7x" * 334 + "@db.internal/wire")
        self.assertEqual(out, "postgres://app:[redacted password]@db.internal/wire")
        self.assertIn("database url with password", detector_hits("postgres://app:" + "Q7x" * 334 + "@db/x"))

    def test_a_port_and_a_path_with_an_at_sign_are_not_a_password(self):
        for url in ("postgres://db.internal:5432/app?notify=ops@example.com",
                    "redis://cache:6379/0#owner@team",
                    "mysql://db:3306/shop?contact=dba@example.org"):
            self.assertEqual(redact_text(url), (url, []), url)
            self.assertEqual(secret_hits(url), [], url)

    def test_a_jwt_after_an_earlier_eyj_fragment_in_the_same_run(self):
        jwt = "ey" + "J" + MIX[:20] + ".ey" + "J" + MIX[:24] + "." + MIX[:20]
        out, hits = redact_text("eyJfoo." + jwt)
        self.assertEqual(out, "eyJfoo.[redacted jwt]")
        out, hits = redact_text("eyJfoo.eyJbar." + jwt + " tail")
        self.assertEqual(out, "eyJfoo.eyJbar.[redacted jwt] tail")
        out, hits = redact_text("eyJfoo" + jwt)
        self.assertEqual(hits, ["jwt"])
        self.assertNotIn(MIX[:24], out)
        self.assertEqual(detector_hits("eyJfoo." + jwt), ["jwt"])
        for keep in ("eyJaa.eyJbb.cc", "eyJfoo.eyJbar.baz.eyJqux", "eyJ" + "a" * 40 + ".short"):
            self.assertEqual(redact_text(keep), (keep, []), keep)
            self.assertEqual(detector_hits(keep), [], keep)

    def test_a_long_jwt_payload_still_matches(self):
        jwt = "ey" + "J" + MIX[:30] + ".ey" + "J" + (MIX * 200)[:10000] + "." + MIX[:43]
        out, hits = redact_text("Authorization: Bearer " + jwt)
        self.assertEqual(out, "Authorization: Bearer [redacted jwt]")
        self.assertIn("jwt", detector_hits(jwt))
        self.assertEqual(redact_text("see eyJ" + "a" * 20 + " in the docs")[1], [])


class Linear(unittest.TestCase):
    """A long run of a prefix must not make a pattern scan the rest of the text per start."""

    def test_long_prefix_runs_finish_quickly(self):
        runs = ["eyJ" * 50000, "eyJaaaaaaaaaaaa.eyJ" + "eyJ" * 50000, "eyJ." * 37500,
                "-----BEGIN RSA PRIVATE KEY-----" * 4800, "postgres://u:" * 11500,
                "postgres://u:" + "a/" * 75000, "postgres://u:" + "1/" * 75000,
                "postgres://u:" + "a" * 150000, "eyJfoo." * 21000]
        for text in runs:
            for fn in (redact_text, detector_hits):
                started = time.perf_counter()
                fn(text)
                self.assertLess(time.perf_counter() - started, 0.5, (fn.__name__, text[:20]))


class DetectorAgreesWithRedactor(unittest.TestCase):
    """The detector (drop a line, fail closed) and redact_text (rewrite a value) know the same
    shapes; they differ only in the redactor's leniency for glued identifiers."""

    def test_the_detector_runs_every_redactor_shape(self):
        detector = {(rx.pattern, check) for rx, _name, check in DETECTOR}
        for kind, rx, check, _glued in SHAPES:
            self.assertIn((rx.pattern, check), detector, kind)

    def test_the_corpus_covers_every_redactor_shape(self):
        kinds = set()
        for token, _glued in TOKEN_CORPUS:
            kinds.update(redact_text(token)[1])
        self.assertEqual(kinds, {kind for kind, _rx, _check, _glued in SHAPES})

    def test_corpus(self):
        for token, glued in TOKEN_CORPUS:
            contexts = [token, "x " + token + " tail", "?q=" + token + "&x=1"]
            if glued:
                contexts += ["word" + token, "key_" + token + " tail"]
            for text in contexts:
                with self.subTest(text=text[:40]):
                    out, hits = redact_text(text)
                    self.assertTrue(hits)
                    self.assertNotIn(token, out)
                    self.assertTrue(detector_hits(text))
                    self.assertEqual(detector_hits(out), [], out)
                    self.assertEqual(redact_text(out)[1], [], out)

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
