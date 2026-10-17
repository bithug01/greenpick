"""Render the GreenPick logo to a transparent PNG using only Pillow (no native SVG deps).

Reproduces docs/img/logo.svg geometry: an ovate leaf (cubic-Bezier outline sampled to a polygon),
a small angled stem, irregular white circuit traces, and hollow via pads. The whole mark is rotated
+38deg about the canvas centre, matching the SVG's transform.
"""
from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw

GREEN = (22, 163, 74, 255)      # #16a34a
STEM = (21, 128, 61, 255)       # #15803d
WHITE = (255, 255, 255, 255)

SS = 4                           # supersample factor for smooth edges
OUT_PX = 512                     # final size
C = OUT_PX * SS / 2              # canvas centre (supersampled)
ANGLE = math.radians(38)         # SVG rotate(38)

# --- SVG was viewBox 0..300; mark group was translate(150,150) rotate(38) translate(-70,-120).
# So a point (x,y) in leaf-local coords maps: subtract (70,120), rotate +38, add (150,150),
# then scale to the supersampled canvas (300 -> OUT_PX*SS).
S = OUT_PX * SS / 300.0


def tx(x: float, y: float) -> tuple[float, float]:
    lx, ly = x - 70.0, y - 120.0
    rx = lx * math.cos(ANGLE) - ly * math.sin(ANGLE)
    ry = lx * math.sin(ANGLE) + ly * math.cos(ANGLE)
    return ((rx + 150.0) * S, (ry + 150.0) * S)


def cubic(p0, p1, p2, p3, n=24):
    out = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        x = (mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0])
        y = (mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1])
        out.append((x, y))
    return out


# Leaf outline (matches the SVG path's cubic segments), sampled to a polygon.
leaf_pts = []
leaf_pts += cubic((70, 18), (118, 54), (140, 112), (110, 176))
leaf_pts += cubic((110, 176), (100, 198), (84, 210), (70, 214))
leaf_pts += cubic((70, 214), (56, 210), (40, 198), (30, 176))
leaf_pts += cubic((30, 176), (0, 112), (22, 54), (70, 18))

# Circuit traces (polylines) and via pads (cx,cy,r) — straight from the SVG.
traces = [
    [(68, 206), (68, 176), (58, 164), (58, 132), (72, 118), (72, 92), (64, 82), (64, 52), (74, 40), (74, 30)],
    [(58, 164), (40, 164), (32, 154)],
    [(58, 150), (80, 150), (92, 138)],
    [(72, 118), (94, 118), (102, 110), (102, 100)],
    [(72, 108), (54, 108), (46, 100)],
    [(64, 82), (84, 82), (90, 76)],
    [(64, 70), (48, 70), (42, 62), (42, 54)],
    [(74, 52), (90, 52)],
    [(58, 140), (50, 132)],
    [(72, 100), (78, 94)],
    [(68, 190), (82, 190), (88, 184)],
]
pads = [(74, 30, 4.6), (68, 206, 4.6), (32, 154, 3.6), (92, 138, 3.6), (102, 100, 3.6),
        (46, 100, 3.2), (90, 76, 3.2), (42, 54, 3.6), (90, 52, 3.2), (50, 132, 2.9),
        (78, 94, 2.9), (88, 184, 3.2)]
stem = [(70, 226), (76, 216), (74, 206), (62, 196)]  # bezier ctrl pts; sample it


def draw(img_draw):
    # stem (sampled bezier), green-dark, round caps approximated by thick line
    sp = cubic((70, 226), (76, 216), (74, 206), (62, 196), n=20)
    _polyline(img_draw, sp, STEM, 6)
    # leaf body
    img_draw.polygon([tx(x, y) for (x, y) in leaf_pts], fill=GREEN)
    # traces (white)
    for tr in traces:
        _polyline(img_draw, tr, WHITE, 3)
    # hollow pads: green fill + white ring
    for cx, cy, r in pads:
        _ring(img_draw, cx, cy, r, ring=WHITE, fill=GREEN, rw=2.4)


def _polyline(d, pts, color, w):
    sp = [tx(x, y) for (x, y) in pts]
    wpx = w * S
    d.line(sp, fill=color, width=max(1, int(round(wpx))), joint="curve")
    # round the ends/joints with dots
    r = wpx / 2
    for (x, y) in sp:
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def _ring(d, cx, cy, r, ring, fill, rw):
    x, y = tx(cx, cy)
    R = r * S
    d.ellipse([x - R, y - R, x + R, y + R], fill=ring)
    inner = R - rw * S
    if inner > 0:
        d.ellipse([x - inner, y - inner, x + inner, y + inner], fill=fill)


def main():
    big = Image.new("RGBA", (OUT_PX * SS, OUT_PX * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    draw(d)
    out = Path("docs/img")
    for name, px in [("logo.png", 512), ("logo-256.png", 256)]:
        img = big.resize((px, px), Image.LANCZOS)
        img.save(out / name)
        print("wrote", out / name, f"{px}x{px}")


if __name__ == "__main__":
    main()
