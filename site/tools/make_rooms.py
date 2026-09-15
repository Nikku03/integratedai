"""
Generate the three illustrated room interiors used behind the door in the
home-page door sequence: room-cafe.svg (08:00), room-restaurant.svg (14:00),
room-bar.svg (23:00). One-point perspective, flat "set design" style.

Replace any of them with a real photo of the same name (or update the src in
index.html). Recommended photo: landscape, 1600px+ wide, the room seen from
the doorway.

    python3 site/tools/make_rooms.py
"""
from __future__ import annotations
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "img"
W, H = 1600, 1000
VPX, VPY = 800, 470      # vanishing point
K = 0.35                 # back-wall scale (depth 1)

def P(x, y, t):
    """Project a front-plane point (x, y) at depth t in [0,1] (1 = back wall)."""
    s = 1 - (1 - K) * t
    return VPX + (x - VPX) * s, VPY + (y - VPY) * s

def pts(*ps):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in ps)

def poly(ps, fill, op=1.0, extra=""):
    return f'<polygon points="{pts(*ps)}" fill="{fill}" opacity="{op:.2f}" {extra}/>'

def ellipse(cx, cy, rx, ry, fill, op=1.0):
    return f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" fill="{fill}" opacity="{op:.2f}"/>'

def rect(x, y, w, h, fill, op=1.0, rx=0):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" opacity="{op:.2f}" rx="{rx}"/>'

ROOMS = {
    "cafe": dict(
        wall="#efe7d4", wall_side="#e4dac2", back="#e9dfc6", ceil="#f3eee2", floor="#d3bf9c", board="rgba(90,70,40,0.18)",
        furn="#46523d", furn2="#5a6850", lamp="#fff1c4", glow="rgba(255,241,196,0.55)", sky_a="#cfe0ea", sky_b="#f6f0dc",
        trim="#46523d", wash="rgba(255,248,224,0.55)", vignette=0.18, night=False, kind="cafe"),
    "restaurant": dict(
        wall="#e3cfae", wall_side="#d5be97", back="#d9bf98", ceil="#e6d8c0", floor="#9e6e44", board="rgba(50,30,15,0.28)",
        furn="#4a3222", furn2="#5a3f2a", lamp="#ffd08a", glow="rgba(255,208,138,0.55)", sky_a="#e6cfae", sky_b="#f0c084",
        trim="#5a3f2a", wash="rgba(255,222,170,0.5)", vignette=0.26, night=False, kind="restaurant"),
    "bar": dict(
        wall="#1d2822", wall_side="#18211c", back="#141c17", ceil="#0f1614", floor="#0f1516", board="rgba(240,192,112,0.06)",
        furn="#0b100d", furn2="#2a2320", lamp="#f0c070", glow="rgba(240,192,112,0.55)", sky_a="#0f1a17", sky_b="#1c2a24",
        trim="rgba(240,192,112,0.5)", wash="rgba(240,192,112,0.28)", vignette=0.55, night=True, kind="bar"),
}

def table(x, t, c, rnd):
    s = 1 - (1 - K) * t
    top = P(x, 1000 - 78, t); base = P(x, 1000, t)
    out = [ellipse(base[0], base[1], 34 * s, 8 * s, "#000", 0.18)]
    out.append(rect(top[0] - 5 * s, top[1], 10 * s, base[1] - top[1], c["furn"]))
    out.append(ellipse(base[0], base[1], 30 * s, 7 * s, c["furn"]))
    out.append(ellipse(top[0], top[1], 70 * s, 16 * s, c["furn"]))
    out.append(ellipse(top[0], top[1] - 2 * s, 70 * s, 14 * s, c["furn2"]))
    return out

def chair(x, t, c, flip=False):
    s = 1 - (1 - K) * t
    seat = P(x, 1000 - 48, t); base = P(x, 1000, t); back = P(x + (-26 if flip else 26), 1000 - 100, t)
    out = [rect(seat[0] - 26 * s, seat[1], 52 * s, 8 * s, c["furn"]),
           rect(seat[0] - 22 * s, seat[1] + 8 * s, 5 * s, base[1] - seat[1] - 8 * s, c["furn"]),
           rect(seat[0] + 17 * s, seat[1] + 8 * s, 5 * s, base[1] - seat[1] - 8 * s, c["furn"]),
           rect(back[0] - 4 * s, back[1], 8 * s, seat[1] - back[1] + 8 * s, c["furn"]),
           rect(back[0] - 4 * s, back[1], 8 * s * (1 if flip else 1), 6 * s, c["furn"])]
    return out

def lamp(x, t, c, drop=300, r=1.0):
    s = 1 - (1 - K) * t
    top = P(x, 0, t); shade = P(x, 1000 - (1000 - drop), t)
    cx, cy = shade
    out = [f'<circle cx="{cx:.1f}" cy="{cy + 40*s:.1f}" r="{230*s*r:.1f}" fill="url(#glow)"/>',
           rect(top[0] - 1.5 * s, top[1], 3 * s, cy - top[1], c["furn"]),
           f'<path d="M{cx-34*s:.1f},{cy:.1f} Q{cx:.1f},{cy+40*s:.1f} {cx+34*s:.1f},{cy:.1f} L{cx+34*s:.1f},{cy-10*s:.1f} Q{cx:.1f},{cy-22*s:.1f} {cx-34*s:.1f},{cy-10*s:.1f} Z" fill="{c["furn"]}"/>',
           ellipse(cx, cy + 12 * s, 18 * s, 6 * s, c["lamp"], 0.95)]
    return out

def plant(x, t, c):
    s = 1 - (1 - K) * t
    base = P(x, 1000, t); top = P(x, 1000 - 60, t)
    g = "#6f7f62" if not c["night"] else "#243128"
    out = [poly([(base[0] - 28 * s, top[1] + 10 * s), (base[0] + 28 * s, top[1] + 10 * s), (base[0] + 22 * s, base[1]), (base[0] - 22 * s, base[1])], c["furn2"])]
    for dx, dy, rr in [(0, 60, 44), (-34, 40, 30), (34, 44, 32), (0, 95, 26), (-18, 80, 22)]:
        out.append(f'<circle cx="{base[0] + dx*s:.1f}" cy="{top[1] + 10*s - dy*s:.1f}" r="{rr*s:.1f}" fill="{g}" opacity="0.9"/>')
    return out

def window(c, x0, x1, y0, y1):
    out = [f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="url(#sky)"/>',
           f'<rect x="{x0}" y="{y0}" width="{x1-x0}" height="{y1-y0}" fill="none" stroke="{c["trim"]}" stroke-width="7"/>',
           f'<line x1="{(x0+x1)/2}" y1="{y0}" x2="{(x0+x1)/2}" y2="{y1}" stroke="{c["trim"]}" stroke-width="5"/>',
           f'<line x1="{x0}" y1="{(y0+y1)/2}" x2="{x1}" y2="{(y0+y1)/2}" stroke="{c["trim"]}" stroke-width="5"/>']
    # light shaft onto the floor
    fl = P((x0 + x1) / 2, 1000, 0.55)
    out.insert(0, poly([(x0, y1), (x1, y1), (fl[0] + 260, fl[1] + 120), (fl[0] - 260, fl[1] + 120)], "url(#wash)", 0.9))
    return out

def build(name, c, seed):
    rnd = random.Random(seed)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{name} interior illustration">']
    o.append(f'''<defs>
  <radialGradient id="glow"><stop offset="0" stop-color="{c["lamp"]}" stop-opacity="{0.55 if c["night"] else 0.35}"/><stop offset="1" stop-color="{c["lamp"]}" stop-opacity="0"/></radialGradient>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["sky_a"]}"/><stop offset="1" stop-color="{c["sky_b"]}"/></linearGradient>
  <linearGradient id="wash" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["wash"]}"/><stop offset="1" stop-color="{c["wash"]}" stop-opacity="0"/></linearGradient>
  <linearGradient id="lwall" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#000" stop-opacity="0.0"/><stop offset="1" stop-color="#000" stop-opacity="0.22"/></linearGradient>
  <linearGradient id="rwall" x1="1" y1="0" x2="0" y2="0"><stop offset="0" stop-color="#000" stop-opacity="0.0"/><stop offset="1" stop-color="#000" stop-opacity="0.22"/></linearGradient>
  <linearGradient id="ceil" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0.18"/><stop offset="1" stop-color="#000" stop-opacity="0.02"/></linearGradient>
  <linearGradient id="floor" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="#000" stop-opacity="0.22"/><stop offset="1" stop-color="#000" stop-opacity="0"/></linearGradient>
  <radialGradient id="pool" cx="0.5" cy="0.5" r="0.5"><stop offset="0" stop-color="{c["lamp"]}" stop-opacity="{0.45 if c["night"] else 0.5}"/><stop offset="1" stop-color="{c["lamp"]}" stop-opacity="0"/></radialGradient>
  <radialGradient id="vig" cx="0.5" cy="0.5" r="0.75"><stop offset="0.55" stop-color="#000" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity="{c["vignette"]}"/></radialGradient>
  <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="{seed}" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.1"/></feComponentTransfer><feBlend in2="SourceGraphic" mode="overlay"/></filter>
</defs>''')
    bx0, by0 = P(0, 0, 1); bx1, by1 = P(1600, 1000, 1)
    # surfaces
    o.append(poly([(0, 0), (1600, 0), (bx1, by0), (bx0, by0)], c["ceil"]))
    o.append(poly([(0, 0), (1600, 0), (bx1, by0), (bx0, by0)], "url(#ceil)"))
    o.append(poly([(0, 1000), (1600, 1000), (bx1, by1), (bx0, by1)], c["floor"]))
    o.append(poly([(0, 1000), (1600, 1000), (bx1, by1), (bx0, by1)], "url(#floor)"))
    for i in range(-2, 20):
        x = i * 90 - 20
        a = P(x, 1000, 0); b = P(x, 1000, 1)
        o.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{c["board"]}" stroke-width="2"/>')
    o.append(poly([(0, 0), (bx0, by0), (bx0, by1), (0, 1000)], c["wall_side"]))
    o.append(poly([(0, 0), (bx0, by0), (bx0, by1), (0, 1000)], "url(#lwall)"))
    o.append(poly([(1600, 0), (bx1, by0), (bx1, by1), (1600, 1000)], c["wall_side"]))
    o.append(poly([(1600, 0), (bx1, by0), (bx1, by1), (1600, 1000)], "url(#rwall)"))
    o.append(rect(bx0, by0, bx1 - bx0, by1 - by0, c["back"]))
    # skirting
    for a, b in [((0, 1000), (bx0, by1)), ((1600, 1000), (bx1, by1))]:
        o.append(f'<line x1="{a[0]}" y1="{a[1]-6}" x2="{b[0]:.1f}" y2="{b[1]-3:.1f}" stroke="{c["trim"]}" stroke-width="5" opacity="0.5"/>')
    o.append(f'<line x1="{bx0:.1f}" y1="{by1-3:.1f}" x2="{bx1:.1f}" y2="{by1-3:.1f}" stroke="{c["trim"]}" stroke-width="4" opacity="0.5"/>')

    kind = c["kind"]
    if kind == "cafe":
        o += window(c, bx0 + 40, bx0 + 200, by0 + 50, by0 + 230)
        o += window(c, bx1 - 200, bx1 - 40, by0 + 50, by0 + 230)
        # counter on the left, along the wall
        for t in (0.35,):
            s = 1 - (1 - K) * t
            a = P(-120, 1000 - 110, 0.15); b = P(-120, 1000 - 110, 0.75); d = P(-120, 1000, 0.75); e = P(-120, 1000, 0.15)
            o.append(poly([(a[0] + 190, a[1]), (b[0] + 190 * (1 - (1 - K) * 0.75) / (1 - (1 - K) * 0.15) * 0 + 190 * 0.6, b[1]), (d[0] + 190 * 0.6, d[1]), (e[0] + 190, e[1])], c["furn"]))
            o.append(poly([(a[0] + 190, a[1]), (b[0] + 190 * 0.6, b[1]), (b[0] + 190 * 0.6 - 30, b[1] - 10), (a[0] + 190 - 40, a[1] - 14)], c["furn2"]))
        o += lamp(-140, 0.3, c, drop=280); o += lamp(360, 0.55, c, drop=330, r=0.9); o += lamp(1180, 0.42, c, drop=300, r=0.9)
        o += table(1180, 0.62, c, rnd); o += chair(1060, 0.62, c); o += chair(1300, 0.62, c, flip=True)
        o += table(1350, 0.30, c, rnd); o += chair(1230, 0.30, c); o += chair(1480, 0.30, c, flip=True)
        o += table(950, 0.82, c, rnd)
        o += plant(1560, 0.12, c); o += plant(560, 0.9, c)
    elif kind == "restaurant":
        o += window(c, bx0 + 30, bx0 + 190, by0 + 40, by0 + 250)
        o += window(c, bx1 - 190, bx1 - 30, by0 + 40, by0 + 250)
        # banquette along the left wall
        a = P(-160, 1000 - 90, 0.1); b = P(-160, 1000 - 90, 0.85); d = P(-160, 1000, 0.85); e = P(-160, 1000, 0.1)
        o.append(poly([(a[0] + 200, a[1]), (b[0] + 120, b[1]), (d[0] + 120, d[1]), (e[0] + 200, e[1])], c["furn2"]))
        o.append(poly([(a[0] + 200, a[1]), (b[0] + 120, b[1]), (b[0] + 120, b[1] - 60), (a[0] + 200, a[1] - 100)], c["furn"]))
        o += lamp(-100, 0.25, c, drop=320); o += lamp(800, 0.5, c, drop=340); o += lamp(1250, 0.35, c, drop=320); o += lamp(700, 0.85, c, drop=360, r=0.7)
        o += table(120, 0.28, c, rnd); o += table(160, 0.58, c, rnd)
        o += table(1080, 0.55, c, rnd); o += chair(960, 0.55, c); o += chair(1200, 0.55, c, flip=True)
        o += table(1380, 0.25, c, rnd); o += chair(1260, 0.25, c); o += chair(1500, 0.25, c, flip=True)
        o += table(820, 0.8, c, rnd); o += chair(740, 0.8, c); o += chair(900, 0.8, c, flip=True)
        o += plant(1560, 0.1, c)
    else:  # bar
        # back-bar on the back wall
        o.append(rect(bx0 + 30, by0 + 40, bx1 - bx0 - 60, by1 - by0 - 130, "#0b100d"))
        for row in range(3):
            y = by0 + 60 + row * 90
            o.append(rect(bx0 + 40, y + 70, bx1 - bx0 - 80, 5, c["lamp"], 0.85))
            x = bx0 + 50
            while x < bx1 - 60:
                w = rnd.uniform(9, 16); h = rnd.uniform(34, 60)
                o.append(rect(x, y + 70 - h, w, h, c["lamp"], rnd.uniform(0.55, 0.9)))
                x += w + rnd.uniform(10, 26)
        # counter across the room
        t0, t1 = 0.55, 0.62
        a = P(300, 1000 - 100, t0); b = P(1300, 1000 - 100, t0); d = P(1300, 1000, t0); e = P(300, 1000, t0)
        a2 = P(300, 1000 - 100, t1); b2 = P(1300, 1000 - 100, t1)
        o.append(poly([(a[0], a[1]), (b[0], b[1]), (d[0], d[1]), (e[0], e[1])], c["furn2"]))
        o.append(poly([(a[0], a[1]), (b[0], b[1]), (b2[0], b2[1]), (a2[0], a2[1])], "#5a4a3c"))
        o.append(poly([(a[0], a[1] + 4), (b[0], b[1] + 4), (b[0], b[1] + 10), (a[0], a[1] + 10)], c["lamp"], 0.35))
        for x in (420, 640, 860, 1080):   # stools
            s = 1 - (1 - K) * 0.44
            seat = P(x, 1000 - 70, 0.44); base = P(x, 1000, 0.44)
            o.append(rect(seat[0] - 3 * s, seat[1], 6 * s, base[1] - seat[1], "#3a3028"))
            o.append(ellipse(base[0], base[1], 22 * s, 6 * s, "#3a3028"))
            o.append(ellipse(seat[0], seat[1], 30 * s, 9 * s, "#4a3a2c"))
        for x in (330, 640, 950, 1260):
            o += lamp(x, 0.5, c, drop=290, r=1.1)
        o += table(120, 0.3, c, rnd); o += table(1480, 0.3, c, rnd)
        # light pools on the floor under the lamps
        for x in (330, 640, 950, 1260):
            p = P(x, 1000, 0.5); s = 1 - (1 - K) * 0.5
            o.append(f'<ellipse cx="{p[0]:.1f}" cy="{p[1]:.1f}" rx="{160*s:.1f}" ry="{50*s:.1f}" fill="url(#pool)"/>')
    if kind != "bar":
        p = P(800, 1000, 0.5)
        o.append(f'<ellipse cx="{p[0]:.1f}" cy="{p[1]:.1f}" rx="520" ry="150" fill="url(#pool)"/>')
    o.append(rect(0, 0, W, H, "url(#vig)"))
    o.append(f'<rect width="{W}" height="{H}" fill="#000" opacity="0.001" filter="url(#grain)"/>')
    o.append("</svg>")
    return "\n".join(o)

def main():
    for i, (name, c) in enumerate(ROOMS.items()):
        (OUT / f"room-{name}.svg").write_text(build(name, c, 300 + i))
        print("wrote", f"room-{name}.svg")

if __name__ == "__main__":
    main()
