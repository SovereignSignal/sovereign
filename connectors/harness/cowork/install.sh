#!/bin/bash
# Sovereign connector installer: Cowork (Claude Desktop local agent mode).
#
#   sov connect cowork --host client --vault "~/My Brain" --apply
#
# Write wire: launchd job running mirror.sh (each project's memory -> the lane).
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
sov_plan "read       instruction (no hooks in Cowork): see $HERE/INSTRUCTION.md" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s as $LABEL"
sov_write_pointers
sov_link_bins
sov_install_launchd "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "instruction (owner pastes INSTRUCTION.md into each Cowork project)"
sov_smoke_mirror "$HERE/mirror.sh"
say; say "paste this into each Cowork project's instructions:"; say
sed -e "s|{{VAULT}}|$VAULT|g" "$HERE/INSTRUCTION.md"
