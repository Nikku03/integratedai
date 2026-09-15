"""
Generate abstract placeholder "renders" for the portfolio.

Deliberately non-photographic: layered washes, light shafts and furniture
silhouettes in the room's time-of-day palette (morning café, afternoon
restaurant, night bar, sage shop). Replace any of them by dropping a JPG/WebP
with the same filename into assets/img/ (see site/README.md).

    python3 site/tools/make_placeholders.py
"""
from __future__ import annotations

import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "img"

# Palettes: (base, mid, accent, glow, silhouette). Light themes read well on the
# off-white site; the bar/night set stays dark on purpose.
MORNING   = ("#efe7d2", "#f7f1e1", "#8fa07c", "#fff3cf", "#46523d")
AFTERNOON = ("#e7cfa9", "#f2dfbf", "#b9722f", "#ffd79a", "#4a3a2a")
NIGHT     = ("#141c17", "#233129", "#46523d", "#f0c070", "#0b100d")
SAGE      = ("#e3e6d8", "#eff0e6", "#7f8f66", "#f6f4e6", "#3b4634")
STUDIO    = ("#ece9df", "#f4f2ec", "#46523d", "#fbf7ea", "#2c3428")

# name, palette
PROJECTS = [
    ("hero-01",        AFTERNOON),
    ("hero-02",        NIGHT),
    ("hero-03",        SAGE),
    ("cafe-morning",   MORNING),
    ("rest-ember",     AFTERNOON),
    ("rest-salt",      MORNING),
    ("rest-verano",    AFTERNOON),
    ("rest-nori",      SAGE),
    ("bar-velvet",     NIGHT),
    ("bar-ninety",     NIGHT),
    ("bar-tempo",      NIGHT),
    ("bar-lumen",      NIGHT),
    ("shop-form",      SAGE),
    ("shop-atlas",     STUDIO),
    ("shop-clay",      AFTERNOON),
    ("shop-grove",     SAGE),
    ("studio-team",    STUDIO),
    ("studio-process", STUDIO),
    ("texture-grain",  SAGE),
]

W, H = 1600, 1100


def rect(x, y, w, h, fill, op=1.0, rx=0):
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'fill="{fill}" opacity="{op:.2f}" rx="{rx}"/>')


def build(name, pal, seed):
    base, mid, accent, glow, sil = pal
    dark = base.lower() in ("#141c17",)
    rnd = random.Random(seed)
    parts = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
                 f'width="{W}" height="{H}" role="img" aria-label="{name} placeholder render">')
    parts.append(f'''<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{mid}"/><stop offset="1" stop-color="{base}"/>
  </linearGradient>
  <radialGradient id="glow" cx="{rnd.uniform(0.2,0.8):.2f}" cy="{rnd.uniform(0.1,0.5):.2f}" r="0.7">
    <stop offset="0" stop-color="{glow}" stop-opacity="{0.7 if dark else 0.9}"/>
    <stop offset="0.5" stop-color="{glow}" stop-opacity="0.25"/>
    <stop offset="1" stop-color="{base}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="shaft" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{glow}" stop-opacity="{0.4 if dark else 0.55}"/>
    <stop offset="1" stop-color="{glow}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="floor" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0" stop-color="{sil}" stop-opacity="0"/>
    <stop offset="1" stop-color="{sil}" stop-opacity="{0.7 if dark else 0.28}"/>
  </linearGradient>
  <filter id="grain">
    <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="{seed}" stitchTiles="stitch"/>
    <feColorMatrix type="saturate" values="0"/>
    <feComponentTransfer><feFuncA type="linear" slope="0.12"/></feComponentTransfer>
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

    # horizon / floor
    horizon = rnd.uniform(0.58, 0.72) * H
    parts.append(rect(0, horizon, W, H - horizon, "url(#floor)"))

    # furniture silhouettes: tables, seating, counters, shelving
    n = rnd.randint(6, 11)
    for i in range(n):
        w = rnd.uniform(90, 360)
        h = rnd.uniform(40, 260)
        x = rnd.uniform(-40, W - w + 40)
        y = horizon - h + rnd.uniform(-20, 80)
        shade = rnd.choice([sil, sil, accent])
        op = rnd.uniform(0.35, 0.75) if dark else rnd.uniform(0.18, 0.45)
        parts.append(rect(x, y, w, h, shade, op, rx=rnd.choice([0, 0, 6, 120])))

    # pendant lights
    for _ in range(rnd.randint(2, 5)):
        cx = rnd.uniform(100, W - 100)
        cy = rnd.uniform(80, horizon * 0.65)
        r = rnd.uniform(14, 48)
        parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r*3:.0f}" fill="{glow}" '
                     f'opacity="{0.28 if dark else 0.5}" filter="url(#soft)"/>')
        parts.append(f'<line x1="{cx:.0f}" y1="0" x2="{cx:.0f}" y2="{cy - r:.0f}" '
                     f'stroke="{sil}" stroke-opacity="0.5" stroke-width="2"/>')
        parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{glow}" opacity="0.95"/>')

    # accent block (a wall panel / bar front)
    aw = rnd.uniform(240, 620)
    ax = rnd.uniform(0, W - aw)
    parts.append(rect(ax, horizon - rnd.uniform(160, 420), aw, 520, accent, 0.3))

    parts.append(f'<rect width="{W}" height="{H}" fill="{base}" opacity="0.001" filter="url(#grain)"/>')
    parts.append('</svg>')
    return "\n".join(parts)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (name, pal) in enumerate(PROJECTS):
        (OUT / f"{name}.svg").write_text(build(name, pal, seed=100 + i))
        print("wrote", name)


if __name__ == "__main__":
    main()
