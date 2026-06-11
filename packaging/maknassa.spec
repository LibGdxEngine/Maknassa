# PyInstaller spec for the Maknassa desktop app (one-folder build).
#
# Builds a native-window Streamlit app that bundles the Playwright Chromium so the
# end-user needs no separate `playwright install`. Build with:
#
#     python -m PyInstaller --noconfirm --clean packaging/maknassa.spec
#
# (packaging/build.sh wraps this and installs the browser first.)
#
# Streamlit is notoriously lazy-import-heavy; `collect_all` + `copy_metadata`
# cover the known cases. If the FIRST build on a platform reports a
# ModuleNotFoundError at runtime, add that module to `hiddenimports` below — this
# is expected for a Streamlit freeze and is the one manual step the plan calls out.

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

REPO = Path(SPECPATH).parent  # packaging/ -> repo root
ICON_DIR = REPO / "packaging" / "icons"
# Per-OS icon for the executable / .app (None if the file is missing -> default icon).
_WIN_ICON = ICON_DIR / "maknassa.ico"
_MAC_ICON = ICON_DIR / "maknassa.icns"
EXE_ICON = str(_WIN_ICON) if _WIN_ICON.exists() else None
MAC_ICON = str(_MAC_ICON) if _MAC_ICON.exists() else None

datas = []
binaries = []
# streamlit_app.py ships as DATA (never analyzed by PyInstaller), so every
# reactions.* module it imports must be forced in — a hand-picked list silently
# drops whatever the UI imports next (v1.0.0 shipped without reactions.ui_fetch).
hiddenimports = collect_submodules("reactions")

# Pull data files, binaries, and submodules for the heavy/lazy packages.
# NB: pandas/pyarrow/altair are deliberately NOT collected — they back Streamlit's
# dataframe & chart features, which this app never uses (it renders images,
# checkboxes, and columns). Excluding them (see `excludes` below) drops ~200 MB of
# uncompressed bundle. numpy stays: st.image() needs it to marshal avatar images.
for pkg in (
    "streamlit",
    "playwright",
    "playwright_stealth",
    "pydantic",
    "tenacity",
    "platformdirs",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Streamlit reads its own (and friends') distribution metadata at runtime.
for dist in ("streamlit", "playwright", "pydantic", "platformdirs", "pywebview"):
    datas += copy_metadata(dist)

# The UI script must sit at the bundle root so desktop.resolve_script_path()
# finds it at sys._MEIPASS/streamlit_app.py when frozen.
datas += [(str(REPO / "streamlit_app.py"), ".")]

# Bundled Playwright Chromium (build.sh installs it into packaging/ms-playwright).
# desktop._apply_runtime_env() points PLAYWRIGHT_BROWSERS_PATH at this folder.
#
# macOS exception: do NOT bundle it through PyInstaller here. On Apple Silicon
# PyInstaller ad-hoc re-signs every Mach-O it collects, and `codesign` rejects
# Chromium's main executable ("bundle format unrecognized, invalid, or unsuitable")
# because it's the entry binary of a nested .app bundle and must be signed as a
# bundle, not as a bare file. Instead packaging/macos/build_dmg.sh injects Chromium
# into the built .app (beside streamlit_app.py, i.e. the same _MEIPASS root the app
# reads at runtime) and signs the whole app with `codesign --deep`, which handles the
# nested .app correctly. Windows/Linux have no such constraint and bundle it normally.
browsers = REPO / "packaging" / "ms-playwright"
if browsers.exists() and sys.platform != "darwin":
    datas += [(str(browsers), "ms-playwright")]

a = Analysis(
    [str(REPO / "reactions" / "desktop.py")],
    pathex=[str(REPO)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Drop dev tools and Streamlit's unused dataframe/chart stack (see note above).
    excludes=["pytest", "mypy", "ruff", "PyInstaller", "pandas", "pyarrow", "altair"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="maknassa-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # strip ELF/Mach-O symbols to shrink the bundle (safe; app is unsigned)
    upx=False,
    console=False,  # GUI app: no console window. Flip to True to debug a frozen build.
    icon=EXE_ICON,  # used on Windows; ignored on Linux. macOS icon is set on the BUNDLE.
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=True,
    upx=False,
    name="maknassa",
)

# macOS: wrap the one-folder build into a proper Maknassa.app so it can be dragged
# into /Applications and packaged into a .dmg. No-op on Linux/Windows.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Maknassa.app",
        icon=MAC_ICON,
        bundle_identifier="com.maknassa.app",
        info_plist={
            "CFBundleName": "Maknassa",
            "CFBundleDisplayName": "Maknassa",
            "CFBundleShortVersionString": "1.0.0",
            "NSHighResolutionCapable": True,
        },
    )
