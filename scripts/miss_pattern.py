"""The two ways the reading was wrong, tested on the panel rather than the misses.

Window C produced 24 directional calls, 10 right and 11 wrong. The misses are
not randomly distributed. Splitting the judged-positive filings by what the
price had already done gives, on the 45 and again on the pooled 114:

    judged good, FELL   median 20-day momentum  +64%   (pooled +31%)
    judged good, ROSE   median 20-day momentum   -2%   (pooled -12%)

and splitting the judged-negative ones by how far the name had already fallen:

    judged bad, ROSE    median 86% below its 52-week high, 172% realised vol
    judged bad, FELL    median 72% below,                  124%

Both say the same thing: **the filing was judged in isolation, and the price had
already moved.** Good news bought after the move fails; bad news on equity that
is already priced as an option re-rates upward when it turns out not to be
fatal.

That is a story fitted to 114 outcomes, which is exactly the kind of thing this
repository keeps having to retract. So it is tested here on the gated panel --
roughly 160,000 rows over fifteen walk-forward blocks -- through the one proxy
that exists at that scale: a filing that actually moved volume is a filing the
market has already read.

Two questions
-------------
1. Inside the gate, does prior momentum predict the forward return **more** for
   names whose filing produced a volume surge than for names whose did not? If
   the "already in the price" story is right, extended names with a surge should
   be the worst cell in the table.
2. Does depth of drawdown predict the forward return for the most volatile
   names? If the "already an option" story is right, the most-crushed,
   most-volatile cell should be the best.

The answer to both is measured, not asserted -- and both stories come out
mostly wrong. See `docs/RESULT_MISS_PATTERN.md`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import company_context as cc  # noqa: E402
import loss_autopsy as la  # noqa: E402


def cell_table(S, rowcol, colcol, rowbins, colbins, rowlab, collab):
    """Mean forward return in each cell of a two-way conditional sort."""
    r = pd.qcut(S[rowcol], rowbins, labels=False, duplicates="drop")
    c = pd.qcut(S[colcol], colbins, labels=False, duplicates="drop")
    T = S.assign(_r=r, _c=c).dropna(subset=["_r", "_c"])
    piv = T.pivot_table(index="_r", columns="_c", values="net", aggfunc="mean") * 100
    cnt = T.pivot_table(index="_r", columns="_c", values="net", aggfunc="size")
    print(f"\n  rows = {rowlab} (low to high), cols = {collab} (low to high)")
    hdr = "".join(f"{f'C{int(c)+1}':>11s}" for c in piv.columns)
    print(f"  {'':10s}{hdr}{'spread':>11s}")
    for i in piv.index:
        vals = "".join(f"{piv.loc[i, c]:>+10.2f}%" for c in piv.columns)
        sp = piv.loc[i, piv.columns[-1]] - piv.loc[i, piv.columns[0]]
        print(f"  {f'R{int(i)+1}':10s}{vals}{sp:>+10.2f}pp")
    print(f"  {'n/cell':10s}" + "".join(f"{int(cnt[c].mean()):>11,d}" for c in piv.columns))
    lo = piv.loc[piv.index[-1], piv.columns[-1]]
    hi = piv.loc[piv.index[0], piv.columns[0]]
    print(f"  R5C5 {lo:+.2f}%   R1C1 {hi:+.2f}%   difference {lo - hi:+.2f}pp")
    return piv


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args()

    d, A, X = la.build_panel(args)
    S = d.copy()
    for i, c in enumerate(cc.PANEL_COLS):
        S[c] = X[:, i]
    S["net"] = S.ret - la.COST
    S = S.dropna(subset=["ctx_mom20", "ctx_volratio", "ctx_from_high", "ctx_vol20"])
    print(f"  usable rows: {len(S):,}")

    print("\n" + "=" * 92)
    print("1. DOES A VOLUME SURGE MEAN THE NEWS IS ALREADY IN THE PRICE?")
    print("=" * 92)
    print("  If it does, the worst cell is high prior momentum AND a big filing-day")
    print("  surge -- a name that already ran on news the market has already read.")
    cell_table(S, "ctx_mom20", "ctx_volratio", 5, 5,
               "20-day momentum", "filing-day volume vs its 20-day median")

    print("\n" + "=" * 92)
    print("2. IS DEEPLY DISTRESSED EQUITY AN OPTION?")
    print("=" * 92)
    print("  ctx_from_high is negative, so R1 is the MOST crushed and R5 is nearest")
    print("  the 52-week high. If the option story is right, R1C5 -- most crushed and")
    print("  most volatile -- is the best cell.")
    cell_table(S, "ctx_from_high", "ctx_vol20", 5, 5,
               "distance below 52-week high", "realised volatility")

    print("\n" + "=" * 92)
    print("3. THE TWO RULES THE MISSES SUGGEST, AS FILTERS")
    print("=" * 92)
    print("  Applied to the whole gate, not to a judgement, since there are no")
    print("  judgements at this scale. Each keeps or drops rows and reports what")
    print("  the kept set returns.\n")
    med_m = S.groupby("date")["ctx_mom20"].transform("median")
    med_v = S.groupby("date")["ctx_volratio"].transform("median")
    hi_dd = S.groupby("date")["ctx_from_high"].transform(lambda x: x.quantile(0.20))
    hi_vol = S.groupby("date")["ctx_vol20"].transform(lambda x: x.quantile(0.80))

    def line(tag, mask):
        s = S[mask]
        lg = np.log1p(np.clip(s.net.to_numpy(), -0.99, None))
        print(f"  {tag:48s}{len(s):>9,d}{s.net.mean() * 100:>+9.2f}%"
              f"{s.net.median() * 100:>+9.2f}%{np.exp(lg.mean()) * 100 - 100:>+11.2f}%")

    print(f"  {'subset':48s}{'rows':>9s}{'mean':>10s}{'median':>9s}{'compounds':>11s}")
    line("the whole gate", S.index == S.index)
    line("extended (mom20 above median)", S.ctx_mom20 > med_m)
    line("not extended", S.ctx_mom20 <= med_m)
    line("extended AND filing surged volume", (S.ctx_mom20 > med_m) & (S.ctx_volratio > med_v))
    line("not extended AND filing surged volume",
         (S.ctx_mom20 <= med_m) & (S.ctx_volratio > med_v))
    line("bottom quintile from high", S.ctx_from_high <= hi_dd)
    line("bottom quintile from high AND top vol quintile",
         (S.ctx_from_high <= hi_dd) & (S.ctx_vol20 >= hi_vol))
    return 0


if __name__ == "__main__":
    sys.exit(main())
