# {{SOVEREIGN_NAME}} — Sovereign instance

This vault is an **archive**: one organized, plain-text memory that people and AI tools read from and write to under the rules below. The rules are short on purpose. If something needs more rules, it probably does not belong in the archive.

This file is the law. **Part 1** is the standard every instance shares. **Part 2** is specific to this instance — fill it in.

# Part 1 — the standard

## The folders

Four memory folders, plus one optional for code.

| Folder | Its job | Who writes |
|---|---|---|
| `raw/` | The loading dock. Tools and agents drop material here, tagged with where it came from. Messy is fine. Never hand-edited. | Each producer, only in its own lane: `raw/tools/<tool>/` or `raw/workspaces/<name>/` |
| `workstreams/` | The desk. Active work, where most life happens. A workstream can be a single project or a standing collection of work and tasks that projects live inside. | The owner |
| `knowledge/` | The trusted layer. Curated entities, concepts, and syntheses. The part everything leans on. | The owner, and the curator |
| `archive/` | The basement. Cold storage, out of active recall. | Rarely, anyone |
| `repos/` (optional) | The workshop. Code working trees. Workspace, not memory: keeps its own git story outside the archive repo. | Via git, never via note editing |

Keep it flat. `knowledge/entities/`, `knowledge/concepts/`, and `knowledge/syntheses/` never grow deeper. Detail lives in note labels, never in folder paths. The folder also carries trust: anything in `knowledge/` is trusted, anything in `raw/` is not, so no note needs a trust label.

## Every note starts with labels

Two required labels, one auto-filled date, two optional. Order does not matter; git tracks every change, so there is no `updated` field to forget.

```yaml
---
type: entity                  # required, from the list below
source: me                    # required: a URL, the owner's name, or the raw/ path it came from
created: 2026-01-01           # auto-filled by the note template
title: Acme County            # optional, when the filename is not enough
link: https://...             # optional: the matching record in your tables tool
---
```

### The note types

Never invent a type; add to this list instead, with the owner's sign-off.

| type | What it is | Home |
|---|---|---|
| `entity` | One real thing: a person, org, place, or system | `knowledge/entities/` |
| `concept` | An idea, playbook, position, or piece of language | `knowledge/concepts/` |
| `synthesis` | A writeup that pulls several things together | `knowledge/syntheses/` |
| `plan` | A plan of record: sequenced work with owners and gates, kept current | `knowledge/syntheses/` |
| `review` | A retrospective or assessment of something that happened, with verdicts | `knowledge/syntheses/` |
| `note` | Working material for an active workstream | `workstreams/<ws>/` |
| `log` | A running record of what happened, newest on top | `workstreams/<ws>/` |
| `capture` | Raw material from a tool or agent | `raw/` |
| `snapshot` | A point-in-time backup taken before a change | `archive/` |

## The shape of a workstream

Every workstream folder under `workstreams/` has a known front door:

- **`overview.md`** — what is true right now. The first thing any person or agent reads.
- **`log.md`** — what happened, newest entry on top.
- Everything else in the folder is working material.

An agent that reads `overview.md` should be able to start working.

## Written for context windows

Notes in `knowledge/` are briefing cards, never articles. Short, dense, self-contained; one screen is the target. Sovereign's product is the right two thousand tokens for the task at hand, so the curator distills, it does not transcribe. If a note outgrows a screen, split it or tighten it.

## Who writes where

1. **The owner** can edit anything, anywhere. Owner edits always win.
2. **Tools and agents** write only inside their own lane in `raw/`, fed by one-way pipes (rsync or similar). The pipe points one direction, so the rule enforces itself. Never hand-write `raw/` from the agent side.
3. **The curator** is the only thing besides the owner that writes to `knowledge/` and `workstreams/`. It promotes good material out of `raw/`, fills in labels, distills to one screen, and **links instead of copying**.
4. **Anything destructive asks a human first**: bulk deletes, renames, moves, or any change to these rules.
5. **Machine writers to `knowledge/` run on owner-controlled compute.** Any model that judges, drafts, or promotes trusted knowledge runs on inference the owner controls. Cloud models may assist only with material the owner has explicitly released, and never hold the gate.

## The curator's defaults

- **The default answer is no.** Most raw material never promotes. That is the system working.
- **Config is not knowledge.** If a running job reads a file, link to it, never copy it.
- **No web.** The curator works only from the vault and the owner. Research is a producer's job; web findings enter through `raw/` with provenance like everything else.
- **New entities start with the owner.** Before a card for a new entity lands, the curator asks the owner what is missing. The owner is the richest producer the archive has.

## Curation policy

How finely the curator slices a subject (one summary card, or a node per person, product, or program) is set per instance, never by the standard. The standard ships the mechanism; each owner supplies the answers.

- **Default: depth follows engagement.** With no configuration, the curator goes finer where the owner invests more (more raw arriving on a subject, and the owner repeatedly approving fine-grained cards there) and stays coarse elsewhere. A fresh instance curates sensibly from day one, shaped by behavior, not by a hardcoded list.
- **Optional policy, shipped empty.** An owner may override the default by writing a short policy in Part 2: a default depth, a go-deep list, and a never-promote list. The standard names the fields; the owner names the values.
- **The gate decides, the log remembers.** The curator proposes at the chosen depth; the owner keeps, edits, or drops each; every verdict lands in the decisions log. Consistent verdicts are how the policy tightens over time.
- **The curator suggests, the owner decides.** It may note that a subject looks deep and ask, but it never sets policy or changes depth on its own. Policy changes never graduate.

## Validation and trust

The curator drafts proposals into its own lane in `raw/`; a proposal becomes trusted only when it moves into `knowledge/`, and the move is the approval. Every verdict (approved, edited, rejected, and why) goes in an append-only decisions log. The curator runs in one of three gears per kind of action: **ask first**, **act and report** (apply it, list it in the next digest; git makes undo one command), or **routine** (logged only). Everything starts at ask-first. When the log shows a kind of action approved repeatedly without edits, the curator may propose its own promotion to the next gear; only the owner grants it. **A decision that authorizes future agent behavior must be made outside the agent.** That rule, plus a human on anything irreversible and the owner's eyes on anything newly real, is why some things never graduate: new entity cards, anything destructive, anything crossing a doorway to another archive, and changes to these rules.

## Connectors

Any tool or agent that uses the archive is a **connector**, bound by a three-part contract. It is *in the loop* only when all three hold:

1. **Read first.** Before acting on the archive's subject matter, it loads the relevant slice of `knowledge/` — an entry topic, its linked neighbors, and a small always-on core — so it works from current truth, not a stale copy.
2. **Write to its lane.** Its outputs flow one-way into its own `raw/` lane, never straight into `knowledge/` (the write rule above).
3. **Promote through the curator.** Raw becomes knowledge only via the curator and the owner's gate (the trust rule above).

The archive never *controls* a connector. For an autonomous agent the archive only *offers* the read path and the norm to consult it; the agent decides when. A connector keeps its own memory thin — it does not copy the archive's knowledge (it reloads that on demand), though it may keep a log of its own actions.

## How to read the archive

1. Read this `CLAUDE.md`. It is the whole law.
2. Working on a workstream? Read its `overview.md`, then its `log.md`.
3. Need background? Prefer `knowledge/` over `raw/`. Trust flows from the folder.
4. Never bulk-load `raw/` into a context window. It is a loading dock, not a library.

## Search is disposable

The archive's native retrieval is filenames, folders, grep, and links between notes. Any index built on top (vector, full-text, graph) is a client-side convenience: rebuildable from the files, never the truth, never required. If an index disappears, the archive has lost nothing.

## Rollout is forward-only

New notes get labels from day one. `knowledge/` starts empty, so it is clean from the first note. Older notes get labels when next touched. No bulk migration, ever.

# Part 2 — this instance (fill this in)

These change per instance. Replace the placeholders below.

- **Hub:** `<which machine holds the canonical copy>`.
- **Versioning:** `<git remote — keep it owned; the archive should not depend on a cloud git provider you do not control>`.
- **Connectors (live pipes):** `<tool → raw/tools/<tool>/, cadence>` for each tool feeding this instance.
- **Curator:** `<which agent/model curates, and what gear it is in today>`.
- **Naming:** kebab-case for files and folders. No dates in top-level names.
- **Source of truth:** `<where design intent lives, if anywhere, vs. this file which is the operating law>`.
