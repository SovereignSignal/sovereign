# Changelog

## 0.9.0 "Capture" (unreleased)

- Session capture for Claude Code, off until you turn it on. Quiet sessions are
  distilled into candidate captures in the tool's own lane, for the curator to judge.
  A model-free pre-filter drops most sessions before any call; the rest send a
  redacted excerpt of typed prompts and replies, never tool results or the archive's
  own session-start pack, to the archive's own curator provider through the inference
  guard. At most 3 calls and 60,000 characters per tick, 30 calls a day.
- `sov ingest sessions` shows a dry plan first, `--show <id>` prints the exact excerpt
  a model would receive, and `--on [--since D]`, `--off`, `--allow`, `--deny`,
  `--apply` and `status` do the rest. Settings › Session capture offers the same, and
  Turn on appears only after a Preview.
- A session that ran inside an archive is always refused. Client Macs of a hub archive
  stay off, since the model is on the hub. Session captures are always screened by the
  curator and held at ask-first until they earn their own record; nothing reaches
  `knowledge/` without your approval.
- Sources and Review show session captures. Open session opens Terminal in the folder
  the session ran in and resumes it, and only when the transcript is on this Mac, so
  not on a client Mac of a hub archive, where the archive's model runs on the hub.
- `sov-capture` on a staged host: a capture for a lane with no `raw/workspaces/<lane>`
  now lands in the staging area's `raw/tools/<lane>`, as the write wires already did,
  instead of the vault's `raw/workspaces/<lane>`.

## 0.8.0 "Reach" (build 51)

Status: closed beta, release candidate, a signed, notarized download.
Validation on clean macOS 13 and current macOS installs is recorded in the
release record.

- `sov mcp`: a read-only MCP server any MCP client can use. Four tools
  (`load_context`, `read_card`, `search_cards`, `list_cards`) serve the
  trusted layer only, each card with its path and content hash. No symlink
  is followed out of the archive, an ambiguous slug is refused, anything
  shaped like a secret is redacted on the way out, and the read gate is
  checked on every call. There is no write path.
- Import from ChatGPT, in Settings › Import or with `sov import chatgpt`: a
  prompt for ChatGPT, a preview, then one untrusted capture per memory for
  the curator to judge. Re-importing brings in only what changed.
- Settings › Curator walks a newcomer through getting a key from each
  provider: the steps, the provider's own key and spend-limit pages (opened
  in the browser), and where a provider documents no spend limit, it says
  so. Save key now sits beside the key field instead of below it.
- A new archive's curator now judges what connected tools saved before it
  was turned on, such as existing Claude Code memory, 20 files a pass.
  Before, it looked back only two days and never saw the rest.
- Capture titles and origins that YAML would misread (`[Work] notes`,
  `2026`) are quoted, so a capture's labels always parse.
- `sov mcp` serves an archive reached through a symlink, caps a single
  card's size, and answers an unexpected failure with an error instead of
  ending the session.
- Settings › Version › Check for updates installs the latest signed
  release from GitHub. Before anything is replaced, the download has to match
  its published checksum, carry Sovereign's Developer ID signature, pass
  Gatekeeper and be the version and build it claims; the current app is kept
  under `~/sovereign-rollback/`. Nothing is contacted until you click it.
  Update from source still appears when this device's checkout is newer.
- The README, the welcome screen and the release notes now lead with what
  Sovereign is for: memory you can audit, kept as plain files you own.

## 0.7.1 (build 50) — release candidate

Status: closed beta, published as a signed, notarized download. Validated end
to end on clean installs of macOS 13.6 and the current macOS. Supersedes build 49.

- New archives now default to the home folder instead of Documents. On a
  clean Mac, macOS privacy rules deny Sovereign's background connector jobs
  inside Documents, which stalled the first-run loop (found in Parallels
  validation of build 49). Existing archives are untouched.
- The hubless curator can run on the owner's choice of hosted provider:
  Anthropic, OpenAI, Google Gemini, xAI Grok, or Muse, one at a time under
  the owner's own key. Switching provider returns trust to ask-first.

## 0.7.0 (build 49) — release candidate

Status: signed source-preview candidate. It is not a public download until
Apple notarization, stapling, exact-artifact Gatekeeper validation, and clean
Parallels macOS validation are complete.

- Added a Muse Code connector with an instruction-based read wire and a
  one-way distilled-memory lane.
- Added calibrate-then-fade curator trust: eligibility evidence after ten
  clean routine decisions, explicit owner grant and revoke, a 12-card pass
  cap, recent landed-card review, and confirmed retirement.
- Kept flagged items, entities, collisions, destructive changes, and
  auto-rejection outside background landing.
- Added structural Claude SessionStart validation so a mirror can no longer
  look green while the read hook is malformed, points at a missing Python, or
  no longer runs at startup.
- Added connector Checks in Sources for the read hook, memory source,
  background saver, and last mirror, with a guided reinstall path.
- Published privacy-conscious bug and feature templates, a security policy,
  and a support route.
