# Orca connector

Orca is an orchestrator over coding agents (Claude Code, Codex, Cursor, Droid, Grok). It
keeps its record only in `~/Library/Application Support/Orca/orchestration.db`.

- **Write wire:** `mirror.sh` copies the database with its WAL and renders one markdown
  capture per run (`runs/<date>-<objective>.md`: tasks, decision gates, questions,
  messages) into `raw/tools/orca-<host>/`. Rewritten only when a run changed.
- **Read wire:** none. The agents Orca drives carry their own.
- **Install:** `sov connect orca --host <host> --apply` (or Connect in the console).
- **Never mirrored:** auth and account files, terminal archives, blob storage, caches;
  credential-shaped fields are withheld at export.
