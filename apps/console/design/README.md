# Sovereign interface contract

One application, one source checkout, one installed `Sovereign.app`. Five destinations
share one left rail and one page frame, and each answers one question:

| Destination | Question | Holds |
|---|---|---|
| Today | What needs me? | One headline, the things that need the owner, four figures |
| Review | What do I decide? | The proposal queue beside one proposal |
| Sources | What feeds the archive? | Tools, Devices, and the Map |
| Library | What do I have? | Cards by type, by week, by origin; loose ends |
| Backups | Is it safe? | The archive backup, and the copies and machine images |

Settings sits at the foot of the rail with the open archive. Jobs, Hub setup and
Permissions are reached from Settings; they are the engine room, not destinations.
The compact menu-bar Glance is the only separate frame.

First launch is a page of its own, without the rail: with no archive open, Today offers
Create archive… and Open existing…. A fresh create or open shows one connect step, once
per archive and only while no tool feeds it, listing tools found on this Mac; each row
hands over to Sources › Add, where connecting keeps its preview and confirm.

## Words

The interface was measured at about 4,500 words across twelve screens on 2026-09-30.
These rules are what brought it to about a tenth of that, and they are part of the contract:

- A row is a dot, a name, where it is, at most a two-word state, and an age.
- A sentence about a thing lives in the detail that opens when its row is chosen, once.
- Nothing states its status twice. A green dot is the healthy state; a state word
  appears only when it adds something the dot does not say.
- One noun per thing. A tool or lane that feeds the archive is a source; a machine is a
  device; a note in the trusted layer is a card.
- How long ago status was read, and how long the check took, is evidence. It lives in
  the tooltip on the observed time, never in a line of the page.
- A row's action names where it lands, in one word.

## Appearance and shell

Signal Night is the default: midnight navy, warm amber actions and restrained cyan
context indicators. `NSApp.effectiveAppearance` supplies `data-theme` to both pages
at document start. `SOV_APPEARANCE=light|dark` explicitly overrides the default for
native QA. Loading, alerts and the window ground follow that same appearance.
Light uses paper ground, white panels and graphite ink. Settings offers System, Dark
and Light; the explicit override remains a launch environment setting for QA.

Default window: 900 × 600 pt. Minimum: 720 × 460 pt. Rail width is 170 pt, 140 pt at
narrow sizes. Every page has the same 52 pt header: its title, one line of summary,
its own controls, the time status was observed and Refresh. Content scrolls within its
pane. Archive files remain available in Finder; preparation records open in the default
editor. No conversational suggestion cards anywhere.

`ui/shell.js` and `ui/shell.css` define the shared rail; `ui/app.css` defines the page
frame and the shared marks; `home.css` and `operations-shell.css` define the page layouts. `design/tokens.css` supplies all palette roles. Cyan is for context
indicators only. A chart that shows magnitude alone uses Series 1 and prints its
numbers beside its marks. Categorical series, in order:

| Appearance | Panel | Series 1 | Series 2 | Series 3 |
|---|---|---|---|---|
| Signal Night | #0f1a2a | #c9821c | #4F89D2 | #39A064 |
| Light | #FFFFFF | #A87C12 | #2F6FBF | #2E8B57 |

SF Pro carries sentences; SF Mono carries identifiers and numbers. Existing type,
spacing and motion tokens remain authoritative. Reduced motion disables transitions.
The crown is the product mark. Archive and machine names come from status.

## Status and evidence

`ui/status-model.js` supplies one assessment to Today, Review, Sources and the menu-bar
Glance, so no two places can disagree. Today's headline counts attention items, not
individual proposals; the Review badge counts proposals.

- Explicit `delivery: accepted` establishes hub acceptance; waiting warns.
- Missing or unrecognized delivery is idle. It never enters Today or a verdict solely
  because it is unknown.
- Job failures and unreachable hosts retain their alerts. A separately unreachable
  hub is also an alert, without duplicating its offline fleet-host row.
- Node reachability is a network observation. Hook configuration is setup evidence.
- Existing preparation receipts establish preparation only. Delivery and loading
  stay unconfirmed. Any future consumer acknowledgement requires the exact pack
  hash and full session identity; it cannot establish verified model use.
- Tool receipts require a matching archive and producer lane. Opening another local
  archive shows the mismatch and never implies connection to the fleet.

Today reads the installed status command and bundled local archive API. Its only
command is the app's own update; every other row is a jump. Approvals happen in
Review; connection changes in Sources; schedules in Settings. Stale-response guards
apply across navigation.

## Today and compact Glance

Today answers what needs me. Worst state comes first: failed jobs or unreachable
devices; other attention items. A row's sentence, its cause, the next step and how to
tell it worked open under the row. Work the system is doing by itself appears under
Watching, never in the count. Cadence is per kind, never one global age. Unknown
acceptance is not a failed or late delivery observation. Status failures are the only
banner; a healthy app has none.

The menu-bar Glance retains its compact header, verdict, operational summary rows,
footer, keyboard shortcuts and drawer behavior. It does not show the full-window
rail. Neither frame changes approval, capture or producer write contracts.

## Review

The queue and one proposal sit side by side at every window size. An update opens on
Changes: the current card's blocks against the proposal's, with unchanged runs folded.
Proposed and Current are one tab away. Card text is escaped before any markup is
restored, and only headings, list items, bold and code are restored. J and K move
through the queue. R arms Reject and a second press fires it. Approve takes ⌘↵, because
it puts a card into trusted knowledge.

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
consult the pending-decision guard in both documents. At 120 seconds,
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
`test-release.py --evidence <folder>` captures light and dark Today, Review, the Map
and Sources at both supported sizes, checking themes, the rail's five destinations,
the single frame and attention counts.
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
