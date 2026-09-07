# Cowork project memory → brain

Claude Desktop keeps a per-project memory store on disk: distilled `feedback_*.md`, `project_*.md`, and `reference_*.md` files it maintains as you work. That store is often the richest un-piped knowledge on the machine — it is literally your tool's own curation of your working style and projects.

This pipe mirrors every project's `memory/` directory into `raw/tools/cowork-<machine>/<project-id>/`, one-way, on the machine's connector tick (every 15 minutes by default). Project ids are opaque folder names; the files identify themselves — your curator judges content, and provenance is the path.

Install: `sov connect cowork --apply`. That declares the lane in the machine's connector manifest and makes sure the one shared connector job exists; it does not add a background item of its own, so connecting a further tool later still leaves one job. To run this pipe by hand at any time: `sov connect cowork --apply` re-runs it, or run `mirror.sh` directly.

The standalone recipe here still works if you would rather not use the harness: set `BRAIN_ROOT` (and optionally `MACHINE`) in `mirror.sh` and run it once by hand to check the lane.
