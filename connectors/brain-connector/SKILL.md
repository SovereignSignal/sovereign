---
name: brain-connector
description: Use when you are a producer of a brain (a plain-text knowledge vault with a curator and an owner gate) — read the brain before working on its subject matter, write outputs only to your own lane, never promote. Three wires; hold all three or you are not in the loop.
---

# Brain Connector

You are a **producer** of this brain. Your contract is your lane's `LANE.md` (at your lane's
root) — it names your lane, your transport, and your gear. This skill is the process around
that contract. Three wires; hold all three or you are not in the loop.

## 1. Read (before you work)

Run `brain-load <entry-slug>` at the start of any task that touches the brain's subject
matter. It prints the entry card, its linked neighbors, and the always-on core (identity,
how-to-work-with-the-owner). Work from current truth, not a stale copy or a guess. If no
card matches your topic, say so plainly — do not invent context.

## 2. Write (your lane only)

You write ONLY into your lane (`raw/…/<your-lane>/`). Use `brain-capture`:

```
brain-capture <slug> --from output.md            # body from a file
brain-capture <slug> --note "one-line capture"   # short inline capture
echo "$BODY" | brain-capture <slug> --from -     # body from stdin
```

It writes a markdown capture with provenance labels (`type: capture`, `source: <your-lane>`,
`created`), refuses any path outside your lane, and — on a `write: git-branch` lane — commits
to your declared `lane/<slug>` branch and pushes. Rules:

- Never write anywhere else. Never edit `LANE.md` (the owner writes your contract).
- Never push any ref except your lane branch. Never merge. Never touch `main`.
- Capture the distilled artifact, not your session exhaust.
- No secrets, no credentials, no tokens — ever, in any file.

## 3. Promote (never)

You never promote. `raw/` becomes `knowledge/` only through the curator and the owner's
gate. Your captures wait in your lane until the curator proposes and the owner approves.
Do not edit `knowledge/` or `workstreams/`. If you believe a capture is urgent or canonical,
say so IN the capture and flag it to the owner — do not act on that belief.

## Heartbeat (git lanes)

End EVERY run — captures or none — by pushing the lane heartbeat (contract: the
heartbeat notes in `LANE.md`). It proves the whole pipe — script ran, exchange
reachable, hub fetched — where a log line only proves the first link. It is
best-effort: never let it raise, never let it fail the run. Reference
implementation, matching the shipped capture-script shape (a `log()` logger, a
`git()` helper running in the lane clone, `BRANCH = "lane/<slug>"`):

```python
def _heartbeat():
    """Prove the whole pipe: an annotated tag (tagger date = now) forced onto
    the exchange's reserved heartbeat ref, fetched by the hub's fence.
    Best-effort by contract: never raises, never fails the run — a failed
    push just leaves the heartbeat stale, which is the hub's alarm working."""
    try:
        lane = BRANCH.split("/", 1)[1]          # lane/<slug> -> <slug>
        t = git("tag", "-f", "-a", "hb-local", "-m", "heartbeat", "HEAD")
        if t.returncode != 0:
            log(f"heartbeat: tag failed (non-fatal): {t.stderr.strip()}")
            return
        p = git("push", "-qf", "origin",
                f"refs/tags/hb-local:refs/heartbeats/{lane}")
        if p.returncode != 0:
            log(f"heartbeat: push failed (non-fatal): {p.stderr.strip()}")
            return
        log("heartbeat: pushed")
    except Exception as e:
        log(f"heartbeat: failed (non-fatal): {e}")
```

Call it at the end of `main()`, after the capture loop, regardless of capture
count — a quiet day still heartbeats; that is the point. Skip it on a dry run:
a rehearsal must not fake liveness.

## Defaults

- Transport comes from your `LANE.md` (`read:`, `write:`). Defaults: `git` / `git-branch`.
- Keep your own memory thin: no duplicate of the brain's knowledge — reload it on demand
  with `brain-load`. A changelog of your own actions is fine; a second copy of the brain
  is not.
- Your `gear` (in `LANE.md`) starts at ask-first and is granted, never assumed. Nothing you
  do graduates into writing trusted layers — that never-graduates.
- When in doubt: capture and flag; do not decide what is canonical.
