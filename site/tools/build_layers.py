"""
Render the aligned layers for "The build" and write one partial per venue (partials/build-<venue>.html).

Every venue starts from ONE finished photograph. Each stage of the build is a rendering of that
same photograph, so the layers line up pixel for pixel and the last stage is the real room:

    sketch  pencil perspective on paper (difference-of-Gaussians line work + tone hatching)
    shell   the white model before the fit-out: joinery and furniture only set out (a faint outline)
    clay    the white model with its fit-out: L0-flat card planes, high key, the sketch's lines drawn on
    dim     the finishes in working light, before the lights come on (bloom removed, highlights pulled, cool)
    lit     the finished photograph

Venues: cafe, restaurant, bar, retail. Each partial is self-contained (intro, the scrubbed build with its trust
notes, the reduced-motion stills and notes); a page includes it with <!-- @partial:build-<venue> --> plus
assets/css/build.css and assets/js/build.js. (partials/build.html, the old three-venue section, is no longer written.)

Regions (build.json): "shell" polygons are structure (the empty model rises over the sketch, feathered
~3% of the width); "fit" polygons are joinery and fit-out (solid over their outline, feathered beyond it,
where shell and clay are the same pixels); "flat" polygons flatten fine texture (bottles) into plain planes.

    python3 tools/build_layers.py images [venue ...]   # assets/img/build/<venue>-<layer>-{1920,960}.webp
    python3 tools/build_layers.py images --clay        # only re-render shell + clay (and the masks)
    python3 tools/build_layers.py html [venue ...]     # partials/build-<venue>.html from assets/data/build.json
    python3 tools/build_layers.py preview [venue ...]  # grid + region overlays (to OUT_PREVIEW) for placing polygons

Pillow + numpy only. Sources are the 2400px originals (see SRC below); the region polygons, glows,
plans and copy live in assets/data/build.json.
"""
from __future__ import annotations

import html as H
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

SITE = Path(__file__).resolve().parents[1]
DATA = SITE / "assets/data/build.json"
OUT = SITE / "assets/img/build"
SRC = Path(os.environ.get("BUILD_SRC", "/tmp/claude-0/-home-user-integratedai/20d3b9a0-766a-5cf0-adc3-7ed0645662b0/scratchpad/media/photos-hospitality"))
OUT_PREVIEW = Path(os.environ.get("BUILD_PREVIEW", "/tmp/claude-0/-home-user-integratedai/20d3b9a0-766a-5cf0-adc3-7ed0645662b0/scratchpad/build/build-v2"))
WIDTHS = (1920, 960)
PAPER = np.array([242, 239, 230], np.float32) / 255      # drawing paper, a shade warmer than --paper
GRAPHITE = np.array([38, 41, 39], np.float32) / 255
CLAY = np.array([246, 244, 239], np.float32) / 255       # white card / plaster model


# ------------------------------------------------------------------ numpy helpers
def to_f(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("RGB"), np.float32) / 255


def to_im(a: np.ndarray) -> Image.Image:
    return Image.fromarray(np.clip(a * 255 + 0.5, 0, 255).astype(np.uint8))


def luma(a: np.ndarray) -> np.ndarray:
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def gauss(a: np.ndarray, s: float) -> np.ndarray:
    """Separable Gaussian blur (edge padded). Large sigmas run on a downsampled copy."""
    if s <= 0:
        return a
    if s > 12:
        f = int(s // 6)
        h, w = a.shape[:2]
        small = a[: h - h % f, : w - w % f]
        small = small.reshape(h // f, f, w // f, f, *a.shape[2:]).mean(axis=(1, 3))
        b = gauss(small, s / f)
        b = np.repeat(np.repeat(b, f, 0), f, 1)
        out = np.empty_like(a)
        out[: b.shape[0], : b.shape[1]] = b
        out[b.shape[0]:] = out[b.shape[0] - 1: b.shape[0]]
        out[:, b.shape[1]:] = out[:, b.shape[1] - 1: b.shape[1]]
        return out
    r = max(1, int(math.ceil(s * 3)))
    x = np.arange(-r, r + 1, dtype=np.float32)
    k = np.exp(-(x * x) / (2 * s * s))
    k /= k.sum()
    out = a
    for axis in (0, 1):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="edge")
        acc = np.zeros_like(out)
        n = out.shape[axis]
        for i, kv in enumerate(k):
            sl = [slice(None)] * a.ndim
            sl[axis] = slice(i, i + n)
            acc += kv * p[tuple(sl)]
        out = acc
    return out


def box(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 window via integral images (edge padded)."""
    p = np.pad(a, [(r + 1, r)] + [(r + 1, r)] + [(0, 0)] * (a.ndim - 2), mode="edge").astype(np.float64)
    c = p.cumsum(0).cumsum(1)
    n = 2 * r + 1
    s = c[n:, n:] - c[:-n, n:] - c[n:, :-n] + c[:-n, :-n]
    return (s / (n * n)).astype(np.float32)


def guided(I: np.ndarray, p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """He et al. guided filter (grey guide). Edge-preserving smoothing when I is p."""
    mI, mp = box(I, r), box(p, r)
    cov = box(I * p, r) - mI * mp
    var = box(I * I, r) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    return box(a, r) * I + box(b, r)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def maxf(m: np.ndarray, size=3) -> np.ndarray:
    im = Image.fromarray((m * 255).astype(np.uint8))
    return np.asarray(im.filter(ImageFilter.MaxFilter(size)), np.float32) / 255


def noise(h, w, scale, seed):
    """Smooth value noise in [-1, 1] at a given feature scale (px)."""
    rng = np.random.default_rng(seed)
    gh, gw = max(2, int(h / scale) + 2), max(2, int(w / scale) + 2)
    g = rng.standard_normal((gh, gw)).astype(np.float32)
    im = Image.fromarray(g, mode="F").resize((w, h), Image.BICUBIC)
    a = np.asarray(im, np.float32)
    return a / (np.abs(a).max() + 1e-6)


def src_path(venue: dict) -> Path:
    """A bare file name lives in SRC (photos-hospitality); a relative path is under SRC's parent (SP/media)."""
    s = venue["src"]
    return SRC / s if "/" not in s else SRC.parent / s


def load(venue: dict, W: int) -> np.ndarray:
    im = Image.open(src_path(venue)).convert("RGB")
    h = round(im.height * W / im.width)
    return to_f(im.resize((W, h), Image.LANCZOS))


# ------------------------------------------------------------------ layers
def sobel(S):
    p = np.pad(S, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return gx, gy


def nms(mag, gx, gy):
    """Thin edges to one pixel along the gradient direction (Canny)."""
    ang = (np.degrees(np.arctan2(gy, gx)) + 180) % 180
    p = np.pad(mag, 1)
    c = p[1:-1, 1:-1]
    n = {0: (p[1:-1, 2:], p[1:-1, :-2]), 45: (p[2:, 2:], p[:-2, :-2]), 90: (p[2:, 1:-1], p[:-2, 1:-1]), 135: (p[2:, :-2], p[:-2, 2:])}
    q = np.select([(ang < 22.5) | (ang >= 157.5), ang < 67.5, ang < 112.5], [0, 45, 90], 135)
    keep = np.zeros_like(mag, bool)
    for d, (a, b) in n.items():
        m = q == d
        keep |= m & (c >= a) & (c >= b)
    return keep


def stroke_weight(mask: np.ndarray, min_len: float, full_len: float) -> np.ndarray:
    """Per-pixel weight from the size of its 8-connected stroke (pure-Python BFS, fine for line maps)."""
    from collections import deque
    h, w = mask.shape
    flat = mask.ravel()
    lab = np.zeros(h * w, np.int32)
    sizes = [0]
    idx = np.flatnonzero(flat)
    nb = (-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1)
    cur = 0
    for i in idx:
        if lab[i]:
            continue
        cur += 1
        lab[i] = cur
        q = deque([i]); n = 0
        while q:
            j = q.popleft(); n += 1
            x = j % w
            for d in nb:
                k = j + d
                if k < 0 or k >= h * w:
                    continue
                kx = k % w
                if abs(kx - x) > 1 or not flat[k] or lab[k]:
                    continue
                lab[k] = cur
                q.append(k)
        sizes.append(n)
    sz = np.asarray(sizes, np.float32)[lab].reshape(h, w)
    return np.where(mask, smoothstep(min_len, full_len, sz) * 0.8 + 0.2 * (sz >= min_len), 0).astype(np.float32)


def ruled_segments(E: np.ndarray, ang: np.ndarray, P: dict, sc: float):
    """Long straight runs in the edge map (orientation-guided Hough), as (x0, y0, x1, y1) segments."""
    h, w = E.shape
    ys, xs = np.nonzero(E)
    th = ang[ys, xs]                                    # gradient direction = line normal, 0..pi
    nb = 180
    tb = (np.round(th / np.pi * nb).astype(int)) % nb
    diag = int(math.hypot(h, w)) + 2
    free = np.ones(len(xs), bool)
    segs = []
    min_len = P.get("rule_min", 70) * sc
    gap = P.get("rule_gap", 7) * sc
    for _ in range(P.get("rule_rounds", 3)):
        acc = np.zeros((nb, 2 * diag), np.int32)
        for off in (-1, 0, 1):
            t = (tb + off) % nb
            tt = t * np.pi / nb
            rho = np.round(xs * np.cos(tt) + ys * np.sin(tt)).astype(int) + diag
            np.add.at(acc, (t[free], rho[free]), 1)
        # peaks
        flat = acc.ravel()
        order = np.argsort(flat)[::-1][: P.get("rule_peaks", 400)]
        took = 0
        for o in order:
            if flat[o] < min_len * 0.8:
                break
            t, r = divmod(o, 2 * diag)
            tt = t * np.pi / nb
            c, s_ = math.cos(tt), math.sin(tt)
            d = xs * c + ys * s_ - (r - diag)
            dt = np.abs(((tb - t + nb // 2) % nb) - nb // 2)
            m = free & (np.abs(d) <= 1.6 * max(sc, 0.7)) & (dt <= 3)
            if m.sum() < min_len * 0.6:
                continue
            u = -xs[m] * s_ + ys[m] * c                    # position along the line
            idx = np.flatnonzero(m)
            o2 = np.argsort(u)
            u, idx = u[o2], idx[o2]
            br = np.flatnonzero(np.diff(u) > gap)
            starts = np.r_[0, br + 1]
            ends = np.r_[br, len(u) - 1]
            for s0, e0 in zip(starts, ends):
                L = u[e0] - u[s0]
                if L < min_len or (e0 - s0 + 1) < L * P.get("rule_fill", 0.45):
                    continue
                rr = r - diag
                x0, y0 = rr * c - u[s0] * s_, rr * s_ + u[s0] * c
                x1, y1 = rr * c - u[e0] * s_, rr * s_ + u[e0] * c
                segs.append((x0, y0, x1, y1, L))
                free[idx[s0: e0 + 1]] = False
                took += 1
        if not took:
            break
    return segs


def draw_segments(segs, h, w, sc, P, seed=9):
    """Rule the segments in pencil: 2x supersampled, a little overshoot, weight by length."""
    rng = np.random.default_rng(seed)
    S2 = 2
    im = Image.new("L", (w * S2, h * S2), 0)
    dr = ImageDraw.Draw(im)
    for x0, y0, x1, y1, L in segs:
        dx, dy = x1 - x0, y1 - y0
        n = math.hypot(dx, dy) or 1
        ux, uy = dx / n, dy / n
        o0 = (P.get("overshoot", 6) * sc) * (0.4 + rng.random())
        o1 = (P.get("overshoot", 6) * sc) * (0.4 + rng.random())
        v = int(255 * (0.62 + 0.38 * smoothstep(60 * sc, 360 * sc, L)))
        wd = max(1, round(P.get("rule_w", 1.5) * sc * S2))
        dr.line(((x0 - ux * o0) * S2, (y0 - uy * o0) * S2, (x1 + ux * o1) * S2, (y1 + uy * o1) * S2), fill=v, width=wd)
    im = im.resize((w, h), Image.LANCZOS)
    return np.asarray(im, np.float32) / 255


def line_work(rgb: np.ndarray, P: dict, W: int = 1920) -> tuple[np.ndarray, np.ndarray]:
    """Pencil lines in [0,1] (1 = full graphite) and the flattened tone they were drawn from.
    Two hands: ruled lines for the architecture (long straight edges), lighter freehand for the rest."""
    sc = W / 1920
    L = luma(rgb)
    S = L
    for r, eps in P.get("flatten", [(3, 0.002)]):
        S = guided(S, S, max(1, int(r * sc)), eps)
    sg = P.get("sigma", 1.3) * sc
    Sg = gauss(S, sg)
    gx, gy = sobel(Sg)
    # colour edges too: orange table legs on a pale floor have little luminance contrast
    cw = P.get("chroma", 0.6)
    if cw:
        rg = gauss(rgb[..., 0] - rgb[..., 1], sg * 1.5)
        by = gauss((rgb[..., 0] + rgb[..., 1]) * 0.5 - rgb[..., 2], sg * 1.5)
        for ch in (rg, by):
            cx, cy = sobel(ch)
            sgn = np.sign(cx * gx + cy * gy + 1e-9)       # keep a consistent direction before summing
            gx = gx + cw * cx * sgn
            gy = gy + cw * cy * sgn
    mag = np.hypot(gx, gy)
    ln = P.get("local", 0.35)
    mag = (1 - ln) * mag / mag.mean() + ln * mag / (gauss(mag, P.get("local_sigma", 40) * sc) + mag.mean() * P.get("local_floor", 0.6))
    thin = nms(mag, gx, gy)
    lo_p, hi_p = P.get("pct", [82.0, 93.0])
    lo, hi = np.percentile(mag, [lo_p, hi_p])
    strong = (thin & (mag >= hi)).astype(np.float32)
    weak = (thin & (mag >= lo)).astype(np.float32)
    grow = strong
    for _ in range(P.get("grow", 24)):
        grow = maxf(grow, 3) * weak
    E = grow > 0
    ang = np.arctan2(gy, gx) % np.pi
    h, w = E.shape
    segs = ruled_segments(E, ang, P, sc)
    line_work.last_segments = segs
    ruled = draw_segments(segs, h, w, sc, P)
    # freehand: what the ruler didn't take, lighter; short fragments fade or go
    taken = maxf((ruled > 0.2).astype(np.float32), 5) > 0
    fh = E & ~taken
    free = fh * (0.55 + 0.45 * smoothstep(lo, hi * 1.8, mag))
    free = free * stroke_weight(fh, P.get("min_len", 22) * sc, P.get("full_len", 120) * sc)
    dens = gauss(free, P.get("dens_sigma", 9) * sc)
    free = free * np.clip(1.0 - (dens - P.get("dens0", 0.06)) * P.get("dens_k", 3.0), P.get("dens_floor", 0.3), 1.0)
    free = free * (0.8 + 0.2 * noise(h, w, 60 * sc, 21))
    free = np.clip(gauss(free, 0.55 * sc) * P.get("weight", 2.0), 0, 1) * P.get("free", 0.62)
    lines = np.maximum(ruled * P.get("rule", 0.95), free)
    line_work.parts = (ruled * P.get("rule", 0.95), free)
    return lines, S


def ruled_segments_for(rgb: np.ndarray, P: dict, n: int = 220) -> list:
    """The ruler's lines at 1920, longest first, as ints — they draw themselves in SVG before the sketch lands."""
    line_work(rgb, P, 1920)
    segs = sorted(line_work.last_segments, key=lambda s: -s[4])[:n]
    return [[round(x0), round(y0), round(x1), round(y1)] for x0, y0, x1, y1, _ in segs]


def strokes(tone: np.ndarray, P: dict, sc: float, seed=5) -> np.ndarray:
    """Hand hatching: short parallel pencil strokes, denser where the room is darker."""
    h, w = tone.shape
    rng = np.random.default_rng(seed)
    im = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(im)
    ang = math.radians(P.get("hatch_angle", 62))
    n = int(P.get("hatch_n", 26000) * sc * sc)
    ys = rng.integers(0, h, n * 3)
    xs = rng.integers(0, w, n * 3)
    t = tone[ys, xs]
    ok = rng.random(n * 3) < t ** 1.6
    ys, xs, t = ys[ok][:n], xs[ok][:n], t[ok][:n]
    L = (16 + 22 * rng.random(len(xs))) * sc
    a = ang + rng.normal(0, 0.035, len(xs))
    dx, dy = np.cos(a) * L / 2, -np.sin(a) * L / 2
    val = (40 + 70 * t).astype(int)
    for x, y, ddx, ddy, v in zip(xs, ys, dx, dy, val):
        dr.line((x - ddx, y - ddy, x + ddx, y + ddy), fill=int(v), width=1)
    a = np.asarray(im, np.float32) / 255
    return gauss(a, 0.45 * sc)


def render_sketch(rgb: np.ndarray, P: dict, W: int, lw=None) -> np.ndarray:
    h, w = rgb.shape[:2]
    sc = W / 1920
    lines, S = lw if lw is not None else line_work(rgb, P, W)
    # tone relative to this photo's own range: 1 = darkest
    lo, hi = np.percentile(S, P.get("tone_pct", [3, 60]))
    tone = 1 - np.clip((S - lo) / (hi - lo), 0, 1)
    tone = gauss(tone, 6.0 * sc)
    tone = smoothstep(P.get("tone0", 0.35), 1.0, tone)
    shade = strokes(tone, P, sc) * P.get("hatch", 0.55)
    wash = gauss(tone, 14 * sc) * P.get("wash", 0.06)          # a faint graphite smudge for form
    grain = 1 + noise(h, w, 1.6 * sc + 0.6, 3) * 0.12            # pencil tooth, subtle
    g = np.clip(lines * P.get("ink", 0.9) * grain + shade * grain + wash, 0, 0.95)
    paper = PAPER[None, None, :] * (1 + noise(h, w, 260 * sc, 11)[..., None] * 0.012)
    return paper * (1 - g[..., None]) + GRAPHITE[None, None, :] * g[..., None]


def l0_smooth(I: np.ndarray, lam: float, kappa: float = 2.0, beta_max: float = 1e5) -> np.ndarray:
    """L0 gradient minimisation (Xu et al. 2011): flat regions with crisp edges, i.e. an untextured model."""
    h, w = I.shape
    fx = np.zeros((h, w), np.float32); fx[0, 0], fx[0, -1] = -1, 1
    fy = np.zeros((h, w), np.float32); fy[0, 0], fy[-1, 0] = -1, 1
    Fx, Fy = np.fft.fft2(fx), np.fft.fft2(fy)
    FI = np.fft.fft2(I)
    den_d = np.abs(Fx) ** 2 + np.abs(Fy) ** 2
    S = I.copy()
    beta = 2 * lam
    while beta < beta_max:
        hgx = np.roll(S, -1, 1) - S
        hgy = np.roll(S, -1, 0) - S
        m = (hgx * hgx + hgy * hgy) < lam / beta
        hgx[m] = 0; hgy[m] = 0
        num = FI + beta * (np.conj(Fx) * np.fft.fft2(hgx) + np.conj(Fy) * np.fft.fft2(hgy))
        S = np.real(np.fft.ifft2(num / (1 + beta * den_d))).astype(np.float32)
        beta *= kappa
    return S


def blur1(a: np.ndarray, s: float, axis: int) -> np.ndarray:
    """Gaussian-ish blur along one axis: three box passes (cumulative sums), any sigma, fast."""
    if s <= 0.5:
        return a
    r = max(1, int(round((math.sqrt(4 * s * s + 1) - 1) / 2)))
    out = a
    for _ in range(3):
        pad = [(0, 0)] * a.ndim
        pad[axis] = (r + 1, r)
        c = np.cumsum(np.pad(out, pad, mode="edge"), axis=axis, dtype=np.float64)
        n = out.shape[axis]
        hi = [slice(None)] * a.ndim; hi[axis] = slice(2 * r + 1, 2 * r + 1 + n)
        lo = [slice(None)] * a.ndim; lo[axis] = slice(0, n)
        out = ((c[tuple(hi)] - c[tuple(lo)]) / (2 * r + 1)).astype(np.float32)
    return out


def clay_tone(rgb: np.ndarray, P: dict, W: int, flats=()) -> tuple[np.ndarray, np.ndarray]:
    """The white model's shading in [0,1] (before colour and line work), and the flattened areas.
    A white model has no materials: walnut, steel, brick and leaves are all the same card. So each plane keeps
    only a small, compressed share of its own value (L0-flattened: flat planes, crisp edges). Fine texture that
    would turn to blobs (the bottles on a back-bar) is authored as a flat area: one plain plane in the room's light."""
    sc = W / 1920
    L = luma(rgb)
    h, w = L.shape
    half = np.asarray(Image.fromarray(L, mode="F").resize((w // 2, h // 2), Image.BILINEAR), np.float32)
    F = l0_smooth(half, P.get("l0", 0.012))
    F = guided(L, np.asarray(Image.fromarray(F, mode="F").resize((w, h), Image.BICUBIC), np.float32), max(1, int(3 * sc)), 1e-3)
    flat = np.zeros((h, w), np.float32)
    for f in flats:
        m = gauss(poly_grow(f["poly"], w, h, 0), f.get("soft", 0.004) * w)
        sy, sx = f.get("blur", [4, 60])
        Fb = blur1(blur1(F, sy * sc, 0), sx * sc, 1)
        F = F * (1 - m) + Fb * m
        flat = np.maximum(flat, m * f.get("k", 1.0))
    lo, hi = np.percentile(F, [1.0, 99.5])
    t = (np.clip((F - lo) / (hi - lo), 0, 1) ** P.get("clay_gamma", 0.6)).astype(np.float32)
    base, span = P.get("clay_range", [0.8, 0.18])
    shade = base + span * t
    ao = np.clip(gauss(F, 24 * sc) - F, 0, 1) * P.get("clay_ao", 0.22)
    shade = shade - ao
    y = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    shade = shade * (1.0 + P.get("clay_sky", 0.03) * (0.5 - y))
    return shade.astype(np.float32), flat


def clay_colour(shade: np.ndarray) -> np.ndarray:
    warm = CLAY[None, None, :]
    cool = np.array([0.90, 0.915, 0.93], np.float32)[None, None, :]
    k = np.clip((1 - shade[..., None]) * 2.2, 0, 1)            # shadows go a touch cooler, like card under daylight
    return np.clip(shade[..., None] * (warm * (1 - k * 0.5) + cool * k * 0.5), 0, 1)


def clay_ink(col: np.ndarray, lines: np.ndarray, P: dict) -> np.ndarray:
    """The sketch's line work multiplied over the card: the model's edges are drawn."""
    ink = np.clip(lines, 0, 1)[..., None] * P.get("clay_lines", 0.85)
    return col * (1 - ink * (1 - GRAPHITE[None, None, :]))


def clay_lines(parts, flat: np.ndarray, P: dict) -> np.ndarray:
    """Ruled lines in full; freehand ones fade out over the flat areas, so the bottles don't come back as doodles."""
    ruled, free = parts
    return np.maximum(ruled, free * (1 - flat * P.get("flat_lines", 0.85)) * P.get("clay_free", 0.85))


def push_pull(a: np.ndarray, k: np.ndarray) -> np.ndarray:
    """Fill where k is 0 from where it is 1 (k in [0,1]): a smooth membrane, via a push-pull pyramid."""
    a, k = a.astype(np.float32), k.astype(np.float32)
    h, w = k.shape
    if h <= 3 or w <= 3:
        m = (a * k[..., None]).sum((0, 1)) / max(k.sum(), 1e-6)
        return np.broadcast_to(m, a.shape).astype(np.float32)
    ph, pw = h % 2, w % 2
    ka = np.pad(k, ((0, ph), (0, pw)), mode="edge")
    aa = np.pad(a * k[..., None], ((0, ph), (0, pw), (0, 0)), mode="edge")
    H2, W2 = ka.shape[0] // 2, ka.shape[1] // 2
    k2 = ka.reshape(H2, 2, W2, 2).sum((1, 3))
    a2 = aa.reshape(H2, 2, W2, 2, -1).sum((1, 3))
    c = push_pull(a2 / np.maximum(k2, 1e-6)[..., None], np.clip(k2, 0, 1))
    up = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(c[..., i]), mode="F").resize((W2 * 2, H2 * 2), Image.BILINEAR), np.float32)
                   for i in range(c.shape[-1])], -1)[:h, :w]
    return a * k[..., None] + up * (1 - k[..., None])


def poly_grow(poly, w, h, r, ss=2) -> np.ndarray:
    """A polygon grown by r px (round joins), anti-aliased, as [0,1] at w x h."""
    im = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(im)
    pts = [(x * w * ss, y * h * ss) for x, y in poly]
    d.polygon(pts, fill=255)
    R = r * ss
    if R >= 1:
        d.line(pts + [pts[0]], fill=255, width=int(round(2 * R)), joint="curve")
        for x, y in pts:
            d.ellipse((x - R, y - R, x + R, y + R), fill=255)
    return np.asarray(im.resize((w, h), Image.BILINEAR), np.float32) / 255


GHOST = (0.006, 0.004)      # the fit-out's ghost in the empty shell: grown by, and feathered by (fractions of the width)


def fit_ghost(v: dict, w: int, h: int) -> np.ndarray:
    """Where the fit-out will stand, soft-edged: in the empty shell it is only set out (a faint outline)."""
    g, s = GHOST
    m = np.zeros((h, w), np.float32)
    for r in v["regions"]:
        if r["group"] == "fit":
            m = np.maximum(m, poly_grow(r["poly"], w, h, g * w))
    return np.clip(gauss(m, s * w), 0, 1)


def render_clay(rgb: np.ndarray, P: dict, W: int, v: dict, parts) -> tuple[np.ndarray, np.ndarray]:
    """(clay, shell): the white model with its fit-out, and the same model before the fit-out: the joinery
    and furniture are only set out there (the walls and floor carried through, a faint outline), so each
    piece can be set down in its place."""
    sc = W / 1920
    shade, flat = clay_tone(rgb, P, W, v.get("flat", []))
    lines = clay_lines(parts, flat, P)
    clay = clay_ink(clay_colour(shade), lines, P)
    h, w = shade.shape
    G = fit_ghost(v, w, h)
    known = (G < 0.01).astype(np.float32)
    filled = push_pull(shade[..., None], known)[..., 0]
    filled = gauss(filled, 4 * sc) * (1 - known) + filled * known
    empty = shade * (1 - G) + (filled * 0.6 + shade * 0.4) * G
    shell = clay_ink(clay_colour(empty), lines * (1 - G * (1 - P.get("ghost_lines", 0.28))), P)
    return clay, shell


def lamp_mask(h: int, w: int, lamps: list, sc: float) -> np.ndarray:
    """1 at a lamp's centre, falling to 0 at its radius (radius as a fraction of width)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    m = np.zeros((h, w), np.float32)
    for g in lamps:
        cx, cy, r = g["x"] * w, g["y"] * h, max(2.0, g.get("rr", g["r"] * 0.7) * w)
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        m = np.maximum(m, np.clip(1 - d, 0, 1) ** 1.5 * g.get("k", 1.0))
    return m


def render_dim(rgb: np.ndarray, P: dict, W: int, lamps=()) -> np.ndarray:
    """The same room before the lights come on: an exposure down, working light, the lamps out."""
    h, w = rgb.shape[:2]
    lin = rgb ** 2.2
    lin = lin * P.get("dim_exposure", 0.5)
    if lamps:
        m = lamp_mask(h, w, lamps, W / 1920)
        m = gauss(m, 4 * W / 1920)
        Y = luma(lin)[..., None]
        grey = Y * 0.9
        lin = lin * (1 - m[..., None] * P.get("dim_lamp", 0.8)) + grey * m[..., None] * 0.0
    # a gentle shoulder so the brightest things don't still read as lit
    Y = luma(lin)
    cap = P.get("dim_cap", 0.6)
    comp = Y / (1 + Y / cap)
    lin = lin * (comp / (Y + 1e-5))[..., None]
    Y3 = luma(lin)[..., None]
    lin = Y3 + (lin - Y3) * P.get("dim_sat", 0.6)
    lin = lin * np.array(P.get("dim_tint", [0.9, 0.97, 1.06]), np.float32)[None, None, :]
    return np.clip(lin, 0, 1) ** (1 / 2.2)


MASK_W = 640


def region_masks(v: dict) -> dict:
    """Soft masks at MASK_W. Shell regions (structure) reveal the empty white model over the sketch, feathered
    wide (about 3% of the frame) so no edge reads as a cut. Fit regions (joinery and fit-out) are solid over
    the hole cut for them in the empty shell and feather out beyond it, where the empty shell and the full
    model are the same pixels: set down, a piece covers its hole exactly and its feather never shows.
    A later piece owns any overlap with an earlier one."""
    im = Image.open(src_path(v)).convert("RGB")
    w, h = MASK_W, round(im.height * MASK_W / im.width)
    R = v.get("render", {})
    fe = R.get("feather", 0.011) * w               # gaussian sigma: 10-90% over ~2.8% of the width
    hole = (GHOST[0] + 3 * GHOST[1]) * w           # the ghost's full reach in the empty shell
    out, cores = {}, {}
    for r in v["regions"]:
        if r["group"] == "shell":
            m = gauss(poly_grow(r["poly"], w, h, 1.2 * fe), fe)
        else:
            core = poly_grow(r["poly"], w, h, hole + 0.004 * w)
            m = np.maximum(core, gauss(poly_grow(r["poly"], w, h, hole + 0.004 * w + 2.5 * fe), fe))
            cores[r["id"]] = core
        out[r["id"]] = np.clip(m, 0, 1)
    fits = [r["id"] for r in v["regions"] if r["group"] == "fit"]
    for i, rid in enumerate(fits):
        for later in fits[i + 1:]:
            out[rid] = out[rid] * (1 - cores[later])
    return out


def write_masks(v: dict) -> dict:
    """assets/img/build/<venue>-m-<region>.webp (alpha masks cropped to their box) + their boxes."""
    ms = region_masks(v)
    boxes = {}
    for rid, m in ms.items():
        h, w = m.shape
        ys, xs = np.nonzero(m > 0.02)
        if not len(xs):
            continue
        pad = 2
        m = np.where(m > 0.004, m, 0)
        x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
        y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
        crop = m[y0:y1, x0:x1]
        a = (np.clip(crop, 0, 1) * 255 + 0.5).astype(np.uint8)
        rgba = np.dstack([np.full_like(a, 255)] * 3 + [a])
        p = OUT / f"{v['id']}-m-{rid}.webp"
        Image.fromarray(rgba, "RGBA").save(p, "WEBP", lossless=True, quality=100, method=6)
        boxes[rid] = [round(x0 / w, 5), round(y0 / h, 5), round((x1 - x0) / w, 5), round((y1 - y0) / h, 5)]
    return boxes


def save(a: np.ndarray, venue_id: str, layer: str, W: int, q: int):
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"{venue_id}-{layer}-{W}.webp"
    to_im(a).save(p, "WEBP", quality=q, method=6)
    return p


def images(ids):
    data = json.loads(DATA.read_text())
    for v in data["venues"]:
        if ids and v["id"] not in ids:
            continue
        P = v.get("render", {})
        meta = {"boxes": write_masks(v)}
        rgb0 = load(v, 1920)
        segs = ruled_segments_for(rgb0, P)
        meta["segments"] = segs
        meta["size"] = [rgb0.shape[1], rgb0.shape[0]]
        (OUT / f"{v['id']}-meta.json").write_text(json.dumps(meta, separators=(",", ":")))
        print(f"  {v['id']}: {len(meta['boxes'])} masks, {len(segs)} ruled lines")
        if "--masks" in sys.argv:
            continue
        for W in WIDTHS:
            rgb = load(v, W)
            only_clay = "--clay" in sys.argv          # re-render just the white model (shell + clay)
            if W == 1920:
                lw = line_work(rgb, P, W)
                cl, sh = render_clay(rgb, P, W, v, line_work.parts)
                cache = {"shell": sh, "clay": cl}
                if not only_clay:
                    cache["sketch"] = render_sketch(rgb, P, W, lw)
                    cache["dim"] = render_dim(rgb, P, W, [g for g in v.get("glows", []) if g.get("lamp", True)])
            else:
                # the phone set is resampled from the 1920 renders so it matches them exactly
                cache = {k: np.asarray(to_im(a).resize((W, rgb.shape[0]), Image.LANCZOS), np.float32) / 255 for k, a in cache.items()}
                # thin lines lose weight when halved; give the graphite a little back
                # the white model's drawn edges too: a light unsharp mask keeps them crisp at half size
                for k in ("shell", "clay"):
                    c = cache[k]
                    cache[k] = np.clip(c + 0.7 * (c - gauss(c, 1.2)), 0, 1)
                if "sketch" in cache:
                    sk = cache["sketch"]
                    g = 1 - (luma(sk) / luma(PAPER[None, None, :]))
                    g = np.clip(g * 1.25, 0, 1)
                    cache["sketch"] = PAPER[None, None, :] * (1 - g[..., None]) + GRAPHITE[None, None, :] * g[..., None]
            q = {"sketch": 80, "shell": 80, "clay": 80, "dim": 76}
            for k, a in cache.items():
                p = save(a, v["id"], k, W, q[k])
                print(f"  {p.relative_to(SITE)}  {p.stat().st_size // 1024} KB")
            if only_clay:
                continue
            p = save(rgb, v["id"], "lit", W, 82)
            print(f"  {p.relative_to(SITE)}  {p.stat().st_size // 1024} KB")


# ------------------------------------------------------------------ plans (inline SVG, drawn to look like a real drawing)
PS = 40  # svg units per metre


def _f(v):
    return f"{v * PS:.1f}".rstrip("0").rstrip(".")


def plan_svg(v: dict, uid: str) -> str:
    """A plausible plan of the room in the photograph: poché walls, openings, door swings, joinery, furniture,
    a structural grid, overall dimensions, a scale bar and a north point. Every stroke carries pathLength=1
    and a data-g group so build.js can draw it in order: grid, walls, open, fixed, furn, anno."""
    P = v["plan"]
    W, D = P["size"]
    m = 2.6                                              # margin in metres (grid bubbles, dimensions)
    vb = f"{-m * PS:.0f} {-m * PS:.0f} {(W + 2 * m) * PS:.0f} {(D + 2 * m + 1.4) * PS:.0f}"
    el = []
    def L(g, d, cls="pl-l", extra=""):
        draw = not ("pl-dash" in cls or "pl-grid" in cls)     # dashed lines fade in; solid ones draw themselves
        cl, pl = (cls + " pl-draw", ' pathLength="1"') if draw else (cls, "")
        el.append(f'<path class="{cl}" data-g="{g}" d="{d}"{pl}{extra}/>')
    rect = lambda x0, y0, x1, y1: f"M{_f(x0)} {_f(y0)}H{_f(x1)}V{_f(y1)}H{_f(x0)}Z"
    def circ(cx, cy, r):
        return f"M{_f(cx - r)} {_f(cy)}a{_f(r)} {_f(r)} 0 1 0 {_f(2 * r)} 0a{_f(r)} {_f(r)} 0 1 0 {_f(-2 * r)} 0Z"
    # structural grid
    for i, x in enumerate(P.get("gx", [])):
        L("grid", f"M{_f(x)} {_f(-1.6)}V{_f(D + 0.6)}", "pl-grid")
        el.append(f'<g data-g="grid" class="pl-bub"><circle cx="{_f(x)}" cy="{_f(-2.0)}" r="{_f(0.4)}"/><text x="{_f(x)}" y="{_f(-2.0)}">{"ABCDEFGH"[i]}</text></g>')
    for i, y in enumerate(P.get("gy", [])):
        L("grid", f"M{_f(-1.6)} {_f(y)}H{_f(W + 0.6)}", "pl-grid")
        el.append(f'<g data-g="grid" class="pl-bub"><circle cx="{_f(-2.0)}" cy="{_f(y)}" r="{_f(0.4)}"/><text x="{_f(-2.0)}" y="{_f(y)}">{i + 1}</text></g>')
    # walls: poché fill (fades in) + outline (draws)
    for w_ in P["walls"]:
        x0, y0, x1, y1 = w_[:4]
        kind = w_[4] if len(w_) > 4 else ""
        fill = f"url(#hatch-{uid})" if kind == "brick" else "currentColor"
        el.append(f'<path class="pl-poche" data-g="poche" d="{rect(x0, y0, x1, y1)}" fill="{fill}"/>')
        L("walls", rect(x0, y0, x1, y1), "pl-wall")
    for x0, y0, x1, y1 in P.get("glazing", []):
        horiz = abs(x1 - x0) > abs(y1 - y0)
        if horiz:
            ym = (y0 + y1) / 2
            L("open", f"M{_f(x0)} {_f(y0)}H{_f(x1)}M{_f(x0)} {_f(y1)}H{_f(x1)}M{_f(x0)} {_f(ym)}H{_f(x1)}", "pl-l pl-thin")
            n = max(1, round(abs(x1 - x0) / 1.2))
            L("open", "".join(f"M{_f(x0 + (x1 - x0) * k / n)} {_f(y0)}V{_f(y1)}" for k in range(n + 1)), "pl-l pl-thin")
        else:
            xm = (x0 + x1) / 2
            L("open", f"M{_f(x0)} {_f(y0)}V{_f(y1)}M{_f(x1)} {_f(y0)}V{_f(y1)}M{_f(xm)} {_f(y0)}V{_f(y1)}", "pl-l pl-thin")
            n = max(1, round(abs(y1 - y0) / 1.2))
            L("open", "".join(f"M{_f(x0)} {_f(y0 + (y1 - y0) * k / n)}H{_f(x1)}" for k in range(n + 1)), "pl-l pl-thin")
    for d in P.get("doors", []):
        hx, hy, r, a0, a1 = d                      # hinge, leaf length, closed angle, open angle (degrees)
        t0, t1 = math.radians(a0), math.radians(a1)
        ex, ey = hx + r * math.cos(t1), hy + r * math.sin(t1)
        sx, sy = hx + r * math.cos(t0), hy + r * math.sin(t0)
        sweep = 1 if (a1 - a0) % 360 < 180 else 0
        L("open", f"M{_f(hx)} {_f(hy)}L{_f(ex)} {_f(ey)}", "pl-l")
        L("open", f"M{_f(ex)} {_f(ey)}A{_f(r)} {_f(r)} 0 0 {1 - sweep} {_f(sx)} {_f(sy)}", "pl-l pl-thin pl-dash")
    for c in P.get("columns", []):
        cx, cy, r = c[:3]
        shape = c[3] if len(c) > 3 else "sq"
        d = circ(cx, cy, r) if shape == "o" else rect(cx - r, cy - r, cx + r, cy + r)
        el.append(f'<path class="pl-poche" data-g="poche" d="{d}" fill="currentColor"/>')
        L("walls", d, "pl-wall")
    # fixed: joinery, stair, overhead
    for f in P.get("fixed", []):
        kind = f[0]
        if kind == "rect":
            L("fixed", rect(*f[1:5]))
            if len(f) > 5 and f[5] == "top":        # a counter: draw the worktop overhang
                x0, y0, x1, y1 = f[1:5]
                L("fixed", rect(x0 + 0.08, y0 + 0.08, x1 - 0.08, y1 - 0.08), "pl-l pl-thin")
        elif kind == "poly":
            pts = f[1]
            L("fixed", "M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in pts) + "Z")
        elif kind == "stair":
            x0, y0, x1, y1, n = f[1:6]
            L("fixed", rect(x0, y0, x1, y1))
            L("fixed", "".join(f"M{_f(x0 + (x1 - x0) * k / n)} {_f(y0)}V{_f(y1)}" for k in range(1, n)), "pl-l pl-thin")
            ym = (y0 + y1) / 2
            L("fixed", f"M{_f(x0 + 0.3)} {_f(ym)}H{_f(x1 - 0.35)}M{_f(x1 - 0.7)} {_f(ym - 0.22)}L{_f(x1 - 0.35)} {_f(ym)}L{_f(x1 - 0.7)} {_f(ym + 0.22)}", "pl-l pl-thin")
            el.append(f'<text class="pl-note" data-g="anno" x="{_f(x0 + 0.5)}" y="{_f(y1 + 0.45)}">UP</text>')
        elif kind == "over":                     # overhead: mezzanine edge, trusses, arches
            L("fixed", "M" + "L".join(f"{_f(x)} {_f(y)}" for x, y in f[1]), "pl-l pl-thin pl-dash")
        elif kind == "overc":
            L("fixed", circ(*f[1:4]), "pl-l pl-thin pl-dash")
        elif kind == "slats":
            x0, y0, x1, n = f[1:5]
            L("fixed", "".join(f"M{_f(x0 + (x1 - x0) * k / n)} {_f(y0 - 0.12)}V{_f(y0 + 0.12)}" for k in range(n + 1)), "pl-l pl-thin")
    # furniture
    for f in P.get("furn", []):
        kind = f[0]
        if kind == "table":                      # x, y (centre), w, d, chairs per long side, chairs at ends
            cx, cy, w, d_, n = f[1:6]
            ends = f[6] if len(f) > 6 else 0
            L("furn", rect(cx - w / 2, cy - d_ / 2, cx + w / 2, cy + d_ / 2))
            cs = 0.42
            for k in range(n):
                x = cx - w / 2 + w * (k + 0.5) / n
                L("furn", rect(x - cs / 2, cy - d_ / 2 - 0.12 - cs, x + cs / 2, cy - d_ / 2 - 0.12), "pl-l pl-thin")
                L("furn", rect(x - cs / 2, cy + d_ / 2 + 0.12, x + cs / 2, cy + d_ / 2 + 0.12 + cs), "pl-l pl-thin")
            for sgn in ([-1, 1] if ends else []):
                x = cx + sgn * (w / 2 + 0.12 + cs / 2)
                L("furn", rect(x - cs / 2, cy - cs / 2, x + cs / 2, cy + cs / 2), "pl-l pl-thin")
        elif kind == "round":                    # round table with n chairs
            cx, cy, r, n = f[1:5]
            L("furn", circ(cx, cy, r))
            for k in range(n):
                t = 2 * math.pi * k / n + math.pi / 4
                L("furn", circ(cx + (r + 0.35) * math.cos(t), cy + (r + 0.35) * math.sin(t), 0.22), "pl-l pl-thin")
        elif kind == "stool":
            L("furn", circ(f[1], f[2], f[3] if len(f) > 3 else 0.2), "pl-l pl-thin")
        elif kind == "plant":
            cx, cy, r = f[1:4]
            L("furn", circ(cx, cy, r), "pl-l pl-thin")
            L("furn", circ(cx, cy, r * 0.55), "pl-l pl-thin pl-dash")
        elif kind == "booth":                    # x0, y0, x1, y1, seat depth: seats north and south of a fixed table
            x0, y0, x1, y1, sd = f[1:6]
            L("furn", rect(x0, y0, x1, y0 + sd))
            L("furn", rect(x0, y1 - sd, x1, y1))
            L("furn", rect(x0 + 0.05, y0 + sd + 0.12, x1 - 0.35, y1 - sd - 0.12), "pl-l pl-thin")
        elif kind == "rect":
            L("furn", rect(*f[1:5]), "pl-l pl-thin")
    # annotation: overall dimensions, room label, north point, scale bar, title
    tick = lambda x, y: f"M{_f(x - 0.18)} {_f(y + 0.18)}L{_f(x + 0.18)} {_f(y - 0.18)}"
    yd = -0.9
    L("anno", f"M0 {_f(yd)}H{_f(W)}" + tick(0, yd) + tick(W, yd), "pl-l pl-thin")
    el.append(f'<text class="pl-dim" data-g="anno" x="{_f(W / 2)}" y="{_f(yd - 0.25)}">{int(W * 1000):,}</text>'.replace(",", " "))
    xd = W + 0.9
    L("anno", f"M{_f(xd)} 0V{_f(D)}" + tick(xd, 0) + tick(xd, D), "pl-l pl-thin")
    el.append(f'<text class="pl-dim" data-g="anno" x="{_f(xd + 0.3)}" y="{_f(D / 2)}" transform="rotate(90 {_f(xd + 0.3)} {_f(D / 2)})">{int(D * 1000):,}</text>'.replace(",", " "))
    lx, ly = P["label"]["at"]
    el.append(f'<text class="pl-room" data-g="anno" x="{_f(lx)}" y="{_f(ly)}">{H.escape(P["label"]["name"])}</text>')
    el.append(f'<text class="pl-note" data-g="anno" x="{_f(lx)}" y="{_f(ly + 0.75)}">{H.escape(P["label"]["area"])}</text>')
    # north point (bottom right) and scale bar (bottom left)
    nx, ny = W - 0.6, D + 1.8
    el.append(f'<g data-g="anno" class="pl-north" transform="translate({_f(nx)} {_f(ny)}) rotate({P.get("north", 0)})">'
              f'<circle r="{_f(0.55)}"/><path d="M0 {_f(-0.55)}L{_f(0.2)} {_f(0.3)}L0 {_f(0.12)}L{_f(-0.2)} {_f(0.3)}Z"/>'
              f'<text y="{_f(-0.85)}">N</text></g>')
    sy = D + 1.8
    segs = [(0, 1), (1, 2), (2, 3), (3, 5)]
    for i, (a0, a1) in enumerate(segs):
        el.append(f'<rect class="pl-scale{" is-f" if i % 2 == 0 else ""}" data-g="anno" x="{_f(a0)}" y="{_f(sy - 0.12)}" width="{_f(a1 - a0)}" height="{_f(0.24)}"/>')
    for t in (0, 1, 2, 5):
        el.append(f'<text class="pl-note" data-g="anno" x="{_f(t)}" y="{_f(sy + 0.7)}">{t}</text>')
    el.append(f'<text class="pl-note" data-g="anno" x="{_f(5.35)}" y="{_f(sy + 0.7)}" text-anchor="start">m</text>')
    el.append(f'<text class="pl-title" data-g="anno" x="0" y="{_f(sy + 1.55)}">{H.escape(P["title"])}</text>')
    defs = (f'<defs><pattern id="hatch-{uid}" width="{_f(0.22)}" height="{_f(0.22)}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<path d="M0 0V{_f(0.22)}" stroke="currentColor" stroke-width="1.4"/></pattern></defs>')
    return (f'<svg class="build__plan-svg" viewBox="{vb}" role="img" aria-label="{H.escape(P["aria"])}" preserveAspectRatio="xMidYMid meet">'
            + defs + f'<g id="build-plan-{uid}">' + "".join(el) + "</g></svg>")


def plan_use(v: dict, uid: str) -> str:
    """The same drawing again (reduced-motion spread), by reference."""
    P = v["plan"]
    W, D = P["size"]
    m = 2.6
    vb = f"{-m * PS:.0f} {-m * PS:.0f} {(W + 2 * m) * PS:.0f} {(D + 2 * m + 1.4) * PS:.0f}"
    return (f'<svg class="build__plan-svg is-static" viewBox="{vb}" role="img" aria-label="{H.escape(P["aria"])}" preserveAspectRatio="xMidYMid meet">'
            f'<use href="#build-plan-{uid}"/></svg>')


# ------------------------------------------------------------------ the partials (one per venue)
ROOT = "{{root}}"          # sync_partials.py replaces it with the path back to the site root ("" or "../")


def _n(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _href(h: str) -> str:
    """A site-relative link from build.json, rooted for the page the partial lands on."""
    return H.escape(h if h.startswith(("#", "http", "mailto:", "tel:")) else ROOT + h)


def _arr() -> str:
    return '<span class="arr" aria-hidden="true">→</span>'


def pop_body(p: dict, e=H.escape) -> str:
    """The inside of one note: label, the line (a numeral, a quote or plain text), an optional action."""
    kind = p.get("kind", "promise")
    if kind == "client":
        body = (f'<blockquote class="build__pop-quote"><p>“{e(p["text"])}”</p></blockquote>'
                f'<p class="build__pop-cite">{e(p["cite"])}</p>')
    elif p.get("value"):
        body = f'<p class="build__pop-text"><span class="build__pop-num t-num">{e(p["value"])}</span> {e(p["text"])}</p>'
    else:
        body = f'<p class="build__pop-text">{e(p["text"])}</p>'
    a = p.get("action")
    if a:
        here = f' data-here="{e(a["here"])}"' if a.get("here") else ""
        body += f'<a class="build__pop-link" href="{_href(a["href"])}"{here}>{e(a["label"])} {_arr()}</a>'
    return body


def pops_html(v: dict, C: dict) -> str:
    """The trust notes: one small card per stage, popped up by build.js as that stage arrives (and put away as it
    ends). A polite live region reads each one once; the close button puts them all away for this venue."""
    e = H.escape
    cards = "".join(
        f'<div class="build__pop" data-pop="{i}" data-kind="{e(p.get("kind", "promise"))}"><div class="build__pop-in">'
        f'<p class="build__pop-label t-label">{e(p["label"])}</p>{pop_body(p)}'
        f'<button class="build__pop-close" type="button" data-pop-close aria-label="{e(C["popClose"])}"><i aria-hidden="true"></i></button>'
        f'</div></div>'
        for i, p in enumerate(v["copy"]["pops"]))
    return (f'<div class="build__pops" data-pops role="group" aria-label="{e(C["popsGroup"])}">'
            f'<p class="sr-only" aria-live="polite" data-pop-live></p>{cards}</div>')


def notes_html(v: dict, C: dict) -> str:
    """Reduced motion / no JS: the same notes as a small list beside the stills."""
    e, vid = H.escape, v["id"]
    items = "".join(
        f'<li class="build__note" data-kind="{e(p.get("kind", "promise"))}"><p class="build__note-label t-label"><span class="t-num">{i + 1:02d}</span> {e(p["label"])}</p>'
        f'{pop_body(p)}</li>'
        for i, p in enumerate(v["copy"]["pops"]))
    return (f'<div class="build__notes"><p class="build__notes-title t-label" id="build-{vid}-notes">{e(C["popsLabel"])}</p>'
            f'<ol class="build__notes-list" aria-labelledby="build-{vid}-notes">{items}</ol></div>')


def end_actions(v: dict, C: dict, solid=False) -> str:
    """Stage 07's actions. The café opens the corner table (cafe-seq); the others go to their sector page and
    to a prefilled brief. A link to the page it's on goes to its data-here section instead (build.js)."""
    e, end = H.escape, v["copy"]["end"]
    main = "btn--solid" if solid else "btn--paper"
    if end["kind"] == "cafe":
        cta = (f'<button class="btn {main} build__cta" type="button" data-cafe-seq-open aria-haspopup="dialog" aria-controls="corner-table" '
               f'aria-label="{e(end["aria"])}" data-cursor="Sit down">{e(end["label"])} {_arr()}</button>')
        if solid:      # no JS: the dialog opens by :target
            cta += f'<a class="btn btn--solid build__cta cafe-seq-fallback" href="#corner-table">{e(end["label"])} {_arr()}</a>'
        return cta
    here = f' data-here="{e(end["here"])}"' if end.get("here") else ""
    second = "" if solid else " btn--on-dark"
    return (f'<a class="btn {main} build__cta" href="{_href(end["href"])}"{here} aria-label="{e(end["aria"])}" data-cursor="Enter">{e(end["label"])} {_arr()}</a>'
            f'<a class="btn{second} build__cta build__cta--2" href="{_href(end["start"])}">{e(C["start"]["label"])} {_arr()}</a>')


def venue_html(v: dict, C: dict) -> str:
    vid, c = v["id"], v["copy"]
    meta = json.loads((OUT / f"{vid}-meta.json").read_text())
    Wm, Hm = meta["size"]
    ar = Wm / Hm
    st = v.get("stage", {})
    e = H.escape
    rule = "".join(f'<path d="M{x0} {y0}L{x1} {y1}" pathLength="1"/>' for x0, y0, x1, y1 in meta["segments"])
    regs = []
    for r in v["regions"]:
        if r["id"] not in meta["boxes"]:
            continue
        x, y, w, h = meta["boxes"][r["id"]]
        src = "shell" if r["group"] == "shell" else "clay"
        regs.append((r["group"], f'<div class="build__reg build__reg--{src}" data-g="{r["group"]}" data-m="{vid}-m-{r["id"]}.webp" '
                     f'style="--x:{_n(x)};--y:{_n(y)};--w:{_n(w)};--h:{_n(h)}"><i></i></div>'))
    grp = lambda g: "".join(h for gg, h in regs if gg == g)
    glows = "".join(f'<i class="build__glow{" build__glow--" + g["c"] if g.get("c") else ""}" style="--x:{_n(g["x"])};--y:{_n(g["y"])};--r:{_n(g["r"])}"></i>'
                    for g in v.get("glows", []))
    # the image box, bottom to top: the sketch and the ruler's lines; the shell (structure regions, then the whole
    # empty model); the fit-out (each piece, then the whole model); the finishes (one soft sweep); the lit room; glows
    box = (f'<div class="build__box" data-box aria-hidden="true">'
           f'<div class="build__layer" data-layer="sketch"></div>'
           f'<svg class="build__rule" viewBox="0 0 {Wm} {Hm}" preserveAspectRatio="none" focusable="false">{rule}</svg>'
           f'{grp("shell")}<div class="build__layer" data-layer="shell"></div>'
           f'{grp("fit")}<div class="build__layer" data-layer="clay"></div>'
           f'<div class="build__sweep" data-sweep><div class="build__layer" data-layer="dim"></div></div>'
           f'<div class="build__layer" data-layer="lit"></div>'
           f'<div class="build__glows">{glows}</div></div>')
    end = c["end"]
    stages = C["stages"]
    diary = "".join(
        f'<li class="build__entry" data-i="{i}"><p class="build__stage-name"><span class="t-num">{i + 1:02d}</span> {e(stages[i])}</p>'
        f'<p class="build__week t-label">{e(wk)}</p><p class="build__cap t-small">{e(cap)}</p></li>'
        for i, (wk, cap) in enumerate(c["diary"]))
    index = "".join(f'<li data-i="{i}"><span>{i + 1:02d}</span></li>' for i in range(len(stages)))
    plan = plan_svg(v, vid)
    skip = (f'<a class="build__skip" href="#build-{vid}-after">{e(C["skip"].split(" ")[0])}<span class="sr-only"> '
            f'{e(" ".join(C["skip"].split(" ")[1:]))}</span> <span class="build__skip-arr" aria-hidden="true">↓</span></a>')
    stage = (f'<div class="build__track" data-track><div class="build__stage" data-stage>'
             f'<div class="build__frame" data-frame>'
             f'<div class="build__plan" data-plan aria-hidden="true">{plan}</div>'
             f'<div class="build__paper" data-paper aria-hidden="true"></div>{box}'
             f'<div class="build__scrim" data-scrim aria-hidden="true"></div>'
             f'<div class="build__end" data-end><p class="build__end-time t-label"><span class="t-num">{c["time"]}</span> · {e(c["diary"][-1][0].split(" · ")[0])}</p>'
             f'<h3 class="build__title t-display-xl" id="build-{vid}-title"><em>{e(end["title"])}</em></h3>'
             f'<div class="build__actions">{end_actions(v, C)}</div></div></div>'
             f'<div class="build__card" data-card><div class="build__card-head t-label"><span class="build__card-where"><span class="t-num">{c["time"]}</span> · {e(c["name"])}</span>'
             f'<span class="build__count t-num" aria-hidden="true"><b data-now>01</b> / {len(stages):02d}</span>{skip}</div>'
             f'<ol class="build__diary">{diary}</ol><ol class="build__index" aria-hidden="true">{index}</ol></div>'
             f'{pops_html(v, C)}'
             f'</div></div>')
    sizes = "(max-width: 900px) 100vw, 31vw"
    def fig(layer, alt, cap):
        src = f"{ROOT}assets/img/build/{vid}-{layer}"
        return (f'<figure class="build__spread-fig"><div class="media" style="aspect-ratio:{Wm}/{Hm}">'
                f'<img src="{src}-1920.webp" srcset="{src}-960.webp 960w, {src}-1920.webp 1920w" '
                f'sizes="{sizes}" width="{Wm}" height="{Hm}" alt="{e(alt)}" loading="lazy" decoding="async"></div>'
                f'<figcaption class="build__spread-cap"><span class="t-label">{cap[0]}</span><span class="t-small">{e(cap[1])}</span></figcaption></figure>')
    L3 = C["spreadLabels"]
    d = c["diary"]
    spread = (f'<div class="build__spread">'
              f'<div class="build__spread-head"><p class="t-label"><span class="t-num">{c["time"]}</span> · {e(c["project"])}</p>'
              f'<h3 class="build__spread-title t-display-m">{e(end["title"])}</h3></div>'
              f'<div class="build__spread-row">'
              f'<figure class="build__spread-fig build__spread-fig--plan"><div class="build__spread-plan" style="aspect-ratio:{Wm}/{Hm}">{plan_use(v, vid)}</div>'
              f'<figcaption class="build__spread-cap"><span class="t-label">01 · {e(L3[0])} · {e(d[0][0])}</span><span class="t-small">{e(d[0][1])}</span></figcaption></figure>'
              + fig("clay", c["alts"]["clay"], (f"03 · {e(L3[1])} · {e(d[2][0])}", d[2][1]))
              + fig("lit", c["alts"]["lit"], (f"07 · {e(L3[2])} · {e(d[6][0])}", d[6][1]))
              + f'</div>{notes_html(v, C)}<div class="build__spread-end">{end_actions(v, C, solid=True)}</div></div>')
    pan = st.get("pan", [0.5, 0.5])
    return (f'<article class="build__venue" id="build-{vid}-room" data-venue="{vid}" aria-labelledby="build-{vid}-title" '
            f'style="--ar:{ar:.4f};--fx:{st.get("fx", 0.5)};--fy:{st.get("fy", 0.5)}" data-pan="{pan[0]},{pan[1]}" data-card="{st.get("card", "left")}">'
            f'{stage}{spread}</article>')


def write_html(ids=()):
    """partials/build-<venue>.html: one self-contained section per venue (intro, the build, the notes, the stills)."""
    data = json.loads(DATA.read_text())
    C = data["copy"]
    e = H.escape
    for v in data["venues"]:
        if ids and v["id"] not in ids:
            continue
        vid, c = v["id"], v["copy"]
        out = f"""<!-- The build: {e(c["name"])} ({c["time"]}). GENERATED by tools/build_layers.py html from assets/data/build.json: edit those, not this.
     Needs assets/css/build.css and assets/js/build.js{" (and the cafe-seq partial, css and js for the corner table)" if c["end"]["kind"] == "cafe" else ""}. -->
<section class="build" id="build-{vid}" data-build data-build-root="{ROOT}assets/img/build/" aria-labelledby="build-{vid}-heading">
  <div class="build__intro wrap">
    <p class="build__eyebrow t-label" data-reveal>{e(C["eyebrow"])}</p>
    <h2 class="build__headline t-display-l" id="build-{vid}-heading" data-split>{C["headline"]}</h2>
    <p class="build__body t-lede" data-reveal data-float="0.6">{e(c["intro"])}</p>
    <p class="sr-only">{e(c["srSummary"])}</p>
    <p class="build__rm-note t-small">{e(C["rmNote"])}</p>
  </div>
  <div class="build__venues">
{venue_html(v, C)}
  </div>
  <div class="build__after" id="build-{vid}-after" tabindex="-1"></div>
</section>
"""
        p = SITE / f"partials/build-{vid}.html"
        p.write_text(out)
        print(f"  {p.relative_to(SITE)}  {len(out) // 1024} KB")


# ------------------------------------------------------------------ authoring preview
def preview(ids):
    """Grid (every 5%, labelled every 10%) plus the regions and glows from build.json, for placing polygons by eye."""
    data = json.loads(DATA.read_text())
    OUT_PREVIEW.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    cols = {"shell": (255, 60, 60), "fit": (40, 140, 255)}
    for v in data["venues"]:
        if ids and v["id"] not in ids:
            continue
        im = Image.open(src_path(v)).convert("RGB")
        W = 1600
        im = im.resize((W, round(im.height * W / im.width)), Image.LANCZOS)
        w, h = im.size
        ov = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ov)
        for i in range(21):
            x, y = i * w / 20, i * h / 20
            a = 150 if i % 2 == 0 else 70
            d.line((x, 0, x, h), fill=(255, 255, 255, a), width=1)
            d.line((0, y, w, y), fill=(255, 255, 255, a), width=1)
            if i % 2 == 0 and 0 < i < 20:
                d.text((x + 3, 3), str(i * 5), fill=(255, 255, 0, 255), font=font)
                d.text((3, y + 3), str(i * 5), fill=(255, 255, 0, 255), font=font)
        for r in v.get("regions", []):
            c = cols.get(r["group"], (0, 255, 0))
            pts = [(x * w, y * h) for x, y in r["poly"]]
            d.polygon(pts, fill=c + (60,), outline=c + (255,))
            cx = sum(p[0] for p in pts) / len(pts); cy = sum(p[1] for p in pts) / len(pts)
            d.text((cx, cy), r["id"], fill=(255, 255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0, 255))
        for g in v.get("glows", []):
            cx, cy, r = g["x"] * w, g["y"] * h, g["r"] * w
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(0, 255, 120, 255), width=2)
        out = Image.alpha_composite(im.convert("RGBA"), ov).convert("RGB")
        p = OUT_PREVIEW / f"grid-{v['id']}.jpg"
        out.save(p, quality=88)
        print(p)


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:] or ["images"]
    if cmd == "images":
        images([a for a in rest if not a.startswith("--")])
    elif cmd == "html":
        write_html(rest)
    elif cmd == "preview":
        preview(rest)  # noqa: F821
    else:
        raise SystemExit(__doc__)
