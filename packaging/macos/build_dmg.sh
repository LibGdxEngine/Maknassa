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

# Inject the bundled Chromium into the .app. PyInstaller can't bundle it on macOS
# (maknassa.spec skips it there): it ad-hoc re-signs every collected Mach-O, and
# codesign rejects Chromium's inner executable because it's the entry binary of a
# nested .app. So we copy Chromium in here, beside streamlit_app.py — i.e. at the same
# _MEIPASS root that reactions.desktop.resolve_browsers_path() reads at runtime
# (bundle_dir()/ms-playwright) — then sign the whole app, which signs the nested
# Chromium .app correctly (unlike PyInstaller's per-file approach).
BROWSERS="$REPO/packaging/ms-playwright"
if [ -d "$BROWSERS" ]; then
  MEIPASS="$(dirname "$(find "$APP/Contents" -name streamlit_app.py -print -quit)")"
  if [ ! -d "$MEIPASS" ]; then
    echo "error: streamlit_app.py not found in $APP — can't locate the bundle root." >&2
    exit 1
  fi
  echo ">> Injecting bundled Chromium into ${MEIPASS#$REPO/}/ms-playwright"
  rm -rf "$MEIPASS/ms-playwright"
  cp -R "$BROWSERS" "$MEIPASS/ms-playwright"
  echo ">> Ad-hoc signing the app (arm64 requires a valid signature; --deep covers the nested Chromium .app)"
  xattr -cr "$APP"                       # strip detritus codesign would reject
  codesign --force --deep --sign - "$APP"
else
  echo "warning: $BROWSERS missing — DMG will have no bundled Chromium." >&2
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
cp -R "$APP" "$STAGING/"
ln -s /Applications "$STAGING/Applications"   # drag-target in the DMG window

rm -f "$DMG"
hdiutil create -volname "Maknassa" -srcfolder "$STAGING" -ov -format UDZO "$DMG"
echo ">> Done: $DMG"
