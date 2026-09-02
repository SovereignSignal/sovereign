#!/usr/bin/env python3
"""sov connect all: connect every tool found on this machine, in one go.

Reads the harness catalog, keeps the ones whose `detect` paths exist and that are
not already connected, and runs each installer with the same flags. Without
--apply every installer prints its dry run and changes nothing.

Usage: connect-all.py [--host H] [--vault V] [--core a,b] [--hub alias:/path] [--apply]
"""
import os, sys, json, glob, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
args = sys.argv[1:]
status = json.loads(subprocess.run([sys.executable, os.path.join(TEMPLATE, "bin", "brain-status"), "--json", "--no-hub"],
                                   capture_output=True, text=True).stdout or "{}")
catalog = status.get("harnesses")
if not catalog:  # not connected yet: build the catalog from detect paths alone
    catalog = []
    for hd in sorted(glob.glob(os.path.join(TEMPLATE, "connectors", "harness", "*"))):
        h = os.path.basename(hd)
        if h.startswith("_") or not os.path.isdir(hd):
            continue
        try:
            meta = json.load(open(os.path.join(hd, "harness.json")))
        except Exception:
            meta = {}
        det = meta.get("detect")
        catalog.append({"id": h, "name": meta.get("name", h), "state": "not connected",
                        "detected": any(os.path.exists(os.path.expanduser(x)) for x in det) if det else None})
todo = [h for h in catalog if h.get("detected") is not False and h.get("state") != "connected"]
if not todo:
    print("every tool found on this machine is already connected: " + ", ".join(h["name"] for h in catalog if h.get("detected")))
    sys.exit(0)
print("connecting %d tool(s): %s%s" % (len(todo), ", ".join(h["name"] for h in todo), "" if "--apply" in args else "  (dry run)"))
rc = 0
for h in todo:
    print("\n=== %s ===" % h["name"])
    r = subprocess.run(["/bin/bash", os.path.join(TEMPLATE, "connectors", "harness", h["id"], "install.sh")] + args)
    rc = rc or r.returncode
sys.exit(rc)
