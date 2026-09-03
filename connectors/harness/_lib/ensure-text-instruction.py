#!/usr/bin/env python3
"""Append a Sovereign read instruction to a plain-text rules file, once.

For tools with no hooks but a global rules or instructions file the agent always
reads (Windsurf's global_rules.md, an AGENTS.md, a system prompt file). Idempotent
by sentinel, backs the file up once per day, creates it when missing, writes
atomically, never touches anything above the appended block.

Usage: ensure-text-instruction.py <rules-file> <instruction.md> [--dry-run]
Config: ~/.brain-root (or $BRAIN_ROOT) fills {{VAULT}} in the instruction.
"""
import os, sys, datetime, tempfile

SENTINEL = "[Sovereign]"


def pointer(p):
    try:
        return open(os.path.expanduser(p), encoding="utf-8").read().strip() or None
    except OSError:
        return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if len(args) < 2:
        print(__doc__); sys.exit(64)
    target, instruction = os.path.expanduser(args[0]), os.path.expanduser(args[1])
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    if not root:
        print("ensure-text-instruction: no ~/.brain-root; nothing applied"); return
    text = open(instruction, encoding="utf-8").read().strip().replace("{{VAULT}}", root)
    block = "\n\n" + SENTINEL + " " + " ".join(text.split()) + "\n"
    cur = open(target, encoding="utf-8").read() if os.path.exists(target) else ""
    if SENTINEL in cur:
        print("ensure-text-instruction: already present in %s" % target); return
    if dry:
        print("ensure-text-instruction: would append to %s" % target); return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if cur:
        bak = target + ".bak-" + datetime.date.today().isoformat()
        if not os.path.exists(bak):
            open(bak, "w", encoding="utf-8").write(cur)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), prefix=".sov-", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(cur.rstrip("\n") + block if cur.strip() else block.lstrip("\n"))
    os.replace(tmp, target)
    print("ensure-text-instruction: appended to %s" % target)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ensure-text-instruction: %s" % e, file=sys.stderr)
    sys.exit(0)
