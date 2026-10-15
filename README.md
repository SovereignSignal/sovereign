# Sovereign

**Your context, in plain text you own, read by every AI tool you use.**

Every AI tool you use starts each session knowing nothing about you. You re-explain your projects, your people, the decisions you already made. Sovereign keeps that context in one place you own: a folder of Markdown files on your Mac, versioned with git, that your tools read before they work and add to as they go. You approve what becomes trusted. Switch models or tools and your context comes with you.

It's deliberately simple. The whole standard fits on one page ([`CLAUDE.md`](CLAUDE.md)), the archive is ordinary files you can open in any editor, and nothing about it depends on this app, this repo, or any one AI company staying around.

## How it works

```
  your tools ──save──▶  raw/          loading dock: what tools and agents drop off
                          │
                       curator        drafts short cards from what arrived
                          │
                        you           approve, edit or reject each card
                          ▼
  your tools ◀──read──  knowledge/    the trusted layer, loaded into each new session
```

- **The archive** is five folders with one job each: `raw/` (the loading dock), `knowledge/` (the trusted cards), `workstreams/` (your active work), `archive/` (cold storage) and an optional `repos/` for code.
- **Connectors** tie a tool to the archive both ways. Claude Code reads the relevant cards when a session starts and saves its memory into its own lane in `raw/`.
- **The curator** reads what arrived, drafts one-screen briefing cards, and asks you before any of it becomes trusted. Its default answer is no: most raw material never becomes a card, and that's the system working.

## Get started on a Mac (about five minutes)

You need an Apple Silicon Mac on macOS 13 or later, [Claude Code](https://claude.com/claude-code), and an [Anthropic API key](https://console.anthropic.com/) for the curator.

1. **Install Sovereign.** A signed, notarized download is on its way. Until it's published, [build the app from source](#build-the-app-from-source), which takes a few minutes more.
2. **Create an archive.** Open Sovereign and choose **Create archive…**. Pick where it lives; `~/Sovereign` is a good default.
3. **Connect Claude Code.** On the screen that follows, choose **Connect…** next to Claude Code, check the preview, then install. Claude Code will now read your archive at the start of every session.
4. **Turn on the curator.** In **Settings › Curator**, paste your Anthropic API key and choose **Turn on**. The key is stored in your login Keychain, never in a plain file. Every two hours the curator sends newly saved material to Anthropic, under your account, and drafts cards. Nothing it drafts becomes trusted until you approve it.
5. **Save something worth remembering.** In Claude Code, tell it something durable, such as *"Remember: I'm building a garden planner for small urban plots, and it has to work offline."* Then choose **Curate now** in Settings › Curator.
6. **Approve your first card.** Open **Review**, read the drafted card, and approve it.
7. **See it used.** Start a new Claude Code session. It opens already knowing what you approved, and **Today** ticks off its **First steps**.

## What leaves your Mac

Out of the box, nothing. Sovereign has no account, no telemetry and no server. The only outbound traffic is what you turn on:

- **The hosted curator** sends newly saved material to Anthropic under your own key. Each pass costs cents, and the key can carry a spend limit you set in the Anthropic console.
- **Optional connectors**, such as a Notion mirror, talk to the service they mirror.

If you want nothing to leave at all, run the curator on a local model instead (see [Curating with a local model](#curating-with-a-local-model)). An archive can declare itself local-only, and the curator then refuses any hosted model.

## Use it without the app

The archive is just folders, so you can start with the command line and an editor like [Obsidian](https://obsidian.md):

```bash
git clone https://github.com/SovereignSignal/sovereign.git && cd sovereign
bin/sov-init ~/my-archive "My Archive"     # scaffold a fresh archive
# open ~/my-archive in Obsidian and point its Templates plugin at .obsidian/templates
bin/sov-check ~/my-archive                 # confirm every note carries its labels
```

Every note starts with two labels, `type` and `source`, plus an auto-filled `created` date. [`CLAUDE.md`](CLAUDE.md) is the whole rulebook, about two minutes to read.

## Connect a tool

`bin/sov` is the front door. Connecting a tool installs both wires: the read at session start and the write into its own lane.

```bash
bin/sov connect claude-code --vault ~/my-archive          # preview what it will change
bin/sov connect claude-code --vault ~/my-archive --apply  # install
bin/sov load <topic>      # the context pack a session receives
bin/sov status            # what's connected, and how fresh each lane is
bin/sov disconnect claude-code --apply   # undo; the lane's files in raw/ stay as history
```

Claude Code is the first fully supported tool. The repo also ships connectors for Codex, Cursor, Claude Desktop, Windsurf, Hermes and a Notion mirror, plus a plain watch folder (`sov relay add <path>`) for anything else. One background job per Mac runs every connected tool's save on a schedule; when the app installs it, macOS lists it under Login Items as Sovereign.

## Curating

### With Claude (no extra setup)

The app's **Settings › Curator** is the whole setup. From the command line, with the app installed: `sov curator key` (reads the key from stdin), `sov curator enable --apply`, `sov curator run`, `sov curator status`. The curator never approves anything by itself on this path: every card waits for you in Review.

The curator's default answer is no: most of what tools save never becomes a card. In a new archive it starts with a short owner profile (`raw/workspaces/curator/profile.md`) telling it that your own notes about your projects, goals, decisions and preferences are worth keeping. Rewrite it to say who you are and what matters to you; the curator reads it with every judgment.

### Curating with a local model

For a fully local setup, the app can prepare a **Hub** that curates on a model you run yourself (for example through Ollama). Open **Settings › Jobs › Hub setup…**; every step shows a preview first. See the [Hub setup and recovery guide](docs/hub-setup.md). Every card it drafts waits in Review for you; a prepared Hub keeps automatic approval off.

`bin/sov-judge-bakeoff` helps you pick a local model on calibration rather than benchmarks. It runs the real curator against a bundled, entirely fictional corpus and scores false promotions, missed knowledge and resistance to adversarial documents:

```bash
bin/sov-judge-bakeoff <model-a> <model-b> --runs 3 --json bakeoff.json
```

## Build the app from source

You need an Apple Silicon Mac with Apple's command-line developer tools (`xcode-select --install`). Nothing else: the build downloads its own Python and checks it against a pinned hash.

```bash
git clone https://github.com/SovereignSignal/sovereign.git && cd sovereign
python3 apps/console/fetch-runtime.py            # downloads the pinned runtime and checks its hash
SOV_PYTHON_RUNTIME="$PWD/apps/console/build/runtime/python" bash apps/console/build.sh
mkdir -p ~/Applications && mv apps/console/build/Sovereign.app ~/Applications/
open ~/Applications/Sovereign.app
```

The build signs the app with a local signature, so it runs on the Mac that built it. More detail is in [`apps/console/DISTRIBUTION.md`](apps/console/DISTRIBUTION.md).

## Principles

- **Simple enough to explain in a minute.** If something needs a manual, it waits.
- **Yours by default.** You hold the files, the history and the keys. No vendor sits inside your memory.
- **Works alongside what you already use.** Notion, your CRM and your docs stay authoritative for their own records; a small connector carries what matters in.
- **Context follows its owner.** A person's archive goes with the person, an organization's stays with the organization, and the two connect only through doors you open.

## For maintainers

- **Tests:** `export PYTHONPATH=$PWD/lib; python3 -m unittest discover -s tests`, plus the app's suites (see [`docs/release-checks.md`](docs/release-checks.md)).
- **Distribution:** `apps/console/build.sh` signs with a Developer ID when one is present; `apps/console/notarize.sh` submits to Apple, staples the ticket and checks it with Gatekeeper.
- **Archive evidence:** `bin/sov-evidence` is an opt-in helper for exact trusted-card evidence and report-only freshness checks. It never writes to the archive.
- **Compatibility:** every former `brain-*` command is a symlink to its `sov-*` replacement, and configuration resolves `BRAIN_*` variables and `~/.brain-*` pointer files before the newer `SOVEREIGN_*` names. Existing settings win when both are present.
- **Publishing:** a hub can publish this repo's `main` and `docs/lane-source-map` branches through `kit.template_publications` in its `hub.json`. Never add an archive repository or its data to a publication destination.

## License

[MIT](LICENSE). Fork it and make it yours.
