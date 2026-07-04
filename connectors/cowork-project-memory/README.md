# Cowork project memory → brain

Claude Desktop keeps a per-project memory store on disk: distilled `feedback_*.md`, `project_*.md`, and `reference_*.md` files it maintains as you work. That store is often the richest un-piped knowledge on the machine — it is literally your tool's own curation of your working style and projects.

This pipe mirrors every project's `memory/` directory into `raw/tools/cowork-<machine>/<project-id>/`, one-way, every 15 minutes. Project ids are opaque folder names; the files identify themselves — your curator judges content, and provenance is the path.

Install: set `BRAIN_ROOT` (and optionally `MACHINE`) in `mirror.sh`, run it once by hand, check the lane, then schedule it — macOS: a launchd plist calling the script with `StartInterval` 900 (`launchctl bootstrap gui/$UID <plist>` on modern macOS; plain `load` fails over SSH); Linux: `*/15 * * * * bash mirror.sh` in crontab.
