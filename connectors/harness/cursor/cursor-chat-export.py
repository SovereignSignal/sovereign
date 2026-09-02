#!/usr/bin/env python3
"""Export Cursor GUI composer conversations from state.vscdb to markdown.

Cursor keeps chat history only in SQLite (cursorDiskKV: composerData:<id> for the
conversation shell, bubbleId:<composerId>:<bubbleId> for each message). This renders
one markdown file per conversation into the vault lane.

Env: DB=<path to a *copy* of state.vscdb>  OUT=<destination dir>
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DB = os.environ["DB"]
OUT = os.environ["OUT"]

# Cursor bubble types: 1 = user turn, 2 = assistant turn.
ROLE = {1: "user", 2: "assistant"}


def slug(text, limit=60):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:limit] or "untitled"


def ms_to_date(ms):
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).astimezone()
    except (TypeError, ValueError, OSError):
        return None


def bubble_body(b):
    """Readable text for one bubble, with a marker when it did tool/terminal work."""
    parts = []
    text = (b.get("text") or "").strip()
    if text:
        parts.append(text)
    thinking = b.get("thinking")
    if isinstance(thinking, dict) and (thinking.get("text") or "").strip():
        parts.append("> [!note]- thinking\n> " + thinking["text"].strip().replace("\n", "\n> "))
    for blk in b.get("suggestedCodeBlocks") or []:
        uri = (blk.get("uri") or {}).get("path") or blk.get("uri") or ""
        if uri:
            parts.append(f"`edit: {uri}`")
    n_tools = len(b.get("toolResults") or [])
    if n_tools:
        parts.append(f"`[{n_tools} tool result(s)]`")
    return "\n\n".join(parts)


def main():
    con = sqlite3.connect(DB)
    rows = con.execute(
        "select key, value from cursorDiskKV where key like 'composerData:%'"
    ).fetchall()

    written = 0
    for key, value in rows:
        cid = key.split(":", 1)[1]
        if cid == "empty-state-draft":
            continue
        try:
            data = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            continue

        headers = data.get("fullConversationHeadersOnly") or []
        if not headers:
            continue

        created = ms_to_date(data.get("createdAt"))
        date_str = created.strftime("%Y-%m-%d") if created else "undated"
        name = data.get("name") or (data.get("text") or "").strip().split("\n")[0]
        fname = f"{date_str}-{slug(name)}-{cid[:8]}.md"

        lines = [
            "---",
            f"source: cursor-gui",
            f"composer_id: {cid}",
            f"title: {json.dumps(name or 'untitled')}",
            f"created: {created.isoformat() if created else 'unknown'}",
            f"messages: {len(headers)}",
            "egress: local-only",
            "---",
            "",
            f"# {name or 'untitled'}",
            "",
        ]

        for h in headers:
            bid = h.get("bubbleId")
            if not bid:
                continue
            r = con.execute(
                "select value from cursorDiskKV where key = ?",
                (f"bubbleId:{cid}:{bid}",),
            ).fetchone()
            if not r:
                continue
            try:
                b = json.loads(r[0])
            except (json.JSONDecodeError, TypeError):
                continue
            body = bubble_body(b)
            if not body:
                continue
            lines.append(f"## {ROLE.get(b.get('type'), 'unknown')}")
            lines.append("")
            lines.append(body)
            lines.append("")

        content = "\n".join(lines)
        path = os.path.join(OUT, fname)
        # Rewrite only on change: conversations grow, but an unchanged export should
        # not churn the file mtime (the vault mirrors on mtime).
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                if f.read() == content:
                    continue
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        written += 1

    con.close()
    # stdout, not stderr: the error log must stay a true error signal. A routine status
    # line there makes a real failure harder to spot, which is how the cowork lane sat
    # broken for 17 days.
    print(f"cursor-chat-export: {written} conversation(s) written to {OUT}")


if __name__ == "__main__":
    main()
