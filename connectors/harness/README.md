# Harness connectors

A tool is *in the loop* when it reads the brain before it works and writes its
distilled output to its own lane. Each folder here packages both wires for one
tool, installed on one machine with one command:

```
sov connect <harness> --host <short-name> --vault <path> --core <slug,slug>        # dry run
sov connect <harness> ... --apply                                                  # install
```

| Harness | Read wire | Write wire | One manual step |
|---|---|---|---|
| `claude-code` | SessionStart hook in `~/.claude/settings.json`, pack injected as `additionalContext` | every project's memory folder, never transcripts | none |
| `codex` | SessionStart hook in `~/.codex/hooks.json`, same shape, trusted at install by `trust.py` (the same config record the `/hooks` screen writes) | `~/.codex/memories` working tree | none |
| `cursor` | `sessionStart` hook in `~/.cursor/hooks.json`, pack returned as `additional_context` | GUI chats exported from SQLite to markdown, CLI transcripts, plans, skills, config | none |
| `cowork` | no hooks; `ensure-instruction.py` writes the read instruction into every space's instructions field, re-applied each mirror run so new spaces are covered | each project space's memory folder | none (restart Claude Desktop once if it was open) |

## Shared parts, in `_lib/`

- `brainhook.py`: the one read-wire implementation. Working directory to topic
  (`workstreams/<name>` or `repos/<name>` under the vault, else the always-on core),
  brain-load, size caps, the receipt line. Adapters only shape the output.
- `install-common.sh`: pointer files, `~/brain-bin` symlinks, hook merge (Claude Code
  and Codex share one JSON shape, Cursor has its own), a launchd job with
  `StandardErrorPath` always set, LANE.md render or patch, smoke runs.
- `mirror-common.sh`: where a lane is written (`$BRAIN_STAGE`, else `~/.vault-staging`
  on TCC-protected Macs, else the vault) and the `MANIFEST.md` heartbeat.

## Rules every connector keeps

- The pack is injected as context and never written anywhere. A stored copy would
  come back through the loading dock as if it were new material.
- Transcripts never cross. Only distilled memory does.
- A hook never fails the session: any error is one stderr line and exit 0.
- Instance data (vault path, core cards, host name, aliases) lives in pointer files
  under `~`, never in this repo.

## Adding a harness

Copy the smallest folder (`codex/`), change the lane prefix and the hook merge
call, write the adapter's output shape in `session-start.py`, and add a case to
`tests/test_connectors_harnesses.py`. If the tool has no hooks, ship an
`INSTRUCTION.md` like `cowork/` and record `read: instruction` in the lane contract.
