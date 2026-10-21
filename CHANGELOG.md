# Changelog

## 0.8.0 "Reach" (in progress)

- `sov mcp`: a read-only MCP server any MCP client can use. Four tools
  (`load_context`, `read_card`, `search_cards`, `list_cards`) serve the
  trusted layer only, each card with its path and content hash. No symlink
  is followed out of the archive, an ambiguous slug is refused, anything
  shaped like a secret is redacted on the way out, and the read gate is
  checked on every call. There is no write path.

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
