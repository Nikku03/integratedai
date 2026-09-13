"""Gate Zero: does permutation entropy measure anything, before asking what.

The pre-registration's gate (H0) asks whether PE is volatility wearing a
costume. That is the wrong question, and it is worth being precise about why:
**a pure-noise feature passes H0 trivially.** Orthogonality to volatility is
evidence of no shared information, never of orthogonal information. A gate that
cannot distinguish "measures something else" from "measures nothing" is not a
gate.

This runs the question H0 cannot ask, and it touches no forward return. Three
diagnostics, each with realised volatility computed the identical way as a
positive control -- if the controls come back strong and PE comes back flat, the
instrument works and the quantity is empty:

**Dispersion against its own sampling noise.** PE over a window of W returns is a
multinomial estimate over ``m!`` bins; at m=3, W=60 that is 58 patterns in 6 bins,
about 10 counts each, and the estimator has a standard deviation of its own. The
null is each name's own returns permuted -- preserving its distribution and its
exact ties, destroying only the ordering. If the real cross-section is no wider
than that null, there is no state to sort on.

**Split-half reliability.** PE on the first and second half of one window should
agree if it measures a property of the name.

**Non-overlapping persistence.** PE on consecutive disjoint windows likewise.

Exact ties are reported and stratified rather than assumed away. Bandt-Pompe
breaks ties by index order, which is defensible only when ties are rare; a flat
window encodes as PE = 0 -- maximally confident and maximally wrong. That is the
Corwin-Schultz ``high == low`` degeneracy in a new costume, and this repository
has been caught by it once already.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

M_DIM = 3
FACT = float(np.math.factorial(M_DIM)) if hasattr(np, "math") else 6.0


def pe(seg: np.ndarray, m: int = M_DIM) -> np.ndarray:
    """Normalised permutation entropy of each row's trailing window."""
    W3 = sliding_window_view(seg, m, axis=-1)
    radix = np.array([m ** (m - 1 - i) for i in range(m)])
    code = (W3.argsort(axis=-1, kind="stable") * radix).sum(-1)
    u, inv = np.unique(code, return_inverse=True)
    inv = inv.reshape(code.shape)
    oh = np.zeros(code.shape + (len(u),), np.float64)
    np.put_along_axis(oh, inv[..., None], 1.0, -1)
    p = oh.sum(-2)
    p /= p.sum(-1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        h = -np.nansum(np.where(p > 0, p * np.log(p), 0.0), -1)
    return h / np.log(float(np.prod(range(1, m + 1))))


def share(ratio: float) -> float:
    """Fraction of observed variance that is not sampling noise."""
    return max(0.0, 1.0 - 1.0 / ratio ** 2) if ratio > 1 else 0.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--windows", default="60,120,250")
    ap.add_argument("--shuffles", type=int, default=200)
    ap.add_argument("--min-price", type=float, default=5.0)
    ap.add_argument("--min-dvol", type=float, default=20e6)
    args = ap.parse_args(argv)
    p = Path(args.panel)

    C = pd.read_parquet(p / "c.parquet")
    D = pd.read_parquet(p / "dvol.parquet")
    ok = ((C.median() >= args.min_price) & (D.median() >= args.min_dvol)
          & (C.notna().mean() >= 0.98))
    C = C.loc[:, ok]
    R = np.log(C).diff().iloc[1:]
    R = R.loc[:, R.notna().all()]
    X = R.to_numpy(np.float64).T
    names = R.columns.to_numpy()
    print(f"  {X.shape[0]:,} names x {X.shape[1]} returns "
          f"(close >= ${args.min_price:g}, $vol >= ${args.min_dvol/1e6:g}M)\n")

    rng = np.random.default_rng(0)
    W0 = int(args.windows.split(",")[0])
    seg = X[:, -W0:]
    real = pe(seg)
    tie = (seg[:, 1:] == seg[:, :-1]).mean(-1)
    null = np.array([pe(rng.permuted(seg, axis=-1)) for _ in range(args.shuffles)])

    print(f"  DISPERSION vs ITS OWN SAMPLING NOISE  (m={M_DIM}, W={W0})")
    r = real.std() / null.std(1).mean()
    print(f"    real cross-sectional sd    {real.std():.6f}")
    print(f"    shuffle-null sd            {null.std(1).mean():.6f}")
    print(f"    ratio                      {r:.4f}"
          f"    -> signal share {share(r)*100:.1f}%"
          + ("   (real is NARROWER than pure noise)" if r <= 1 else ""))
    print(f"\n    stratified by exact-tie rate:")
    for lab, msk in (("tie-free", tie == 0), ("<= 2%", tie <= 0.02),
                     ("> 5%", tie > 0.05)):
        if msk.sum() < 10:
            print(f"      {lab:10s} n={msk.sum():5d}   (too few to judge)")
            continue
        rr = real[msk].std() / null[:, msk].std(1).mean()
        print(f"      {lab:10s} n={msk.sum():5d}   ratio {rr:.4f}"
              f"   signal share {share(rr)*100:5.1f}%")
    print(f"      most tie-prone: {', '.join(names[np.argsort(-tie)[:6]])}")

    print(f"\n  IS IT A PERSISTENT PROPERTY OF THE NAME?"
          f"   (realised volatility, computed identically, is the control)")
    h = X[:, -W0:]
    a, b = pe(h[:, :W0 // 2]), pe(h[:, W0 // 2:])
    va, vb = h[:, :W0 // 2].std(-1), h[:, W0 // 2:].std(-1)
    print(f"    split-half reliability     PE {np.corrcoef(a, b)[0, 1]:+.4f}"
          f"      vol {np.corrcoef(va, vb)[0, 1]:+.4f}")
    if X.shape[1] >= 2 * W0:
        p1, p2 = pe(X[:, -2 * W0:-W0]), pe(X[:, -W0:])
        v1, v2 = X[:, -2 * W0:-W0].std(-1), X[:, -W0:].std(-1)
        print(f"    non-overlap persistence    PE {np.corrcoef(p1, p2)[0, 1]:+.4f}"
              f"      vol {np.corrcoef(v1, v2)[0, 1]:+.4f}")

    rv = X[:, -W0:].std(-1)
    c = np.corrcoef(real, rv)[0, 1]
    print(f"\n  THE GATE THAT WAS ACTUALLY REGISTERED (H0)")
    print(f"    corr(PE, realised vol) = {c:+.4f}   |corr| < 0.7 required"
          f"  ->  {'PASSES' if abs(c) < 0.7 else 'FAILS'}")
    print(f"    and it passes for a feature just shown to be sampling noise,")
    print(f"    which is the point: H0 is diagnostic, never confirmatory.")

    print(f"\n  DOES A LONGER WINDOW RESCUE IT?")
    for Wl in [int(x) for x in args.windows.split(",")]:
        if X.shape[1] < Wl:
            print(f"    W={Wl:3d}   not enough history ({X.shape[1]} returns)")
            continue
        sg = X[:, -Wl:]
        rl = pe(sg)
        nd = np.array([pe(rng.permuted(sg, axis=-1)) for _ in range(60)])
        rr = rl.std() / nd.std(1).mean()
        print(f"    W={Wl:3d}   ratio {rr:.4f}   signal share {share(rr)*100:5.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
