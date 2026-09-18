#!/usr/bin/env python3
"""Cowork read wire, made automatic.

Cowork (Claude Desktop local agent mode) runs no hooks, but every space it
creates has an `instructions` field in its spaces.json. This script appends the
Sovereign read instruction to every space that lacks it, so the owner never
pastes anything and spaces created later are covered on the next mirror run.

Idempotent by sentinel ("[Sovereign]"). Backs up spaces.json once per day before
the first edit of that day. Writes atomically. Never touches any other field.

Usage: ensure-instruction.py [--dry-run]
Config: ~/.brain-root (or $BRAIN_ROOT) fills {{VAULT}} in INSTRUCTION.md.
        $COWORK_SESSIONS overrides the sessions folder (tests).
"""
import os, sys, json, glob, datetime, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
SENTINEL = "[Sovereign]"


def pointer(p):
    from sovereign_config import pointer as instance_pointer
    return instance_pointer(p)


def main():
    dry = "--dry-run" in sys.argv
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    if not root:
        print("ensure-instruction: no ~/.brain-root; nothing applied")
        return
    text = open(os.path.join(HERE, "INSTRUCTION.md"), encoding="utf-8").read().strip().replace("{{VAULT}}", root)
    block = SENTINEL + " " + " ".join(text.split())
    base = os.environ.get("COWORK_SESSIONS") or os.path.expanduser("~/Library/Application Support/Claude/local-agent-mode-sessions")
    files = glob.glob(os.path.join(base, "*", "*", "spaces.json"))
    applied = skipped = 0
    for path in files:
        try:
            data = json.load(open(path, encoding="utf-8"))
        except Exception as e:
            print("ensure-instruction: cannot read %s: %s" % (path, e), file=sys.stderr)
            continue
        spaces = data.get("spaces") if isinstance(data, dict) else data
        if not isinstance(spaces, list):
            continue
        changed = False
        for sp in spaces:
            if not isinstance(sp, dict):
                continue
            cur = sp.get("instructions") or ""
            if SENTINEL in cur:
                skipped += 1
                continue
            sp["instructions"] = (cur.rstrip() + "\n\n" + block) if cur.strip() else block
            changed = True
            applied += 1
        if changed and not dry:
            stamp = datetime.date.today().isoformat()
            bak = path + ".bak-" + stamp
            if not os.path.exists(bak):
                try:
                    open(bak, "wb").write(open(path, "rb").read())
                except OSError:
                    pass
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".spaces-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
    print("ensure-instruction: %s %d space(s) newly covered, %d already covered, %d spaces file(s)%s"
          % ("would cover" if dry else "covered", applied, skipped, len(files),
             " (restart Claude Desktop to pick up edits made while it was open)" if applied and not dry else ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("ensure-instruction: %s" % e, file=sys.stderr)
    sys.exit(0)
