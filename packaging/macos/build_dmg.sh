#!/usr/bin/env bash
# Package the PyInstaller .app (dist/Maknassa.app) into a drag-to-Applications DMG.
#
#   bash packaging/build.sh            # produces dist/Maknassa.app (mac BUNDLE in the spec)
#   bash packaging/macos/build_dmg.sh  # produces dist/Maknassa.dmg
#
# Uses hdiutil (ships with macOS) so there's no extra dependency. The version-less
# output name keeps the "latest" download link stable.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

APP="$REPO/dist/Maknassa.app"
DMG="$REPO/dist/Maknassa.dmg"

if [ ! -d "$APP" ]; then
  echo "error: $APP not found — run packaging/build.sh on macOS first." >&2
  exit 1
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"   # drag-target in the DMG window

rm -f "$DMG"
hdiutil create -volname "Maknassa" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
echo ">> Done: $DMG"
