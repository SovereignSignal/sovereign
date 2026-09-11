"""Producer removal preserves owner config, history and unrelated collectors."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from test_connectors_install import Box, ROOT, H

spec=importlib.util.spec_from_file_location('disconnect', H/'_lib'/'disconnect.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)

class ProducerRemoval(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.box=Box(self.tmp.name)
        self.env=patch.dict(os.environ,self.box.env(),clear=True);self.env.start();self.addCleanup(self.env.stop)
        self.home=self.box.home
    def write(self,path,value):
        p=self.home/path;p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps(value) if not isinstance(value,str) else value);return p
    def apply_plan(self,h):
        edits=d.cleanup_plan(h,str(self.box.vault))
        for p,b,a,m in edits:
            self.assertEqual(p.read_bytes(),b);d.atomic(p,a,m)
        return edits
    def test_json_hooks_preserve_owner_hooks_and_codex_trust(self):
        for h,folder in [('claude-code','.claude'),('codex','.codex'),('cursor','.cursor')]:
            with self.subTest(h=h):
                hook=str(H/h/'session-start.py')
                hooks={'sessionStart':[{'command':hook},{'command':'owner-hook'}]} if h=='cursor' else {'SessionStart':[{'matcher':'startup','hooks':[{'command':hook},{'command':'owner-hook'}]}]}
                p=self.write(folder+('/settings.json' if h=='claude-code' else '/hooks.json'),{'owner':42,'hooks':hooks})
                if h=='codex':
                    old=str(p)+':session_start:0:1';gone=str(p)+':session_start:0:0'
                    trust=self.write(folder+'/config.toml','model = "owner-model"\n\n[hooks.state.'+json.dumps(gone)+']\ntrusted_hash = "removed"\n\n[hooks.state.'+json.dumps(old)+']\ntrusted_hash = "owner-hash"\n')
                self.apply_plan(h)
                value=json.loads(p.read_text());self.assertEqual(value['owner'],42)
                self.assertNotIn(hook,p.read_text());self.assertIn('owner-hook',p.read_text())
                if h=='codex':
                    self.assertIn('owner-hash',trust.read_text());self.assertNotIn('removed',trust.read_text());self.assertIn(json.dumps(gone),trust.read_text())
                self.assertEqual(self.apply_plan(h),[])
    def test_instruction_cleanup_preserves_surrounding_owner_text(self):
        for h in ('windsurf','cowork'):
            with self.subTest(h=h):
                block='[Sovereign] '+' '.join((H/h/'INSTRUCTION.md').read_text().strip().replace('{{VAULT}}',str(self.box.vault)).split())
                content='Owner before\n\n'+block+'\n\nOwner after'
                if h=='windsurf':p=self.write('.codeium/windsurf/memories/global_rules.md',content)
                else:p=self.write('Library/Application Support/Claude/local-agent-mode-sessions/a/b/spaces.json',{'spaces':[{'id':'keep','instructions':content}],'owner':42})
                self.apply_plan(h);text=p.read_text()
                self.assertIn('Owner before',text);self.assertIn('Owner after',text);self.assertNotIn('[Sovereign]',text)
                self.assertEqual(self.apply_plan(h),[])
    def test_ambiguous_instructions_fail_before_any_write(self):
        p=self.write('.codeium/windsurf/memories/global_rules.md','Owner\n[Sovereign] edited instruction')
        before=p.read_bytes()
        with self.assertRaises(ValueError):self.apply_plan('windsurf')
        self.assertEqual(before,p.read_bytes())
    def test_malformed_json_and_symlink_fail_closed(self):
        p=self.write('.cursor/hooks.json','{broken')
        with self.assertRaises(ValueError):self.apply_plan('cursor')
        p.unlink();target=self.write('owner.json','{}');p.symlink_to(target)
        with self.assertRaises(ValueError):self.apply_plan('cursor')
        self.assertEqual(target.read_text(),'{}')
    def test_hermes_only_removes_owned_command_and_consent(self):
        hook=str(H/'hermes'/'session-start.py')
        p=self.write('.hermes/config.yaml','model: owner\nhooks:\n  pre_llm_call:\n    - command: "'+hook+'"\n      timeout: 30\n    - command: "owner"\n      timeout: 20\n')
        a=self.write('.hermes/shell-hooks-allowlist.json',{'approvals':[{'event':'pre_llm_call','command':hook},{'event':'pre_llm_call','command':'owner'}]})
        self.apply_plan('hermes');self.assertNotIn(hook,p.read_text());self.assertIn('command: "owner"',p.read_text())
        self.assertEqual(json.loads(a.read_text())['approvals'],[{'event':'pre_llm_call','command':'owner'}])
        self.assertEqual(self.apply_plan('hermes'),[])
    def test_write_only_producers_have_no_read_cleanup(self):
        for h in ('orca','notion'):self.assertEqual(self.apply_plan(h),[])
    def test_full_removal_keeps_history_stops_hook_and_reconnects(self):
        r=self.box.connect('windsurf');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        manifest=self.box.state/'connectors.json';record=json.loads(manifest.read_text())['harnesses']['windsurf'];lane=Path(record['lane_dir'])
        raw=lane/'history.md';raw.write_text('preserve provenance')
        # A dry run neither updates config nor touches scheduler state.
        before=manifest.read_bytes();logs=self.box.log.read_bytes()
        r=subprocess.run(['/bin/bash',str(ROOT/'bin'/'sov'),'disconnect','windsurf'],env=self.box.env(),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(before,manifest.read_bytes());self.assertEqual(logs,self.box.log.read_bytes())
        # In-flight collection blocks removal rather than racing its read setup.
        lock=self.box.state/'runner.lock';lock.mkdir()
        r=self.box.disconnect('windsurf');self.assertNotEqual(r.returncode,0);self.assertEqual(before,manifest.read_bytes());lock.rmdir()
        r=self.box.disconnect('windsurf');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        value=json.loads(manifest.read_text());self.assertNotIn('windsurf',value['harnesses']);self.assertFalse(value['retired_harnesses']['windsurf']['cleanup_pending'])
        self.assertEqual(raw.read_text(),'preserve provenance')
        self.assertNotIn('[Sovereign]',(self.home/'.codeium/windsurf/memories/global_rules.md').read_text())
        r=self.box.connect('windsurf');self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        value=json.loads(manifest.read_text());self.assertIn('windsurf',value['harnesses']);self.assertNotIn('windsurf',value['retired_harnesses'])
        self.assertEqual(raw.read_text(),'preserve provenance')
    def test_cloud_removal_reuses_hub_routing(self):
        self.write('.brain-hub','hub-qa:/canonical')
        self.write('.brain-host','desk-qa')
        ssh=self.box.stub/'ssh';ssh.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n');ssh.chmod(0o700)
        r=subprocess.run(['/bin/bash',str(ROOT/'bin'/'sov'),'disconnect','notion'],env=self.box.env(),capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('hub-qa',r.stdout);self.assertIn('connect notion --disconnect',r.stdout)
        self.assertNotIn(str(self.box.vault),r.stdout)
    def test_cli_rejects_path_traversal(self):
        for command in ('connect','disconnect'):
            r=subprocess.run(['/bin/bash',str(ROOT/'bin'/'sov'),command,'../../bad'],env=self.box.env(),capture_output=True,text=True)
            self.assertEqual(r.returncode,64)

if __name__=='__main__':unittest.main()
