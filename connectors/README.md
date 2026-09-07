# Connectors: piping your tools into the brain

Every AI tool you use hoards your context somewhere — a documents folder, an application-support directory, a per-project "memory" store. A **connector pipe** is the small, dumb, one-way job that copies the durable layer of that hoard into the brain's loading dock, where the curator can judge it.

The pattern is always the same, and it is deliberately boring:

1. **One-way.** Source → `raw/tools/<lane>/`. Nothing ever flows back. The pipe's direction enforces the who-writes-where rule physically.
2. **One lane per tool** (and per machine, when the same tool runs on several: `raw/tools/<tool>-<machine>/` — two machines writing one lane through file sync causes churn).
3. **Secrets never travel.** Every pipe excludes `.env`, `.secrets`, tokens, logs. If a tool's store mixes credentials with content, pipe only the content subdirectory.
4. **Pipe the distilled layer, not the exhaust.** Most tools keep both raw session transcripts (exhaust) and curated artifacts — project memory files, scheduled outputs, saved documents. Pipe the artifacts. Let your curator decide what becomes knowledge; don't make it wade through chat logs.
5. **Never mirror empty directories.** File-sync layers (Obsidian Sync and friends) delete folders with no syncable files; your pipe recreates them; the two fight forever. Skip empty dirs in the pipe, and keep a small README.md beside any office-format assets (docx/xlsx/csv) that must live in the tree, so sync has something to hold onto.
6. **Every ~15 minutes, forever.** One background job per machine runs every pipe on a tick (a launchd agent on macOS, a systemd user timer on Linux), plus one rsync mover wherever something has to be carried the last step into the vault. Connecting a tenth tool adds a lane, never a job. Set it and stop thinking about it.

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

Each recipe is a ~15-line shell script. No daemons, no dependencies beyond `rsync`, and no schedule file of its own: the shared connector job runs them all.

## How they run

Two shared jobs at most, whatever the tool count, plus one for the rare lane that runs on a wall clock:

- **The runner.** Every connected tool's `mirror.sh` runs inside it on a tick, each lane with its own time bound, its own exit code and its own pair of logs. One tool hanging or failing cannot stop another. It is declared in `connectors.json` and it reports in `runs.json`; `sov status` reads both.
- **The mover.** One rsync job, installed wherever something has to be carried the last step into `raw/tools/`. Two things put it there. A Mac whose vault sits inside a folder the system protects (`~/Documents`, `~/Desktop`, `~/Downloads`): a background job that runs a script cannot write in there and the denial is silent, so mirrors write to a staging tree and the mover carries them in. And a directory pipe declared with `sov relay add`, on either platform, because nothing else would carry it: a launchd agent named `com.sovereign.connector.relay` on a Mac, a systemd user timer named `sovereign-connector-relay` on Linux. rsync takes many sources and one destination, so it stays one job however many folders you pipe. With nothing staged and nothing piped there is no mover, and `sov relay list` says so rather than naming a job that does not exist.
- **A lane whose cadence is a wall-clock time** keeps a job of its own: the Notion pull is the one shipped today, because a full walk takes hours, and neither launchd nor systemd starts a second run while one is in flight, so such a lane inside the tick would starve every other lane. It is still declared in this machine's connector manifest as a non-runner lane, carrying its own job label and its calendar cadence, so `sov connect all` and `sov disconnect all` reach it. The runner reads that declaration and skips it: it never runs it, never counts it as due, and never stamps it.

## Adding a pipe

```bash
sov connect <tool> --apply          # a tool with a harness: both wires, one command
sov relay add ~/Documents/MyTool    # a plain watch folder: one more source on the mover
sov relay list                      # what the mover carries, and where
sov disconnect <tool> --apply       # undeclare a lane; the folder in raw/ stays
```

`sov relay add` refuses a folder whose name collides with a source you already declared, and one that sits inside the destination. Neither is cosmetic: two sources sharing a name merge into one destination directory at exit 0, and a source under the destination loops. To take a pipe away, `sov relay remove <name>` or `sov disconnect <tool>`; `sov disconnect all` walks every lane this machine declares, the wall-clock one included. The lane and everything in it stay, because `raw/` is provenance, not cache.

## The contract

A pipe is a **producer** in the standard's terms: it writes only its own lane, it never touches `knowledge/`, and promotion always goes through the curator and the owner's gate. If a pipe dies, the brain loses freshness, never truth.
