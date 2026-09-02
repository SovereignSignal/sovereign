#!/usr/bin/env python3
"""Sovereign connector, Claude Code, the READ wire.

Registered as a SessionStart hook. Claude Code hands it JSON on stdin (cwd,
session_id, source). It maps the working directory to a topic, runs brain-load,
and returns the pack as additionalContext so the session starts pre-briefed.

  inside  <vault>/workstreams/<name>/...  ->  topic <name> (through the alias file)
  inside  <vault>/repos/<name>/...        ->  topic <name>
  anywhere else                           ->  the always-on core only

Rules it keeps:
  - It never writes the pack anywhere. Not into the lane, not into Claude Code's
    memory files. The pack reloads every session; a copy would echo back into the
    loading dock as if it were new material.
  - It never fails the session. Any error is one stderr line and exit 0.
  - It leaves a one-line receipt in the lane (brain-load-usage.md) so the owner
    can count how often the brain is actually read.

Config, all instance-level:
  ~/.brain-root   vault path              (or $BRAIN_ROOT)
  ~/.brain-core   csv of always-on slugs  (or $BRAIN_CORE)
  ~/.brain-host   short host name         (or $BRAIN_HOST)
  $BRAIN_HOOK_MAX_CARDS   cap on topic cards in the pack, core rides on top (default 6)
  $BRAIN_HOOK_MAX_CHARS   cap on injected characters (default 40000)
"""
import os, sys, json, re, subprocess, datetime, shutil, socket

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))


def pointer(path):
    try:
        return open(os.path.expanduser(path), encoding="utf-8").read().strip() or None
    except OSError:
        return None


def find_brain_load():
    for cand in (os.path.join(TEMPLATE_ROOT, "bin", "brain-load"),
                 os.path.expanduser("~/brain-bin/brain-load"),
                 shutil.which("brain-load")):
        if cand and os.path.exists(cand):
            return cand
    return None


def lane_dir(root, host):
    lane = f"claude-code-{host}"
    stage = os.environ.get("BRAIN_STAGE")
    if stage:
        return os.path.join(stage, "raw", "tools", lane)
    vs = os.path.expanduser("~/.vault-staging")
    if os.path.isdir(vs):
        return os.path.join(vs, "raw", "tools", lane)
    return os.path.join(root, "raw", "tools", lane)


def receipt(root, host, topic, scope, session_id, source, cards):
    d = lane_dir(root, host)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, "brain-load-usage.md")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write("---\ntype: capture\nsource: claude-code-%s\ncreated: %s\n"
                    "title: brain-load usage receipts\n---\n\n"
                    "One line per Claude Code session start on %s: time, topic, scope, cards loaded.\n\n"
                    % (host, datetime.date.today().isoformat(), host))
    with open(p, "a", encoding="utf-8") as f:
        f.write("- %s %s scope=%s cards=%s source=%s session=%s\n" % (
            datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            topic, scope, cards, source or "?", (session_id or "")[:8]))


def main():
    try:
        inp = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        inp = {}
    cwd = os.path.realpath(inp.get("cwd") or os.getcwd())
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    if not root:
        return  # this machine is not connected; stay silent
    root = os.path.realpath(os.path.expanduser(root))
    core = os.environ.get("BRAIN_CORE") or pointer("~/.brain-core") or ""
    host = (os.environ.get("BRAIN_HOST") or pointer("~/.brain-host")
            or socket.gethostname().split(".")[0].lower())

    topic, scope = None, "core"
    for folder in ("workstreams", "repos"):
        base = os.path.join(root, folder) + os.sep
        if cwd.startswith(base):
            topic = cwd[len(base):].split(os.sep)[0]
            scope = folder[:-1]
            break

    bl = find_brain_load()
    if not bl:
        sys.stderr.write("sovereign hook: brain-load not found\n")
        return
    first_core = next((s.strip() for s in core.split(",") if s.strip()), None)
    entry = topic or first_core
    if not entry:
        return  # nothing to load: no topic and no core configured
    max_cards = os.environ.get("BRAIN_HOOK_MAX_CARDS", "6")   # plus the core: about 2k tokens
    args = [sys.executable, bl, entry, "--root", root, "--max", max_cards]
    if core:
        args += ["--core", core]
    if not topic:
        args += ["--depth", "0"]
    res = subprocess.run(args, capture_output=True, text=True, timeout=25)
    pack = res.stdout.strip()
    if not pack:
        return
    m = re.search(r"_(\d+) cards from the knowledge layer", pack)
    cards = m.group(1) if m else ("core" if not topic else "0")

    limit = int(os.environ.get("BRAIN_HOOK_MAX_CHARS", "40000"))
    if len(pack) > limit:
        pack = pack[:limit] + "\n\n[pack truncated at %d chars; run `brain-load %s` for the rest]" % (limit, entry)

    label = topic or "core"
    header = ("[Sovereign] Brain context for '%s' loaded from the owner's vault (%s). "
              "Treat it as current truth and prefer it over guesses. Do not copy it into "
              "memory files: it reloads every session. For more: `brain-load <topic>`."
              % (label, root))
    try:
        receipt(root, host, label, scope, inp.get("session_id"), inp.get("source"), cards)
    except Exception as e:
        sys.stderr.write("sovereign hook: receipt skipped: %s\n" % e)
    print(json.dumps({
        "hookSpecificOutput": {"hookEventName": "SessionStart",
                               "additionalContext": header + "\n\n" + pack},
        "systemMessage": "Sovereign: loaded %s cards for '%s'" % (cards, label),
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write("sovereign hook: %s\n" % e)
    sys.exit(0)
