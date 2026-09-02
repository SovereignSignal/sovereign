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
if [ ! -f "$BUILD/AppIcon.icns" ]; then
  rm -rf "$BUILD/icon.iconset"
  xcrun swift "$HERE/icon.swift" "$BUILD/icon.iconset" >/dev/null
  iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/AppIcon.icns"
fi

echo "[3] bundle"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/ui"
cp "$BUILD/Sovereign" "$APP/Contents/MacOS/Sovereign"
cp "$HERE/Info.plist" "$APP/Contents/Info.plist"
cp "$BUILD/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
cp "$HERE"/ui/* "$APP/Contents/Resources/ui/"
codesign --force --sign - "$APP" >/dev/null 2>&1 || true
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
