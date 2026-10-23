"""PNG launcher icons for Android 7.0/7.1 (API 24-25), from the brand mark (ADR-570).

    python3 design/build_launcher_bitmaps.py      # needs Pillow; run when the mark changes

Android 8+ uses the adaptive icon that build_brand_assets.py writes (vector
XML). API 24-25 predate adaptive icons and need bitmaps, which need a
rasteriser. That is why this is a separate script: build_brand_assets.py stays
pure standard library so CI's "Design tokens" job can --check it without a
pip install. The PNGs are committed; tests/test_adr570 checks their sizes and
that none is still React Native's default robot.

The geometry is imported from build_brand_assets.py, never restated.
"""
from __future__ import annotations

import json
import pathlib

from PIL import Image, ImageDraw

import build_brand_assets as B

SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
SS = 8                       # supersampling factor; drawn large, then downsampled
MARK_SCALE = 0.62            # the mark's ink spans ~62% of the icon's width


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _draw(size: int, round_: bool, navy: str, gold: str) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = big * 2 / 48                                # legacy icons keep a 2/48 margin
    if round_:
        d.ellipse([pad, pad, big - pad, big - pad], fill=_rgb(navy))
    else:
        d.rounded_rectangle([pad, pad, big - pad, big - pad], radius=big * 0.18, fill=_rgb(navy))

    k = big * MARK_SCALE / (42.3 - 2.8)               # 48-unit ink width -> pixels
    ox, oy = big / 2 - B._INK_CX * k, big / 2 - B._INK_CY * k
    P = lambda x, y: (ox + x * k, oy + y * k)
    w = max(1, round(2.6 * k))

    def line(a, b, colour):
        d.line([P(*a), P(*b)], fill=colour, width=w)
        for x, y in (a, b):                            # round caps
            cx, cy = P(x, y)
            d.ellipse([cx - w / 2, cy - w / 2, cx + w / 2, cy + w / 2], fill=colour)

    def rrect(x, y, ww, hh, r, colour):
        (x0, y0), (x1, y1) = P(x, y), P(x + ww, y + hh)
        d.rounded_rectangle([x0, y0, x1, y1], radius=r * k, fill=colour)

    g, white = _rgb(gold), (255, 255, 255)
    for a, b in B._LINES_IN:
        line(a, b, g)
    for x, y in B._DOTS:
        cx, cy = P(x, y)
        d.ellipse([cx - 2.2 * k, cy - 2.2 * k, cx + 2.2 * k, cy + 2.2 * k], fill=g)
    rrect(*B._BLOCK, white)
    rrect(*B._CORE, _rgb(navy))
    line(*B._LINE_OUT, white)
    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    spec = json.loads(B.SPEC.read_text())
    navy, gold = B.hex_colour(spec, "light", "primary"), B.hex_colour(spec, "dark", "gold")
    for density, px in SIZES.items():
        folder = B.ANDROID_RES / f"mipmap-{density}"
        folder.mkdir(parents=True, exist_ok=True)
        for name, round_ in (("ic_launcher.png", False), ("ic_launcher_round.png", True)):
            _draw(px, round_, navy, gold).save(folder / name, optimize=True)
            print(f"  wrote {(folder / name).relative_to(B.REPO)} ({px}px)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
