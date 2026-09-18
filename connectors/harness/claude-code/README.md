# Connector: Claude Code

Both wires for Claude Code on one machine, installed with one command:

```
sov connect claude-code --host <short-name> --vault <path> --core <slug,slug> --apply
```

Leave off `--apply` to see what it would do first.

## Read wire: `session-start.py`

A SessionStart hook. Claude Code passes it the session's working directory; it
maps that to a topic (`workstreams/<name>` or `repos/<name>` under the vault,
otherwise the always-on core), runs `sov-load`, and hands the pack back as
`additionalContext`. The session starts knowing the trusted slice. A one-line
receipt lands in the lane's `brain-load-usage.md` so reads can be counted.

It never writes the pack into memory files. The pack reloads every session; a
stored copy would come back through the loading dock as if it were new.

## Write wire: `mirror.sh`

Every 15 minutes by default, mirroring every project's distilled memory
(`~/.claude/projects/*/memory/`) into the lane under `memory/<project>/`. Transcripts
never cross. `memory/MANIFEST.md` is the heartbeat: last run, project count, failures.

It is not a background job of its own. One job on the machine, the connector runner,
runs every connected tool's mirror on a tick; this one gets its own time bound, its own
exit code and its own error log inside it, so a tool that hangs or fails cannot stop the
others. On macOS, if the vault sits behind a protected folder the mirror writes to a
staging tree and one rsync job carries it into the vault (a job that runs a script cannot
write into `~/Documents`, and the denial is silent). Error logs are never optional: a job
that fails silently is worse than one that never ran.

## Instance data, never in the template

`~/.brain-root` (vault path), `~/.brain-core` (always-on slugs), `~/.brain-host`
(short host name used in the lane name), `~/.brain-aliases.json` (spoken names
to card slugs). The installer writes the first three from its flags.

## Uninstall

```
sov disconnect claude-code --apply
```

It undeclares the lane, retires its error log, and removes the shared connector job if
this was the last tool connected on the machine. Remove the hook entry from
`~/.claude/settings.json` yourself. The lane and its history stay in the vault: `raw/` is
provenance, and the owner decides what to do with it.
