# LANE.md — the producer lane contract

Every lane in `raw/` may carry a `LANE.md` at its root: the producer's contract with this
archive. The **owner writes it at onboarding**; the producer reads it and follows it; machines
parse the frontmatter. One file makes "in the loop" a checkable property instead of a hope.

The curator never judges `LANE.md` itself (config is not knowledge) — it is the contract
*around* the material, not material.

## The schema

```yaml
---
# ---- identity (required) ----
lane: wire-ops                 # slug; MUST equal this folder's name
producer: wire-room-ops        # the tool/agent that writes here (its registry name)
host: buildbox                 # where it runs: machine name, or provider:app for PaaS
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
capture_window: 30d            # optional: how long this lane may be quiet before the hub's
                               # freshness check complains. Omit it and the default applies.

# ---- source map (optional): what the producer looks at, in three classes ----
sources_documents: 7 settled design documents, the allow-list in <collector script>
sources_processes: <scheduled process whose outputs are captured as dated observations>
sources_excluded: <what never enters the archive from this host, by rule>

# ---- transport details (required for git transports) ----
branch: lane/wire-ops          # the ONLY ref this producer may push
remote: <the archive's reachable remote URL>
auth: deploy-key wire-ops@buildbox      # the credential's identity — never the credential itself
                               # git producers also end every run with a heartbeat push to
                               # refs/heartbeats/<lane> — not a field, a fixed behavior;
                               # see "The heartbeat" under Field notes.

# ---- lifecycle (required) ----
status: proposed               # proposed | onboarded | paused | retired
onboarded:                     # date the three wires were verified live (set by the owner)
---
```

Below the frontmatter, the body is for humans: a short paragraph on what the captures look
like, anything unusual about cadence or shape, and the standing rules restated once:

## The three wires (what every producer holds)

1. **Read first.** Load the archive's relevant slice (`sov-load <topic>`) before working on
   its subject matter. Work from current truth, never a stale copy. What the producer holds
   locally is its `read_scope` (see below), not the whole archive.
2. **Write your lane only.** Captures go to `raw/…/<lane>/` via `sov-capture` (git
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
- **`read_scope`** answers "how much of the archive does this producer hold?". A producer is a
  specialist: it needs the trusted layer, the law, and its own lane, and holding the rest is
  clutter. The hub and the owner's own machines are **not producers** and are never scoped —
  they read everything.
  - **Default when the field is absent:** `CLAUDE.md` (the law), `knowledge/` (the trusted
    layer the read wire exists to serve), and the lane's own folder (`raw/workspaces/<lane>/`
    or `raw/tools/<lane>/`). That is exactly what the three wires need, so most lanes never
    write the field at all.
  - **Declared scope replaces the default, it does not extend it.** Write the whole list.
    A producer that genuinely needs a workstream adds it (`workstreams/grant-wire/`); one
    that needs nothing but its own lane can drop `knowledge/`, at the cost of `sov-load`.
  - **How it is applied.** `sov-lane-scope` on the producer reads this field and runs
    `git sparse-checkout set --cone <paths>`. Cone mode is directory-granular and always
    materialises files in the repository root, so `CLAUDE.md` costs nothing to list and is
    listed for clarity. Re-running is idempotent; the helper refuses a dirty tree or a clone
    that is not on its lane branch.
  - **The honest limit.** Sparse-checkout scopes the **working tree**, not the repository.
    Every commit for every path is still in `.git`, one `git sparse-checkout disable` away.
    This is clarity and hygiene — a producer's disk shows only what it works on — and it is
    **not** isolation from a determined reader on that box. A lane that must not hold other
    material at all needs a different transport, not a narrower cone.
- **The heartbeat (git transports).** At the end of EVERY run — captures or none — the
  producer pushes a timestamped annotated tag object to a reserved ref namespace on the
  exchange, exactly two commands:

  ```
  git tag -f -a hb-local -m heartbeat HEAD
  git push -qf origin refs/tags/hb-local:refs/heartbeats/<lane>
  ```

  - **What it proves.** The tag's tagger date is written at run time and reaches the hub
    only after the exchange accepted the push and the hub's fence fetched the namespace —
    so a fresh heartbeat proves the WHOLE pipe (the script actually ran, AND the exchange
    was reachable, AND the hub fetched), where "cron fired" or a fresh local log line
    proves only the first link. No commits, no working-tree files, invisible to normal
    git operations.
  - **The thresholds the hub applies.** For a daily lane: yellow past **2d**, red past
    **4d**. Once a lane heartbeats, heartbeat age drives the freshness alarm and the
    newest-capture age becomes informational text on the same check line — a scheduled
    producer that runs and correctly captures nothing is healthy, and now provably so.
    (`capture_window` below matters only for lanes with no heartbeat yet.)
  - **Best-effort by design.** The capture run must NEVER fail because the heartbeat
    could not push: wrap it fully, log the failure to the script's own log, and exit as
    the run otherwise would. A failed push just leaves the heartbeat stale — which IS
    the alarm working.
- **`capture_window`** answers "how long may this lane be silent before something is
  wrong?". The hub's daily health check watches the newest capture in every `onboarded`
  lane and complains when it goes stale.
  - **Default when the field is absent:** yellow past **7d**, red past **14d**. Most lanes
    never write the field.
  - **Write it only when the lane's SOURCES are legitimately static** — a program that is
    paused, a season that has closed, a corpus that is finished. A producer that runs on
    schedule and correctly captures nothing is healthy, and a check that fires on a correct
    outcome only teaches the owner to ignore the check.
  - **Format** is a whole number of days (`30d`, `45 days`). Red is always twice the
    declared window. An unreadable value falls back to the default and says so in the check
    line, so a typo can never quietly widen a lane's alarm.
  - **It is not a fix for a broken producer.** Widening the window on a lane that has
    genuinely died hides the death. Remove the field when the sources come back.
- **The source map** (`sources_documents`, `sources_processes`, `sources_excluded`, all
  optional, all one line) answers "what does this producer look at, and what does it leave
  alone?". Three classes: settled documents (an allow-list a collector distils), scheduled
  process outputs (a monitor, an exporter, a job whose result is worth a dated observation
  even when no interactive session happened), and what is excluded by rule. It exists because
  a collector that succeeds every day can still be looking at the wrong things: the first
  producer pilot found a lane green for a month while the workspace it excluded made fifty
  commits. The map is a declaration, not enforcement; the collector's allow-list is the
  enforcement. Producers with a source map should report what each run covered in the
  heartbeat tag message, as one line the hub can parse: `coverage: {"documents": {"declared":
  7, "captured": 0, "unchanged": 7, "skipped": 0}, "process_outputs": {"declared": 1,
  "new_observations": 0, "qualifying": 0, "captured": 0}, "excluded": "..."}`. The hub's
  daily health check prints the declaration and the report side by side on the lane's line;
  no color depends on it.
- **`gear`** governs how the producer's *own* actions escalate (e.g. whether it may
  restructure files inside its lane without asking). It never governs promotion — nothing
  a producer does graduates into writing trusted layers.
- **`status: retired`** + a dated note is how a lane dies. Its material stays in the loading
  dock (or is archived by the owner); the contract records that nothing writes here anymore.
- A lane with **no `LANE.md`** is legacy-tolerated (forward-only rollout) but the weekly
  auditor flags it: undeclared writers are how loading docks rot.

## Onboarding checklist (owner runs this)

1. Create the lane folder; write `LANE.md` (`status: proposed`).
2. Clone the archive on the producer, check out `lane/<slug>`, then run `sov-lane-scope` so
   the clone holds its `read_scope` and nothing else. Do this before the first capture: a
   scoped clone is the normal shape, not a later cleanup.
3. Producer proves the wires: `sov-load` returns the core; `sov-capture` lands a test
   capture; the capture reaches the hub and the curator's next run judges it.
4. Owner sets `status: onboarded` + the date. From here the producer follows the connector
   skill; nothing is re-explained.
