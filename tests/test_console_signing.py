"""The build must select an unambiguous valid signing identity."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SigningSelection(unittest.TestCase):
    def select(self, identities, explicit='', security_exit=0):
        script = (ROOT / 'apps/console/build.sh').read_text()
        start = script.index('SIGN_ID="${SOV_SIGN_ID:-}"')
        end = script.index('if [ -z "$SIGN_ID" ]; then\n  # Ad-hoc', start)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'identities').write_text(identities)
            stub = path / 'security'
            stub.write_text('#!/bin/sh\ncat "$FIXTURE_IDENTITIES"\nexit "$FIXTURE_EXIT"\n')
            stub.chmod(0o700)
            env = dict(os.environ, PATH=tmp + ':/usr/bin:/bin', SOV_SIGN_ID=explicit,
                       FIXTURE_IDENTITIES=str(path / 'identities'), FIXTURE_EXIT=str(security_exit))
            return subprocess.run(['/bin/bash', '-euo', 'pipefail', '-c',
                                   script[start:end] + '\nprintf "%s" "$SIGN_ID"'],
                                  env=env, capture_output=True, text=True)

    def test_selects_fingerprint_instead_of_ambiguous_display_name(self):
        fingerprint = 'A' * 40
        result = self.select('  1) ' + fingerprint + ' "Sovereign Local Signing"\n  1 valid identities found\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, fingerprint)

    def test_multiple_valid_identities_require_explicit_selection(self):
        result = self.select('1) ' + 'A' * 40 + ' "Sovereign Local Signing"\n2) ' + 'B' * 40 + ' "Sovereign Local Signing"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Multiple valid', result.stderr)

    def test_explicit_identity_is_preserved(self):
        result = self.select('', explicit='chosen-identity', security_exit=1)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, 'chosen-identity')

    def test_no_identity_leaves_existing_adhoc_fallback_available(self):
        result = self.select('0 valid identities found\n')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    def test_keychain_query_failure_never_silently_downgrades(self):
        self.assertNotEqual(self.select('', security_exit=1).returncode, 0)
