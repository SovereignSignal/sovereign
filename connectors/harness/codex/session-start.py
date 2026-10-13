#!/usr/bin/env python3
"""Sovereign connector, Codex CLI, the READ wire.

Registered as a SessionStart hook in ~/.codex/hooks.json (matcher: startup|resume).
Codex hands it JSON on stdin (cwd, session_id, ...), the same shape Claude Code
uses, and accepts the same output:

  {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ...},
   "systemMessage": "Sovereign: loaded N cards for '<topic>'"}

Never fails the session: any error is one stderr line and exit 0.
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
    cwd = inp.get("cwd") or os.getcwd()
    pack = brainhook.build_pack(cwd, "codex")
    if not pack:
        return
    lane = "codex-memory-%s" % brainhook.host_name()
    brainhook.receipt(pack["root"], lane, pack["label"], pack["scope"], pack["cards"],
                      inp.get("session_id"), inp.get("source"), pack.get("slugs"))
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart",
                               "additionalContext": pack["context"]},
        "systemMessage": "Sovereign: installation pointer; no context pack" if pack["scope"] == "discovery" else "Sovereign: loaded %s cards for '%s'" % (pack["cards"], pack["label"]),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write("sovereign hook: %s\n" % e)
    sys.exit(0)
