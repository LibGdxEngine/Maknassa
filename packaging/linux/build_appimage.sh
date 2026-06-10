#!/usr/bin/env bash
# Package the PyInstaller one-folder build (dist/maknassa/) into a single-file,
# double-click Maknassa.AppImage.
#
#   bash packaging/build.sh                 # produces dist/maknassa/
#   bash packaging/linux/build_appimage.sh  # produces dist/Maknassa.AppImage
#
# appimagetool is downloaded on demand if not on PATH. The version-less output name
# keeps the "latest" download link stable.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

DIST="$REPO/dist/maknassa"
APPDIR="$REPO/dist/Maknassa.AppDir"
OUT="$REPO/dist/Maknassa.AppImage"

if [ ! -d "$DIST" ]; then
  echo "error: $DIST not found — run packaging/build.sh first." >&2
  exit 1
fi

echo ">> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$DIST/." "$APPDIR/usr/bin/"
cp "$REPO/packaging/icons/maknassa.png" "$APPDIR/maknassa.png"

cat > "$APPDIR/maknassa.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Maknassa
Comment=Review and block the people who reacted to your Facebook post
Exec=maknassa-gui
Icon=maknassa
Categories=Utility;Network;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/maknassa-gui" "$@"
EOF
chmod +x "$APPDIR/AppRun"

# Pinned appimagetool, verified by SHA-256 so the build can't pull an unexpected
# binary (it runs in CI with a release-writing token). Bump both together to update.
AIT_VERSION="1.9.0"
AIT_SHA256="46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"
AIT_URL="https://github.com/AppImage/appimagetool/releases/download/${AIT_VERSION}/appimagetool-x86_64.AppImage"

echo ">> Locating appimagetool"
TOOL="$(command -v appimagetool || true)"
if [ -z "$TOOL" ]; then
  TOOL="$REPO/dist/appimagetool"
  if [ ! -x "$TOOL" ]; then
    echo ">> Downloading appimagetool ${AIT_VERSION}"
    curl -fsSL -o "$TOOL" "$AIT_URL"
    echo "${AIT_SHA256}  ${TOOL}" | sha256sum -c - \
      || { echo "error: appimagetool checksum mismatch — refusing to run." >&2; rm -f "$TOOL"; exit 1; }
    chmod +x "$TOOL"
  fi
fi

echo ">> Building $OUT"
rm -f "$OUT"
# EXTRACT_AND_RUN lets appimagetool (itself an AppImage) run on CI runners without FUSE.
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUT"
echo ">> Done: $OUT"
