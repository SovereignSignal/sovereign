# Harness connectors

A tool is *in the loop* when it reads the archive before it works and writes its
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
| `parallels` | none: contribute-only guests by owner decision, the vault is never shared into a guest | every running Linux guest's Claude Code memory and Claude Desktop outputs, pulled by the host through `prlctl exec`, one folder per guest; stopped guests skipped, credentials and transcripts never asked for | none |

## Shared parts, in `_lib/`

- `brainhook.py`: the one read-wire implementation. Working directory to topic
  (`workstreams/<name>` or `repos/<name>` under the vault, else the always-on core),
  sov-load, size caps, the receipt line. Adapters only shape the output.
- `install-common.sh`: pointer files, `~/brain-bin` symlinks, hook merge (Claude Code
  and Codex share one JSON shape, Cursor has its own), the lane's entry in the machine's
  connector manifest, LANE.md render or patch, smoke runs of both wires and of the
  shipped path.
- `sov-connectors-run` (in `bin/`): the one job on the machine that runs every harness's
  `mirror.sh`. Lanes run in parallel, each bounded by its own timeout and killed with its
  children if it hangs, so one tool cannot stall another. Each lane keeps its own exit
  code and its own `<lane>.log` / `<lane>.error.log`; the job's own error log carries
  only the runner's faults. A lane that was skipped still records that it was visited,
  which is what makes a lane silently dropped from the loop visible instead of green.
- `mirror-common.sh`: where a lane is written (`$BRAIN_STAGE`, else `~/.vault-staging`
  on TCC-protected Macs, else the vault) and the `MANIFEST.md` heartbeat.

## Rules every connector keeps

- The pack is injected as context and never written anywhere. A stored copy would
  come back through the loading dock as if it were new material.
- Transcripts never cross. Only distilled memory does.
- A hook never fails the session: any error is one stderr line and exit 0.
- Instance data (vault path, core cards, host name, aliases) lives in pointer files
  under `~`, never in this repo.
- Secrets never enter the archive. Every write wire ends in `sov_git_publish`, which first
  runs `sov-redact` over what the mirror wrote: credential-shaped values (vendor keys,
  tokens, private keys, passwords in URLs, a value after `password:`) become
  `[redacted <kind>]` before the bytes are committed, relayed or synced. The rules are
  `lib/brain_redact.py`, shared with the Notion mirror; a lane that renders its own text
  calls `redact_text` before writing. Nothing is decided by a file's or page's name.

## One job, not one per tool

Connecting a tool declares a lane; it does not add a background item. Every tick-cadence
harness rides `com.sovereign.connector.runner` (`sovereign-connector-runner` on Linux).
The second item is the mover, `com.sovereign.connector.relay` (`sovereign-connector-relay`
on Linux, a systemd user timer): one rsync job, many sources, one destination. It is
installed wherever something has to be carried the last step into the vault: on a Mac
whose vault sits behind a protected folder, where mirrors stage because only rsync may
write in there, and on either platform once a directory pipe is declared (`sov relay
add`), because nothing else would carry that pipe. That is the whole list: two items at
most however many tools are connected, and only the runner on a machine that neither
stages nor pipes a folder.

The exception is a lane whose cadence is a wall-clock time and whose run is measured in
hours (`notion/`). It keeps a job of its own, because neither launchd nor systemd starts
a second run while one is in flight, so such a lane inside the tick would starve every
other lane. It still declares itself in the machine's manifest, as a non-runner lane
(`"tick": false`, plus its own job label and its calendar cadence), which is how
`sov connect all` settles and how `sov disconnect all` reaches it; the runner reads that
flag and never runs the lane, counts it as due, or stamps it. The installer refuses to
register any lane whose timeout exceeds the tick.

`sov disconnect <harness>` undeclares a lane, retires its error log, and drops the shared
job when it was the last one, and the mover with it unless directory pipes are left for
it to carry. `sov disconnect all` walks the manifest, so it reaches the calendar lane's own
job too. Neither touches the lane directory: `raw/` is provenance.

## Adding a harness

Copy the smallest folder (`codex/`), change the lane prefix and the hook merge
call, write the adapter's output shape in `session-start.py`, and add a case to
`tests/test_connectors_harnesses.py`. If the tool has no hooks, ship an
`INSTRUCTION.md` like `cowork/` and record `read: instruction` in the lane contract.
