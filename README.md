# sovs-brain-template

A dead-simple, owned, plain-text **brain** any person or organization can run, and any AI tool can read and write — under a handful of rules that fit on one page.

The bet: as models commoditize, the edge is **context** — what you know, who you know, what worked last time. This is the durable place to keep it. Not an app, not a SaaS you rent: Markdown files in folders, versioned in git, that outlive any tool or model. Fork it and it is yours.

## What's here

```
CLAUDE.md          the law — the whole standard, ~2 minutes to read
templates/note.md  the new-note template (labels fill themselves in)
bin/new-brain.sh   scaffold a fresh brain into a target folder
bin/brain-check.sh the label-checker — keeps the brain from drifting
skeleton/          the empty five-folder brain that ships into a new brain
```

## The shape, in one breath

Five folders, each with one job: **raw/** (loading dock, where tools drop things), **workstreams/** (the desk), **knowledge/** (the trusted, curated layer), **archive/** (cold storage), and an optional **repos/** (code). Every note opens with two labels — `type` and `source` — plus an auto-filled `created`. One rule for who writes where. That's it. Read `CLAUDE.md` for the full law.

## Quick start (under five minutes)

```bash
# 1. stand up a fresh brain
bin/new-brain.sh ~/my-brain "My Brain"

# 2. open ~/my-brain in Obsidian; point the Templates plugin at .obsidian/templates
# 3. write your first note from the template (labels are pre-filled)
# 4. confirm it's clean
bin/brain-check.sh ~/my-brain
```

## Principles (why it stays simple)

- **Dead simple.** If it needs a manual, it waits. A new person or agent is productive in minutes.
- **Owned by default.** You hold the storage, keys, and history. No vendor sits inside your memory.
- **Plays well with others.** The brain never replaces the systems around it (Notion, Salesforce, whatever). A small connector carries data in; each tool stays authoritative for its own records.
- **Context follows its owner.** A person's brain follows the person; an org's brain stays with the org. Same shape for both, owned separately, connected through explicit doors — never merged.

## The next layer (not required to start)

A **curator** — an agent (a local model works well) that reads the raw loading dock and proposes promotions into the trusted `knowledge/` layer. It starts as a proposer: it drafts, you approve, and it earns more autonomy as its track record proves out. The brain works as plain files long before any agent touches it; the curator just makes it tend itself.

## License

MIT (intended). Fork freely.
