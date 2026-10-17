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
STEM = (134, 239, 172, 255)     # #86efac (light stem)
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

# midrib is now a single arc (cubic Bezier), sampled to a polyline:
midrib = cubic((68, 206), (58, 150), (66, 78), (74, 30), n=40)

# Circuit branch traces (polylines) and via pads (cx,cy,r) — v7 geometry (no base pad).
traces = [
    [(61, 168), (40, 168), (32, 158)],
    [(62, 150), (82, 150), (92, 140)],
    [(66, 120), (92, 120), (100, 112), (100, 102)],
    [(64, 110), (48, 110), (40, 102)],
    [(69, 84), (88, 84), (94, 78)],
    [(68, 72), (52, 72), (46, 64), (46, 56)],
    [(73, 54), (89, 54)],
    [(61, 142), (53, 134)],
    [(67, 100), (73, 94)],
    [(63, 188), (80, 188), (86, 182)],
]
pads = [(74, 30, 4.6), (32, 158, 3.6), (92, 140, 3.6), (100, 102, 3.6),
        (40, 102, 3.2), (94, 78, 3.2), (46, 56, 3.6), (89, 54, 3.2), (53, 134, 2.9),
        (73, 94, 2.9), (86, 182, 3.2)]


def draw(img_draw):
    # stem (sampled bezier), light green, thinner
    sp = cubic((70, 226), (76, 216), (74, 206), (62, 196), n=20)
    _polyline(img_draw, sp, STEM, 5)
    # leaf body
    img_draw.polygon([tx(x, y) for (x, y) in leaf_pts], fill=GREEN)
    # midrib arc (white)
    _polyline(img_draw, midrib, WHITE, 3.2)
    # branch traces (white)
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
