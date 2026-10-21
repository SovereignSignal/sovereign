"""sov import: bring what another AI tool already knows about the owner into a raw lane.

Nothing here is trusted on arrival. Each memory becomes one capture in the source's own
import lane, written by sov-capture (the one writer that owns redaction, frontmatter and
never-overwrite), and the curator judges it like anything else. One capture per memory is
deliberate: a single pasted blob would get one judgment and could become one card at most.

Import lanes live under raw/workspaces/, never raw/imports/: curator-run skips any
/imports/ path, so material there would never be judged.
"""
import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

from brain_redact import redact_text
from sovereign_config import pointer

CAPTURE = Path(__file__).resolve().parents[1] / "bin" / "sov-capture"
MAX_INPUT = 1024 * 1024
MIN_BODY = 24
HEADING = re.compile(r"^#{1,3}\s+(.+?)\s*#*\s*$", re.M)

CHATGPT_PROMPT = """I'm moving my long-term context into a personal archive that my AI tools read from. \
Please list everything you remember about me from our past conversations and your saved memories: \
who I am, the projects I'm working on, my goals, decisions I've made, constraints I work under, the \
people and organizations I work with, and how I like to work.

Rules:
- One memory per section. Start each section with a line "## <short title>", then two to five plain sentences.
- Only include what you actually remember. Don't guess, and don't fill gaps with assumptions.
- If you're not sure something is still true, end that section with "(unsure)".
- Leave out passwords, keys, account numbers, and health or financial details.
- No introduction or summary, just the sections."""

SOURCES = {
    "chatgpt": {"name": "ChatGPT", "lane": "chatgpt-import", "prompt": CHATGPT_PROMPT,
                "where": "a new ChatGPT chat (with memory on)"},
}

LANE_TEMPLATE = """---
lane: {lane}
producer: sov-import-{source}
mission: >
  One-shot import of what {name} remembers about the owner, taken by hand with
  `sov import {source}`. Each memory is one capture; the curator judges each.

write: local
read: none
gear: ask-first

sources_documents: {name}'s answer to the Sovereign import prompt, pasted by the owner
sources_processes: none
sources_excluded: anything the prompt asks {name} to leave out (credentials, health, finances)

status: proposed
onboarded:
---

Declared by the owner on {today} by running `sov import {source} --apply`.

{name}'s answer is untrusted: it is a model's recollection, not the owner's own words.
Nothing here is a card until the curator drafts it and the owner (or an earned gear)
approves it. Re-running the same import is a no-op: a memory already captured under the
same title is skipped. This lane is one-shot; a quiet lane here is finished, not broken.
"""


def kebab(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:limit].rstrip("-") or "memory"


def split_memories(text: str) -> List[Tuple[str, str]]:
    """(title, body) per '## heading' section. Text with no headings is one memory.

    Text before the first heading is dropped: the prompt puts every memory under a heading,
    so a lead is the model's preamble ("Here is what I remember"), not something it knows.
    """
    marks = list(HEADING.finditer(text))
    if not marks:
        body = text.strip()
        return [("Imported memory", body)] if len(body) >= MIN_BODY else []
    items = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        title = re.sub(r"[*_`]", "", m.group(1)).strip()
        if title and len(body) >= MIN_BODY:
            items.append((title[:120], body))
    return items


def resolve_vault() -> Optional[Path]:
    root = os.environ.get("BRAIN_ROOT") or pointer("~/.brain-root")
    root = Path(os.path.expanduser(root)) if root else None
    return root if root and (root / "knowledge").is_dir() else None


def plan(root: Path, source: str, text: str) -> List[dict]:
    """One row per memory. A memory is skipped only when the lane already holds its exact
    text: a later answer that changed what ChatGPT remembers under the same title is new."""
    lane_dir = root / "raw" / "workspaces" / SOURCES[source]["lane"]
    held = [p.read_text(encoding="utf-8", errors="replace") for p in sorted(lane_dir.glob(f"{source}-*.md"))] \
        if lane_dir.is_dir() else []
    rows, used = [], set()
    for title, body in split_memories(text):
        stored = redact_text(body)[0]  # captures hold the redacted text, so compare against that
        if any(stored in h for h in held):
            rows.append({"slug": f"{source}-{kebab(title)}", "title": title, "body": body,
                         "skip": "already imported", "redactions": 0})
            continue
        base = f"{source}-{kebab(title)}"
        slug, n = base, 2
        while slug in used or (lane_dir / f"{slug}.md").exists():
            slug, n = f"{base}-{n}", n + 1
        used.add(slug)
        rows.append({"slug": slug, "title": title, "body": body, "skip": None,
                     "redactions": len(redact_text(body)[1])})
    return rows


def apply(root: Path, source: str, rows: List[dict]) -> Tuple[int, List[str]]:
    spec = SOURCES[source]
    lane_dir = root / "raw" / "workspaces" / spec["lane"]
    lane_md = lane_dir / "LANE.md"
    if not lane_md.exists():
        lane_dir.mkdir(parents=True, exist_ok=True)
        lane_md.write_text(LANE_TEMPLATE.format(lane=spec["lane"], source=source, name=spec["name"],
                                                today=date.today().isoformat()))
    captured, failed = 0, []
    env = dict(os.environ, BRAIN_ROOT=str(root))
    stamp = date.today().isoformat()
    for row in rows:
        if row["skip"]:
            continue
        # The provenance line also keeps the body from opening with "---", which sov-capture refuses.
        body = f"Source: {spec['name']}'s recollection, pasted by the owner on {stamp}. Untrusted until judged.\n\n" \
               f"## {row['title']}\n\n{row['body']}"
        cp = subprocess.run([sys.executable, str(CAPTURE), row["slug"], "--lane", spec["lane"], "--from", "-",
                             "--type", "capture", "--title", row["title"],
                             "--origin", f"{source} memory import"],
                            input=body, text=True, capture_output=True, env=env, timeout=120)
        if cp.returncode == 0:
            captured += 1
        else:
            failed.append(f"{row['slug']}: {cp.stderr.strip()[:160]}")
    return captured, failed


def read_input(src: str) -> str:
    if src == "-":
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    else:
        with open(os.path.expanduser(src), "rb") as fh:
            raw = fh.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("the answer is over 1 MiB; split it and import each part")
    return raw.decode("utf-8", errors="replace")


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="sov import",
                                 description="Bring what another AI tool remembers about you into its own raw lane.")
    ap.add_argument("source", choices=sorted(SOURCES))
    ap.add_argument("--from", dest="src", help="the tool's answer: a file, or - for stdin")
    ap.add_argument("--apply", action="store_true", help="capture; without it this is a dry plan")
    ap.add_argument("--prompt", action="store_true", help="print only the prompt (what the app shows)")
    a = ap.parse_args(argv)
    spec = SOURCES[a.source]

    if a.prompt:
        print(spec["prompt"])
        return 0
    if not a.src:
        print(f"Step 1. Paste this into {spec['where']}:\n")
        print(spec["prompt"])
        print(f"\nStep 2. Save {spec['name']}'s answer to a file and preview the import:\n"
              f"  sov import {a.source} --from answer.md\n\nStep 3. Add --apply to bring it in.")
        return 0
    root = resolve_vault()
    if not root:
        print("sov import: no archive is configured on this Mac", file=sys.stderr)
        return 1
    try:
        text = read_input(a.src)
    except (OSError, ValueError) as exc:
        print(f"sov import: {exc}", file=sys.stderr)
        return 1
    rows = plan(root, a.source, text)
    if not rows:
        print(f"sov import: found no memories in that answer. Expected sections starting with '## '.", file=sys.stderr)
        return 1
    new = [r for r in rows if not r["skip"]]
    print(f"{spec['name']} import into raw/workspaces/{spec['lane']}/: {len(new)} new, {len(rows) - len(new)} already imported")
    for r in rows:
        note = f"  ({r['skip']})" if r["skip"] else (f"  ({r['redactions']} secret-shaped value(s) will be redacted)" if r["redactions"] else "")
        print(f"  {r['slug']}{note}")
    if not a.apply:
        if not (root / "raw" / "workspaces" / spec["lane"] / "LANE.md").exists():
            print(f"\n--apply also declares the lane (writes its LANE.md), since this is its first import.")
        print("dry run. add --apply to import. Nothing becomes trusted until the curator drafts it and you approve.")
        return 0
    captured, failed = apply(root, a.source, rows)
    print(f"imported {captured} memor{'y' if captured == 1 else 'ies'}; the curator judges them on its next pass.")
    for f in failed:
        print(f"  failed: {f}", file=sys.stderr)
    return 1 if failed else 0
