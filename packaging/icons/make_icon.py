"""Generate Maknassa's placeholder app icon in PNG / ICO / ICNS.

A simple, recognizable mark — a rounded indigo tile with a white "block" symbol
(circle + diagonal slash), echoing the app's 🚫 motif. Replace the output files
with real artwork any time; the build references whatever sits in this folder.

Run from the repo root (Pillow ships with Streamlit, so it's already installed)::

    python packaging/icons/make_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
SIZE = 1024
BG = (79, 70, 229)  # indigo-600
FG = (255, 255, 255)


def render(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Rounded-square background tile.
    pad = int(size * 0.06)
    radius = int(size * 0.22)
    draw.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=BG)
    # "Block" symbol: ring + diagonal slash.
    ring = int(size * 0.10)
    box = [int(size * 0.27), int(size * 0.27), int(size * 0.73), int(size * 0.73)]
    draw.ellipse(box, outline=FG, width=ring)
    off = int(size * 0.105)  # pull the slash inside the ring's stroke
    draw.line([box[0] + off, box[1] + off, box[2] - off, box[3] - off], fill=FG, width=ring)
    return img


def main() -> None:
    base = render()
    base.save(HERE / "maknassa.png")
    base.save(
        HERE / "maknassa.ico",
        sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    try:
        base.save(HERE / "maknassa.icns")
    except Exception as exc:  # noqa: BLE001 - ICNS save is best-effort on this platform
        print(f"note: could not write .icns here ({exc}); CI/macOS will generate it.")
    print(f"wrote icons to {HERE}")


if __name__ == "__main__":
    main()
