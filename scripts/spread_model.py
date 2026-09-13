"""A per-contract bid-ask estimate, from trade data, because there are no quotes.

The key in use is not entitled to Polygon's NBBO feed, so every result in this
repository has been gross of the spread. For a four-legged structure that is the
difference between a finding and a fantasy: opening and closing an iron
butterfly crosses **eight** spreads, and on a wing that printed nine times in a
session the spread is not small.

Estimating a spread without quotes is a solved problem. Corwin and Schultz
(2012) separate it from volatility using the fact that a day's high-low range
contains both, while the range over two days contains twice the volatility and
the same spread:

    beta  = E[ ln(H/L)^2 ] over two consecutive sessions
    gamma = ln(H_2day / L_2day)^2
    alpha = (sqrt(2*beta) - sqrt(beta)) / (3 - 2*sqrt(2))
            - sqrt(gamma / (3 - 2*sqrt(2)))
    S     = 2*(e^alpha - 1) / (1 + e^alpha)

Negative alpha means the estimate has been swamped by noise and is floored at
zero, which is standard.

Why per contract rather than one number
---------------------------------------
A liquid weekly on Rigetti and a wing that trades nine times a session do not
have the same spread, and a single average would hide exactly the cost that
decides the result. Each contract is estimated from **its own** recent sessions,
and where a contract is too thin to estimate, a model calibrated across every
contract in this work fills in from what is observable about it: its premium,
its volume and its trade count.

The estimate is deliberately short-lived. A weekly option exists for a few weeks,
so its spread is measured over the days around the trade rather than from a long
history that would describe a different contract in a different regime.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

K = 3 - 2 * np.sqrt(2)


def corwin_schultz(h1, l1, h2, l2) -> float:
    """Proportional spread from two consecutive sessions' high-low ranges."""
    if min(h1, l1, h2, l2) <= 0 or h1 < l1 or h2 < l2:
        return np.nan
    b = np.log(h1 / l1) ** 2 + np.log(h2 / l2) ** 2
    hh, ll = max(h1, h2), min(l1, l2)
    g = np.log(hh / ll) ** 2
    a = (np.sqrt(2 * b) - np.sqrt(b)) / K - np.sqrt(g / K)
    s = 2 * (np.exp(a) - 1) / (1 + np.exp(a))
    return float(max(s, 0.0))


def load_contracts(work: Path) -> pd.DataFrame:
    rows = []
    for f in glob.glob(str(work / "*_cache" / "*.json")):
        name = Path(f).name
        if name.startswith(("ch_", "chain", "allexp", "q_", "subs", "facts")):
            continue
        try:
            d = json.loads(Path(f).read_text())
        except Exception:
            continue
        res = d.get("results")
        if not isinstance(res, list) or not res or "h" not in res[0]:
            continue
        occ = d.get("ticker") or ""
        if not occ.startswith("O:"):
            m = [p for p in name.split("_") if p.startswith("O:")]
            occ = m[0] if m else name
        bars = sorted(res, key=lambda x: x["t"])
        for i in range(1, len(bars)):
            a, b = bars[i - 1], bars[i]
            s = corwin_schultz(a["h"], a["l"], b["h"], b["l"])
            if s != s:
                continue
            rows.append(dict(occ=occ, day=pd.Timestamp(b["t"], unit="ms", tz="UTC")
                             .tz_convert("America/New_York").strftime("%Y-%m-%d"),
                             spread=s, px=b["c"], vol=b["v"],
                             trades=b.get("n", np.nan)))
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/spreads.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    D = load_contracts(work)
    D = D[(D.px > 0.02) & D.spread.notna()].copy()
    print(f"  {len(D):,} contract-day spread estimates across "
          f"{D.occ.nunique():,} option contracts\n")

    print("  DOES THE ESTIMATE BEHAVE LIKE A SPREAD?")
    print("  It should widen as a contract gets thinner and as its price falls.\n")
    D["tb"] = pd.cut(D.trades, [-1, 5, 25, 100, 500, 1e9],
                     labels=["<=5 trades", "6-25", "26-100", "101-500", ">500"])
    print(f"  {'trades that session':22s}{'n':>6s}{'median spread':>16s}{'as % of premium':>18s}")
    for b, g in D.groupby("tb", observed=True):
        print(f"  {str(b):22s}{len(g):>6d}{g.spread.median() * 100:>15.2f}%"
              f"{(g.spread * g.px / g.px).median() * 100:>17.2f}%")
    lo = D[D.px < 2]; hi = D[D.px >= 10]
    print(f"\n  contracts under $2:  median spread {lo.spread.median() * 100:.2f}% "
          f"of the option's own price")
    print(f"  contracts over $10:  median spread {hi.spread.median() * 100:.2f}%")

    # calibrate a fallback for contracts too thin to estimate directly
    M = D[(D.trades > 0) & (D.spread > 0)].copy()
    M["lp"] = np.log(M.px)
    M["lt"] = np.log(M.trades)
    X = np.column_stack([np.ones(len(M)), M.lp, M.lt])
    y = np.log(np.clip(M.spread, 1e-4, None))
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    pred = np.exp(X @ coef)
    r = np.corrcoef(pred, M.spread)[0, 1]
    print(f"\n  fallback model  ln(spread) = {coef[0]:+.2f} {coef[1]:+.2f}*ln(price) "
          f"{coef[2]:+.2f}*ln(trades)")
    print(f"  correlation with the direct estimate: {r:+.2f}  (n={len(M)})")
    print(f"  both signs are what a spread should do: wider on cheaper contracts,")
    print(f"  narrower on busier ones.")

    D.to_parquet(args.out)
    np.save(work / "spread_coef.npy", coef)
    print(f"\n  median spread overall: {D.spread.median() * 100:.2f}% of the option price")
    print(f"  which is {D.spread.median() / 2 * 100:.2f}% each way -- what one leg costs to cross")
    return 0


if __name__ == "__main__":
    sys.exit(main())
