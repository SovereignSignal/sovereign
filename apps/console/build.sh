#!/bin/bash
# Build Sovereign.app from main.swift + ui/, no Xcode project needed.
#   apps/console/build.sh [--install] [--open]
# --install copies the app to ~/Applications (so it shows in Launchpad and can be
# kept in the Dock). --open launches it. Ad-hoc signed: fine for a locally built app.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"; APP="$BUILD/Sovereign.app"
INSTALL=0; OPEN=0; PREVIEW=0
for a in "$@"; do case "$a" in --install) INSTALL=1;; --open) OPEN=1;; --preview) PREVIEW=1;; *) echo "unknown option: $a" >&2; exit 64;; esac; done
if [ "$PREVIEW" -eq 1 ]; then APP="$BUILD/Sovereign Preview.app"; fi
if [ "$PREVIEW" -eq 1 ] && [ "$INSTALL" -eq 1 ]; then echo "Preview builds stay separate; do not use --install." >&2; exit 64; fi
RUNTIME="${SOV_PYTHON_RUNTIME:-}"
[ -x "$RUNTIME/bin/python3" ] || { echo "Set SOV_PYTHON_RUNTIME to a verified redistributable Python installation. See DISTRIBUTION.md." >&2; exit 66; }

mkdir -p "$BUILD"
echo "[1] compiling"
MACOSX_DEPLOYMENT_TARGET=13.0 xcrun swiftc -target arm64-apple-macos13.0 -module-cache-path "$BUILD/module-cache" -O -parse-as-library -framework Cocoa -framework WebKit -o "$BUILD/Sovereign" "$HERE/main.swift"

MACOSX_DEPLOYMENT_TARGET=13.0 xcrun swiftc -target arm64-apple-macos13.0 -module-cache-path "$BUILD/module-cache" -O -o "$BUILD/hub-crypto" "$HERE/hub-crypto.swift"

echo "[2] icon"
PNG="$HERE/design/icon/AppIcon-1024.png"
if [ -f "$PNG" ] && { [ ! -f "$BUILD/AppIcon.icns" ] || [ "$PNG" -nt "$BUILD/AppIcon.icns" ]; }; then
  rm -rf "$BUILD/icon.iconset"; mkdir -p "$BUILD/icon.iconset"
  for sz in 16 32 128 256 512; do
    sips -z $sz $sz "$PNG" --out "$BUILD/icon.iconset/icon_${sz}x${sz}.png" >/dev/null
    sips -z $((sz*2)) $((sz*2)) "$PNG" --out "$BUILD/icon.iconset/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/AppIcon.icns"
elif [ ! -f "$BUILD/AppIcon.icns" ]; then
  echo "    no design/icon/AppIcon-1024.png and no cached icon; add the PNG" >&2; exit 1
fi

echo "[3] bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp "$BUILD/Sovereign" "$APP/Contents/MacOS/Sovereign"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
# Stamp the source this bundle was built from. Without it nothing can compare an
# installed app against available source, which is how one machine ran a 0.1
# prototype for months while the other moved through twenty-two builds.
SRC_REV="$(git -C "$HERE/../.." log -1 --format=%h 2>/dev/null || echo unknown)"
SRC_DIRTY=""; [ -z "$(git -C "$HERE/../.." status --porcelain 2>/dev/null)" ] || SRC_DIRTY="+local"
/usr/libexec/PlistBuddy -c "Add :SovereignSourceCommit string ${SRC_REV}${SRC_DIRTY}" "$APP/Contents/Info.plist"
if [ "$PREVIEW" -eq 1 ]; then
  /usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier com.sovereign.console.preview' "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c 'Set :CFBundleName Sovereign Preview' "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName Sovereign Preview' "$APP/Contents/Info.plist"
  /usr/libexec/PlistBuddy -c 'Add :SovereignPreview bool true' "$APP/Contents/Info.plist"
fi
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$HERE"/ui/* "$APP/Contents/Resources/ui/"
cp "$HERE/design/tokens.css" "$APP/Contents/Resources/ui/tokens.css"
cp "$HERE/design/glyphs/MenuBarTemplate.png" "$HERE/design/glyphs/MenuBarTemplate@2x.png" "$APP/Contents/Resources/"
BACKEND="$APP/Contents/Resources/backend"
mkdir -p "$BACKEND/bin" "$BACKEND/lib" "$BACKEND/templates"
cp "$HERE/diagnostics.py" "$BACKEND/"
cp "$HERE/gate_check.py" "$APP/Contents/Resources/"
cp "$HERE/../../bin/sov-local" "$HERE/../../bin/sov-about" "$HERE/../../bin/sov-discover" "$BACKEND/bin/"
cp "$HERE/../../lib/brain_discovery.py" "$HERE/../../lib/brain_harness_discovery.py" "$BACKEND/lib/"
mkdir -p "$BACKEND/connectors/harness/_lib"
cp "$HERE/../../connectors/harness/_lib/known-tools.json" "$BACKEND/connectors/harness/_lib/"
MACOSX_DEPLOYMENT_TARGET=13.0 xcrun swiftc -target arm64-apple-macos13.0 -module-cache-path "$BUILD/module-cache" -O -o "$APP/Contents/MacOS/sov" "$HERE/about-cli.swift"
cp "$HERE/../../lib/sovereign_config.py" "$HERE/../../lib/brain_local.py" "$HERE/../../lib/brain_redact.py" "$BACKEND/lib/"
cp "$HERE/../../templates/note.md" "$BACKEND/templates/"
cp "$HERE/../../CLAUDE.md" "$BACKEND/"
# Hub setup includes the same general tools as the template, plus the bundled Python.
# Omit development caches; no instance configuration is part of this payload.
"$RUNTIME/bin/python3" -I -B - "$HERE/../.." "$BACKEND" <<'BUNDLE'
from pathlib import Path
import shutil,sys
source,dest=map(Path,sys.argv[1:])
for name in ('bin','lib','connectors','templates'):
    shutil.copytree(source/name,dest/name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
BUNDLE
cp "$BUILD/hub-crypto" "$BACKEND/bin/hub-crypto"

cp -R "$RUNTIME" "$APP/Contents/Resources/runtime"
cp -R "$HERE/licenses" "$APP/Contents/Resources/licenses"
cp "$HERE/runtime.lock.json" "$APP/Contents/Resources/runtime.lock.json"
# Signing decides whether macOS remembers its answer to "may Sovereign read your
# Documents?". An ad-hoc signature pins the app's identity to the hash of the binary, so
# every rebuild is a new app to the privacy database and the prompt comes back. Sign with
# a stable identity when the machine has one (SOV_SIGN_ID, or a certificate whose name
# starts with "Sovereign Local Signing") and the grant survives rebuilds.
SIGN_ID="${SOV_SIGN_ID:-}"
if [ -z "$SIGN_ID" ] && security find-identity -v -p codesigning 2>/dev/null | grep -q "Sovereign Local Signing"; then
  SIGN_ID="Sovereign Local Signing"
fi
SIGN_ID="${SIGN_ID:--}"
# Sign embedded Mach-O code inside out; never silently downgrade a requested identity.
while IFS= read -r -d '' nested; do
  if file -b "$nested" | grep -q 'Mach-O'; then
    codesign --force --sign "$SIGN_ID" --options runtime "$nested" >/dev/null 2>&1
  fi
done < <(find "$APP/Contents/Resources/runtime" -type f -print0)
codesign --force --sign "$SIGN_ID" --options runtime "$BACKEND/bin/hub-crypto"
codesign --force --sign "$SIGN_ID" --options runtime "$APP/Contents/MacOS/sov"
codesign --force --sign "$SIGN_ID" --options runtime "$APP" >/dev/null 2>&1
codesign --verify --deep --strict "$APP"
echo "    signed and verified (distribution notarization is separate)"
echo "    $APP"

if [ "$INSTALL" -eq 1 ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Sovereign.app"
  cp -R "$APP" "$HOME/Applications/Sovereign.app"
  echo "[4] installed to ~/Applications/Sovereign.app"
  # Leave exactly one bundle macOS can index. Every copy carries the same
  # CFBundleIdentifier and macOS resolves an id to the HIGHEST VERSION it has seen,
  # not to ~/Applications: on 2026-09-20 four copies shared com.sovereign.console on
  # one machine, the Dock and `open -b` both reached an unreleased build in
  # /private/tmp, and the installer's own "quit normally" step quit the wrong app.
  # The build output is kept, just not as something that can be launched by mistake.
  rm -rf "$BUILD/Sovereign.app-built"
  mv "$APP" "$BUILD/Sovereign.app-built"
  echo "    build copy parked as Sovereign.app-built so only the installed one is launchable"
  APP="$HOME/Applications/Sovereign.app"
fi
[ "$OPEN" -eq 1 ] && open "$APP"
exit 0
