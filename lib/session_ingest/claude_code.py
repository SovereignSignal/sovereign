"""Read Claude Code session transcripts: metadata plus typed prompts, nothing else.

A transcript is JSON lines under ~/.claude/projects/<folder>/<session>.jsonl. Most of
its bytes are not the conversation: the archive's own session-start pack arrives as a
hook_success attachment, and thinking, tool inputs and results, request copies, file
snapshots and queue operations sit beside the turns. scan() keeps the human's typed
prompts, the assistant's text blocks and the names of the tools it called, and drops
the rest by line kind, so nothing it never meant to keep can reach an excerpt.

The projects/ folder name is a lossy encoding of the working directory and is never
used for a decision; the cwd fields inside the file are, through cwd_check.
"""
import glob
import json
import os
import re

TOOL = "claude-code"
LANE_PREFIX = "claude-code"

# A user line whose text opens with one of these was written by the harness, not typed:
# reminders, slash-command echoes, local command output, background task notices and
# the output of a `!` shell command.
_HARNESS_TEXT = ("<system-reminder>", "<command-", "<local-command-", "<task-notification>",
                 "<bash-input>", "<bash-stdout>", "<bash-stderr>")


# The archive's own session-start pack travels inside reminder text, so a reminder is
# cut out wherever it sits in a part, not only when it opens one; an unclosed one runs
# to the end of the part.
_REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.S)


def list_transcripts(home):
    """Every top-level transcript, one level under projects/. Subagent, tool-result and
    workflow files live a level deeper and are never reached; symlinks are skipped."""
    root = os.path.join(str(home), ".claude", "projects")
    found = []
    for path in glob.glob(os.path.join(glob.escape(root), "*", "*.jsonl")):
        if os.path.islink(path) or os.path.islink(os.path.dirname(path)):
            continue
        if os.path.isfile(path):
            found.append(path)
    return sorted(found)


def first_cwd(path):
    """The realpath of the first working directory the transcript names, or None. The
    read stops at that line, so nothing after it is parsed; status uses it to list a
    project for a session the watermark holds no cwd for."""
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            cwd = line.get("cwd") if isinstance(line, dict) else None
            if isinstance(cwd, str) and cwd and "\x00" not in cwd:
                return os.path.realpath(cwd)
    return None


def _prompt_text(line):
    """The typed prompt this user line carries, or None when it is not one."""
    if line.get("isMeta") or "toolUseResult" in line:
        return None
    if line.get("isCompactSummary") or line.get("isVisibleInTranscriptOnly"):
        return None
    origin = line.get("origin")
    if isinstance(origin, dict) and origin.get("kind") not in (None, "human"):
        return None
    message = line.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        parts = [content]
    elif isinstance(content, list) and content:
        if not all(isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
                   for b in content):
            return None
        parts = [b["text"] for b in content]
    else:
        return None
    parts = [_REMINDER.sub("", p) for p in parts]
    kept = [p.strip() for p in parts if not p.lstrip().startswith(_HARNESS_TEXT)]
    text = "\n".join(p for p in kept if p)
    return text or None


def scan(path, cwd_check=None):
    """Stream one transcript into metadata and turns. Malformed lines are skipped.

    cwd_check(realpath) runs once for each new working directory; a non-None answer
    becomes `stopped`, empties `turns` and ends the read, so a refused session's
    conversation is never held in memory past that line."""
    st = os.stat(path)
    out = {"id": None, "path": str(path), "size": st.st_size, "mtime": st.st_mtime, "cwds": [],
           "entrypoint": None, "sidechain": False, "title": None, "first_ts": None, "last_ts": None,
           "turns": [], "stopped": None}
    turn = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict):
                continue
            if out["id"] is None and isinstance(line.get("sessionId"), str) and line["sessionId"]:
                out["id"] = line["sessionId"]
            cwd = line.get("cwd")
            if "cwd" in line and (not isinstance(cwd, str) or "\x00" in cwd):
                continue  # malformed: realpath refuses a NUL, and a non-string is no path
            if cwd:
                real = os.path.realpath(cwd)
                if real not in out["cwds"]:
                    out["cwds"].append(real)
                    verdict = cwd_check(real) if cwd_check else None
                    if verdict is not None:
                        out["stopped"] = verdict
                        out["turns"] = []
                        break
            if out["entrypoint"] is None and isinstance(line.get("entrypoint"), str) and line["entrypoint"]:
                out["entrypoint"] = line["entrypoint"]
            if line.get("isSidechain") is True:
                out["sidechain"] = True
            ts = line.get("timestamp")
            if isinstance(ts, str) and ts:
                out["first_ts"] = out["first_ts"] or ts
                out["last_ts"] = ts
            kind = line.get("type")
            if kind == "ai-title":
                if isinstance(line.get("aiTitle"), str):
                    out["title"] = line["aiTitle"]
            elif kind == "user":
                text = _prompt_text(line)
                if text is not None:
                    turn = {"n": len(out["turns"]) + 1, "prompt": text, "assistant": [], "tools": []}
                    out["turns"].append(turn)
            elif kind == "assistant" and turn is not None:
                message = line.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str):
                    content = [{"type": "text", "text": content}]
                for block in content if isinstance(content, list) else ():
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                        turn["assistant"].append(block["text"].strip())
                    elif block.get("type") == "tool_use" and isinstance(block.get("name"), str):
                        turn["tools"].append(block["name"])
    if out["id"] is None:
        out["id"] = os.path.splitext(os.path.basename(str(path)))[0]
    return out
