"""What the defined-risk sell returned, and what it gave up to be defined.

Two comparisons matter and both are reported. Against the **naked** short
straddle -- the same trade without wings -- to see what the protection cost.
And against the **long** option books, which is what every earlier test in this
repository was doing.

Return is quoted on **maximum loss**, which for a defined-risk spread is both
the worst case and the margin a broker holds. That makes it directly comparable
across trades of different sizes, and it is a number knowable before the trade
rather than discovered afterwards.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MIN_VOL = 25


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)
    C = pd.read_parquet(Path(args.work) / "condor.parquet")
    C = C[C.maxloss > 0].copy()
    # An iron butterfly cannot be worth more than its wing width: the two call
    # legs cannot be deeper in the money than the distance between them, and
    # arbitrage enforces it. Two closing marks here exceeded the width -- QUBT
    # by 0.34 and EOSE by 0.02, both on gaps far beyond the upper wing -- which
    # means the short leg's opening print and the wing's came from different
    # moments, not that the position lost more than it structurally can. The
    # cost is clamped at the width, which is the price a closing order would
    # actually have met.
    C["width_full"] = C.credit + C.maxloss
    C["clamped"] = C.close_cost > C.width_full + 1e-9
    C["close_cost"] = np.minimum(C.close_cost, C.width_full)
    C["pnl"] = C.credit - C.close_cost
    C["ret_margin"] = C.pnl / C.maxloss
    C["naked"] = C.credit - (C.gap.abs() * C.spot)          # at expiry, no wings
    C["ret"] = C.ret_margin
    C["ok"] = C.minvol >= MIN_VOL

    print("\n" + "=" * 100)
    print("EVERY IRON BUTTERFLY  (sold at the close before, bought back into the gap)")
    print("=" * 100)
    print(f"  {'tkr':7s}{'entry':12s}{'gap':>8s}{'credit':>8s}{'maxloss':>9s}"
          f"{'P&L':>8s}{'on margin':>11s}{'naked P&L':>11s}{'vol':>7s}")
    for _, r in C.sort_values("ret").iterrows():
        print(f"  {r.ticker:7s}{r.entry:12s}{r.gap * 100:>+7.1f}%{r.credit:>8.2f}"
              f"{r.maxloss:>9.2f}{r.pnl:>+8.2f}{r.ret * 100:>+10.0f}%"
              f"{r.naked:>+11.2f}{r.minvol:>7,.0f}")

    print("\n" + "=" * 100)
    print("THE RESULT")
    print("=" * 100)
    for lab, g in (("all priced", C), (f"both wings traded >={MIN_VOL}", C[C.ok])):
        if not len(g):
            continue
        r = g.ret.to_numpy()
        eq = args.stake
        for x in r:
            eq *= (1 + x)
        print(f"\n  {lab}  (n={len(g)})")
        print(f"    mean return on margin        {r.mean() * 100:>+7.1f}%")
        print(f"    median                       {np.median(r) * 100:>+7.1f}%")
        print(f"    win rate                     {(r > 0).mean() * 100:>7.0f}%")
        print(f"    worst single trade           {r.min() * 100:>+7.0f}%   "
              f"(the structure caps it at -100%)")
        print(f"    total credit collected       {g.credit.sum():>7.2f} per share")
        print(f"    total P&L                    {g.pnl.sum():>+7.2f} per share")
        print(f"    ${args.stake:.0f} compounded            {eq:>7.2f}")
        if len(g) > 3:
            b = np.array([np.mean(np.random.default_rng(s).choice(r, len(r)))
                          for s in range(4000)])
            print(f"    95% interval on the mean     "
                  f"[{np.percentile(b, 2.5) * 100:+.0f}, {np.percentile(b, 97.5) * 100:+.0f}]%")

    print("\n" + "=" * 100)
    print("WHAT THE WINGS COST, AND WHAT THEY SAVED")
    print("=" * 100)
    nk = C.naked / C.spot * 100
    cd = C.pnl / C.spot * 100
    print(f"  {'':28s}{'naked short':>15s}{'with wings':>14s}")
    print(f"  {'mean P&L, % of spot':28s}{nk.mean():>14.2f}%{cd.mean():>13.2f}%")
    print(f"  {'worst trade, % of spot':28s}{nk.min():>14.2f}%{cd.min():>13.2f}%")
    print(f"  {'trades losing >5% of spot':28s}{(nk < -5).sum():>14d}{(cd < -5).sum():>13d}")
    print("\n  The wings give up part of the credit on every trade and take the")
    print("  unbounded loss off the table on the few that matter.")
    if C.clamped.any():
        print(f"\n  {int(C.clamped.sum())} closing marks were clamped to the wing width "
              f"({', '.join(C[C.clamped].ticker)}),")
        print("  because the printed legs implied a value the structure cannot reach.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
