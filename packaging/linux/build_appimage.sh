#!/usr/bin/env bash
# Pack electron-builder's linux-unpacked output into dist/Maknassa.AppImage with
# appimagetool. electron-builder's own AppImage target embeds the legacy type-2
# runtime that dlopen()s libfuse.so.2 — absent on stock Ubuntu 22.04+ — while
# appimagetool >= 1.9 embeds the new static runtime that needs no FUSE at all
# (and zstd compresses ~15% smaller). build.sh runs this after electron-builder.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

UNPACKED="$REPO/dist/electron/linux-unpacked"
APPDIR="$REPO/dist/Maknassa.AppDir"
OUT="$REPO/dist/Maknassa.AppImage"

if [ ! -x "$UNPACKED/maknassa" ]; then
  echo "error: $UNPACKED not found — run packaging/build.sh first." >&2
  exit 1
fi

echo ">> Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r "$UNPACKED/." "$APPDIR/usr/bin/"
cp "$REPO/packaging/icons/maknassa.png" "$APPDIR/maknassa.png"

cat > "$APPDIR/maknassa.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Maknassa
Comment=Review and block the people who reacted to your Facebook post
Exec=maknassa
Icon=maknassa
Categories=Utility;Network;
Terminal=false
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
# Electron's setuid sandbox helper can't work from an AppImage (squashfs is
# nosuid) and Ubuntu 24.04+ also blocks the unprivileged-userns fallback, so the
# bundled chrome-sandbox aborts. Pass --no-sandbox unconditionally: the renderer
# only ever loads our local bundle and the localhost API, never remote content.
exec "$HERE/usr/bin/maknassa" --no-sandbox "$@"
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
# --comp zstd: smaller image than the default gzip, with fast startup decompression.
# EXTRACT_AND_RUN lets appimagetool (itself an AppImage) run on CI runners without FUSE.
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" --comp zstd "$APPDIR" "$OUT"
rm -rf "$APPDIR"
echo ">> Done: $OUT"
