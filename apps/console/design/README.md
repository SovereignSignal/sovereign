# Sovereign interface contract

One application, one source checkout, one installed `Sovereign.app`. Home, System, Review and
Operations share the same left navigation rail and native window.
Operations keeps its internal Hosts, Archive, Lanes, Tools, Hub and Backups tabs.
The compact menu-bar Glance is the only separate frame.

## Appearance and shell

Signal Night is the default: midnight navy, warm amber actions and restrained cyan
context indicators. `NSApp.effectiveAppearance` supplies `data-theme` to both pages
at document start. `SOV_APPEARANCE=light|dark` explicitly overrides the default for
native QA. Loading, alerts and the window ground follow that same appearance.
Light uses paper ground, white panels and graphite ink. There is no appearance
picker in this release; the explicit override is a launch environment setting.

Default window: 900 × 600 pt. Minimum: 720 × 460 pt. Rail width is 170 pt, 140 pt at
narrow sizes. Content scrolls within its pane. Nodes stay visible on Home with an
expansion control. Selecting a tool filters its context receipts. Review contains
attention items and contributions. Archive files remain available in Finder; preparation records open in the default editor.
No conversational suggestion cards on Home.

`ui/shell.css` defines the shared rail; `home.css` and `operations-shell.css` define
the page layouts. `design/tokens.css` supplies all palette roles. Cyan is for context
indicators only. Categorical series, in order:

| Appearance | Panel | Series 1 | Series 2 | Series 3 |
|---|---|---|---|---|
| Signal Night | #0f1a2a | #c9821c | #4F89D2 | #39A064 |
| Light | #FFFFFF | #A87C12 | #2F6FBF | #2E8B57 |

SF Pro carries sentences; SF Mono carries identifiers and numbers. Existing type,
spacing and motion tokens remain authoritative. Reduced motion disables transitions.
The crown is the product mark. Archive and machine names come from status.

## Status and evidence

`ui/status-model.js` supplies one assessment to Home, Review, full-window Operations
and menu-bar Glance. The Review count equals the grouped Needs you count for the
same status payload. Counts represent attention items, not individual proposals.

- Explicit `delivery: accepted` establishes hub acceptance; waiting warns.
- Missing or unrecognized delivery is idle: “acceptance not reported by this status
  version”. It never enters Needs you or a verdict solely because it is unknown.
- Job failures and unreachable hosts retain their alerts. A separately unreachable
  hub is also an alert, without duplicating its offline fleet-host row.
- Node reachability is a network observation. Hook configuration is setup evidence.
- Existing preparation receipts establish preparation only. Delivery and loading
  stay unconfirmed. Any future consumer acknowledgement requires the exact pack
  hash and full session identity; it cannot establish verified model use.
- Tool receipts require a matching archive and producer lane. Opening another local
  archive shows the mismatch and never implies connection to the fleet.

Home reads the installed status command and bundled local archive API. Approvals,
connection changes and schedules require an explicit action in Operations. Draft
protection and stale-response guards apply across navigation.

## Operations and compact Glance

The resting Operations view answers what needs me, what is fresh, what is stale.
Its three columns retain grouped rows and drill-downs. Worst state comes first in
the verdict: failed jobs or unreachable hosts; other attention items; overdue
observations; otherwise a fresh fact. Cadence is per kind, never one global age.
Unknown acceptance is not a failed or late delivery observation.

The menu-bar Glance retains its compact header, verdict, operational summary rows,
footer, keyboard shortcuts and drawer behavior. It does not show the full-window
rail. Neither frame changes approval, capture or producer write contracts.

## Approval decisions

Selecting a proposal reads its current contents and matching trusted cards from the
approval machine. Approve stays disabled until that check succeeds. Cross-type
collisions and undeclared replacements show a comparison and a copyable resolution
request. Resolving or retiring trusted cards still requires an owner decision.

A decision carries a fingerprint of the reviewed proposal, existing cards and
review metadata. The bundled helper checks it again before invoking the existing
owner gate. It never force-approves. An archive-scoped lock prevents overlapping
console decisions; legacy command-line writers do not participate in that lock.
Their existing curator guards remain authoritative.

Results appear inline with the card name. Success requires the proposal to have
moved and the destination to match the reviewed content. Commit or push trouble
is reported separately as a saved decision with sync needing attention. Lost
connections and timeouts remain unconfirmed until the queue is checked again.
Repeat clicks are blocked during execution. Navigation and native normal quit
consult the pending-decision guard in both Home and Operations. At 120 seconds,
the interface releases that guard and reports an unconfirmed result; it does not
claim cancellation. Late replies cannot overwrite this result. The native bridge
keeps blocking new gate actions while its command is still running, and the
archive lock remains authoritative across console processes.

Status refreshes preserve checks when only proposal age changes. Changed proposal
fields, archive or hub routing invalidate the check. This cache is advisory:
every decision still rechecks the complete content fingerprint on the approval
machine, and Check again explicitly refreshes a selected card.

Repeated rejections may create a stamped destination. Confirmation requires a new
matching destination, the reviewed bytes and removal of the proposal. Older
matching files do not prove the current decision succeeded.
Technical details are collapsed and use the existing bounded redaction path.

## Verification and diagnostics

`tests/test_gate_check.py` covers checks, content changes, lock ownership, command
timeouts and real curator approve/reject/push-failure paths in disposable Git
archives. `tests/gate-model.cjs` checks action eligibility and result wording.
`test-gate.py --evidence <folder>` runs native approval, conflict, rejection and
failure scenarios, including repeat clicks, real native quit dispatch during a
decision and after completion, status refresh behavior, and timeout recovery with
late replies. Timeout QA accelerates the scheduled 120-second browser timer while
keeping the real helper running. Its fixture HOME
override is accepted only during snapshot QA.

`test-home.py` exercises native rendering, labels, safe text, draft preservation,
stale replies and a capture/read roundtrip in a disposable archive.
`tests/status-model.cjs` covers unknown/waiting/accepted lanes and real failures.
`test-release.py --evidence <folder>` captures light and dark Home, Review, System
and Operations at both supported sizes, checking themes, rails and attention counts.
Use `--live` for a screenshot against the installed status command.

Snapshot anchors accept `view:<name>[+open:<id>]` on the current page and
`operations:view:<name>[+open:<id>]` across pages. The latter waits for navigation,
status and the target view before capturing. `SOV_QA_STATUS_COMMAND` is available
only during snapshot runs for isolated fixtures and failure tests.

Status failures keep a generic visible sentence. The `detail` field and local log
contain up to the last 400 UTF-8 bytes after credential redaction. Redaction runs
before truncation; failed redaction never returns raw stderr. Recognized credential
patterns and labelled passwords are removed; arbitrary prose remains diagnostic
content, so do not publish logs without inspecting them.

This corrective release requires Fable's diff and evidence review before install.
Fresh-device distribution and consumer acknowledgement are later acceptance gates.
