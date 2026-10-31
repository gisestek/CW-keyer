"""Generate the CW Station app icon: a relay whose coil-to-contact linkage is the Morse letter K (-.-).

    python packaging/make_icon.py

Writes cwstation/assets/: icon.svg (master), icon-<size>.png and icon.ico.
Palette "panel grey": light grey tile, black symbol, red Morse linkage.
Sizes up to 32 px use a bolder drawing (16 px a pixel-aligned one) so the lines stay crisp on the taskbar.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "cwstation" / "assets"
BG, BORDER, FG, ACCENT = "#C9CCD1", "#9CA0A6", "#1C1C1C", "#D7263D"
GRID = 160  # design grid, tile = 0..160

# (x1, y1, x2, y2) segments on the 160 grid; a zero-length segment is a dit
REGULAR = dict(
    stroke=5, border=1.5,
    lines=[(42, 28, 42, 62), (42, 98, 42, 132),             # coil leads
           (130, 28, 130, 64), (130, 98, 130, 132),         # contact terminals
           (130, 98, 114, 66)],                             # contact lever (open)
    coil=(22, 62, 62, 98),
    morse=[(68, 82, 80, 82), (88, 82, 88, 82), (96, 82, 108, 82)],  # K = dah dit dah
)
BOLD = dict(
    stroke=10, border=6,
    lines=[(34, 22, 34, 56), (34, 104, 34, 138),
           (140, 22, 140, 60), (140, 100, 140, 138),
           (140, 100, 124, 62)],
    coil=(18, 56, 50, 104),
    morse=[(64, 80, 74, 80), (92, 80, 92, 80), (109, 80, 119, 80)],
)
# 16 px: every stroke sits on whole pixels (1 px = 10 units), so dah-dit-dah stays three separate marks
TINY = dict(
    stroke=10, border=6,
    lines=[(25, 25, 25, 55), (25, 105, 25, 135),
           (135, 25, 135, 65), (135, 105, 135, 135),
           (135, 105, 125, 65)],
    coil=(15, 55, 35, 105),
    morse=[(55, 85, 65, 85), (85, 85, 85, 85), (105, 85, 115, 85)],
)
SIZES = [16, 20, 24, 32, 48, 64, 128, 256, 512, 1024]
ICO_SIZES = [16, 20, 24, 32, 48, 64, 128, 256]


def svg(v: dict) -> str:
    s = v["stroke"]
    seg = lambda x1, y1, x2, y2, c: (f'<line x1="{x1}" y1="{y1}" x2="{x2 + (0.01 if (x1, y1) == (x2, y2) else 0)}" '
                                     f'y2="{y2}" stroke="{c}" stroke-width="{s}" stroke-linecap="round"/>')
    x1, y1, x2, y2 = v["coil"]
    b = v["border"]
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {GRID} {GRID}" width="{GRID}" height="{GRID}">',
             '<title>CW Station</title>',
             f'<rect x="{b / 2}" y="{b / 2}" width="{GRID - b}" height="{GRID - b}" rx="28" fill="{BG}" '
             f'stroke="{BORDER}" stroke-width="{b}"/>',
             *(seg(*l, FG) for l in v["lines"]),
             f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" rx="2" fill="none" stroke="{FG}" '
             f'stroke-width="{s}"/>',
             *(seg(*m, ACCENT) for m in v["morse"]),
             '</svg>']
    return "\n".join(parts) + "\n"


def render(v: dict, size: int, ss: int = 8) -> Image.Image:
    n = size * ss
    k = n / GRID
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    b = v["border"] * k
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=28 * k, fill=BORDER)
    d.rounded_rectangle((b, b, n - 1 - b, n - 1 - b), radius=28 * k - b, fill=BG)
    w = v["stroke"] * k

    def seg(x1, y1, x2, y2, c):
        p1, p2 = (x1 * k, y1 * k), (x2 * k, y2 * k)
        if p1 != p2:
            d.line((p1, p2), fill=c, width=round(w))
        for x, y in (p1, p2):  # round caps
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=c)

    for l in v["lines"]:
        seg(*l, FG)
    x1, y1, x2, y2 = (c * k for c in v["coil"])
    d.rectangle((x1 - w / 2, y1 - w / 2, x2 + w / 2, y2 + w / 2), outline=FG, width=round(w))
    for m in v["morse"]:
        seg(*m, ACCENT)
    return im.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "icon.svg").write_text(svg(REGULAR), encoding="utf-8")
    (OUT / "icon-small.svg").write_text(svg(BOLD), encoding="utf-8")
    images = {}
    for size in SIZES:
        images[size] = render(TINY if size == 16 else BOLD if size <= 32 else REGULAR, size)
        images[size].save(OUT / f"icon-{size}.png")
    ico = [images[s] for s in ICO_SIZES]
    ico[-1].save(OUT / "icon.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=ico[:-1])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
