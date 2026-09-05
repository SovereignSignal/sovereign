# Connectors: piping your tools into the brain

Every AI tool you use hoards your context somewhere — a documents folder, an application-support directory, a per-project "memory" store. A **connector pipe** is the small, dumb, one-way job that copies the durable layer of that hoard into the brain's loading dock, where the curator can judge it.

The pattern is always the same, and it is deliberately boring:

1. **One-way.** Source → `raw/tools/<lane>/`. Nothing ever flows back. The pipe's direction enforces the who-writes-where rule physically.
2. **One lane per tool** (and per machine, when the same tool runs on several: `raw/tools/<tool>-<machine>/` — two machines writing one lane through file sync causes churn).
3. **Secrets never travel.** Every pipe excludes `.env`, `.secrets`, tokens, logs. If a tool's store mixes credentials with content, pipe only the content subdirectory.
4. **Pipe the distilled layer, not the exhaust.** Most tools keep both raw session transcripts (exhaust) and curated artifacts — project memory files, scheduled outputs, saved documents. Pipe the artifacts. Let your curator decide what becomes knowledge; don't make it wade through chat logs.
5. **Never mirror empty directories.** File-sync layers (Obsidian Sync and friends) delete folders with no syncable files; your pipe recreates them; the two fight forever. Skip empty dirs in the pipe, and keep a small README.md beside any office-format assets (docx/xlsx/csv) that must live in the tree, so sync has something to hold onto.
6. **Every ~15 minutes, forever.** launchd on macOS, cron/systemd on Linux. Set it and stop thinking about it.

## Finding your tools' hoards

The single most valuable discovery step: for each tool you work in daily, ask *where does it write?* Common answers:

| Tool | Where the durable layer usually lives |
|---|---|
| Claude Code / Desktop ("Cowork") output folders | the documents folder you configured (e.g. `~/Documents/Claude/`) — scheduled-task outputs, project folders |
| Claude Desktop **project memory** | `~/Library/Application Support/Claude/local-agent-mode-sessions/*/*/spaces/<project>/memory/*.md` — dense, curated, per-project memory files. Often the richest un-piped store on the machine. |
| Codex CLI | its configured output folder (e.g. `~/Documents/Codex/`); automations under `~/.codex/automations/` |
| Anything else | check `~/Library/Application Support/<app>` (macOS), `~/.config/<app>` and `~/.local/share/<app>` (Linux) |

A quick way to find a suspected store: pick one distinctive artifact you know the tool made and run `mdfind -name "<its filename>"` (macOS) or `grep -r` under the app-support directories.

## Shipped recipes

- `cowork-project-memory/` — mirrors every Claude Desktop project's memory store into a machine-scoped lane. This is the recipe that motivated the pattern: project memory files (`feedback_*.md`, `project_*.md`, `reference_*.md`) are pre-distilled knowledge your curator will love.
- `generic-dir/` — mirror any directory into any lane; copy it and set two paths. The Claude/Codex documents-folder pipes are just this recipe with the paths filled in.
- `harness/notion/`: the official-API Notion mirror as a connector. Connect it from the app's Tools view or with `sov connect notion`; one integration token, every connected page and database, daily, in the export's own folder layout. The script is `bin/brain-mirror-notion`.

Each recipe is a ~15-line shell script plus a schedule file. No daemons, no dependencies beyond `rsync`.

## Adding a pipe (macOS)

```bash
cp -r connectors/generic-dir ~/brain-connectors/my-tool
$EDITOR ~/brain-connectors/my-tool/mirror.sh        # set SRC, BRAIN_ROOT, LANE
bash ~/brain-connectors/my-tool/mirror.sh           # test once, inspect the lane
# then install the schedule (see the recipe README; use launchctl bootstrap gui/$UID on modern macOS)
```

On Linux, skip the plist and add a crontab line: `*/15 * * * * bash ~/brain-connectors/my-tool/mirror.sh`

## The contract

A pipe is a **producer** in the standard's terms: it writes only its own lane, it never touches `knowledge/`, and promotion always goes through the curator and the owner's gate. If a pipe dies, the brain loses freshness, never truth.
