---
type: concept
source: robin
created: 2026-04-25
title: Probe vault inspection rounds
---

# Probe vault inspection rounds

**Why this matters:** Most readings the practice has had to throw away failed in the vault, not in the probe, so the inspection round is the cheapest quality control the owner has.

Standing physical inspection of the below-grade chambers that house distribution-ring probes. Runs independently of any telemetry alarm, on a fixed cadence, because the failures it catches are silent.

- **Cadence:** every measurement point twice a year, flood-prone chambers quarterly.
- **What it catches:** standing water, silt over the stem, cable chafe, seized isolation valves, a partner unit swapped out of pair.
- **Rule:** an inspection is logged even when nothing is found; an empty finding is the baseline.
- **Handoff:** findings go to the utility's maintenance queue, never to the telemetry pipeline.

Living detail sits in `workstreams/meridian-pilot/`.
