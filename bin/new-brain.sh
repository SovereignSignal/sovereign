#!/usr/bin/env bash
#
# new-brain.sh — stand up a fresh, empty brain from this template.
#
#   new-brain.sh <target-dir> [brain-name]
#
# Lays down the five-folder skeleton, the rules (CLAUDE.md), and the note template,
# then git-inits it. Running it in an empty dir yields a clean, fork-ready brain.

set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="${1:?usage: new-brain.sh <target-dir> [brain-name]}"
NAME="${2:-$(basename "$TARGET")}"

mkdir -p "$TARGET"
rsync -a "$HERE/skeleton/" "$TARGET/"
mkdir -p "$TARGET/.obsidian/templates"
cp "$HERE/templates/note.md" "$TARGET/.obsidian/templates/note.md"
# drop the rules in, stamped with the brain's name
sed "s/{{BRAIN_NAME}}/$NAME/g" "$HERE/CLAUDE.md" > "$TARGET/CLAUDE.md"

cat > "$TARGET/.gitignore" <<'EOF'
.DS_Store
.obsidian/workspace*
archive/
repos/
EOF

( cd "$TARGET" && git init -q && git add -A && git commit -q -m "new brain: $NAME (from sovs-brain-template)" )

echo "Brain '$NAME' created at $TARGET"
echo "Next: open it in Obsidian, set the Templates folder to .obsidian/templates, write your first note, then run:"
echo "  $HERE/bin/brain-check.sh \"$TARGET\""
