#!/usr/bin/env python3
"""Record trust for the Sovereign hook in Codex's config, the way /hooks does.

Codex refuses to run a hook until the owner trusts it. The terminal program's
/hooks screen records that trust in ~/.codex/config.toml as

    [hooks.state."<hooks.json path>:session_start:<group>:<handler>"]
    trusted_hash = "sha256:<hash>"

where the hash is SHA-256 over the canonical JSON of the normalized hook
definition (event label, matcher, and the handler with its defaults filled in;
see codex-rs/hooks/src/engine/discovery.rs and config/src/fingerprint.rs).
This script computes the same key and hash for the Sovereign hook and writes
the same record, so `sov connect codex --apply` is the owner trusting the hook
they just installed, and nobody types /hooks.

Usage:
  trust.py            write or refresh the trust record (backup kept)
  trust.py --check    exit 0 if the installed hook is trusted, 1 if not, 2 if absent
Env: CODEX_HOME (default ~/.codex), SOV_HOOK (default this folder's session-start.py)
"""
import os, sys, json, hashlib, re, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LIMIT = 2500
EVENT_LABELS = {"SessionStart": "session_start", "SessionEnd": "session_end", "UserPromptSubmit": "user_prompt_submit",
                "PreToolUse": "pre_tool_use", "PostToolUse": "post_tool_use", "PermissionRequest": "permission_request",
                "PreCompact": "pre_compact", "PostCompact": "post_compact", "SubagentStart": "subagent_start",
                "SubagentStop": "subagent_stop", "Stop": "stop", "Interrupt": "interrupt"}


def normalized_identity(event, group, h):
    default_timeout = 30 if event in ("SessionEnd", "Interrupt") else 600
    handler = {"type": "command", "command": h["command"], "timeout": int(h.get("timeout", default_timeout)),
               "async": bool(h.get("async", False))}
    if h.get("statusMessage") is not None:
        handler["statusMessage"] = h["statusMessage"]
    if h.get("commandWindows") is not None:
        handler["commandWindows"] = h["commandWindows"]
    lim = h.get("additionalContextLimit")
    if lim is not None and lim != DEFAULT_LIMIT and event in ("PreToolUse", "PostToolUse", "SessionStart", "UserPromptSubmit", "SubagentStart"):
        handler["additionalContextLimit"] = lim
    ident = {"event_name": EVENT_LABELS[event], "hooks": [handler]}
    if group.get("matcher") is not None:
        ident["matcher"] = group["matcher"]
    return ident


def hook_hash(event, group, h):
    canon = json.dumps(normalized_identity(event, group, h), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canon).hexdigest()


def find_hook(hooks_path, hook_cmd, event="SessionStart"):
    try:
        d = json.load(open(hooks_path, encoding="utf-8"))
    except Exception:
        return None
    for gi, group in enumerate(d.get("hooks", {}).get(event, [])):
        for hi, h in enumerate(group.get("hooks", [])):
            if h.get("type", "command") == "command" and h.get("command") == hook_cmd:
                key = "%s:%s:%d:%d" % (hooks_path, EVENT_LABELS[event], gi, hi)
                return key, hook_hash(event, group, h)
    return None


def escaped(key):
    return key.replace("\\", "\\\\").replace('"', '\\"')


def read_trusted(config_text, key):
    header = '[hooks.state."%s"]' % escaped(key)
    m = re.search(re.escape(header) + r"[^\n]*\n((?:(?!\[)[^\n]*\n?)*)", config_text)
    if not m:
        return None
    tm = re.search(r'(?m)^\s*trusted_hash\s*=\s*"([^"]*)"', m.group(1))
    return tm.group(1) if tm else None


def write_trusted(config_path, key, hash_):
    text = open(config_path, encoding="utf-8").read() if os.path.exists(config_path) else ""
    header = '[hooks.state."%s"]' % escaped(key)
    if read_trusted(text, key) == hash_:
        return "already"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    if text:
        open(config_path + ".bak-" + stamp, "w", encoding="utf-8").write(text)
    m = re.search(re.escape(header) + r"[^\n]*\n((?:(?!\[)[^\n]*\n?)*)", text)
    if m:
        body = m.group(1)
        if re.search(r'(?m)^\s*trusted_hash\s*=', body):
            body2 = re.sub(r'(?m)^(\s*trusted_hash\s*=\s*)"[^"]*"', r'\1"%s"' % hash_, body, count=1)
        else:
            body2 = 'trusted_hash = "%s"\n' % hash_ + body
        text = text[:m.start(1)] + body2 + text[m.end(1):]
        verb = "updated"
    else:
        text = text.rstrip("\n") + '\n\n%s\ntrusted_hash = "%s"\n' % (header, hash_)
        verb = "written"
    open(config_path, "w", encoding="utf-8").write(text)
    return verb


def main():
    codex_home = os.path.expanduser(os.environ.get("CODEX_HOME", "~/.codex"))
    hook_cmd = os.environ.get("SOV_HOOK") or os.path.join(HERE, "session-start.py")
    hooks_path = os.path.join(codex_home, "hooks.json")
    config_path = os.path.join(codex_home, "config.toml")
    found = find_hook(hooks_path, hook_cmd)
    if not found:
        print("trust: Sovereign hook not found in %s" % hooks_path)
        sys.exit(2)
    key, hash_ = found
    if "--check" in sys.argv:
        cur = read_trusted(open(config_path, encoding="utf-8").read() if os.path.exists(config_path) else "", key)
        print("trust: %s (%s)" % ("trusted" if cur == hash_ else "NOT trusted", key))
        sys.exit(0 if cur == hash_ else 1)
    verb = write_trusted(config_path, key, hash_)
    print("trust: %s in %s for %s" % (verb, config_path, key))


if __name__ == "__main__":
    main()
