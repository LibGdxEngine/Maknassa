#!/usr/bin/env bash
# Build the Maknassa desktop app (Linux/macOS): Electron shell + frozen Python backend.
#
#   bash packaging/build.sh
#
# Output:
#   Linux  -> dist/Maknassa.AppImage
#   macOS  -> dist/electron/mac*/Maknassa.app   (then run packaging/macos/build_dmg.sh)
#
# Pipeline: freeze the FastAPI backend with PyInstaller (bundling the Playwright
# Chromium), then electron-builder packs it into the Electron app via extraResources.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

echo ">> Installing the app and build deps"
python -m pip install -e ".[build]"

echo ">> Installing Chromium into the bundle ($HERE/ms-playwright)"
export PLAYWRIGHT_BROWSERS_PATH="$HERE/ms-playwright"
python -m playwright install chromium

echo ">> Freezing the backend with PyInstaller"
python -m PyInstaller --noconfirm --clean packaging/backend.spec

echo ">> Building the Electron app"
cd "$REPO/app"
npm ci
npm run build

if [ "$(uname)" = "Darwin" ]; then
  # Unsigned build: skip identity discovery; ad-hoc signing happens in build_dmg.sh
  # AFTER Chromium is injected (see backend.spec for why it can't be frozen in).
  export CSC_IDENTITY_AUTO_DISCOVERY=false
  npx electron-builder --mac dir --publish never
  echo ">> Done. Next: bash packaging/macos/build_dmg.sh"
else
  npx electron-builder --linux AppImage --publish never
  cp "$REPO/dist/electron/Maknassa.AppImage" "$REPO/dist/Maknassa.AppImage"
  echo ">> Done: $REPO/dist/Maknassa.AppImage"
fi
