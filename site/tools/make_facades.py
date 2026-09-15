"""
Generate the three shopfront "entrance" illustrations that hang as framed
pictures in the home-page walk: facade-cafe.svg, facade-restaurant.svg,
facade-bar.svg. All are 693x900 with the door in the SAME place, so a real
photo cropped to the same composition drops in without touching the CSS:

    door rect (percent of image):  x 48.3  y 29.8  w 26  h 62.2   hinge: right

    python3 site/tools/make_facades.py
"""
from __future__ import annotations
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "assets" / "img"
W, H = 693, 900
DX, DY, DW, DH = 0.483 * W, 0.298 * H, 0.26 * W, 0.622 * H   # door rect in px

def rect(x, y, w, h, fill, op=1.0, rx=0, extra=""):
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" opacity="{op:.2f}" rx="{rx}" {extra}/>'

def door(c, glass_top=True, round_window=False):
    x, y, w, h = DX, DY, DW, DH
    o = [rect(x - 14, y - 16, w + 28, h + 16, c["frame"]),                 # door frame / architrave
         rect(x, y, w, h, c["door"]),                                       # leaf
         rect(x + 10, y + 12, w - 20, h - 24, "none", 1, 0, f'stroke="{c["door_line"]}" stroke-width="3"')]
    if glass_top:   # two arched glass panes
        for i in (0, 1):
            px = x + 18 + i * (w / 2 - 12)
            pw = w / 2 - 30
            o.append(f'<path d="M{px:.1f},{y + 200:.1f} L{px:.1f},{y + 60:.1f} A{pw/2:.1f},{pw/2:.1f} 0 0 1 {px + pw:.1f},{y + 60:.1f} L{px + pw:.1f},{y + 200:.1f} Z" fill="url(#glow)"/>')
            o.append(f'<path d="M{px:.1f},{y + 200:.1f} L{px:.1f},{y + 60:.1f} A{pw/2:.1f},{pw/2:.1f} 0 0 1 {px + pw:.1f},{y + 60:.1f} L{px + pw:.1f},{y + 200:.1f} Z" fill="none" stroke="{c["door_line"]}" stroke-width="3"/>')
    if round_window:
        o.append(f'<circle cx="{x + w/2:.1f}" cy="{y + 120:.1f}" r="34" fill="url(#glow)" stroke="{c["door_line"]}" stroke-width="4"/>')
    # lower panels
    for i in (0, 1):
        px = x + 18 + i * (w / 2 - 12)
        o.append(rect(px, y + h * 0.5, w / 2 - 30, h * 0.18, "none", 1, 0, f'stroke="{c["door_line"]}" stroke-width="3"'))
        o.append(rect(px, y + h * 0.73, w / 2 - 30, h * 0.18, "none", 1, 0, f'stroke="{c["door_line"]}" stroke-width="3"'))
    o.append(rect(x + 14, y + h * 0.47, 12, 34, c["brass"], 1, 3))          # handle (left → hinge right)
    o.append(rect(x + w * 0.35, y + h * 0.42, w * 0.3, 16, c["brass"], 0.8, 2))  # letter plate
    o.append(rect(x, y + h - 8, w, 8, c["door_line"], 0.6))                 # threshold
    return o

def facade(name, c, seed):
    rnd = random.Random(seed)
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{name} entrance illustration">',
         f'''<defs>
  <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["sky_a"]}"/><stop offset="1" stop-color="{c["sky_b"]}"/></linearGradient>
  <radialGradient id="glow" cx="0.5" cy="0.6" r="0.8"><stop offset="0" stop-color="{c["glow"]}"/><stop offset="1" stop-color="{c["glow_b"]}"/></radialGradient>
  <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["wall_a"]}"/><stop offset="1" stop-color="{c["wall_b"]}"/></linearGradient>
  <linearGradient id="pave" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{c["pave_a"]}"/><stop offset="1" stop-color="{c["pave_b"]}"/></linearGradient>
  <linearGradient id="shade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#000" stop-opacity="0.35"/><stop offset="1" stop-color="#000" stop-opacity="0"/></linearGradient>
  <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="{seed}" stitchTiles="stitch"/><feColorMatrix type="saturate" values="0"/><feComponentTransfer><feFuncA type="linear" slope="0.09"/></feComponentTransfer><feBlend in2="SourceGraphic" mode="overlay"/></filter>
  <filter id="soft"><feGaussianBlur stdDeviation="10"/></filter>
</defs>''']
    o.append(rect(0, 0, W, H, "url(#wall)"))
    # stone courses
    for i in range(0, 14):
        y = 40 + i * 62
        o.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#000" stroke-opacity="0.06" stroke-width="2"/>')
    # pavement
    o.append(rect(0, DY + DH, W, H - (DY + DH), "url(#pave)"))
    o.append(f'<line x1="0" y1="{DY + DH + 1:.0f}" x2="{W}" y2="{DY + DH + 1:.0f}" stroke="#000" stroke-opacity="0.25" stroke-width="3"/>')
    # big window left of the door
    wx0, wx1, wy0, wy1 = 22, DX - 60, 225, 640
    o.append(rect(wx0 - 12, wy0 - 12, wx1 - wx0 + 24, wy1 - wy0 + 24, c["frame"]))
    o.append(rect(wx0, wy0, wx1 - wx0, wy1 - wy0, "url(#glow)"))
    # things seen through the window: lamps + shelves
    for i, cx in enumerate((wx0 + 60, wx0 + 150, wx0 + 230)):
        cy = wy0 + 70 + (i % 2) * 30
        o.append(f'<circle cx="{cx}" cy="{cy}" r="34" fill="{c["lamp"]}" opacity="0.35" filter="url(#soft)"/>')
        o.append(f'<circle cx="{cx}" cy="{cy}" r="16" fill="{c["lamp"]}" opacity="0.95"/>')
        o.append(f'<line x1="{cx}" y1="{wy0}" x2="{cx}" y2="{cy - 16}" stroke="{c["door_line"]}" stroke-opacity="0.6" stroke-width="2"/>')
    for i in range(3):
        y = wy0 + 190 + i * 95
        o.append(rect(wx0 + 20, y, wx1 - wx0 - 40, 6, c["frame"], 0.7))
        x = wx0 + 26
        while x < wx1 - 40:
            bw = rnd.uniform(10, 22); bh = rnd.uniform(28, 60)
            o.append(rect(x, y - bh, bw, bh, rnd.choice([c["frame"], c["door"], c["brass"]]), rnd.uniform(0.5, 0.9), 2))
            x += bw + rnd.uniform(8, 22)
    o.append(rect(wx0, wy0, wx1 - wx0, wy1 - wy0, "url(#shade)"))
    o.append(rect(wx0, wy1 - 60, wx1 - wx0, 60, c["frame"], 0.9))   # sill board
    # awning / fascia
    if c["awning"]:
        o.append(f'<path d="M-10,60 L{W + 10},20 L{W + 10},{c["awning_h"]} L-10,{c["awning_h"] + 40} Z" fill="{c["awning"]}"/>')
        o.append(f'<path d="M-10,{c["awning_h"] + 40} L{W + 10},{c["awning_h"]} L{W + 10},{c["awning_h"] + 22} L-10,{c["awning_h"] + 62} Z" fill="{c["awning_edge"]}"/>')
        o.append(f'<path d="M-10,{c["awning_h"] + 62} L{W + 10},{c["awning_h"] + 22} L{W + 10},{c["awning_h"] + 130} L-10,{c["awning_h"] + 170} Z" fill="url(#shade)"/>')
    else:   # fascia board with a lit sign line
        o.append(rect(0, 120, W, 90, c["frame"]))
        o.append(rect(60, 150, W - 120, 8, c["lamp"], 0.9, 4))
        o.append(rect(40, 130, W - 80, 50, c["lamp"], 0.25, 6, 'filter="url(#soft)"'))
    o += door(c, glass_top=c["glass_top"], round_window=c["round"])
    # planter / flowers right of the door
    px = DX + DW + 30
    o.append(rect(px + 20, DY + DH - 120, 80, 120, c["planter"], 1, 6))
    for _ in range(26):
        cx = rnd.uniform(px + 10, W - 10); cy = rnd.uniform(DY + 40, DY + DH - 110)
        o.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rnd.uniform(14, 26):.0f}" fill="{c["leaf"]}" opacity="0.9"/>')
    for _ in range(16):
        cx = rnd.uniform(px + 20, W - 20); cy = rnd.uniform(DY + 60, DY + DH - 130)
        o.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rnd.uniform(7, 12):.0f}" fill="{c["flower"]}" opacity="0.95"/>')
    # bistro table + chair left of the door on the pavement
    tx, ty = 110, DY + DH - 10
    o.append(f'<ellipse cx="{tx}" cy="{ty - 150}" rx="70" ry="14" fill="{c["metal"]}"/>')
    o.append(rect(tx - 3, ty - 150, 6, 150, c["metal"]))
    o.append(f'<ellipse cx="{tx}" cy="{ty}" rx="34" ry="6" fill="{c["metal"]}"/>')
    o.append(f'<ellipse cx="{tx}" cy="{ty - 152}" rx="12" ry="5" fill="{c["lamp"]}" opacity="0.9"/>')   # cup
    o.append(f'<ellipse cx="{tx + 130}" cy="{ty - 95}" rx="36" ry="9" fill="{c["metal"]}"/>')
    o.append(rect(tx + 96, ty - 95, 5, 95, c["metal"])); o.append(rect(tx + 160, ty - 95, 5, 95, c["metal"]))
    o.append(f'<path d="M{tx + 100},{ty - 95} Q{tx + 130},{ty - 200} {tx + 160},{ty - 95}" fill="none" stroke="{c["metal"]}" stroke-width="5"/>')
    # night / day light
    if c["night"]:
        o.append(rect(0, 0, W, H, "#0a0f0c", 0.28))
        o.append(f'<ellipse cx="{DX + DW/2:.0f}" cy="{DY + DH:.0f}" rx="200" ry="60" fill="{c["glow"]}" opacity="0.35" filter="url(#soft)"/>')
    else:
        o.append(f'<path d="M{W},0 L{W},{H} L{W - 260},{H} Z" fill="#000" opacity="{c["shadow"]}"/>')
    o.append(f'<rect width="{W}" height="{H}" fill="#000" opacity="0.001" filter="url(#grain)"/>')
    o.append("</svg>")
    return "\n".join(o)

FACADES = {
    "cafe": dict(wall_a="#d9cfbe", wall_b="#c9bda9", pave_a="#b9b3a6", pave_b="#8f8a80", sky_a="#dfe7ea", sky_b="#f1eadb",
                 frame="#3f4a3a", door="#4f5c48", door_line="#33402f", brass="#c9a36b", glow="#f2d9a6", glow_b="#7a5a32", lamp="#ffe6b0",
                 awning="#efe6d2", awning_edge="#e3d8bf", awning_h=170, glass_top=True, round=False, planter="#5a4a3a", leaf="#5b6e4d", flower="#d98aa3",
                 metal="#2e2e2c", night=False, shadow=0.06),
    "restaurant": dict(wall_a="#dcc7a7", wall_b="#cbb08a", pave_a="#b5a48e", pave_b="#8a7c69", sky_a="#e8d4b4", sky_b="#f1c58c",
                 frame="#3a2a1e", door="#4a3222", door_line="#2a1c12", brass="#d4a85a", glow="#ffd08a", glow_b="#6e4318", lamp="#ffd9a0",
                 awning="#2f2a24", awning_edge="#1f1b17", awning_h=150, glass_top=False, round=True, planter="#4a3a2c", leaf="#6d7a4f", flower="#e0b060",
                 metal="#2a2320", night=False, shadow=0.12),
    "bar": dict(wall_a="#2a2f2b", wall_b="#1a1f1c", pave_a="#2a2c2b", pave_b="#141616", sky_a="#0f1a17", sky_b="#1c2a24",
                 frame="#0e120f", door="#15191a", door_line="#f0c070", brass="#f0c070", glow="#f0c070", glow_b="#4a3510", lamp="#f0c070",
                 awning=None, awning_edge=None, awning_h=0, glass_top=False, round=True, planter="#1a1c1a", leaf="#243128", flower="#f0c070",
                 metal="#0e120f", night=True, shadow=0),
}

def main():
    for i, (name, c) in enumerate(FACADES.items()):
        (OUT / f"facade-{name}.svg").write_text(facade(name, c, 500 + i))
        print("wrote", f"facade-{name}.svg")

if __name__ == "__main__":
    main()
