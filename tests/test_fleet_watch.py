"""How loud the fleet watcher stays, and when it goes quiet.

On 2026-10-13 two VMs were retired on purpose (biscuitclaw, mc-agents-sandbox). Each
shutdown paged "went offline" and would have reminded every hour for as long as the VM
stayed off. Adding a host to the ignore list then paged "Fleet recovered: <host> back
online" for a VM that was still powered off, and the ignore list had grown seven dead
entries for hosts already removed from the tailnet. These pin the fix: yellow events
remind daily, a non-critical host down for a week is muted as retired, and a host that
leaves the fleet (tailnet removal or ignore list) is never announced as recovered. Red
events keep their hourly reminder, which is what this watcher exists for.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

WATCH = Path(__file__).resolve().parents[1] / "bin" / "sov-fleet-watch"
BASE = {"proxmox": True, "uniclaude": True, "spp3": True, "clawkeep": True,
        "pi1": True, "pi2": True}


def iso_ago(**kw):
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(**kw)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class FleetWatch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.state, self.conf, self.fleet = d / "state.json", d / "conf.env", d / "fleet.json"
        (d / "bin").mkdir()
        fake = d / "bin" / "tailscale"
        fake.write_text("#!/bin/sh\ncat '%s'\n" % self.fleet)
        fake.chmod(0o755)
        self.path = "%s:/usr/bin:/bin" % (d / "bin")
        self.configure()

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, ignore="", critical="proxmox"):
        self.conf.write_text("SOV_FLEET_IGNORE=%s\nSOV_FLEET_CRITICAL=%s\n" % (ignore, critical))

    def tailnet(self, hosts):
        peers = {str(i): {"HostName": h, "Online": up, "TailscaleIPs": ["100.0.0.%d" % i]}
                 for i, (h, up) in enumerate(hosts.items(), 1)}
        self.fleet.write_text(json.dumps({"Peer": peers}))

    def run_watch(self, *args):
        env = dict(os.environ, PATH=self.path, SOV_FLEET_CONF=str(self.conf),
                   SOV_FLEET_STATE=str(self.state), SOV_FLEET_NOTIFY="/usr/bin/true")
        cp = subprocess.run([sys.executable, str(WATCH), *args], env=env,
                            capture_output=True, text=True)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stderr, "")
        return cp.stdout.strip()

    def patch_state(self, **kw):
        st = json.loads(self.state.read_text())
        st.update(kw)
        self.state.write_text(json.dumps(st))

    def test_all_up_is_silent(self):
        self.tailnet(BASE)
        self.assertEqual(self.run_watch(), "")

    def test_a_single_host_down_reminds_daily_not_hourly(self):
        self.tailnet(dict(BASE, spp3=False))
        self.assertIn("went offline", self.run_watch())
        self.patch_state(last_alert=iso_ago(minutes=90))
        self.assertEqual(self.run_watch(), "")
        self.patch_state(last_alert=iso_ago(hours=25))
        self.assertIn("STILL DOWN", self.run_watch())

    def test_a_real_recovery_is_announced(self):
        self.tailnet(dict(BASE, spp3=False))
        self.run_watch()
        self.tailnet(BASE)
        self.assertIn("recovered: spp3", self.run_watch())

    def test_a_host_removed_from_the_tailnet_is_not_a_recovery(self):
        self.tailnet(dict(BASE, spp3=False))
        self.run_watch()
        gone = dict(BASE)
        gone.pop("spp3")
        self.tailnet(gone)
        self.assertEqual(self.run_watch(), "")
        self.assertNotIn("spp3", json.loads(self.state.read_text()).get("offline", {}))

    def test_a_newly_ignored_host_is_not_a_recovery(self):
        self.tailnet(dict(BASE, spp3=False))
        self.run_watch()
        self.configure(ignore="spp3")
        self.assertEqual(self.run_watch(), "")

    def test_red_still_reminds_hourly(self):
        self.tailnet(dict(BASE, proxmox=False))
        self.assertIn("critical host down: proxmox", self.run_watch())
        self.patch_state(last_alert=iso_ago(minutes=61))
        self.assertIn("STILL DOWN", self.run_watch())

    def test_a_week_down_mutes_once_then_stays_quiet_until_it_returns(self):
        self.tailnet(dict(BASE, clawkeep=False))
        self.configure(critical="proxmox")
        self.run_watch()
        self.patch_state(offline={"clawkeep": iso_ago(days=7, minutes=5)},
                         last_alert=iso_ago(hours=25))
        out = self.run_watch()
        self.assertIn("treating as retired", out)
        self.assertNotIn("STILL DOWN", out)
        self.patch_state(last_alert=iso_ago(days=3))
        self.assertEqual(self.run_watch(), "")
        summary = json.loads(self.run_watch("--json"))
        self.assertEqual((summary["muted"], summary["offline"]), (["clawkeep"], []))
        self.tailnet(BASE)
        self.assertIn("recovered: clawkeep", self.run_watch())
        self.assertNotIn("muted", json.loads(self.state.read_text()))

    def test_a_critical_host_is_never_muted(self):
        self.tailnet(dict(BASE, proxmox=False))
        self.run_watch()
        self.patch_state(offline={"proxmox": iso_ago(days=8)}, last_alert=iso_ago(minutes=61))
        out = self.run_watch()
        self.assertNotIn("treating as retired", out)
        self.assertIn("STILL DOWN", out)

    def test_a_muted_host_removed_from_the_tailnet_is_forgotten_silently(self):
        self.tailnet(dict(BASE, pi2=False))
        self.run_watch()
        self.patch_state(offline={"pi2": iso_ago(days=8)})
        self.run_watch()
        gone = dict(BASE)
        gone.pop("pi2")
        self.tailnet(gone)
        self.assertEqual(self.run_watch(), "")
        self.assertNotIn("muted", json.loads(self.state.read_text()))

    def test_a_mass_outage_is_red(self):
        self.tailnet({h: False for h in BASE})
        out = self.run_watch()
        self.assertTrue(out.startswith("Fleet DOWN"), out)
        self.assertIn("shared infrastructure", out)


if __name__ == "__main__":
    unittest.main()
