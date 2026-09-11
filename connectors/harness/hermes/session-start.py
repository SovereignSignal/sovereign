#!/usr/bin/env python3
"""Sovereign connector, Hermes agent, the READ wire.

Registered as a `pre_llm_call` shell hook in ~/.hermes/config.yaml. Hermes pipes
a JSON payload on stdin before every model turn and reads JSON back; `{"context":
"..."}` is prepended to the user message. This adapter injects the pack only at
the start of a conversation (empty or one-message history), so a long chat is not
re-briefed on every turn, and keeps a short-lived cache so a busy session does not
rerun brain-load.

Hermes chats have no working directory, so the pack is the always-on core plus the
identity line; a message that names a workstream in [brackets] or as `sov load x`
gets that topic instead.

Never fails the turn: any error is one stderr line and `{}`.
Config and rules: see connectors/harness/_lib/brainhook.py.
"""
import os, sys, json, re, time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "_lib"))
import brainhook  # noqa: E402

CACHE = os.path.expanduser("~/.cache/sovereign/hermes-pack.json")
CACHE_TTL = 600


def topic_from(message):
    m = re.search(r"sov load ([a-z0-9-]+)", message or "") or re.search(r"\[([a-z0-9-]+)\]", message or "")
    return m.group(1) if m else None


def main():
    if not brainhook.read_enabled("hermes"):
        print("{}"); return  # Check before reading a cached pack or a brain pointer.
    try:
        inp = json.load(sys.stdin) if not sys.stdin.isatty() else {}
    except Exception:
        inp = {}
    extra = inp.get("extra") or {}
    history = extra.get("conversation_history") or []
    if isinstance(history, list) and len(history) > 1:
        print("{}"); return  # mid-conversation: already briefed
    root = brainhook.vault_root()
    if not root:
        print("{}"); return
    topic = topic_from(extra.get("user_message") or "")
    cwd = os.path.join(root, "workstreams", topic) if topic and os.path.isdir(os.path.join(root, "workstreams", topic)) else os.path.expanduser("~")
    pack = None
    if not topic:
        try:
            c = json.load(open(CACHE))
            if time.time() - c.get("ts", 0) < CACHE_TTL and c.get("root") == root:
                pack = c["pack"]
        except Exception:
            pack = None
    if pack is None:
        pack = brainhook.build_pack(cwd, "hermes")
        if not pack:
            print("{}"); return
        if not topic:
            try:
                os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                json.dump({"ts": time.time(), "root": root, "pack": pack}, open(CACHE, "w"))
            except Exception:
                pass
    lane = "hermes-%s" % brainhook.host_name()
    brainhook.receipt(pack["root"], lane, pack["label"], pack["scope"], pack["cards"], inp.get("session_id"), "pre_llm_call")
    print(json.dumps({"context": pack["context"]}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        sys.stderr.write("sovereign hook: %s\n" % e)
        print("{}")
    sys.exit(0)
