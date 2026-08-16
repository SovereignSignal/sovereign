# LANE.md — the producer lane contract

Every lane in `raw/` may carry a `LANE.md` at its root: the producer's contract with this
brain. The **owner writes it at onboarding**; the producer reads it and follows it; machines
parse the frontmatter. One file makes "in the loop" a checkable property instead of a hope.

The curator never judges `LANE.md` itself (config is not knowledge) — it is the contract
*around* the material, not material.

## The schema

```yaml
---
# ---- identity (required) ----
lane: wire-ops                 # slug; MUST equal this folder's name
producer: wire-room-ops        # the tool/agent that writes here (its registry name)
host: node-11              # where it runs: machine name, or provider:app for PaaS
mission: >                     # one sentence: what this lane carries and why it exists
  Daily grant-intel captures distilled from the Wire Room pipeline.

# ---- the wires (required) ----
write: git-branch              # git-branch (default) | rsync | local
read: git                      # git (default) | rsync | none (a write-only producer)
read_scope:                    # optional: the vault paths this producer's clone materialises.
  - CLAUDE.md                  # omit the field and the default below applies.
  - knowledge/
  - raw/workspaces/wire-ops/
gear: ask-first                # ask-first | act-and-report | routine — mirrors the curator's gears;
                               # starts at ask-first, graduates only by owner grant, resets when
                               # the pipeline that earned it changes

# ---- transport details (required for git transports) ----
branch: lane/wire-ops          # the ONLY ref this producer may push
remote: <the brain's reachable remote URL>
auth: deploy-key wire-ops@node-11   # the credential's identity — never the credential itself

# ---- lifecycle (required) ----
status: proposed               # proposed | onboarded | paused | retired
onboarded:                     # date the three wires were verified live (set by the owner)
---
```

Below the frontmatter, the body is for humans: a short paragraph on what the captures look
like, anything unusual about cadence or shape, and the standing rules restated once:

## The three wires (what every producer holds)

1. **Read first.** Load the brain's relevant slice (`brain-load <topic>`) before working on
   its subject matter. Work from current truth, never a stale copy. What the producer holds
   locally is its `read_scope` (see below), not the whole brain.
2. **Write your lane only.** Captures go to `raw/…/<lane>/` via `brain-capture` (git
   producers: committed on `lane/<slug>`, pushed, owner merges). Valid capture = markdown
   with `type: capture`, `source`, `created` frontmatter. No secrets, ever; no binaries;
   the pipe or CLI enforces the excludes.
3. **Never promote.** `raw/` → `knowledge/` is the curator plus the owner's gate, nothing
   else. Never write `knowledge/`, `workstreams/`, another lane, or `main`.

## Field notes

- **`write: git-branch`** is the shipped default because it is the most universal transport
  (works on a LAN, across the internet, behind NAT) and every write arrives as a reviewable
  commit with an author, a diff, and a revert. `rsync` is the right adapter for same-machine
  or LAN file-drops (see `generic-dir/`); `local` is a producer that lives on the hub itself.
- **`read_scope`** answers "how much of the brain does this producer hold?". A producer is a
  specialist: it needs the trusted layer, the law, and its own lane, and holding the rest is
  clutter. The hub and the owner's own machines are **not producers** and are never scoped —
  they read everything.
  - **Default when the field is absent:** `CLAUDE.md` (the law), `knowledge/` (the trusted
    layer the read wire exists to serve), and the lane's own folder (`raw/workspaces/<lane>/`
    or `raw/tools/<lane>/`). That is exactly what the three wires need, so most lanes never
    write the field at all.
  - **Declared scope replaces the default, it does not extend it.** Write the whole list.
    A producer that genuinely needs a workstream adds it (`workstreams/grant-wire/`); one
    that needs nothing but its own lane can drop `knowledge/`, at the cost of `brain-load`.
  - **How it is applied.** `brain-lane-scope` on the producer reads this field and runs
    `git sparse-checkout set --cone <paths>`. Cone mode is directory-granular and always
    materialises files in the repository root, so `CLAUDE.md` costs nothing to list and is
    listed for clarity. Re-running is idempotent; the helper refuses a dirty tree or a clone
    that is not on its lane branch.
  - **The honest limit.** Sparse-checkout scopes the **working tree**, not the repository.
    Every commit for every path is still in `.git`, one `git sparse-checkout disable` away.
    This is clarity and hygiene — a producer's disk shows only what it works on — and it is
    **not** isolation from a determined reader on that box. A lane that must not hold other
    material at all needs a different transport, not a narrower cone.
- **`gear`** governs how the producer's *own* actions escalate (e.g. whether it may
  restructure files inside its lane without asking). It never governs promotion — nothing
  a producer does graduates into writing trusted layers.
- **`status: retired`** + a dated note is how a lane dies. Its material stays in the loading
  dock (or is archived by the owner); the contract records that nothing writes here anymore.
- A lane with **no `LANE.md`** is legacy-tolerated (forward-only rollout) but the weekly
  auditor flags it: undeclared writers are how loading docks rot.

## Onboarding checklist (owner runs this)

1. Create the lane folder; write `LANE.md` (`status: proposed`).
2. Clone the brain on the producer, check out `lane/<slug>`, then run `brain-lane-scope` so
   the clone holds its `read_scope` and nothing else. Do this before the first capture: a
   scoped clone is the normal shape, not a later cleanup.
3. Producer proves the wires: `brain-load` returns the core; `brain-capture` lands a test
   capture; the capture reaches the hub and the curator's next run judges it.
4. Owner sets `status: onboarded` + the date. From here the producer follows the connector
   skill; nothing is re-explained.
