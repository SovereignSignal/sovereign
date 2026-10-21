"""Turn a scanned session into the bounded, cleaned excerpt a distiller may read.

The excerpt lives only in memory. build() numbers the turns T1..Tn, cuts each prompt
and each assistant block, folds tool calls to their names, and keeps the whole thing
under a character cap. clean() is the write-boundary redaction: shapes are redacted,
and a line that still looks like it carries a credential is dropped whole, since a
half-scrubbed line is worse than a missing one.
"""
from brain_redact import redact_text
from sovereign_intake.selection import secret_hits

PROMPT_CUT = 1500
ASSISTANT_CUT = 600
HEAD_TURNS = 3
DROPPED_LINE = "[line dropped]"


def _cut(text, limit):
    return text if len(text) <= limit else text[:limit] + "…"


def _labelled(label, text):
    """`label` before the first line; continuation lines are indented, so a line in a
    prompt can never pass for a turn of its own."""
    lines = text.splitlines() or [""]
    return [label + lines[0]] + ["  " + ln for ln in lines[1:]]


def _tool_lines(tools):
    out = []
    for name in tools:
        name = " ".join(str(name).split())[:80]
        if out and out[-1][0] == name:
            out[-1][1] += 1
        else:
            out.append([name, 1])
    return ["[tool: %s]" % n if c == 1 else "[tool: %s] x%d" % (n, c) for n, c in out]


def _render(turn):
    n = turn["n"]
    lines = _labelled("T%d user: " % n, _cut(turn["prompt"], PROMPT_CUT))
    for block in turn.get("assistant") or ():
        lines += _labelled("T%d assistant: " % n, _cut(block, ASSISTANT_CUT))
    return "\n".join(lines + _tool_lines(turn.get("tools") or ()))


def _gap(turns, lo, hi):
    a, b = turns[lo]["n"], turns[hi]["n"]
    return "[T%d omitted]" % a if a == b else "[T%d..T%d omitted]" % (a, b)


def _assemble(turns, blocks, keep):
    """The excerpt text for the kept positions, one omitted line per gap."""
    pieces, prev = [], -1
    for i in sorted(keep):
        if i > prev + 1:
            pieces.append(_gap(turns, prev + 1, i - 1))
        pieces.append(blocks[i])
        prev = i
    if keep and prev < len(turns) - 1:
        pieces.append(_gap(turns, prev + 1, len(turns) - 1))
    return "\n".join(pieces)


def build(turns, hit_turns=frozenset(), cap=24000):
    """Return (text, turn_ids): the excerpt and the turn numbers (ints, ascending) it
    holds. Over the cap it keeps T1 to T3, every hit turn, then the latest turns that
    fit, each added only while the text stays within the cap."""
    blocks = [_render(t) for t in turns]
    keep = set(range(len(turns)))
    text = "\n".join(blocks)
    if len(text) > cap:
        keep = set()
        hits = set(hit_turns)
        order = list(range(min(HEAD_TURNS, len(turns))))
        order += [i for i, t in enumerate(turns) if t["n"] in hits and i >= HEAD_TURNS]
        for i in order:
            if len(_assemble(turns, blocks, keep | {i})) <= cap:
                keep.add(i)
        for i in range(len(turns) - 1, -1, -1):
            if i in keep:
                continue
            if len(_assemble(turns, blocks, keep | {i})) > cap:
                break
            keep.add(i)
        text = _assemble(turns, blocks, keep)
    return text, [turns[i]["n"] for i in sorted(keep)]


def clean(text):
    """Return (text, dropped): credentials redacted by shape, then every line that
    still trips secret_hits replaced by `[line dropped]`; dropped counts those lines."""
    text, _ = redact_text(text)
    out, dropped = [], 0
    for line in text.split("\n"):
        if secret_hits(line):
            out.append(DROPPED_LINE)
            dropped += 1
        else:
            out.append(line)
    return "\n".join(out), dropped
