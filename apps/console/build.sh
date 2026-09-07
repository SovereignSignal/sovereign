#!/bin/bash
# Build Sovereign.app from main.swift + ui/, no Xcode project needed.
#   apps/console/build.sh [--install] [--open]
# --install copies the app to ~/Applications (so it shows in Launchpad and can be
# kept in the Dock). --open launches it. Ad-hoc signed: fine for a locally built app.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD="$HERE/build"; APP="$BUILD/Sovereign.app"
INSTALL=0; OPEN=0
for a in "$@"; do case "$a" in --install) INSTALL=1;; --open) OPEN=1;; esac; done

mkdir -p "$BUILD"
echo "[1] compiling"
xcrun swiftc -O -parse-as-library -framework Cocoa -framework WebKit -o "$BUILD/Sovereign" "$HERE/main.swift"

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
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$HERE"/ui/* "$APP/Contents/Resources/ui/"
cp "$HERE/design/tokens.css" "$APP/Contents/Resources/ui/tokens.css"
cp "$HERE/design/glyphs/MenuBarTemplate.png" "$HERE/design/glyphs/MenuBarTemplate@2x.png" "$APP/Contents/Resources/"
# Signing decides whether macOS remembers its answer to "may Sovereign read your
# Documents?". An ad-hoc signature pins the app's identity to the hash of the binary, so
# every rebuild is a new app to the privacy database and the prompt comes back. Sign with
# a stable identity when the machine has one (SOV_SIGN_ID, or a certificate whose name
# starts with "Sovereign Local Signing") and the grant survives rebuilds.
SIGN_ID="${SOV_SIGN_ID:-}"
if [ -z "$SIGN_ID" ] && security find-identity -v -p codesigning 2>/dev/null | grep -q "Sovereign Local Signing"; then
  SIGN_ID="Sovereign Local Signing"
fi
if [ -n "$SIGN_ID" ] && codesign --force --sign "$SIGN_ID" --options runtime "$APP" >/dev/null 2>&1; then
  echo "    signed as $SIGN_ID (the privacy grant survives rebuilds)"
else
  codesign --force --sign - "$APP" >/dev/null 2>&1 || true
  [ -n "$SIGN_ID" ] && echo "    could not sign as $SIGN_ID; fell back to ad-hoc"
fi
echo "    $APP"

if [ "$INSTALL" -eq 1 ]; then
  mkdir -p "$HOME/Applications"
  rm -rf "$HOME/Applications/Sovereign.app"
  cp -R "$APP" "$HOME/Applications/Sovereign.app"
  echo "[4] installed to ~/Applications/Sovereign.app"
  APP="$HOME/Applications/Sovereign.app"
fi
[ "$OPEN" -eq 1 ] && open "$APP"
exit 0
