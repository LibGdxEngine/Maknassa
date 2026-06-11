# PyInstaller spec for the Maknassa backend sidecar (one-folder build).
#
# Freezes `reactions/backend.py` — the localhost FastAPI service the Electron
# shell spawns — together with the Playwright Chromium, WITHOUT the retired
# Streamlit/pywebview stack. Build with:
#
#     python -m PyInstaller --noconfirm --clean packaging/backend.spec
#
# (packaging/build.sh wraps this, installs the browser first, then runs
# electron-builder which embeds dist/maknassa-backend/ via extraResources.)

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

REPO = Path(SPECPATH).parent  # packaging/ -> repo root

datas = []
binaries = []
# The API wraps the whole reactions package; force every submodule in so a new
# import inside the core can never silently drop out of the bundle.
hiddenimports = collect_submodules("reactions")
# uvicorn picks its loop/protocol/lifespan classes via string-based dynamic
# imports PyInstaller can't follow; collect everything (it's small).
hiddenimports += collect_submodules("uvicorn")

for pkg in ("playwright", "playwright_stealth", "pydantic", "tenacity", "platformdirs"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# /api/health reports importlib.metadata.version("maknassa"); playwright and
# friends read their own metadata at runtime too.
for dist in ("maknassa", "playwright", "pydantic", "platformdirs", "fastapi", "uvicorn"):
    datas += copy_metadata(dist)

# Bundled Playwright Chromium (build.sh installs it into packaging/ms-playwright).
# reactions.backend points PLAYWRIGHT_BROWSERS_PATH at <bundle>/ms-playwright when frozen.
#
# macOS exception: PyInstaller ad-hoc re-signs every Mach-O it collects and codesign
# rejects Chromium's nested-.app entry binary, so packaging/macos/build_dmg.sh injects
# Chromium post-build and deep-signs the whole Electron .app instead (same approach
# the retired maknassa.spec used).
browsers = REPO / "packaging" / "ms-playwright"
if browsers.exists() and sys.platform != "darwin":
    datas += [(str(browsers), "ms-playwright")]

a = Analysis(
    [str(REPO / "reactions" / "backend.py")],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "mypy", "ruff", "PyInstaller", "streamlit", "pywebview",
              "pandas", "pyarrow", "altair", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="maknassa-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=False,
    # console=True keeps stdout alive for the PORT/TOKEN handshake (a windowed
    # build has no stdout on Windows). Electron spawns it with windowsHide so
    # no console window ever shows.
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name="maknassa-backend",
)
