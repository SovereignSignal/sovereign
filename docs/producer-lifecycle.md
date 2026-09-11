# Producer lifecycle

Operations → Lanes lists supported producers above their saved lane history. Add producer opens the chosen connector. Each producer has a Remove producer action with a dry-run preview and a separate apply button. Removed producers can be added again.

This manages the existing connector catalog: Claude Code, Codex, Cowork, Cursor, Hermes, Windsurf, Orca and Notion. Desktop connectors run on this Mac. Notion uses the existing cloud installer on the configured Hub. Historical lanes owned by another machine identify that owner; local controls do not revoke remote intake access or delete lane history.

Removal undeclares collection, stops the producer's own job if present, and retains shared jobs needed by other producers or directory pipes. For local context integrations it removes only Sovereign's exact registered hook or managed instruction, preserving owner hooks, instructions and trust. Codex trust records follow surviving handler indices. Edited or malformed managed configuration fails before scheduler changes. Configuration originals are backed up beside each changed file.

An in-flight shared collector blocks removal with a retry message. The runner reloads its manifest after acquiring its lock so an earlier snapshot cannot restart a removed producer. Removed hook integrations reject future context preparation, including commands cached by an open tool. Existing sessions can retain already loaded context until the tool restarts.

Captured raw history, original tool data, shared archive pointers, credentials and unrelated integrations stay in place. Retirement metadata is local connector state. A failed cleanup is reported as incomplete and can be retried. Reconnecting clears retirement when the connector is registered again.

The native bridge verifies the selected archive, current service pointer and supported connector before execution. Apply requires a successful preview for the same archive, producer and action. Only the fixture QA build environment can substitute its command runner.

Validation:

- `tests/test_producer_removal.py`: exact cleanup across the catalog, owner configuration preservation, malformed and linked configuration refusal, dry runs, in-flight refusal, historical captures, reconnect and cloud routing.
- `tests/test_connectors_install.py` and `tests/test_connectors_runner.py`: shared scheduler and collector regression checks.
- `apps/console/test-producers.py`: real native bridge with a disposable archive, fake commands and isolated preferences; preview/apply, rejection, cancel, failure, reconnect and narrow layout.
- `apps/console/tests/producer-lifecycle.cjs`: preserved history without active routes or stale producer alarms.
