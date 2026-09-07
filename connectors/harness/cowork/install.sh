#!/bin/bash
# Sovereign connector installer: Cowork (Claude Desktop local agent mode).
#
#   sov connect cowork --host <short-name> --vault <path> --apply
#
# Write wire: mirror.sh (each project's memory -> the lane), ticked by the shared connector job.
# Read wire: Cowork runs no hooks, so the read is an instruction the owner pastes
# into each Cowork project (printed at the end, also in INSTRUCTION.md). The lane
# contract records it as `read: instruction`.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=cowork; LANE_PREFIX=cowork
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "read       instruction, written into every Cowork space by $HERE/ensure-instruction.py (no hooks in Cowork)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s in $RUNNER_LABEL (this machine's one connector job)"
sov_write_pointers
sov_link_bins
sov_register_connector "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "instruction (auto-applied to every Cowork space)"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_runner "$HARNESS"
/usr/bin/python3 "$HERE/ensure-instruction.py"
say; say "done. every Cowork space now carries the Sovereign read instruction; restart Claude Desktop once if it was open."
