"""Fleet rows for local (Parallels) guests: online means the hypervisor says running, and
the guest's folder in this host's parallels lane is its lane, so the row is not "no tools"."""
import importlib.machinery, importlib.util, os, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "bin" / "sov-status"


def load_status():
    loader = importlib.machinery.SourceFileLoader("brain_status_local_vms_under_test", str(STATUS))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(m)
    return m


class LocalVmRows(unittest.TestCase):
    def setUp(self):
        self.m = load_status()
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "vault"
        (self.root / "raw/tools").mkdir(parents=True); (self.root / "raw/workspaces").mkdir(parents=True)
        # a pulled guest: one project with two cards, under this host's parallels lane
        g = self.root / "raw/tools/parallels-testbox/alpha-ubuntu-vm/claude-code/memory/-home-me"
        g.mkdir(parents=True); (g / "MEMORY.md").write_text("- [x](x.md)\n"); (g / "x.md").write_text("fact\n")
        (self.root / "raw/tools/parallels-testbox/LANE.md").write_text("---\nlane: parallels-testbox\nhost: testbox\nproducer: guests\nread: none\nwrite: rsync\nstatus: onboarded\n---\n")
        (self.root / "raw/tools/parallels-testbox/MANIFEST.md").write_text("Last run: 2026-09-22T13:19:58Z on testbox. Items mirrored: 1. Failed: 0.\n")
        self.m.tailscale_peers = lambda: {}
        self.m.parse_hosts_md = lambda root: ({}, None)
        self.m.pointer = lambda name: "testbox" if name == "~/.brain-host" else ""
        self.m.port_open = lambda *a, **k: self.fail("a guest with no address must not be port-probed")
        self.m.bootstrap_handoff = lambda: None

    def rows(self, vms):
        self.m.local_vms = lambda: vms
        return {h["host"]: h for h in self.m.fleet_view(str(self.root))["hosts"]}

    def test_a_running_guest_is_online_by_the_hypervisors_word_and_carries_its_lane(self):
        hosts = self.rows([{"tool": "parallels", "name": "Alpha Ubuntu VM", "status": "running", "ip": None, "uuid": "u1", "os": "ubuntu"}])
        row = hosts["alpha-vm"]
        self.assertEqual(row["net"], {"online": True, "ip": None, "via": "parallels"})
        self.assertEqual([l["lane"] for l in row["lanes"]], ["parallels-testbox/alpha-ubuntu-vm"])
        self.assertEqual(row["lanes"][0]["pulled"], ["claude-code"])
        self.assertIn("contribute-only", row["lanes"][0]["read"])
        h = row["harnesses"][0]
        self.assertEqual((h["harness"], h["projects"], h["md_files"], h["pulled_by"]), ("claude-code", 1, 2, "testbox"))
        self.assertIn("Items mirrored: 1", h["last_run"])

    def test_a_stopped_guest_is_offline_not_unknown(self):
        hosts = self.rows([{"tool": "parallels", "name": "Beta Box", "status": "stopped", "ip": None, "uuid": "u2", "os": "ubuntu"}])
        row = hosts["beta-vm"]
        self.assertEqual(row["net"]["online"], False)
        self.assertEqual(row["net"]["via"], "parallels")
        self.assertEqual(row["lanes"], [], "nothing was ever pulled from it, so no lane is invented")
        self.assertEqual(row["harnesses"], [])

    def test_a_guest_with_an_address_keeps_the_port_probe_answer(self):
        self.m.port_open = lambda *a, **k: True
        hosts = self.rows([{"tool": "parallels", "name": "Gamma VM", "status": "running", "ip": "10.0.0.9", "uuid": "u3", "os": "ubuntu"}])
        self.assertEqual(hosts["gamma-vm"]["net"], {"online": True, "ip": "10.0.0.9", "via": "parallels"})


    def vm(self, name, status):
        return {"tool": "parallels", "name": name, "status": status, "ip": None, "uuid": "u-" + status, "os": "ubuntu"}

    def test_a_guest_put_away_on_purpose_is_not_a_reachability_failure(self):
        for status in ("suspended", "stopped"):
            with self.subTest(status=status):
                hosts = self.rows([self.vm("Delta VM", status)])
                self.assertEqual(hosts["delta-vm"]["net"]["online"], False)
                self.assertEqual(self.m.fleet_needs({"hosts": list(hosts.values())}), [])

    def test_a_guest_in_any_other_state_still_cannot_be_reached(self):
        for status in ("paused", "unrecognized"):
            with self.subTest(status=status):
                hosts = self.rows([self.vm("Delta VM", status)])
                rows = self.m.fleet_needs({"hosts": list(hosts.values())})
                self.assertEqual([r["host"] for r in rows], ["delta-vm"])
                self.assertIn("cannot currently reach delta-vm", rows[0]["text"])

    def test_an_unreachable_host_that_is_not_a_guest_still_raises_its_row(self):
        host = {"host": "host-a", "net": {"online": False, "ip": None, "via": "tailscale"}}
        self.assertEqual([r["host"] for r in self.m.fleet_needs({"hosts": [host]})], ["host-a"])
        # A stopped hypervisor record does not excuse a host whose network check was not the hypervisor's.
        host["vm"] = self.vm("Host A", "stopped")
        self.assertEqual([r["host"] for r in self.m.fleet_needs({"hosts": [host]})], ["host-a"])

if __name__ == "__main__":
    unittest.main()
