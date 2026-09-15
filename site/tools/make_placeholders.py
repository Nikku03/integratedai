"""
Generate abstract placeholder "renders" for the portfolio.

These are deliberately non-photographic: layered washes, light shafts and
furniture silhouettes in each sector's palette. Replace any of them by
dropping a JPG/WebP with the same filename into assets/img/ (see site/README.md).

    python3 site/tools/make_placeholders.py
"""
from __future__ import annotations

import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "img"

# name, sector, base, mid, accent, glow
PROJECTS = [
    ("hero-01",        "restaurant", "#1b1512", "#3a2a22", "#c8793f", "#f2c28a"),
    ("hero-02",        "bar",        "#0f1016", "#26202f", "#7c5cff", "#3ad6c2"),
    ("hero-03",        "retail",     "#15170f", "#2f3323", "#a6b37a", "#e8d9b4"),
    ("rest-ember",     "restaurant", "#1c1410", "#4a2e1f", "#d47a3a", "#f5c078"),
    ("rest-salt",      "restaurant", "#171614", "#3f3a30", "#c9b48a", "#f0e5cc"),
    ("rest-verano",    "restaurant", "#1a1715", "#59392a", "#e0955b", "#ffd6a3"),
    ("rest-nori",      "restaurant", "#121514", "#243330", "#6fa08d", "#d4e8dc"),
    ("bar-velvet",     "bar",        "#120c14", "#3a1d3c", "#c0489a", "#ff9ed8"),
    ("bar-ninety",     "bar",        "#0d1218", "#1b2a3b", "#3aa0d9", "#a9e4ff"),
    ("bar-tempo",      "bar",        "#141014", "#33222e", "#e0653c", "#ffc3a1"),
    ("bar-lumen",      "bar",        "#0f1210", "#1f2d24", "#5fd68a", "#d5ffe4"),
    ("shop-form",      "retail",     "#181614", "#3a352d", "#d8c9a8", "#fff5e0"),
    ("shop-atlas",     "retail",     "#121417", "#2b3038", "#8aa2c2", "#dbe7f7"),
    ("shop-clay",      "retail",     "#1a1512", "#4e3527", "#c67e5a", "#f7c7a8"),
    ("shop-grove",     "retail",     "#12160f", "#26301e", "#8fb06b", "#e2f2c8"),
    ("studio-team",    "studio",     "#161514", "#33302c", "#bfae94", "#eee4d2"),
    ("studio-process", "studio",     "#131517", "#2a2f36", "#98a6b8", "#e1e8f0"),
    ("texture-grain",  "misc",       "#151413", "#2a2725", "#8c7f6c", "#d8cdb8"),
]

W, H = 1600, 1100


def rect(x, y, w, h, fill, op=1.0, rx=0):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" opacity="{op:.2f}" rx="{rx}"/>')


def build(name, sector, base, mid, accent, glow, seed):
    rnd = random.Random(seed)
    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                 f'width="{W}" height="{H}" role="img" aria-label="{name} placeholder render">')
    parts.append(f'''<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{mid}"/><stop offset="1" stop-color="{base}"/>
  </linearGradient>
  <radialGradient id="glow" cx="{rnd.uniform(0.2,0.8):.2f}" cy="{rnd.uniform(0.1,0.5):.2f}" r="0.7">
    <stop offset="0" stop-color="{glow}" stop-opacity="0.55"/>
    <stop offset="0.5" stop-color="{accent}" stop-opacity="0.18"/>
    <stop offset="1" stop-color="{base}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="shaft" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{glow}" stop-opacity="0.35"/>
    <stop offset="1" stop-color="{glow}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{base}" stop-opacity="0"/>
    <stop offset="1" stop-color="#000" stop-opacity="0.65"/>
  </linearGradient>
  <filter id="grain">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="{seed}" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
    <feComponentTransfer><feFuncA type="linear" slope="0.14"/></feComponentTransfer>
    <feBlend in2="SourceGraphic" mode="overlay"/>
  </filter>
  <filter id="soft"><feGaussianBlur stdDeviation="28"/></filter>
</defs>''')
    parts.append(rect(0, 0, W, H, "url(#bg)"))
    parts.append(rect(0, 0, W, H, "url(#glow)"))

    # light shafts
    for _ in range(rnd.randint(2, 4)):
        x = rnd.uniform(0, W)
        w = rnd.uniform(60, 220)
        skew = rnd.uniform(-18, 18)
        parts.append(f'<g transform="translate({x:.0f} 0) skewX({skew:.1f})">'
                     f'{rect(0, 0, w, H, "url(#shaft)", 0.9)}</g>')

    # horizon / floor line
    horizon = rnd.uniform(0.58, 0.72) * H
    parts.append(rect(0, horizon, W, H - horizon, "url(#floor)"))

    # furniture silhouettes: tables, seating, counters, shelving
    n = rnd.randint(6, 11)
    for i in range(n):
        w = rnd.uniform(90, 360)
        h = rnd.uniform(40, 260)
        x = rnd.uniform(-40, W - w + 40)
        y = horizon - h + rnd.uniform(-20, 80)
        shade = rnd.choice(["#000", "#000", base, mid])
        op = rnd.uniform(0.25, 0.7)
        parts.append(rect(x, y, w, h, shade, op, rx=rnd.choice([0, 0, 6, 120])))

    # pendant lights / accent discs
    for _ in range(rnd.randint(2, 5)):
        cx = rnd.uniform(100, W - 100)
        cy = rnd.uniform(80, horizon * 0.65)
        r = rnd.uniform(14, 48)
        parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r*3:.0f}" fill="{glow}" '
                     f'opacity="0.18" filter="url(#soft)"/>')
        parts.append(f'<line x1="{cx:.0f}" y1="0" x2="{cx:.0f}" y2="{cy - r:.0f}" '
                     f'stroke="{accent}" stroke-opacity="0.35" stroke-width="2"/>')
        parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{glow}" opacity="0.9"/>')

    # accent block (a wall panel / bar front)
    aw = rnd.uniform(240, 620)
    ax = rnd.uniform(0, W - aw)
    parts.append(rect(ax, horizon - rnd.uniform(160, 420), aw, 520, accent, 0.22))

    # vignette + grain
    parts.append(rect(0, 0, W, H, "#000", 0.0))
    parts.append(f'<rect width="{W}" height="{H}" fill="{base}" opacity="0.001" filter="url(#grain)"/>')
    parts.append('</svg>')
    return "\n".join(parts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (name, sector, base, mid, accent, glow) in enumerate(PROJECTS):
        svg = build(name, sector, base, mid, accent, glow, seed=100 + i)
        (OUT / f"{name}.svg").write_text(svg)
        print("wrote", name)


if __name__ == "__main__":
    main()
