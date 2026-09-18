"""The hypervisor backup probe must never stall the status.

Found 2026-09-11: with both Proxmox nodes unreachable from the client laptop, `sov status --json`
took 49.5 s (two nodes, two attempts each, 12 s ssh timeout, serial) and the console
rendered an empty environment for the whole wait, then again two minutes later when
the failure cache expired. A backup-posture probe is optional detail; it may not hold
the fleet, harness and archive facts hostage.

Pinned here: a node whose port 22 does not answer is never ssh-ed to (the existing
port_open pre-check decides in one second), nodes are probed concurrently so the
worst case is one node's budget rather than the sum, and the failure is still recorded
and cached exactly as before.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "bin" / "sov-status"


def reader():
    loader = importlib.machinery.SourceFileLoader("brain_status_hv_under_test", str(STATUS))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def fleet_two_nodes():
    return {"hosts": [
        {"host": "worker-a", "meta": {"kind": "Ubuntu VM 102", "where": "Proxmox node node-a"}},
        {"host": "worker-b", "meta": {"kind": "Ubuntu VM 103", "where": "Proxmox node node-a"}},
        {"host": "worker-c", "meta": {"kind": "Ubuntu VM 108", "where": "Proxmox node node-b (Nuc)"}},
        {"host": "laptop-a", "meta": {"kind": "laptop", "where": "here"}},
    ]}


class HypervisorProbe(unittest.TestCase):
    def setUp(self):
        self.mod = reader()
        # never touch the real subprocess module: it is shared with every other test
        self.mod.subprocess = types.SimpleNamespace(
            run=subprocess.run, CompletedProcess=subprocess.CompletedProcess,
            TimeoutExpired=subprocess.TimeoutExpired, PIPE=subprocess.PIPE)
        self.home = tempfile.mkdtemp(prefix="hv-home-")
        self.saved_home = os.environ.get("HOME")
        os.environ["HOME"] = self.home

    def tearDown(self):
        if self.saved_home is not None:
            os.environ["HOME"] = self.saved_home

    def test_closed_port_means_no_ssh_and_a_fast_failure(self):
        m = self.mod
        calls = []

        def fake_run(argv, **kw):
            calls.append(argv)
            if argv[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(argv, 0, stdout="hostname 100.64.0.9\nport 22\n", stderr="")
            raise subprocess.TimeoutExpired(argv, kw.get("timeout", 12))

        m.subprocess.run = fake_run
        m.port_open = lambda host, port=22, timeout=1.0: False
        t0 = time.time()
        view = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        elapsed = time.time() - t0
        probes = [a for a in calls if a[0] == "ssh" and a[1] != "-G"]
        self.assertEqual(probes, [], "an unreachable node must not be ssh-ed to")
        self.assertLess(elapsed, 2.0)
        hosts = {h["host"]: h for h in view["hosts"]}
        self.assertEqual(set(hosts), {"worker-a", "worker-b", "worker-c"})
        self.assertFalse(any(h["reachable"] for h in hosts.values()))
        self.assertTrue(all(h["jobs"] is None for h in hosts.values()))

    def test_reachable_nodes_are_probed_concurrently(self):
        m = self.mod
        lock, active, peak = threading.Lock(), [0], [0]

        def fake_run(argv, **kw):
            if argv[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(argv, 0, stdout="hostname 100.64.0.9\nport 22\n", stderr="")
            with lock:
                active[0] += 1; peak[0] = max(peak[0], active[0])
            time.sleep(0.4)
            with lock:
                active[0] -= 1
            return subprocess.CompletedProcess(argv, 0, stdout="1\n1700000000 vzdump-qemu-102-x.vma\n", stderr="")

        m.subprocess.run = fake_run
        m.port_open = lambda host, port=22, timeout=1.0: True
        t0 = time.time()
        view = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        elapsed = time.time() - t0
        self.assertGreaterEqual(peak[0], 2, "the two nodes must be probed at the same time")
        self.assertLess(elapsed, 0.75, "two 0.4 s probes in parallel, not in series")
        hosts = {h["host"]: h for h in view["hosts"]}
        self.assertTrue(hosts["worker-a"]["reachable"])
        self.assertEqual(hosts["worker-a"]["jobs"], 1)
        self.assertIsNotNone(hosts["worker-a"]["last_dump_age_h"])

    def test_a_hanging_session_is_bounded_and_not_retried(self):
        """Port 22 answers but the session never completes (the 2026-09-11 case)."""
        m = self.mod
        calls = []

        def fake_run(argv, **kw):
            if argv[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(argv, 0, stdout="hostname h\nport 22\n", stderr="")
            calls.append(argv)
            self.assertLessEqual(kw.get("timeout", 99), 6, "a probe may not wait longer than its budget")
            time.sleep(3.1)                               # a hang that ran into the budget
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

        m.subprocess.run = fake_run
        m.port_open = lambda host, port=22, timeout=1.0: True
        t0 = time.time()
        view = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        elapsed = time.time() - t0
        self.assertEqual(len(calls), 2, "one attempt per node, no retry after a hang")
        self.assertLess(elapsed, 4.5, "two hanging nodes cost one budget, in parallel")
        self.assertFalse(any(h["reachable"] for h in view["hosts"]))

    def test_tailscale_recheck_is_named_with_its_link_in_needs_you(self):
        """The failure must say what to do. A Tailscale SSH re-check surfaces as one
        needs-you row per node with the link, not as a bare 'unreachable'."""
        m = self.mod
        banner = (b"# Tailscale SSH requires an additional check.\n"
                  b"# To authenticate, visit: https://login.tailscale.com/a/abc123\n")

        def fake_run(argv, **kw):
            if argv[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(argv, 0, stdout="hostname h\nport 22\n", stderr="")
            raise subprocess.TimeoutExpired(argv, kw.get("timeout"), output=b"", stderr=banner)

        m.subprocess.run = fake_run
        m.port_open = lambda host, port=22, timeout=1.0: True
        view = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        detail = {h["node"]: h["detail"] for h in view["hosts"]}
        self.assertEqual(detail["node-a"]["why"], "tailscale-check")
        self.assertEqual(detail["node-a"]["url"], "https://login.tailscale.com/a/abc123")
        self.assertIn("ssh node-a", detail["node-a"]["action"])
        rows = m.hypervisor_needs(view)
        self.assertEqual([r["node"] for r in rows], ["node-a", "node-b"])
        self.assertEqual(rows[0]["kind"], "hypervisor")
        self.assertEqual(rows[0]["url"], "https://login.tailscale.com/a/abc123")
        self.assertIn("worker-a", rows[0]["text"])
        self.assertIn("open the link", rows[0]["text"])
        # a reachable node produces no row, and a closed port names that cause
        self.assertEqual(m.hypervisor_needs({"hosts": [{"host": "x", "node": "n", "reachable": True}]}), [])
        m.port_open = lambda host, port=22, timeout=1.0: False
        os.environ["HOME"] = tempfile.mkdtemp(prefix="hv-home2-")
        closed = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        self.assertEqual(closed["hosts"][0]["detail"]["why"], "port-closed")
        self.assertIn("Port 22 did not answer", m.hypervisor_needs(closed)[0]["text"])

    def test_nonzero_ssh_exit_does_not_report_reachable(self):
        m = self.mod
        def fake_run(argv, **kw):
            if argv[:2] == ["ssh", "-G"]:
                return subprocess.CompletedProcess(argv, 0, stdout="hostname h\nport 22\n", stderr="")
            return subprocess.CompletedProcess(argv, 255, stdout="", stderr="Permission denied")
        m.subprocess.run = fake_run
        m.port_open = lambda *args, **kwargs: True
        view = m.backups_view("/nonexistent", {}, fleet_two_nodes())
        self.assertFalse(any(h["reachable"] for h in view["hosts"]))
        self.assertTrue(all(h["jobs"] is None for h in view["hosts"]))
        for row in m.hypervisor_needs(view):
            for key in ("why", "action", "verify"):
                self.assertTrue(row[key])

    def test_failure_is_cached_and_a_fresh_failure_is_not_reprobed(self):
        m = self.mod
        calls = []
        m.subprocess.run = lambda argv, **kw: (calls.append(argv), subprocess.CompletedProcess(argv, 0, stdout="hostname h\nport 22\n", stderr=""))[1]
        m.port_open = lambda host, port=22, timeout=1.0: False
        m.backups_view("/nonexistent", {}, fleet_two_nodes())
        first = len(calls)
        self.assertGreater(first, 0)
        m.backups_view("/nonexistent", {}, fleet_two_nodes())
        self.assertEqual(len(calls), first, "a failure younger than its TTL is served from cache")


if __name__ == "__main__":
    unittest.main()
