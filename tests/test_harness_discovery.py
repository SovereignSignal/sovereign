import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from brain_harness_discovery import discover, CATALOG


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.apps = self.home / 'Applications'; self.apps.mkdir()
        self.bin = self.home / 'bin'; self.bin.mkdir()
        self.catalog = json.loads(CATALOG.read_text())

    def scan(self):
        return {t['id']: t for t in discover(self.catalog, self.home, [self.apps], [self.bin])['tools']}

    def test_config_is_evidence_not_installation_or_connection(self):
        (self.home / '.codex').mkdir()
        (self.home / '.codex/credentials').write_text('must never read')
        with patch.object(Path, 'read_text', side_effect=AssertionError('contents read')):
            tool = self.scan()['codex']
        self.assertTrue(tool['detected']); self.assertFalse(tool['installed'])
        self.assertNotIn('connected', tool)
        self.assertEqual(tool['evidence'], [{'path': str(self.home / '.codex'), 'kind': 'configuration'}])

    def test_app_and_executable_found_without_execution(self):
        (self.apps / 'Cursor.app').mkdir()
        command = self.bin / 'gemini'; command.write_text('#!/bin/sh\ntouch '+str(self.home/'executed'))
        command.chmod(0o700)
        tools = self.scan()
        self.assertTrue(tools['cursor']['installed']); self.assertTrue(tools['gemini-cli']['installed'])
        self.assertIsNone(tools['gemini-cli']['connector']); self.assertFalse((self.home/'executed').exists())

    def test_aliases_share_one_producer_and_evidence_is_unique(self):
        (self.home / '.hermes').mkdir(); (self.home / '.hermes/config.yaml').touch()
        (self.apps / 'Hermes.app').mkdir()
        tools = self.scan()
        self.assertNotIn('hermes-desktop', tools)
        self.assertIn('Hermes desktop app', tools['hermes']['aliases'])
        self.assertEqual(len(tools['hermes']['evidence']), 2)

    def test_cloud_and_absent_tools_are_explicit(self):
        tools = self.scan()
        self.assertTrue(tools['notion']['cloud']); self.assertFalse(tools['notion']['detected'])
        self.assertFalse(tools['windsurf']['installed']); self.assertFalse(tools['windsurf']['detected'])

    def test_nonexecutable_and_broken_symlink_do_not_count(self):
        (self.bin/'gemini').touch(); (self.bin/'codex').symlink_to(self.home/'missing')
        tools = self.scan()
        self.assertFalse(tools['gemini-cli']['detected']); self.assertFalse(tools['codex']['detected'])

    def test_permission_failure_is_visible_without_losing_other_results(self):
        original = Path.stat
        def stat(path, *args, **kwargs):
            if path == self.home / '.codex': raise PermissionError()
            return original(path, *args, **kwargs)
        with patch.object(Path, 'stat', stat):
            result = discover(self.catalog, self.home, [self.apps], [self.bin])
        self.assertIn('Could not inspect '+str(self.home/'.codex'), result['warnings'])
        self.assertTrue(any(t['cloud'] for t in result['tools']))

if __name__ == '__main__': unittest.main()
