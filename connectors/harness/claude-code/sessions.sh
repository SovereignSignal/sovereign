#!/bin/bash
# Sovereign connector, Claude Code, session capture.
#
# Distils quiet Claude Code sessions into candidate captures in this machine's lane,
# under sessions/, through the archive's own model. Off until the owner turns it on
# (`sov ingest sessions --on`); while off this exits 0 and touches nothing. Transcripts
# never cross: only the captures the curator will judge, and sessions/MANIFEST.md.
#
# Each tick collects into a private stage, publishes through the same redaction pass
# and rsync as the memory mirror, then commits the session watermark. A failed publish
# discards the tick's verdicts so every session retries.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/../_lib/mirror-common.sh"
TEMPLATE="$(cd "$HERE/../../.." && pwd)"
. "$TEMPLATE/bin/_sov-python.sh"
PY="$(sov_python "$TEMPLATE")"
sov_python_is_bundled "$PY" && export PYTHONDONTWRITEBYTECODE=1

ingest() { "$PY" "$TEMPLATE/bin/sov-ingest" sessions "$@"; }

LANE="claude-code-$BRAIN_HOST_RESOLVED"
ingest --gate; rc=$?
case "$rc" in
  0) ;;
  3) exit 0 ;;
  *) echo "sessions: the session capture gate failed (exit $rc)" >&2; exit 1 ;;
esac

sov_prepare "$LANE/sessions" "claude-code/sessions" || exit 1
# sov-capture writes into <stage>/raw/tools/<lane>/sessions, so the private collection
# folder takes that shape inside the private directory.
STAGE="$SOV_PRIVATE/stage"
mkdir -p "$STAGE/raw/tools/$LANE" || { echo "sessions: cannot create the private stage" >&2; exit 1; }
mv "$DEST" "$STAGE/raw/tools/$LANE/sessions" || { echo "sessions: cannot move the collection into the private stage" >&2; exit 1; }
DEST="$STAGE/raw/tools/$LANE/sessions"

failed=0
ingest --tick --dest "$DEST" || failed=1
if sov_finish "Claude Code session capture"; then
  ingest --commit-tick || { echo "sessions: published, but the watermark could not be committed" >&2; exit 1; }
  exit 0
fi
ingest --discard-tick || echo "sessions: the staged watermark could not be discarded" >&2
exit 1
