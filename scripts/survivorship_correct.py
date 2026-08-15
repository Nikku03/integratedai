"""What the strategy is worth once the dead companies are put back.

The panel cannot be literally rebuilt with delisted names. Yahoo returns 404 for
every dead ticker tested — SIVBQ, BBBYQ, HTZGQ, PRTYQ, RADCQ, ZGNX, OTIC, KDMN,
CHMA, AMRS — and also for acquired ones (ATVI, TWTR, XLNX, CERN, NUAN). Worse,
two of the twenty-two came back with data that is not the original company's:
SBNY returns 345 bars starting August 2024, seventeen months after Signature
Bank failed, because the ticker was reissued. Missing data announces itself;
recycled data does not, which makes the vendor unusable for this even where it
answers. Stooq is unreachable from this network. `src/iai/sources/prices.py`
already documents the fix — a paid extract with delisted history — and there is
no free substitute.

What *can* be recovered from primary sources is the **rate**, and the rate is
what settles the question. `RESULT_AGREED_STRATEGY.md` computed the breakeven:
the book dies once about **1.1% of trades** are undisclosed total losses. So the
whole survivorship argument reduces to one comparison — is the real probability
that a ten-session position sits in a company about to be struck from its
exchange above or below 1.1%?

Three quantities, each measured rather than assumed
---------------------------------------------------
1. **How many common stocks are involuntarily delisted per year.** From
   `delist_census.py`, which reads the security class and rule provision out of
   the Form 25-NSE filings themselves rather than trusting the submissions API.
2. **How over-exposed the strategy is to that population.** The picks are not a
   random draw: their median price is $6.39 against $30.59 for the pool, and
   they sit in sub-$5 names 6.1x as often and sub-$2 names 10.3x as often. That
   ratio is the multiplier, and it is measured from the actual trade list.
3. **What a delisting costs.** Not always −100%: a struck stock usually keeps
   trading over the counter at a fraction of its last price. Reported across a
   range rather than picked.

The denominator used to be the weak link. It is now measured: Tiingo publishes a
keyless file giving the first and last date price data exists for every symbol,
so the number of US-listed common stocks on any date can be counted rather than
assumed. It averages 6,644 across 2015-2025 — higher than the 4,000-5,500 that
was previously borrowed from published listing counts, which means every earlier
hazard figure in this repo was overstated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: The denominator, no longer assumed. `iai.sources.universe` reads Tiingo's
#: keyless supported-ticker file, which carries a first and last price date for
#: every symbol, and counting the symbols live on each month-end gives 5,541
#: US-listed common stocks in January 2015 rising to 7,615 in December 2025,
#: mean 6,644. That is measured, and it is well above the 4,000-5,500 band this
#: script previously borrowed from published listing counts -- which means the
#: earlier hazard estimates were too high, not too low. The low end is kept as a
#: deliberately conservative floor so the sensitivity still brackets the old
#: assumption.
#:
#: Run `python3 scripts/api_check.py` to re-measure.
UNIVERSE = (4000, 6644)

#: Realised loss on an involuntary delisting. A struck stock is not
#: automatically worthless -- it moves to the over-the-counter market, usually
#: after a large fall. -1.0 is the bankruptcy case and the others bracket it.
LOSSES = (0.60, 0.80, 1.00)

HOLD = 10
YEAR = 252.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--per-trade", type=float, default=1.115,
                    help="measured mean return per trade, in percent (k=5 book)")
    ap.add_argument("--trades", type=int, default=8795)
    ap.add_argument("--total", type=float, default=292.7,
                    help="measured total return of the same book, in percent")
    ap.add_argument("--years", type=float, default=7.0)
    args = ap.parse_args(argv)
    root = Path(args.root)

    c = pd.read_parquet(root / "delist_census.parquet")
    c["filed"] = pd.to_datetime(c["filed"])
    c["year"] = c.filed.dt.year

    print("=" * 100)
    print("1. COVERAGE -- can the census be trusted year by year?")
    print("=" * 100)
    cov = c.groupby(["year", "form"]).agg(
        filings=("acc", "size"),
        parsed=("security", lambda s: int((s.str.len() > 0).sum()))).reset_index()
    piv = cov.pivot(index="year", columns="form", values="parsed").fillna(0).astype(int)
    tot = cov.pivot(index="year", columns="form", values="filings").fillna(0).astype(int)
    rate = (piv / tot.replace(0, np.nan) * 100).round(1)
    print("  filings with a readable security class, % by form and year:")
    print(rate.to_string())
    print("\n  Form 25 is filed by issuers and older ones are HTML rather than")
    print("  XML, so its class is often unreadable. Form 25-NSE is filed by the")
    print("  exchange and is XML throughout -- and 25-NSE is where involuntary")
    print("  removals live, so the count below does not depend on Form 25.")

    nse = c[(c.form == "25-NSE") & (c.security.str.len() > 0)]
    inv = nse[nse.is_common & nse.involuntary]

    print("\n" + "=" * 100)
    print("2. THE RATE -- involuntary common-stock delistings")
    print("=" * 100)
    g = (nse.assign(common=nse.is_common)
            .groupby("year").agg(nse_filings=("acc", "size"),
                                 common=("common", "sum"),
                                 involuntary=("involuntary",
                                              lambda s: 0)).reset_index())
    peryr = inv.groupby("year").size().reindex(g.year, fill_value=0).to_numpy()
    g["involuntary_common"] = peryr
    g = g.drop(columns="involuntary").set_index("year")
    print(g.to_string())
    full = g.loc[[y for y in g.index if 2015 <= y <= 2025]]
    d_tot = int(full.involuntary_common.sum())
    n_yrs = len(full)
    per_year = d_tot / n_yrs
    print(f"\n  {d_tot:,} involuntary common-stock delistings over {n_yrs} years "
          f"= {per_year:.0f} a year")

    print("\n" + "=" * 100)
    print("3. THE HAZARD a ten-session position faces")
    print("=" * 100)
    print(f"  picks sit in sub-$5 names 6.07x as often as the pool, sub-$2 10.35x")
    print(f"  (measured from the trade list, median pick $6.39 vs pool $30.59)\n")
    print(f"  {'universe':>10s} {'lambda/yr':>10s} " +
          "".join(f"{'m=' + str(m):>12s}" for m in (1, 3, 6, 10)))
    haz = {}
    for uni in UNIVERSE:
        lam = per_year / uni
        cells = []
        for m in (1, 3, 6, 10):
            h = lam * m * HOLD / YEAR
            haz[(uni, m)] = h
            cells.append(f"{h * 100:11.3f}%")
        print(f"  {uni:>10,} {lam * 100:>9.2f}% " + "".join(cells))
    print("\n  cells are P(a given 10-session position is in a name that gets")
    print("  struck). The k=5 book breaks even at 1.10%.")

    print("\n" + "=" * 100)
    print("4. THE CORRECTED BOOK")
    print("=" * 100)
    mu = args.per_trade / 100.0
    print(f"  measured mean per trade {mu * 100:+.3f}%  over {args.trades:,} trades, "
          f"{args.years:.1f} years")
    print(f"\n  {'universe':>9s} {'m':>3s} {'hazard':>8s} " +
          "".join(f"{'loss ' + str(int(l * 100)) + '%':>13s}" for l in LOSSES))
    for uni in UNIVERSE:
        for m in (1, 3, 6, 10):
            h = haz[(uni, m)]
            cells = []
            for L in LOSSES:
                adj = (1 - h) * mu + h * (-L)
                cells.append(f"{adj * 100:+12.3f}%")
            print(f"  {uni:>9,} {m:>3d} {h * 100:>7.3f}% " + "".join(cells))
    print("\n  each cell is the corrected mean per trade. Negative means the book")
    print("  does not survive that combination.")

    print("\n" + "=" * 100)
    print("5. TOTAL RETURN, CORRECTED")
    print("=" * 100)
    # Anchored to the measured book rather than rebuilt from scratch. Modelling
    # the compounding independently gave +610.7% where the actual overlapping-
    # position book returned +292.7%, because it ignores cash drag and the
    # overlap; a standalone number that disagrees with the measurement by a
    # factor of two is not worth printing. Scaling the measured growth by the
    # ratio of corrected to measured per-trade mean keeps the anchor and is
    # first-order right, which is all this needs to be.
    G = 1.0 + args.total / 100.0
    print(f"  measured total {args.total:+.1f}%, scaled by the ratio of corrected "
          f"to measured per-trade mean")
    print(f"\n  {'universe':>9s} {'m':>3s} " +
          "".join(f"{'loss ' + str(int(l * 100)) + '%':>15s}" for l in LOSSES))
    for uni in UNIVERSE:
        for m in (3, 6, 10):
            h = haz[(uni, m)]
            cells = []
            for L in LOSSES:
                adj = (1 - h) * mu + h * (-L)
                cells.append(f"{(G ** (adj / mu) - 1) * 100:+14.1f}%")
            print(f"  {uni:>9,} {m:>3d} " + "".join(cells))

    print("\n" + "=" * 100)
    print("6. WHERE IT BREAKS")
    print("=" * 100)
    for L in LOSSES:
        hstar = mu / (mu + L)
        lam_star = hstar * YEAR / HOLD
        print(f"  at a {int(L * 100)}% loss on delisting, the book breaks even at "
              f"hazard {hstar * 100:.3f}% per trade")
        for uni in UNIVERSE:
            m_star = lam_star / (per_year / uni)
            print(f"      universe {uni:,}: needs the picks to be "
                  f"{m_star:.1f}x the average delisting rate  "
                  f"({'SURVIVES' if m_star > 6.07 else 'FAILS'} at the measured 6.07x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
