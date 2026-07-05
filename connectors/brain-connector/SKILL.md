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

## Defaults

- Transport comes from your `LANE.md` (`read:`, `write:`). Defaults: `git` / `git-branch`.
- Keep your own memory thin: no duplicate of the brain's knowledge — reload it on demand
  with `brain-load`. A changelog of your own actions is fine; a second copy of the brain
  is not.
- Your `gear` (in `LANE.md`) starts at ask-first and is granted, never assumed. Nothing you
  do graduates into writing trusted layers — that never-graduates.
- When in doubt: capture and flag; do not decide what is canonical.
