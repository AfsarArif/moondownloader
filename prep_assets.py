"""Turn raw Higgsfield renders into the two assets the GUI loads at startup.

Run once after generation; the GUI itself never touches this file.

*Pillow's Image.getbbox() only reports the non-zero-alpha box AFTER the alpha
channel exists -- on an RGB render it returns the full frame, so the black key
has to happen first.*
"""
from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageFilter

ASSETS = pathlib.Path(__file__).with_name("web") / "assets"
if not ASSETS.parent.is_dir():                 # Tk builds keep them alongside
    ASSETS = pathlib.Path(__file__).with_name("assets")


def key_black_to_alpha(src: Image.Image, floor: int = 10, ceil: int = 62) -> Image.Image:
    """Luminance-keyed alpha: pure black -> transparent, glow -> soft edge.

    floor/ceil bracket the ramp. Below floor the pixel is fully transparent,
    above ceil fully opaque; in between alpha scales linearly so the render's
    outer glow survives instead of being clipped into a hard halo.
    """
    rgb = src.convert("RGB")
    lum = rgb.convert("L")
    span = max(ceil - floor, 1)
    alpha = lum.point(lambda v: 0 if v <= floor else min(255, int((v - floor) * 255 / span)))
    out = rgb.copy()
    out.putalpha(alpha)
    return out


def build_mark(raw: pathlib.Path, size: int = 512) -> pathlib.Path:
    keyed = key_black_to_alpha(Image.open(raw))
    box = keyed.getbbox()
    if box:
        keyed = keyed.crop(box)
    side = max(keyed.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(keyed, ((side - keyed.width) // 2, (side - keyed.height) // 2))
    mark = square.resize((size, size), Image.LANCZOS)
    dest = ASSETS / "mark.png"
    mark.save(dest)
    return dest


def build_backdrop(raw: pathlib.Path, width: int = 1600, height: int = 220) -> pathlib.Path:
    """Crop the render's right-hand nebula into a header-strip band.

    The header is a wide, short canvas; scaling a 16:9 render into it would
    smear the grain, so this takes a band from the vertical centre instead.
    """
    src = Image.open(raw).convert("RGB")
    target_ratio = width / height
    band_h = int(src.width / target_ratio)
    top = max(0, (src.height - band_h) // 2)
    band = src.crop((0, top, src.width, min(src.height, top + band_h)))
    band = band.resize((width, height), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.7))

    # The raw render is far too bright to sit behind a wordmark: pull it toward
    # the window ink, then ramp that pull left-to-right so the left third (logo,
    # title, subtitle) is effectively pure ink and the nebula only shows on the
    # empty right side.
    ink = Image.new("RGB", band.size, (5, 7, 12))
    band = Image.blend(band, ink, 0.55)
    ramp = Image.linear_gradient("L").rotate(-90, expand=True).resize(band.size)
    ramp = ramp.point(lambda v: int(255 - (v * 0.82)))     # 255 at x=0 -> ~46 at x=w
    band = Image.composite(ink, band, ramp)

    dest = ASSETS / "backdrop.png"
    band.save(dest)
    return dest


def build_window(raw: pathlib.Path, width: int = 1500, height: int = 950) -> pathlib.Path:
    """Window ambience: the glow that shows through the gaps between cards.

    Pushed much further toward black than the header band, because this sits
    behind everything and any texture in it competes with the content. The gaps
    are 7-14px wide, so only a broad corner bloom survives at that scale anyway.
    """
    src = Image.open(raw).convert("RGB").resize((width, height), Image.LANCZOS)
    src = src.filter(ImageFilter.GaussianBlur(2.2))
    ink = Image.new("RGB", src.size, (5, 7, 12))
    src = Image.blend(src, ink, 0.72)

    # Radial-ish vignette: darken toward the bottom-left, keep the top-right glow.
    ramp = Image.linear_gradient("L").rotate(-90, expand=True).resize(src.size)
    ramp = ramp.point(lambda v: int(215 - v * 0.7))
    vertical = Image.linear_gradient("L").resize(src.size).point(lambda v: int(v * 0.75))
    mask = Image.blend(ramp, vertical, 0.5)
    src = Image.composite(ink, src, mask)

    dest = ASSETS / "window.png"
    src.save(dest)
    return dest


def main() -> int:
    ASSETS.mkdir(parents=True, exist_ok=True)
    mark_raw = ASSETS / "mark_raw.png"
    back_raw = ASSETS / "backdrop_raw.png"
    window_raw = ASSETS / "window_raw.png"
    if mark_raw.exists():
        print("mark      ->", build_mark(mark_raw))
    else:
        print("mark_raw.png missing", file=sys.stderr)
    if back_raw.exists():
        print("backdrop  ->", build_backdrop(back_raw))
    else:
        print("backdrop_raw.png missing -- header falls back to the painted gradient",
              file=sys.stderr)
    if window_raw.exists():
        print("window    ->", build_window(window_raw))
    else:
        print("window_raw.png missing -- stage falls back to the painted bloom",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
