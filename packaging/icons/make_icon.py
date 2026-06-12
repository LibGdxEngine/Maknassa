"""Derive Maknassa's per-OS icon files from the canonical artwork.

``maknassa.png`` in this folder is the committed source of truth (any square
PNG); the Windows ``.ico`` and macOS ``.icns`` that electron-builder embeds
(see app/electron-builder.yml) are derived from it. Re-run after replacing
the artwork::

    python packaging/icons/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> None:
    art = Image.open(HERE / "maknassa.png").convert("RGBA")
    if art.width != art.height:
        raise SystemExit(f"artwork must be square, got {art.width}x{art.height}")
    art.save(HERE / "maknassa.ico", sizes=ICO_SIZES)
    try:
        art.save(HERE / "maknassa.icns")
    except Exception as exc:  # noqa: BLE001 - ICNS save is best-effort off-macOS
        print(f"note: could not write .icns here ({exc}); generate it on macOS/CI.")
    print(f"derived maknassa.ico + maknassa.icns from maknassa.png in {HERE}")


if __name__ == "__main__":
    main()
