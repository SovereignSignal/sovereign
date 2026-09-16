"""The kit is what a rebuild needs and nothing more: the instance file, the pointers, the
notify env files, and what the owner lists. Never the key, never the vault. Sealed with
the same tool as the recovery capsule, and it restores byte for byte."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
from sovereign_hub import kit, instance, recovery  # noqa: E402

HELPER = (ROOT / "apps/console/build/hub-crypto").is_file() or (ROOT / "bin/hub-crypto").is_file()


@unittest.skipUnless(HELPER, "needs the built hub-crypto helper")
class Kit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="sov-kit-test-", dir="/private/tmp"); t = Path(self.tmp.name)
        self.home = t / "home"; self.state = self.home / ".local/state/sovereign"; self.state.mkdir(parents=True)
        (t / "vault" / "knowledge").mkdir(parents=True); (self.home / ".brain-root").write_text(str(t / "vault") + "\n")
        (self.home / "secret.env").write_text("TOKEN=abc\n"); (self.home / "tg.env").write_text("TG_BOT_TOKEN=x\n")
        self.keys = t / "keys"; self.keys.mkdir(); self.key = self.keys / "hub.key"; recovery.recovery_key(self.key, True)
        self.target = t / "offsite"; self.target.mkdir()
        instance.write(self.state, {"vault": str(t / "vault"), "lane": "curator", "model": "m:1",
                                    "endpoint": "http://localhost:1/v1/chat/completions",
                                    "snapshot": {"folder": str(t / "snaps"), "keep": 30},
                                    "notify": {"archive": str(self.home / "tg.env")},
                                    "kit": {"include": [str(self.home / "secret.env")], "key_file": str(self.key), "targets": [str(self.target)], "keep": 2}})
        self.inst = instance.load(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def test_inventory_is_exactly_the_declared_set_and_never_the_key_or_the_vault(self):
        names = [n for n, _ in kit.inventory(self.inst, self.state, self.home)]
        self.assertIn("state/hub.json", names); self.assertIn("pointers/.brain-root", names)
        self.assertIn("notify/tg.env", names); self.assertIn("include/secret.env", names)
        self.assertFalse(any("hub.key" in n for n in names))
        bad = json.loads(json.dumps(self.inst)); bad["kit"]["include"] = [str(self.key)]
        with self.assertRaises(ValueError):
            kit.inventory(bad, self.state, self.home)
        bad["kit"]["include"] = [self.inst["vault"]]
        with self.assertRaises(ValueError):
            kit.inventory(bad, self.state, self.home)

    def test_build_seals_copies_keeps_and_restores_byte_for_byte(self):
        folder = Path(self.inst["snapshot"]["folder"]) / "hub-kit"
        kit.build(self.inst, self.state, self.home, ROOT, apply=False)
        self.assertFalse(folder.exists(), "a dry run writes nothing")
        for _ in range(3):
            kit.build(self.inst, self.state, self.home, ROOT, apply=True)
        kits = sorted(folder.glob("*.kit"))
        self.assertEqual(len(kits), 2, "keep=2 prunes the oldest")
        self.assertEqual(sorted(p.name for p in self.target.glob("*.kit")), [p.name for p in kits])
        receipt = json.loads((self.state / "hub" / "kit.json").read_text())
        self.assertEqual(receipt["targets"][str(self.target)]["state"], "copied")
        out = Path(self.tmp.name) / "restored"
        names = kit.restore(kits[-1], out, self.key)
        self.assertIn("include/secret.env", names)
        self.assertEqual((out / "include/secret.env").read_text(), "TOKEN=abc\n")
        self.assertEqual((out / "state/hub.json").read_bytes(), (self.state / "hub.json").read_bytes())

    def test_a_wrong_key_restores_nothing(self):
        kit.build(self.inst, self.state, self.home, ROOT, apply=True)
        capsule = sorted((Path(self.inst["snapshot"]["folder"]) / "hub-kit").glob("*.kit"))[-1]
        other = self.keys / "other.key"; recovery.recovery_key(other, True)
        out = Path(self.tmp.name) / "nope"
        with self.assertRaises(Exception):
            kit.restore(capsule, out, other)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
