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

## Session capture: `sessions.sh`

Off until you turn it on. It reads quiet Claude Code sessions and writes candidate
captures into the lane under `sessions/`, for the curator to judge. The memory mirror
above is unaffected either way. Transcripts are never copied into the archive. Only a
cleaned, redacted excerpt reaches the model you chose for the curator, and only the
captures and `sessions/MANIFEST.md` (last run, this week's counts, and a one-line
Waiting reason when the model cannot be reached) are published.

**What is read.** Your typed prompts, the assistant's text replies and the names of the
tools it called. Everything else in the transcript is dropped: thinking, tool inputs and
results, file snapshots, and anything the harness wrote rather than you, including
`<system-reminder>` spans, which is where the archive's own session-start pack arrives.
Only interactive CLI sessions count. Subagent and sidechain sessions are skipped, as is
any session with fewer than three typed prompts or one touched in the last 45 minutes.
A model-free pre-filter then keeps a session only when it shows signal: one memory phrase
like "remember" or "from now on" is enough; otherwise it needs two points, one per typed
prompt for a decision or a correction phrase and one for a new name with no card yet.
Most sessions stop there, with no model call.

**What is cleaned.** Each prompt and reply is redacted for credentials before it is cut
to length, and a line that still looks like it holds a secret is dropped whole. The
cleaned excerpt is held in memory for the call and never written to disk.

**Where the call runs.** On the archive's own curator provider, through the same
inference guard the curator uses. On a hub it is the hub's local model. A hubless
archive uses the provider you chose in Settings › Curator and needs that provider's key
in the Keychain; a missing key refuses the call. Muse has no fixed API host yet, so
capture stays off while it is the chosen provider. A client Mac of a hub archive stays
off, because the model it would need runs on the hub. In every mode the call ignores proxy
settings, from the environment or the system, and refuses a redirect, so it reaches that
one endpoint or nothing; behind a proxy that is the only way out, capture fails rather
than going through it. On a hub, a tick that finds the curator or the weekly audit using
the model makes no call and says "Waiting: model busy".

**Where it never reads.** A session that ran inside an archive is refused, and no allow
entry overrides that: its transcript carries the archive's own text, and distilling it
would launder knowledge back in through `raw/`. A folder containing an archive is not
refused, so sessions run from your home folder are read. Temporary folders are off
unless you allow them. `--deny <path>` stops anything under a folder.

**Turning it on.** `sov ingest sessions` prints the dry plan, which sessions the next
tick would send and the budget left, with no model call and no write. `--show <id>`
prints the exact excerpt the model would receive for one session. Settings › Session
capture shows the same as Preview and offers Turn on only after a Preview has run.
`sov ingest sessions --on` switches it on from now; `--on --since 30d` also looks back
that far. `--allow` and `--deny` take a path; deny wins. `--apply` runs one tick now,
and `status` shows the switch, the model, the budget and this week's counts.

**Budget.** At most 3 model calls and 60,000 characters per tick, and 30 calls a day,
oldest session first. Each call is one attempt of up to 150 seconds, with no retry inside
the tick. What a tick does not reach waits for the next one. A reply the model rejects
counts against that session, and after three it is left alone. An unreachable model never
counts against a session: the session stays pending and the manifest says "Waiting: model
unreachable". A call that times out is held uncharged until a later call gets an answer;
then the timeout counts against its session, and three timeouts end it. A 401 or 403, or
a refusal by the guard, shows as "model refused this configuration"; a missing key, a
client Mac and anything else have their own fixed phrases, never a host or a path.

**What lands.** Up to three captures per session, each labelled with its session,
project, distiller, kind, confidence and the turns that back it. They arrive untrusted,
like any other lane. The curator always screens session captures for injection and holds
them at ask-first with the reason "session capture: new input class, ask-first until it
earns its own record", whatever gear other work has earned. Nothing reaches `knowledge/`
without your approval.

**Undo.** `sov ingest sessions --off` stops reading at once and leaves captures already
written where they are. A capture still waiting is rejected at the gate like any other
proposal. One you approved is an ordinary card in a git-tracked archive, so you revert
it the way you revert any card.

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
