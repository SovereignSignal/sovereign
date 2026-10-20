# Security

Sovereign is a local-first macOS application for plain-text archives. Security
reports should stay private until a fix is available.

## Report a vulnerability

Use GitHub's private vulnerability reporting for this repository:

https://github.com/SovereignSignal/sovereign/security/advisories/new

Do not open a public issue for a vulnerability. Do not include API keys,
archive cards, raw captures, memory files, private paths, or unredacted logs.

Include the Sovereign version and build, macOS version, affected connector or
surface, reproduction steps using a disposable archive when possible, and the
impact you observed.

## Supported versions

The current `0.7.1` beta line and `main` receive security fixes.
Older preview builds should be upgraded before a report is investigated,
unless the report shows that upgrading is unsafe or impossible.

## Scope notes

The local Hub path is designed to keep judging on owner-controlled local
inference. The hosted Claude path sends newly saved material to Anthropic
under the owner's own API key. A report that confuses those routes, bypasses
the review gate, crosses an identity or workstream boundary, leaks a secret,
or writes trusted knowledge without authorization is in scope.
