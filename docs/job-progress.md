# Job progress

The hub runner records progress for `nightly`, `curate` and `weekly-audit` in
`hub/<job>.progress.json` under its state directory. `sov hub jobs status` and
the app's Operations job details show these observations alongside the last
completed run.

The observation reports the current phase, the item being processed within that
phase, when progress last advanced, and the worker named in the model lock when
waiting. Counts describe the current item, not completed judgments or model
tokens. No source names, document content, prompts or verdicts enter this record.

Each run has a unique identifier and records its runner process's start time.
A status read verifies that process identity before treating the observation as
active. An exited worker, a reused process ID or an outdated status response
cannot establish current activity. A running job does not clear an earlier
failure; only the existing completion receipts establish its outcome.

Updates are atomic and best-effort. Missing or unwritable progress files never
fail the job. Lock polling refreshes the observation without advancing the last
progress timestamp. A single model request may therefore spend several minutes
in one phase. This adds no timeout, model request, schedule or retry behavior.

Jobs already running when the source is updated have no progress record until
their next normal invocation. Standalone worker commands do not opt in unless
the hub runner supplies the run identifier.
