# Connector: Claude Code

Both wires for Claude Code on one machine, installed with one command:

```
sov connect claude-code --host <short-name> --vault <path> --core <slug,slug> --apply
```

Leave off `--apply` to see what it would do first.

## Read wire: `session-start.py`

A SessionStart hook. Claude Code passes it the session's working directory; it
maps that to a topic (`workstreams/<name>` or `repos/<name>` under the vault,
otherwise the always-on core), runs `brain-load`, and hands the pack back as
`additionalContext`. The session starts knowing the trusted slice. A one-line
receipt lands in the lane's `brain-load-usage.md` so reads can be counted.

It never writes the pack into memory files. The pack reloads every session; a
stored copy would come back through the loading dock as if it were new.

## Write wire: `mirror.sh`

A launchd job, every 15 minutes by default, mirroring every project's distilled
memory (`~/.claude/projects/*/memory/`) into the lane under `memory/<project>/`.
Transcripts never cross. `memory/MANIFEST.md` is the heartbeat: last run, project
count, failures. On macOS, if `~/.vault-staging` exists the mirror writes there and
a relay job whose program is rsync carries it into the vault (a bash job cannot
write into `~/Documents` without Full Disk Access). `StandardErrorPath` is always
set: a job that fails silently is worse than one that never ran.

## Instance data, never in the template

`~/.brain-root` (vault path), `~/.brain-core` (always-on slugs), `~/.brain-host`
(short host name used in the lane name), `~/.brain-aliases.json` (spoken names
to card slugs). The installer writes the first three from its flags.

## Uninstall

Remove the hook entry from `~/.claude/settings.json`, `launchctl bootout
gui/$UID/com.sovereign.connector.claude-code`, delete the plist. The lane and its
history stay in the vault; the owner decides what to do with them.
