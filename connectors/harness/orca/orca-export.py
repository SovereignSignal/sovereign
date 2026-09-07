#!/usr/bin/env python3
"""Export Orca's orchestration record to markdown, one file per run.

Orca (an orchestrator over coding agents) keeps its state only in SQLite: runs with an
objective, the tasks it dispatched, the decision gates it raised, the questions workers
asked and the answers, and the messages between coordinator and workers. This renders
each run as one markdown capture into the lane. Rewritten on every mirror pass; the hub
judges a file once by content hash, so unchanged runs cost nothing.

Env: DB=<path to a *copy* of orchestration.db>  OUT=<destination dir>
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

DB = os.environ["DB"]
OUT = os.environ["OUT"]
CAP = 2500                                   # per field, so one run stays a readable capture
SECRET = re.compile(r"(?i)\b(token|secret|api[_-]?key|password|bearer)\b\s*[:=]\s*\S+")


def slug(text, limit=48):
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return s[:limit] or "run"


def clean(text, cap=CAP):
    text = SECRET.sub(r"\1: [withheld]", text or "")
    text = text.strip()
    return text if len(text) <= cap else text[:cap] + " …"


def rows(cur, sql, *args):
    cur.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def jl(s):
    try:
        v = json.loads(s or "[]")
        return v if isinstance(v, list) else [v]
    except ValueError:
        return [s] if s else []


# DB is a COPY in a temp dir (mirror.sh snapshots the db plus its -wal and -shm), so
# opening it read-write is safe and is the only way SQLite replays a copied WAL. A
# read-only open cannot: it has to build the -shm sidecar, so it fails outright on a
# WAL database whose sidecars did not exist at copy time. That is what broke the lane.
con = sqlite3.connect(DB)
cur = con.cursor()
runs = rows(cur, "SELECT id, objective, created_at, updated_at, legacy FROM runs ORDER BY created_at")
os.makedirs(OUT, exist_ok=True)
written = 0
for run in runs:
    rid = run["id"]
    tasks = rows(cur, "SELECT id, task_title, display_name, spec, status, deps, result, created_at, completed_at FROM tasks WHERE run_id=? ORDER BY created_at", rid)
    gates = rows(cur, "SELECT id, task_id, question, options, status, resolution, created_at, resolved_at FROM decision_gates WHERE run_id=? ORDER BY created_at", rid)
    questions = rows(cur, "SELECT message_id, dispatch_id, asker_handle, status, answer_body, created_at, answered_at FROM question_threads WHERE run_id=? ORDER BY created_at", rid)
    msgs = rows(cur, "SELECT from_handle, to_handle, subject, body, type, priority, created_at FROM messages WHERE run_id=? AND type IN ('dispatch','worker_done','merge_ready','escalation','handoff','decision_gate','question') ORDER BY sequence", rid)
    if run.get("legacy") and not (tasks or gates or questions or msgs):
        continue                                     # the empty placeholder run Orca creates on first launch
    created = (run["created_at"] or "")[:10] or datetime.now().date().isoformat()
    title = clean(run["objective"], 120) or rid
    name = "%s-%s.md" % (created, slug(run["objective"]) if run["objective"] else rid)
    out = ["---", "type: capture", "source: orca (orchestration.db)", "created: %s" % created, "title: %s" % title.replace("\n", " "), "---", "",
           "# %s" % title, "", "Orca run `%s`, opened %s, last touched %s. %d task(s), %d decision gate(s), %d question(s)." % (
               rid, run["created_at"], run["updated_at"], len(tasks), len(gates), len(questions)), ""]
    if tasks:
        out.append("## Tasks")
        for t in tasks:
            label = t.get("task_title") or t.get("display_name") or t["id"]
            out.append("- **%s** · %s%s" % (clean(label, 160), t["status"], (" · done " + t["completed_at"]) if t.get("completed_at") else ""))
            deps = jl(t.get("deps"))
            if deps:
                out.append("  - after: " + ", ".join(str(d) for d in deps))
            if t.get("spec"):
                out.append("  - spec: " + clean(t["spec"], 1200).replace("\n", " "))
            if t.get("result"):
                out.append("  - result: " + clean(t["result"], 1200).replace("\n", " "))
        out.append("")
    if gates:
        out.append("## Decision gates")
        for g in gates:
            out.append("- **%s** (%s)" % (clean(g["question"], 400).replace("\n", " "), g["status"]))
            opts = jl(g.get("options"))
            if opts:
                out.append("  - options: " + "; ".join(clean(str(o), 120) for o in opts))
            if g.get("resolution"):
                out.append("  - resolved: " + clean(g["resolution"], 400).replace("\n", " ") + (" · " + g["resolved_at"] if g.get("resolved_at") else ""))
        out.append("")
    if questions:
        out.append("## Questions from workers")
        for q in questions:
            out.append("- %s asked (%s)%s" % (q["asker_handle"], q["status"], (": " + clean(q["answer_body"], 600).replace("\n", " ")) if q.get("answer_body") else ""))
        out.append("")
    if msgs:
        out.append("## Messages")
        for m in msgs:
            out.append("- %s · %s → %s · **%s**%s" % (m["created_at"], m["from_handle"], m["to_handle"], clean(m["subject"], 160).replace("\n", " "),
                                                       (" · " + m["priority"]) if m.get("priority") not in (None, "normal") else ""))
            if m.get("body"):
                out.append("  - " + clean(m["body"], 800).replace("\n", " "))
        out.append("")
    path = os.path.join(OUT, name)
    body = "\n".join(out).rstrip() + "\n"
    try:
        if open(path, encoding="utf-8").read() == body:
            continue
    except OSError:
        pass
    open(path, "w", encoding="utf-8").write(body)
    written += 1
print("orca-export: %d run(s), %d file(s) written" % (len(runs), written))
