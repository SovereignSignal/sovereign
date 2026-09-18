#!/bin/bash
# Connector: any directory -> a lane in the archive's loading dock. One-way.
# Copy this recipe per tool; set SRC and LANE. Secrets are excluded by default.

BRAIN_ROOT="${BRAIN_ROOT:-${SOVEREIGN_ROOT:-${SOVEREIGN_VAULT:-$HOME/brain}}}"
SRC="$HOME/Documents/MyTool"                      # where the tool writes
LANE="mytool"                                     # raw/tools/<LANE>/

rsync -a --delete --max-delete=20 \
  --exclude='.DS_Store' --exclude='.env' --exclude='.secrets' \
  --exclude='*.log' --exclude='.*.tmp' \
  "$SRC/" "$BRAIN_ROOT/raw/tools/$LANE/"
