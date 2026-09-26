# Downloadable app preview

Sovereign starts with one local archive. The Apple Silicon preview can create or open an archive, inspect system status, and review proposed knowledge. It bundles Python. Creating or opening a local archive needs no account, terminal setup, Git, Homebrew, Obsidian, or hub; connected status and proposal review use the configured services.

The main window now opens on a unified Home with nodes, producers, contributions,
and context preparation receipts. Home also shows connection warnings and contribution
acceptance. Review owns the proposal queue, comparison, approval, rejection and
conflict-resolution controls. Signal Night supplies the shared navy, amber and cyan
palette. Preparation records open in your default editor; archive files remain available in Finder. Operations opens
connected setup, statistics and diagnostics in the same window. Home reads status from an
existing installed `sov` command; it does not bundle or install fleet connectors.

The preview has a separate bundle identifier and preferences. Building or opening
it does not replace the installed app, change archive pointer files, connect tools,
install background jobs, or publish files. Local archive selection does not change
the archive configured for connected tools; Home names any mismatch.

## Build

A maintainer needs macOS and the Swift command-line toolchain. Runtime metadata is pinned in `runtime.lock.json`; the digest comes from the provider's release asset metadata.

```sh
python3 apps/console/fetch-runtime.py
SOV_PYTHON_RUNTIME="$PWD/apps/console/build/runtime/python" \
  SOV_SIGN_ID=- bash apps/console/build.sh --preview
```

The result is `apps/console/build/Sovereign Preview.app`. The runtime fetch requires Python 3.12 or newer for safe archive extraction. End users receive the built app and do not run these commands.

Set `SOV_SIGN_ID` to the intended signing identity for a signed build. A signing failure stops the build; it never silently downgrades to an ad-hoc signature. The build signs embedded native code and verifies the completed bundle.

## Current boundary

- Apple Silicon only. The native deployment target is macOS 13; the actual preview has been exercised on the development Mac, not yet every supported macOS version.
- Existing archives must contain all five folders. Opening one does not rewrite its organization. The app does not include a notes browser or capture editor.
- An existing nonempty or empty folder is refused by Create. Use Open for an existing archive. If creation fails partway, the chosen folder may contain an incomplete scaffold; the app does not delete it or bind it as a successful archive.

## Native verification

After building the preview, run:

```sh
python3 apps/console/test-home.py
```

This creates a disposable archive and passes its path through the process's
temporary preferences. It does not change the saved archive selection. The test
does perform a read-only status request on a configured machine.

## Dynamic environment view

System provides four panes over the same archive-scoped observations:

- Environment lays out tools, archive access, the review hub and devices spatially.
- Flow expands a selected component's reported routes and mechanisms. Replay is
  explicitly illustrative, not live traffic. Preparation and acceptance evidence
  are shown separately from route configuration.
- Inspect preserves the selected component, with search, context records,
  reported relationships and links to existing operational actions.
- How it works explains connection, capture, review and context reuse using the
  configured environment's tools and archive.

Selection carries across panes. Archive changes reset selection and hide foreign
connections and receipts. Environment groups lane relationships; Flow retains their
reported steps. Unreported transport endpoints and consuming-tool/model use
remain unknown. Detected-only tools do not acquire active connections.

After building the normal candidate bundle:

```sh
node apps/console/tests/system-model.cjs
python3 apps/console/test-system.py
SOV_WINDOW=720x680 python3 apps/console/test-system.py
python3 apps/console/test-home.py
```

The System native test uses a disposable independent archive and status fixture.
It checks cross-pane selection, routes, component search, safe labels, archive
isolation and navigation. These checks do not install another application.

## Classification conflict review

A declared update to one existing card can retain its current classification
through Resolve and review, followed by Approve update. The preview compares
both versions without writing. Final approval preserves both originals, changes
only the proposed type label and calls the configured owner's approval command.
Moving a card between classifications and merging multiple existing cards remain
manual decisions.

Interrupted resolutions block another console decision and provide a recovery
request. Their receipts and original snapshots are retained under the approval
machine's `~/.sovereign/gate-locks/resolutions/`. Check the recorded hashes, current
proposal and trusted card, decision log and Git state before recovery. Legacy
writers do not share the console lock or recovery receipt, so coordinate them
before attempting a manual retry or restoration.

```sh
python3 apps/console/tests/test_gate_check.py
node apps/console/tests/gate-model.cjs
python3 apps/console/test-gate.py --evidence /tmp/sovereign-gate-qa
```

These approval tests use disposable archives and local test Git remotes.

## Appearance and UI repair (0.4.3)

Appearance is available as System / Dark / Light in Settings and View → Appearance.
System is the default and follows the Mac. Choosing a mode saves immediately in
`sov.appearance`; updates restyle the current documents and native shell without
reloading drafts, note selection or review previews. The menu-bar document uses
the same resolved appearance. System maps use graphite, brass and cyan on paper
in light mode. Flow scales its SVG to the available width and stacks its route
picker on narrower windows.

`SOV_APPEARANCE=system|dark|light` is a process-only QA override; it never changes
the saved choice. Snapshot tests may use `SOV_QA_DEFAULTS_SUITE` with a
`com.sovereign.qa.` prefix to test persistence without touching owner preferences.
The `qaAppearance` bridge route is enabled only in snapshot mode and simulates
an effective-appearance change without changing macOS settings. This exercises
the observer; it is not evidence of a physical System Settings toggle.

Run `python3 apps/console/test-appearance.py --evidence /path/to/evidence` against
the built candidate. It covers appearance persistence, rejected invalid values,
live updates in both web views, draft focus/selection, unchanged proposal previews,
map colors, Flow bounds and every Operations tab. The Hub check injects the old
missing-helper defect into a disposable page and verifies the error is detected.
The ordinary release, System and gate fixture suites remain applicable.

## Proposal queue (0.4.4)

Review is the single decision surface. Its badge counts proposals, independently
of operational warnings. The selected archive must match the connected status
archive before decisions are available. Missing observations, an unavailable hub,
an incomplete list and an explicit empty queue are distinct states. The service
currently supplies at most 60 rows; larger queues show the loaded and total counts.

Run `python3 apps/console/test-review.py --evidence /tmp/sovereign-review-qa` for
native navigation, draft preservation, visible decisions, archive isolation,
failed-status recovery and capped-queue checks. Gate tests use Review and retain
the real local approval command against disposable proposal files.

## Public release gates

This is a development preview. Before advertising a public download:

1. Review the included upstream runtime notices against the final bundle. The verified full distribution supplied the native dependency license texts in `licenses/`; Python and pip retain their own notices in the runtime.
2. Sign with Developer ID, notarize, staple the ticket, and check Gatekeeper on the final download artifact.
3. Run install, capture, search, reopen, upgrade and removal checks on a fresh Mac account without developer tools, including macOS 13 and the latest macOS. Check privacy prompts and application translocation from a downloaded archive.
4. Test archive recovery from a separate copy. Implement a reviewed upgrade path before enabling background connectors from the standalone app.
5. Decide and test additional platforms separately. This build does not claim Intel Mac, Windows, or Linux support.

Sources: [Python standalone distributions](https://github.com/astral-sh/python-build-standalone/blob/main/docs/distributions.rst), [pinned runtime release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901), [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
