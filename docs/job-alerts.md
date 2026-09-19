# Hub job alerts

A completed run and a current problem are separate observations. Home, Operations and the compact menu share the same assessment.

- **Needs attention:** a failed run has an unresolved cause, verification is overdue, or the current recovery check is unavailable. Show the cause, a next step and the recorded output.
- **Awaiting verification:** a bounded check demonstrates the previous blocker has cleared and the expected follow-up is still pending. Keep this separate from attention and from successful completion. Keep the failed receipt available.
- **Succeeded:** a newer completed run returned success. Existing cadence checks still apply.
- **Unknown:** there is no usable completed receipt. Never infer success from a new release or an empty error log.

The first supported recovery check is the backup credential scanner. It rechecks the complete, bounded set of previously rejected files with the installed scanner. It does not stage, redact, commit or push. Paths must remain inside the archive; incomplete output, unsafe or unreadable paths, a failed check, or an unavailable matching scheduler keep the item actionable. The scanner also rejects read errors at the backup commit gate. The verification deadline is the next scheduled run after the failure, with a 15-minute completion allowance. Refreshing never extends that deadline. Other failure types remain actionable until a successful run or a dedicated verifier is implemented.

**Run backup now** previews the configured archive, hub, destination names and operation, then asks for confirmation. Confirmation is bound to the configuration, actual loaded job and calendar, effective Git push URLs, completed receipt and backup/scanner source. Loaded arguments and environment must match the saved manifest; unrecognized scheduler output prevents retry. A changed target or job requires another preview. Destination labels omit URL credentials. The request uses the scheduler without interrupting a running job. The normal credential redaction, commit and configured remote pushes remain in force. Acceptance of the request is reported separately from successful completion. A failed push remains a failure even when there are no new files to commit.

Recovery checks require an updated status service on the hub. Older services retain their visible failed state. The packaged action reports an unavailable preview if the hub lacks the retry command; it never falls back to a shell command from the UI or starts unrelated jobs.
