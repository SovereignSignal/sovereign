#!/bin/bash
# Sovereign connector installer: Muse Code on this machine, both wires.
#
#   sov connect muse --host <short-name> --vault <path> --apply
#
# Read wire: Muse has no session-start hook that injects context, so the read
# instruction goes into Muse's personal memory index (MEMORY.md), which every
# session loads at open (idempotent, re-applied by the mirror).
# Write wire: a scheduled job running mirror.sh (Muse memory -> the lane).
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=muse; LANE_PREFIX=muse
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "read       instruction appended to the Muse personal memory index, MEMORY.md (no context hooks in Muse)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s in $RUNNER_LABEL (this machine's one connector job)"
sov_write_pointers
sov_link_bins
sov_register_connector "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "instruction (auto-applied to the Muse personal memory index)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_runner "$HARNESS"
say; say "done. Muse loads its memory index at session open, so the next Muse session starts with the instruction."
