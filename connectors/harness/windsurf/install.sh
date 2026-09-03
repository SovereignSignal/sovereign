#!/bin/bash
# Sovereign connector installer: Windsurf on this machine, both wires.
#
#   sov connect windsurf --host client --vault "~/My Brain" --apply
#
# Read wire: Cascade's hooks cannot add context, so the read instruction goes into
# ~/.codeium/windsurf/memories/global_rules.md (idempotent, re-applied by the mirror).
# Write wire: a scheduled job running mirror.sh (memories folder -> the lane).
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=windsurf; LANE_PREFIX=windsurf
. "$HERE/../_lib/install-common.sh"

sov_parse_args "$@"
sov_resolve
sov_plan "read       instruction appended to ~/.codeium/windsurf/memories/global_rules.md (no context hooks in Cascade)" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL"
sov_write_pointers
sov_link_bins
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "instruction (auto-applied to global_rules.md)"
sov_smoke_mirror "$HERE/mirror.sh"
say; say "done. Cascade reads global_rules.md every turn, so the next Windsurf chat starts with the instruction."
