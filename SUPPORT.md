# Support

Sovereign is currently a source preview for Apple Silicon Macs. Start with the
status already inside the app before opening an issue.

## Before reporting a problem

1. Open **Sources** and select the affected tool.
2. Read its **Checks** section. For Muse this separates the read hook,
   memory source, background saver, and last mirror result.
3. If the check names **Reinstall**, use that producer action, refresh
   Sources, and start a fresh tool session.
4. For curation, open **Settings → Curator** and note whether it is on,
   whether the key is saved, the trust state, and the last recorded run.
5. Try the smallest reproduction in a disposable archive when the problem
   allows it.

## What to include

Include the Sovereign version and build, source commit when shown, macOS
version, affected tool, exact steps, expected result, actual result, and the
relevant Checks text.

Never attach archive cards, raw captures, tool memory, API keys, tokens,
private paths, or unredacted logs. Review diagnostics locally and remove
anything that should stay on your Mac.

## Security problems

Do not use a public issue. Follow [SECURITY.md](SECURITY.md) and use GitHub's
private vulnerability reporting.
