# Sovereign

A dead-simple, owned, plain-text **archive** any person or organization can run, and any AI tool can read and write — under a handful of rules that fit on one page.

The bet: as models commoditize, the edge is **context** — what you know, who you know, what worked last time. This is the durable place to keep it. Not an app, not a SaaS you rent: Markdown files in folders, versioned in git, that outlive any tool or model. Fork it and it is yours.

## What's here

```
CLAUDE.md          the law — the whole standard, ~2 minutes to read
templates/note.md  the new-note template (labels fill themselves in)
bin/sov-init   scaffold a fresh instance into a target folder
bin/sov-check the label-checker — keeps the archive from drifting
skeleton/          the empty five-folder archive that ships into a new instance
```

## The shape, in one breath

Five folders, each with one job: **raw/** (loading dock, where tools drop things), **workstreams/** (the desk), **knowledge/** (the trusted, curated layer), **archive/** (cold storage), and an optional **repos/** (code). Every note opens with two labels — `type` and `source` — plus an auto-filled `created`. One rule for who writes where. That's it. Read `CLAUDE.md` for the full law.

## Quick start (under five minutes)

```bash
# 1. stand up a fresh instance
bin/sov-init ~/my-archive "My Archive"

# 2. open ~/my-archive in Obsidian; point the Templates plugin at .obsidian/templates
# 3. write your first note from the template (labels are pre-filled)
# 4. confirm it's clean
bin/sov-check ~/my-archive
```

## Principles (why it stays simple)

- **Dead simple.** If it needs a manual, it waits. A new person or agent is productive in minutes.
- **Owned by default.** You hold the storage, keys, and history. No vendor sits inside your memory.
- **Plays well with others.** The archive never replaces the systems around it (Notion, Salesforce, whatever). A small connector carries data in; each tool stays authoritative for its own records.
- **Context follows its owner.** A person's archive follows the person; an org's archive stays with the org. Same shape for both, owned separately, connected through explicit doors — never merged.

## The next layer (not required to start)

A **curator** — an agent (a local model works well) that reads the raw loading dock and proposes promotions into the trusted `knowledge/` layer. It starts as a proposer: it drafts, you approve, and it earns more autonomy as its track record proves out. The archive works as plain files long before any agent touches it; the curator just makes it tend itself.

## Connect a tool (both wires, one command)

A tool is *in the loop* when it reads the archive before it works and writes its distilled
output to its own lane. `connectors/harness/<name>/` packages both wires per tool, and
`bin/sov` is the front door:

```
sov connect claude-code --host laptop --vault ~/my-archive --core me,how-to-work-with-me   # dry run
sov connect claude-code ... --apply                                                      # install
sov relay add ~/Documents/MyTool   # a plain watch folder: one more source on the mover
sov disconnect claude-code --apply # undeclare the lane; the folder in raw/ stays
sov load <topic>        # the context pack, same thing the session-start hook injects
sov status              # pointers, every lane on this machine, freshness per wire
```

Claude Code is the first harness: a SessionStart hook maps the working directory to a
workstream and injects the pack; its mirror copies every project's memory (never
transcripts) into the lane every 15 minutes. Connecting a tool declares a lane, not a
background item: one job per machine runs every connected tool's mirror on a tick, each
lane bounded and logged on its own. A second job, one rsync mover, appears only where
something has to be carried the last step into the vault: a staging hop on a Mac whose
vault sits behind a protected folder, or a folder piped in with `sov relay add`, on either
platform. A lane whose run is measured in hours, like the Notion pull, keeps a job of its
own on a wall clock. Instance data (vault path, core cards, host name, aliases) lives in
pointer files under `~`, never in this repo. Tests:
`python3 -m unittest tests.test_connector_claude_code`.

## Local Hub package

The macOS app includes Hub preparation, guarded job activation and encrypted recovery.
Open Settings → Jobs → Hub setup…, or use `sov hub` from the bundled command.
Preparation leaves jobs inactive; every mutation has a preview. See the [setup and recovery guide](docs/hub-setup.md)
for requirements, the recovery drill and the limits of this clean-install pilot.

## Archive evidence (optional)

`bin/sov-evidence` is a separate, opt-in helper for exact trusted-card evidence and report-only freshness checks. It does not change `sov-load` or write to the archive.

The helper requires an opaque sidecar and a private output directory outside the archive:

```bash
sov-evidence \
  --root "$BRAIN_ROOT" \
  --project-root "$BRAIN_EVIDENCE_STATE" \
  --overlay "$BRAIN_EVIDENCE_STATE/enrollment.json" \
  --ref opaque-reference \
  --output "$BRAIN_EVIDENCE_STATE/runs/new-evidence.json"
```

Use `--audit-overlay` in place of `--ref` for a report-only aggregate freshness receipt. Detailed output can contain trusted text and identifiers, so keep the state directory private. Standard output contains only a sanitized receipt. Missing temporal fields remain findings; the helper never invents or backfills dates.

## Picking a judge (optional)

`bin/sov-judge-bakeoff` scores candidate judge models against the **real** `curator-run` judging path, so a judge is chosen on calibration rather than on benchmarks. Benchmark strength does not predict judge calibration: a strong model can promote everything (useless, since the curator's whole value is default-NO) or promote nothing (equally useless). Both failure modes have been observed on models that benchmark well.

```bash
bin/sov-judge-bakeoff qwen3.8:27b qwen3.6:35b --runs 3 --json bakeoff.json
```

It builds a throwaway vault in a temp dir, seeds it with the bundled synthetic corpus in `connectors/bakeoff-corpus/` (entirely fictional, so the harness is publishable), runs the real curator against it, and prints a scorecard: accuracy, false-promote rate (the dangerous one), false-skip rate, update detection, containment of adversarial documents, and median and p90 latency. Model calls are timed through a loopback proxy, so nothing in `curator-run` is patched to measure it.

It refuses to run if the vault it resolved is inside a real one, caps the act-and-report gears at zero, and writes nothing outside the temp dir and an explicit `--json` path. `--endpoint`, `--keyfile`, and `--key-env` point it at a remote OpenAI-compatible endpoint; the default is local. Add cases by dropping a document and a matching `expected.json` into the corpus, and run `--self-test` to check the scoring logic with no network.

## License

MIT (intended). Fork freely.

## Command and configuration compatibility

The product is Sovereign. Your copy is an instance, its plain-text folder is the archive, and the machine that curates is the hub.

Use `sov` for the front door or `sov-*` for individual commands. Every former `brain-*` command remains a symlink to its `sov-*` replacement. The two exceptions in spelling are `brain-check.sh` → `sov-check` and `brain-hub` → `sov-managed-hub`; `sov-hub` continues to carry the template runner. `new-brain.sh` points to `sov-init`, also available as `sov init`.

Configuration resolves in this order: existing `BRAIN_*` variables (`SOVS_VAULT` also sets the root), existing `~/.brain-*` pointer files, then `SOVEREIGN_ROOT`, `SOVEREIGN_LANE`, `SOVEREIGN_CORE`, and `SOVEREIGN_HOST`. `SOVEREIGN_VAULT` is also accepted for the root. Existing settings win when both generations are present. `SOVEREIGN_STAGE` and `SOVEREIGN_HOOK_MAX_CARDS` / `SOVEREIGN_HOOK_MAX_CHARS` have equivalent legacy-first fallbacks.

The curator's model-facing prompt wording is preserved from the evaluated pipeline. Its remaining legacy terminology will be renamed only after a separate curator evaluation; this release does not change the model or its granted permissions.

For an approved source publication destination, the hub owner can set `kit.template_publications` in `hub.json` to a list of template remote names or URLs. The nightly kit publishes only `main`, `docs/lane-source-map`, and tags, atomically without force or deletion, and records each destination's result. Both branches must exist in the hub's template checkout. `sov hub kit` previews the exact destination and ref set; `--apply` executes it. This list is empty by default. Keep complete recovery mirrors in `offsite.template`; never add the archive repository or its data to a source publication destination.

This release keeps the checkout folders, `~/brain-bin`, existing remote paths, Python module imports, and stored receipt filenames compatible. It does not migrate producer configuration. Folder and remote-path moves belong to the separate recovery drill.
