#!/bin/bash
# Sovereign connector installer: Parallels guests on this Mac, the write wire only.
#
#   sov connect parallels --host <short-name> --vault <path> --core me,how-to-work-with-me --apply
#
# Read wire: none, by owner decision: the guests are contribute-only (see LANE.md.tmpl).
# Write wire: mirror.sh (every running guest's Claude Code memory and Claude Desktop
# outputs, pulled through prlctl exec -> the lane), ticked by the shared connector job.
# Without --apply it prints what it would do and changes nothing.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
HARNESS=parallels; LANE_PREFIX=parallels
. "$HERE/../_lib/install-common.sh"
sov_parse_args "$@"
sov_resolve
[ -x "${PRLCTL:-/usr/local/bin/prlctl}" ] || { echo "parallels: prlctl not found at ${PRLCTL:-/usr/local/bin/prlctl}; is Parallels Desktop installed?" >&2; exit 65; }
sov_plan "read       none: the guests are contribute-only by owner decision; the vault is never shared into a guest" \
         "mirror     $HERE/mirror.sh  every ${INTERVAL}s in $RUNNER_LABEL (this machine's one connector job): every running guest's Claude Code memory and Claude Desktop outputs, pulled through prlctl"
sov_write_pointers
sov_link_bins
sov_register_connector "$HERE/mirror.sh"
sov_lane_contract "$HERE/LANE.md.tmpl" "none"
sov_smoke_mirror "$HERE/mirror.sh"
sov_smoke_runner "$HARNESS"
say; say "done. each running guest now appears under raw/tools/$LANE/<guest-slug>/ after the next tick."
