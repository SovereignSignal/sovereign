#!/usr/bin/env python3
"""Sovereign connector, Cursor, the READ wire.

Registered as a `sessionStart` hook in ~/.cursor/hooks.json. Cursor hands it JSON
on stdin (session_id, is_background_agent, composer_mode) and the project directory
in $CURSOR_PROJECT_DIR. The shared library maps that directory to a topic, runs
sov-load, and this adapter returns the pack in Cursor's shape:

  {"additional_context": "..."}

Never blocks or fails the session: any error is one stderr line and exit 0.
Config and rules: see connectors/harness/_lib/brainhook.py.
"""
import os, sys, json

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
import brainhook  # noqa: E402


def main():
    try:
        inp = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        inp = {}
    cwd = os.environ.get("CURSOR_PROJECT_DIR") or inp.get("cwd") or os.getcwd()
    pack = brainhook.build_pack(cwd, "cursor")
    if not pack:
        print("{}")
        return
    lane = "cursor-%s" % brainhook.host_name()
    brainhook.receipt(pack["root"], lane, pack["label"], pack["scope"], pack["cards"],
                      inp.get("session_id"), inp.get("composer_mode"))
    print(json.dumps({"additional_context": pack["context"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write("sovereign hook: %s\n" % e)
        print("{}")
    sys.exit(0)
