#!/bin/bash
# notarize.sh <path/to/Sovereign.app> [keychain-profile]
#
# Submit a Developer ID build to Apple's notary service, staple the ticket to the app, and
# check it the way Gatekeeper on a stranger's Mac will. Writes <app's folder>/Sovereign-<version>-build<N>.zip
# (the stapled app) for distribution. The credentials are the owner's, stored once with:
#   xcrun notarytool store-credentials sovereign-notary --apple-id <email> --team-id <TEAM>
# This script only ever names the profile; it never sees the password.
set -euo pipefail
APP="${1:?usage: notarize.sh <path/to/Sovereign.app> [keychain-profile]}"
PROFILE="${2:-sovereign-notary}"
[ -d "$APP" ] || { echo "no app at $APP" >&2; exit 64; }
codesign -dv --verbose=2 "$APP" 2>&1 | grep 'Authority=Developer ID Application:' >/dev/null || {
  echo "$APP is not signed with a Developer ID; build it on a Mac that has one" >&2; exit 65; }
codesign --verify --deep --strict "$APP"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"
BUILD="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP/Contents/Info.plist")"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
echo "    submitting $VERSION build $BUILD to Apple (this waits for the verdict)"
ditto -c -k --keepParent "$APP" "$WORK/submit.zip"
if ! xcrun notarytool submit "$WORK/submit.zip" --keychain-profile "$PROFILE" --wait --output-format json > "$WORK/result.json"; then
  cat "$WORK/result.json" >&2 || true; exit 1
fi
STATUS="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("status",""))' "$WORK/result.json" 2>/dev/null || true)"
ID="$(/usr/bin/python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("id",""))' "$WORK/result.json" 2>/dev/null || true)"
if [ "$STATUS" != "Accepted" ]; then
  echo "    notarization: ${STATUS:-unknown}. Apple's log:" >&2
  [ -n "$ID" ] && xcrun notarytool log "$ID" --keychain-profile "$PROFILE" >&2 || true
  exit 1
fi
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl --assess --type execute -vv "$APP"
OUT="$(dirname "$APP")/Sovereign-$VERSION-build$BUILD.zip"
ditto -c -k --keepParent "$APP" "$OUT"
echo "    notarized, stapled and accepted by Gatekeeper"
echo "    $OUT"
