<img src="apps/console/design/icon/AppIcon-1024.png" width="88" alt="Sovereign app icon">

# Sovereign

**Your context, in plain text you own, read by every AI tool you use.**

**Status: closed beta.** The current app is Sovereign 0.7.1 (build 50), built from this repo and in daily use by its maintainer. A signed, notarized download is on the [releases page](https://github.com/SovereignSignal/sovereign/releases), validated on clean installs of macOS 13.6 and the current macOS. Apple Silicon Mac, macOS 13 or later.

Every AI tool you use starts each session knowing nothing about you. You re-explain your projects, your people, the decisions you already made. Sovereign keeps that context in one place you own: a folder of Markdown files on your Mac, versioned with git, that your tools read before they work and add to as they go. You approve what becomes trusted. Switch models or tools and your context comes with you.

It's deliberately simple. The whole standard fits on one page ([`CLAUDE.md`](CLAUDE.md)), the archive is ordinary files you can open in any editor, and nothing about it depends on this app, this repo, or any one AI company staying around. Where Sovereign goes next: [`ROADMAP.md`](ROADMAP.md).

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
- **The curator** reads what arrived in the background and drafts one-screen briefing cards. At first it asks before any of it becomes trusted; routine cards can graduate to landing on their own once its judgments earn it. Its default answer is no: most raw material never becomes a card, and that's the system working.

## Get started on a Mac (about five minutes)

You need an Apple Silicon Mac on macOS 13 or later, [Claude Code](https://claude.com/claude-code), and an API key for the curator (Anthropic by default; OpenAI, Google Gemini, xAI Grok, and Muse are also supported).

1. **Install Sovereign.** Download `Sovereign-0.7.1-build50.zip` from the [v0.7.1 release](https://github.com/SovereignSignal/sovereign/releases/tag/v0.7.1), unzip it, and move `Sovereign.app` to Applications. Prefer source? [Build the app yourself](#build-the-app-from-source).
2. **Create an archive.** Open Sovereign and choose **Create archive…**. Pick where it lives; `~/Sovereign` is a good default.
3. **Connect Claude Code.** On the screen that follows, choose **Connect…** next to Claude Code, check the preview, then install. Claude Code will now read your archive at the start of every session.
4. **Turn on the curator.** In **Settings › Curator**, pick your provider, paste your API key, and choose **Turn on**. The key is stored in your login Keychain, never in a plain file. Every two hours the curator sends newly saved material to that provider, under your account, and drafts cards. At first nothing it drafts becomes trusted until you approve it (see [Approval fades as trust is earned](#approval-fades-as-trust-is-earned)).
5. **Save something worth remembering.** In Claude Code, tell it something durable, such as *"Remember: I'm building a garden planner for small urban plots, and it has to work offline."* Then choose **Curate now** in Settings › Curator.
6. **Approve your first card.** Open **Review**, read the drafted card, and approve it.
7. **See it used.** Start a new Claude Code session. It opens already knowing what you approved, and **Today** ticks off its **First steps**.

## What leaves your Mac

Out of the box, nothing. Sovereign has no account, no telemetry and no server. The only outbound traffic is what you turn on:

- **The hosted curator** sends newly saved material to the one provider you chose (Anthropic, OpenAI, Google Gemini, xAI Grok, or Muse), under your own key and at that provider's own API host only. Each pass costs cents, and the key can carry a spend limit you set with the provider.
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

### Any MCP client, read-only

`sov mcp` serves your trusted cards to any tool that speaks MCP. It has four tools, all read-only: `load_context` (the same slice `sov load` gives a session), `read_card`, `search_cards` and `list_cards`. Every card arrives with its path and content hash, so the tool can cite exactly what it read. It reads only `knowledge/`, never follows a symlink out of the archive, and redacts anything shaped like a secret on the way out. It has no write path at all: new material still enters through a tool's own lane and the curator. In Claude Code:

```bash
claude mcp add sovereign -- ~/brain-bin/sov mcp
```

Other clients take the same command in their MCP settings (`"command": "<path to sov>", "args": ["mcp"]`). With only the app installed, the path is `/Applications/Sovereign.app/Contents/MacOS/sov`, or under `~/Applications` if that's where you put it. A client set to contribute-only gets nothing back.

### Other tools

Claude Code is the one fully supported tool. The repo also ships best-effort connectors for Codex, Cursor, Claude Desktop, Windsurf, Hermes, Muse Code and a Notion mirror, plus a plain watch folder (`sov relay add <path>`) for anything else. Best-effort connectors can break when their tools change. A broken one only stops new captures: everything already in the archive stays, and `sov status` shows how fresh each lane is. One background job per Mac runs every connected tool's save on a schedule; when the app installs it, macOS lists it under Login Items as Sovereign.

## Curating

### With Claude (no extra setup)

The app's **Settings › Curator** is the whole setup. From the command line, with the app installed: `sov curator key` (reads the key from stdin), `sov curator enable --apply`, `sov curator run`, `sov curator status`. This path starts in ask-first: every card waits for you in Review until you grant it more room.

The curator's default answer is no: most of what tools save never becomes a card. In a new archive it starts with a short owner profile (`raw/workspaces/curator/profile.md`) telling it that your own notes about your projects, goals, decisions and preferences are worth keeping. Rewrite it to say who you are and what matters to you; the curator reads it with every judgment.

### Approval fades as trust is earned

Reviewing every card forever would turn memory into inbox zero, so approval is a starting gear, not the steady state. Everything begins in **ask-first**. Once the curator's judgments run clean for a while, you can move routine work to **act-and-report**: it lands on its own in the background, gets listed in the next digest with a per-card revert, and git keeps the undo. Flagged items, new entities, slug collisions, and anything destructive always ask first, whatever the gear.

On the Claude path above, the grant is one command once you are ready:

```bash
sov curator trust            # preview what changes
sov curator trust --apply    # concepts and syntheses at high and medium confidence land on their own, at most 12 per pass
sov curator trust --off --apply   # back to ask-first, any time
```

The grant lives in `gears.json` in the curator lane, and a change to the judging pipeline that earned it (a new model, prompt, or threshold) is the moment to re-earn it. The rulebook's *Validation and trust* section in [`CLAUDE.md`](CLAUDE.md) is the full model.

### Curating with a local model

For a fully local setup, the app can prepare a **Hub** that curates on a model you run yourself (for example through Ollama). Open **Settings › Jobs › Hub setup…**; every step shows a preview first. See the [Hub setup and recovery guide](docs/hub-setup.md). A prepared Hub starts in ask-first with automatic landing off in this build; a hub you run from this repo can use the same gears with its own per-run cap.

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

## Support and security

Start with [SUPPORT.md](SUPPORT.md), which explains the in-app Checks to read
before filing a report. Release notes live in [CHANGELOG.md](CHANGELOG.md).
Report vulnerabilities privately under [SECURITY.md](SECURITY.md), never in a
public issue and never with archive contents or credentials attached.

## License

[MIT](LICENSE). Fork it and make it yours.
