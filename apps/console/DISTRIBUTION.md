# Downloadable app preview

Sovereign starts with one local archive. The Apple Silicon preview can create an archive, capture a note, search titles and contents, read notes, and open the underlying Markdown in a text editor. It bundles Python and requires no account, terminal setup, Git, Homebrew, Obsidian, or separate hub for those operations.

The main window now opens on a unified Home with nodes, producers, contributions,
and context preparation receipts. Review contains attention items and contribution
acceptance. Signal Night supplies the shared navy, amber, and cyan palette. Notes opens the local reader and
capture interface. Operations opens the existing connected console in the same
window and reuses its explicit setup and review actions. Home reads status from an
existing installed `sov` command; it does not bundle or install fleet connectors.

The preview has a separate bundle identifier and preferences. Building or opening
it does not replace the installed app, change brain pointer files, connect tools,
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
- Local captures enter `raw/workspaces/owner`. There is no automatic promotion to trusted knowledge, AI generation, cloud sync, or backup setup in this first-run path.
- Existing archives must contain all five folders. Opening one does not rewrite its organization. The local reader covers Markdown in raw, workstreams, and knowledge. It lists at most 500 matching notes, reports the full match count, and excludes linked files, hidden paths, cold storage, repositories, and notes larger than 2 MiB.
- Captures are limited to 1 MiB and use exclusive writes. Credential recognition is a pattern-based safeguard, not a guarantee that all sensitive information is detected.
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

## Public release gates

This is a development preview. Before advertising a public download:

1. Review the included upstream runtime notices against the final bundle. The verified full distribution supplied the native dependency license texts in `licenses/`; Python and pip retain their own notices in the runtime.
2. Sign with Developer ID, notarize, staple the ticket, and check Gatekeeper on the final download artifact.
3. Run install, capture, search, reopen, upgrade and removal checks on a fresh Mac account without developer tools, including macOS 13 and the latest macOS. Check privacy prompts and application translocation from a downloaded archive.
4. Test archive recovery from a separate copy. Implement a reviewed upgrade path before enabling background connectors from the standalone app.
5. Decide and test additional platforms separately. This build does not claim Intel Mac, Windows, or Linux support.

Sources: [Python standalone distributions](https://github.com/astral-sh/python-build-standalone/blob/main/docs/distributions.rst), [pinned runtime release](https://github.com/astral-sh/python-build-standalone/releases/tag/20260901), [Apple notarization](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).
