#!/usr/bin/env python3
"""Register the Sovereign hook with Hermes and record consent, the documented way.

Hermes runs shell hooks declared under `hooks:` in ~/.hermes/config.yaml and asks
for first-use consent per (event, command), persisting approvals to
~/.hermes/shell-hooks-allowlist.json. Its docs describe manual allowlisting for
non-interactive installs; this script does exactly that for the Sovereign hook.

Usage:
  hooks.py            add the pre_llm_call hook to config.yaml (backup kept) and approve it
  hooks.py --check    exit 0 if registered and approved, 1 if registered but unapproved, 2 if absent
Env: HERMES_HOME (default ~/.hermes), SOV_HOOK (default this folder's session-start.py)
"""
import os, sys, json, re, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
EVENT = "pre_llm_call"


def registered(config_text, cmd):
    return cmd in config_text and re.search(r"(?m)^hooks:\s*$", config_text) is not None


def register(config_path, cmd):
    text = open(config_path, encoding="utf-8").read() if os.path.exists(config_path) else ""
    if registered(text, cmd):
        return "already"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if text:
        open(config_path + ".bak-" + stamp, "w", encoding="utf-8").write(text)
    entry = '    - command: "%s"\n      timeout: 30\n' % cmd
    m = re.search(r"(?m)^hooks:\s*$", text)
    if not m:
        text = text.rstrip("\n") + "\n\n# Sovereign: the archive's read wire (sov connect hermes)\nhooks:\n  %s:\n%s" % (EVENT, entry)
    else:
        # find the hooks block; add or extend the event list inside it
        start = m.end()
        block_end = len(text)
        for mm in re.finditer(r"(?m)^[A-Za-z_]", text[start:]):
            block_end = start + mm.start(); break
        block = text[start:block_end]
        ev = re.search(r"(?m)^  %s:\s*$" % EVENT, block)
        if ev:
            insert_at = start + ev.end() + 1
            text = text[:insert_at] + entry + text[insert_at:]
        else:
            text = text[:block_end].rstrip("\n") + "\n  %s:\n%s" % (EVENT, entry) + text[block_end:]
    open(config_path, "w", encoding="utf-8").write(text)
    return "written"


def approve(allow_path, cmd):
    try:
        d = json.load(open(allow_path))
    except Exception:
        d = {}
    approvals = d.setdefault("approvals", [])
    if any(a.get("event") == EVENT and a.get("command") == cmd for a in approvals):
        return "already"
    approvals.append({"event": EVENT, "command": cmd})
    os.makedirs(os.path.dirname(allow_path), exist_ok=True)
    json.dump(d, open(allow_path, "w"), indent=2)
    return "written"


def main():
    home = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
    cmd = os.environ.get("SOV_HOOK") or os.path.join(HERE, "session-start.py")
    config_path, allow_path = os.path.join(home, "config.yaml"), os.path.join(home, "shell-hooks-allowlist.json")
    if "--check" in sys.argv:
        text = open(config_path, encoding="utf-8").read() if os.path.exists(config_path) else ""
        if not registered(text, cmd):
            print("hooks: Sovereign hook not registered in %s" % config_path); sys.exit(2)
        try:
            ok = any(a.get("event") == EVENT and a.get("command") == cmd for a in json.load(open(allow_path)).get("approvals", []))
        except Exception:
            ok = False
        print("hooks: %s" % ("registered and approved" if ok else "registered, NOT approved")); sys.exit(0 if ok else 1)
    print("hooks: config %s (%s)" % (register(config_path, cmd), config_path))
    print("hooks: consent %s (%s)" % (approve(allow_path, cmd), allow_path))


if __name__ == "__main__":
    main()
