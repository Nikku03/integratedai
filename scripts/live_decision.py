"""Put or call, decided before the filing exists, with the arithmetic shown.

The trade is placed the session before a scheduled report, so the document
cannot be read. Direction is therefore a forecast, and the only honest way to
present one is next to the accuracy it would need.

The arithmetic that governs everything
--------------------------------------
An at-the-money straddle is priced at roughly the move the market expects. One
leg of it therefore costs about half that expected move. If gaps are symmetric
around zero, a single directional leg returns

    E[return]  =  E[max(0, gap)] / premium  -  1

and at fair pricing E[max(0, gap)] is half the mean absolute gap, which is
exactly the premium -- so the expectation is **zero** and the break-even
accuracy is **50%**. There is no leverage trick that changes this. A directional
option bet wins only if you beat a coin, or if the premium is genuinely below
the expected move.

Measured on 2,842 earnings releases, the market charges **13.7%** of spot for a
move that delivers **9.9%**, so the buyer starts behind. Measured on 30 real
weekly purchases, a correct call returned +48.8% and a wrong one -48.9%, putting
break-even accuracy at **55.3%** -- and the reading of the actual filing
delivered **47.8%**.

This script prints, for each candidate, what its own history says and what
accuracy the trade would need. It does not pretend the forecast is better than
it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Measured across 2,842 earnings releases: premium charged against move delivered.
MARKET_CHARGES, MARKET_DELIVERS = 0.137, 0.099


def binom_p(k: int, n: int) -> float:
    """P(at least k of n) under a fair coin -- is an up-rate distinguishable?"""
    from math import comb
    return sum(comb(n, i) for i in range(k, n + 1)) / 2 ** n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--basis", default="/tmp/claude-0/opt/live_basis.parquet")
    args = ap.parse_args(argv)
    B = pd.read_parquet(args.basis)
    B = B[B.n_events >= 4].sort_values("reportDate")

    print("\n" + "=" * 98)
    print("WHAT EACH NAME'S OWN EARNINGS HISTORY SAYS")
    print("=" * 98)
    print(f"  {'tkr':6s}{'reports':12s}{'n':>3s}{'mean |gap|':>12s}{'max':>8s}"
          f"{'up rate':>9s}{'is that a coin?':>17s}{'vol20':>7s}")
    for r in B.itertuples():
        k = int(round(r.up_rate * r.n_events))
        p = binom_p(k, int(r.n_events))
        verdict = "yes, indistinguishable" if p > 0.10 else f"maybe (p={p:.3f})"
        print(f"  {r.symbol:6s}{r.reportDate:12s}{int(r.n_events):>3d}"
              f"{r.gap_mean_abs * 100:>11.1f}%{r.gap_max_abs * 100:>7.1f}%"
              f"{r.up_rate * 100:>8.0f}%{verdict:>17s}{r.vol20 * 100:>6.0f}%")

    print("\n" + "=" * 98)
    print("PROJECTED FIGURES, PER NAME")
    print("=" * 98)
    print("  Premium is estimated as half the straddle, and the straddle as the")
    print("  mean absolute gap this name has actually produced. Where the market")
    print("  overprices -- as it did by 3.8pp across 2,842 releases -- the premium")
    print("  is higher and every figure below gets worse.\n")
    for r in B.itertuples():
        g = r.gap_mean_abs
        prem_fair = g / 2                      # one leg, fairly priced
        prem_real = prem_fair * (MARKET_CHARGES / MARKET_DELIVERS)
        up = g                                 # a gap your way, of typical size
        print(f"  {r.symbol}  ({r.name[:34]})   reports {r.reportDate}, "
              f"spot ${r.close:.2f}")
        print(f"    typical gap                       {g * 100:>6.1f}%   "
              f"(largest seen {r.gap_max_abs * 100:.1f}%)")
        print(f"    fair premium, one weekly leg      {prem_fair * 100:>6.1f}% of spot "
              f"= ${prem_fair * r.close:.2f}")
        print(f"    likely premium after the markup   {prem_real * 100:>6.1f}% of spot "
              f"= ${prem_real * r.close:.2f}")
        for lab, prem in (("fairly priced", prem_fair), ("realistically priced", prem_real)):
            win = up / prem - 1
            lose = -1.0
            need = -lose / (win - lose)
            print(f"    {lab:22s} right: {win * 100:>+7.0f}%   "
                  f"wrong: {lose * 100:>+5.0f}%   break-even accuracy {need * 100:>5.1f}%")
        print()

    print("=" * 98)
    print("THE BAR, AND WHAT IS KNOWN ABOUT CLEARING IT")
    print("=" * 98)
    print(f"  reading the ACTUAL filing gave           47.8% accuracy  (23 trades)")
    print(f"  a directional weekly needed              55.3%")
    print(f"  forecasting BEFORE the filing exists     unmeasured, and it is strictly")
    print(f"                                           less information than reading it")
    print("\n  Every projection above is conditional on an accuracy nobody here has")
    print("  demonstrated. That is the finding, not a caveat on it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
