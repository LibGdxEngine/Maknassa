#!/usr/bin/env bash
# Package the Electron Maknassa.app into a drag-to-Applications DMG.
#
#   bash packaging/build.sh            # produces dist/electron/mac*/Maknassa.app
#   bash packaging/macos/build_dmg.sh  # produces dist/Maknassa.dmg
#
# Injects the Playwright Chromium into the app's frozen-backend resources first:
# PyInstaller can't bundle it on macOS (backend.spec skips it there) because its
# ad-hoc per-file re-signing rejects Chromium's nested-.app entry binary. Copying
# it in afterwards and deep-signing the WHOLE app signs the nested .app correctly.
# Uses hdiutil (ships with macOS) so there's no extra dependency.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

APP="$(find "$REPO/dist/electron" -maxdepth 2 -name "Maknassa.app" -print -quit)"
DMG="$REPO/dist/Maknassa.dmg"

if [ -z "$APP" ] || [ ! -d "$APP" ]; then
  echo "error: Maknassa.app not found under dist/electron — run packaging/build.sh on macOS first." >&2
  exit 1
fi

BROWSERS="$REPO/packaging/ms-playwright"
if [ -d "$BROWSERS" ]; then
  # The frozen backend reads <bundle>/ms-playwright (sys._MEIPASS = _internal/).
  BACKEND_ROOT="$APP/Contents/Resources/backend/_internal"
  if [ ! -d "$BACKEND_ROOT" ]; then
    echo "error: $BACKEND_ROOT not found — was the backend embedded via extraResources?" >&2
    exit 1
  fi
  echo ">> Injecting bundled Chromium into the frozen backend"
  rm -rf "$BACKEND_ROOT/ms-playwright"
  cp -R "$BROWSERS" "$BACKEND_ROOT/ms-playwright"
  # Headless runs use the full Chromium (channel="chromium" in browser.py); the
  # headless-shell build is ~250 MB of dead weight, mirror backend.spec and drop it.
  rm -rf "$BACKEND_ROOT/ms-playwright/chromium_headless_shell-"*
else
  echo "warning: $BROWSERS missing — DMG will have no bundled Chromium." >&2
fi

echo ">> Ad-hoc signing the app (arm64 requires a valid signature; --deep covers nested .apps)"
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"   # drag-target in the DMG window

rm -f "$DMG"
hdiutil create -volname "Maknassa" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
echo ">> Done: $DMG"
