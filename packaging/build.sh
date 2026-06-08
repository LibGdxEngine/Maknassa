#!/usr/bin/env bash
# Build the Maknassa desktop app (Linux/macOS).
#
#   bash packaging/build.sh
#
# Output: dist/maknassa/  (run dist/maknassa/maknassa-gui)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
cd "$REPO"

echo ">> Installing the app and build deps"
python -m pip install -e ".[build]"

echo ">> Installing Chromium into the bundle ($HERE/ms-playwright)"
export PLAYWRIGHT_BROWSERS_PATH="$HERE/ms-playwright"
python -m playwright install chromium

echo ">> Freezing with PyInstaller"
python -m PyInstaller --noconfirm --clean packaging/maknassa.spec

echo ">> Done. Launch: dist/maknassa/maknassa-gui"
