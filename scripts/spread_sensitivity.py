"""How much bid-ask can the butterfly absorb before the edge is gone?

There are no quotes on this key, and two attempts to recover the spread from
trade prints both failed for reasons worth recording:

* **Corwin-Schultz** estimates the spread from consecutive high-low ranges. On a
  contract that prints once or twice a bar the high equals the low, the range is
  zero, and the estimator returns a **zero spread for the thinnest contracts** --
  exactly backwards, and it degenerates precisely where the cost is largest.
* **Price clustering** would work if a contract traded all day between a fixed
  bid and ask. It does not: AAOI's put printed 51 distinct prices in 70 trades,
  because the underlying moves all session. The interquartile range of a day's
  prints is an upper bound mixing spread with drift, not the spread.

So the spread is not estimated here. The question is inverted instead, which
needs no estimate and cannot be wrong: **at what cost per leg does the result
stop being positive?** That number can then be compared against what anyone who
trades these contracts knows the spread to be.

The accounting
--------------
An iron butterfly has four legs. Opening crosses four spreads and closing
crosses four more, so a round trip pays **eight half-spreads**, which is four
full spreads. A one-cent-wide market costs $0.04 per share, or $4 per contract.
US options quote in $0.01 increments below $3 and $0.05 above, so a penny-wide
market is the best case that exists and a nickel is ordinary.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    args = ap.parse_args(argv)
    C = pd.read_parquet(Path(args.work) / "condor.parquet")
    C = C[C.maxloss > 0].copy()
    C["width_full"] = C.credit + C.maxloss
    C["close_cost"] = np.minimum(C.close_cost, C.width_full)
    C["pnl"] = C.credit - C.close_cost

    print(f"  {len(C)} iron butterflies, gross of any transaction cost\n")
    print(f"  mean credit            {C.credit.mean():>7.2f} per share")
    print(f"  mean maximum loss      {C.maxloss.mean():>7.2f} per share  (= the margin)")
    print(f"  mean P&L               {C.pnl.mean():>+7.2f} per share")
    print(f"  mean return on margin  {(C.pnl / C.maxloss).mean() * 100:>+6.1f}%\n")

    print("=" * 92)
    print("THE EDGE AGAINST THE COST OF CROSSING IT")
    print("=" * 92)
    print("  A round trip pays four full spreads (eight halves, four legs each way).\n")
    print(f"  {'spread per leg':16s}{'cost/share':>12s}{'mean on margin':>17s}"
          f"{'median':>10s}{'win rate':>11s}")
    kill = None
    for s in (0.00, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10, 0.15, 0.20):
        cost = 4 * s
        r = (C.pnl - cost) / C.maxloss
        if kill is None and r.mean() <= 0:
            kill = s
        print(f"  ${s:<15.3f}{cost:>11.2f}{r.mean() * 100:>+16.1f}%"
              f"{np.median(r) * 100:>+9.1f}%{(r > 0).mean() * 100:>10.0f}%")

    # exact break-even
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if ((C.pnl - 4 * mid) / C.maxloss).mean() > 0:
            lo = mid
        else:
            hi = mid
    print(f"\n  break-even spread: **${lo:.3f} per leg**")
    print(f"  the edge survives anything tighter than that and dies beyond it.")

    print("\n" + "=" * 92)
    print("IS THAT A REALISTIC SPREAD FOR THESE CONTRACTS?")
    print("=" * 92)
    print("  US options quote in $0.01 increments below $3 and $0.05 above, so the")
    print("  tightest market that can exist on most of these legs is a nickel.\n")
    print(f"  {'contracts by session volume':34s}{'n':>5s}{'mean credit':>13s}"
          f"{'mean maxloss':>14s}")
    C["tier"] = pd.cut(C.minvol, [-1, 25, 250, 1e9],
                       labels=["thinnest leg <25", "25-250", ">250"])
    for b, g in C.groupby("tier", observed=True):
        print(f"  {str(b):34s}{len(g):>5d}{g.credit.mean():>12.2f}{g.maxloss.mean():>13.2f}")
    print("\n  A leg that trades fewer than 25 times a session is not quoted a")
    print("  nickel wide. Those are the ones that decide this.")

    for s, lab in ((0.05, "a nickel on every leg"), (0.10, "a dime on every leg")):
        r = (C.pnl - 4 * s) / C.maxloss
        eq = 40.0
        for x in r * 0.10:          # 10% of capital risked per trade
            eq *= (1 + x)
        print(f"\n  {lab}: mean {r.mean() * 100:+.1f}% on margin, "
              f"win {(r > 0).mean() * 100:.0f}%, $40 at 10% risk -> ${eq:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
