"""Why the same configuration prints +20% in one window and -7% in the next.

Four windows of fifteen sessions have now produced k=1 means of +1.90%, -7.37%,
+4.05% and -5.78%, and earlier arms in the same work printed +19.61% and
-11.30%. That spread invites a story about regimes or about something breaking
between runs. Before telling one, it is worth asking what spread pure noise
would produce, because if noise alone explains it there is nothing else to
explain.

Five candidate sources, measured rather than asserted
-----------------------------------------------------
1. **Sampling.** Fifteen trades drawn from a distribution whose per-trade
   standard deviation is 15-30%. The standard error of the mean is sd/sqrt(15),
   which is 4-8pp before anything else happens.
2. **Overlap.** A ten-session hold entered daily means consecutive trades share
   most of their holding period, so fifteen trades are worth far fewer than
   fifteen independent draws. This inflates (1) rather than adding to it.
3. **Skew.** One +67% name inside a fifteen-trade mean moves it by 4.5pp on its
   own. If the distribution's mean is carried by a thin right tail, whether the
   tail shows up in a given window is most of the answer.
4. **Conditions.** The four windows' universes returned +2.56%, -1.58%, +1.63%
   and +0.63% -- a 4pp range before any selection.
5. **Implementation.** Multi-threaded histogram binning is not bit-reproducible;
   an identical script earlier in this work printed +3.92% and then +4.62%.

The honest test is (1)-(3) together: draw many fifteen-session windows from the
same walk-forward predictions and look at how wide the answers are. If the four
observed numbers sit comfortably inside that spread, the fluctuation is the
sample size and nothing else.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import company_context as cc  # noqa: E402
import loss_autopsy as la  # noqa: E402
from llm_gate_pick import scale_fit  # noqa: E402

OBSERVED = {"A": 1.90, "B": -7.37, "C": 4.05, "D": -5.78}


def scores(A, X, ret, tr, te, seed=0, objective="log"):
    from sklearn.ensemble import HistGradientBoostingRegressor
    M = np.column_stack([A, X])
    Xtr = M[tr]
    y = np.log1p(np.clip(ret, -0.99, None)) if objective == "log" else ret
    ytr = y[tr]
    if len(Xtr) > 250_000:
        k = np.linspace(0, len(Xtr) - 1, 250_000).astype(int)
        Xtr, ytr = Xtr[k], ytr[k]
    med, sc = scale_fit(Xtr)
    kw = {} if objective == "log" else {"quantile": 0.75}
    loss = "squared_error" if objective == "log" else "quantile"
    mo = HistGradientBoostingRegressor(loss=loss, max_iter=250, learning_rate=0.05,
                                       max_depth=6, random_state=seed, **kw)
    mo.fit(np.clip((Xtr - med) / sc, -5, 5), ytr)
    return mo.predict(np.clip((M[te] - med) / sc, -5, 5))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    ap.add_argument("--window", type=int, default=15)
    args = ap.parse_args(argv)

    d, A, X = la.build_panel(args)
    ret = d["ret"].to_numpy()

    vi = list(cc.PANEL_COLS).index("ctx_vol20")
    parts = []
    for a_, tr, te in la.blocks(d["date"]):
        p = scores(A, X, ret, tr, te)
        s = d[te].copy()
        s["p"] = p
        s["vol"] = X[te][:, vi]
        s["net"] = s.ret - la.COST
        cut = s.groupby("date")["vol"].transform(lambda x: x.quantile(0.80))
        parts.append(s[s.vol <= cut])
    S = pd.concat(parts, ignore_index=True).sort_values(["date", "p"],
                                                        ascending=[True, False])
    S["rk"] = S.groupby("date").cumcount() + 1

    print("\n" + "=" * 92)
    print("1. THE PER-TRADE DISTRIBUTION THE WINDOWS ARE DRAWN FROM")
    print("=" * 92)
    for k in (1, 5):
        r = S[S.rk <= k].groupby("date").net.mean().to_numpy() if k > 1 \
            else S[S.rk == 1].net.to_numpy()
        se = r.std() / np.sqrt(args.window)
        print(f"  k={k}: {len(r):,} sessions   mean {r.mean() * 100:+.2f}%   "
              f"sd {r.std() * 100:.1f}%   skew {pd.Series(r).skew():+.2f}")
        print(f"        standard error of a {args.window}-session mean = "
              f"sd/sqrt({args.window}) = **{se * 100:.2f}pp**")
        print(f"        so a 95% interval around any single window is roughly "
              f"+/-{1.96 * se * 100:.1f}pp wide")

    print("\n" + "=" * 92)
    print(f"2. WHAT {args.window}-SESSION WINDOWS ACTUALLY LOOK LIKE, DRAWN FROM HISTORY")
    print("=" * 92)
    print("  Every consecutive window in the walk-forward period, same model, same rule.\n")
    for k in (1, 5):
        per = (S[S.rk == 1].set_index("date").net if k == 1
               else S[S.rk <= k].groupby("date").net.mean())
        per = per.sort_index()
        w = per.rolling(args.window).mean().dropna() * 100
        print(f"  k={k}: {len(w):,} overlapping windows")
        print(f"        mean of window means {w.mean():+.2f}%   sd {w.std():.2f}pp")
        for q in (1, 5, 25, 50, 75, 95, 99):
            print(f"        {q:>2d}th pct {np.percentile(w, q):>+8.2f}%", end="")
            if q in (25, 99):
                print()
        print(f"        P(window mean >= +10%) = {(w >= 10).mean():.3f}   "
              f"P(<= -10%) = {(w <= -10).mean():.3f}   "
              f"P(sign flip vs the true mean) = {(np.sign(w) != np.sign(w.mean())).mean():.3f}")
        obs = np.array(list(OBSERVED.values()))
        pct = [(w < o).mean() * 100 for o in obs]
        if k == 1:
            print("        the four observed windows sit at percentiles: "
                  + ", ".join(f"{n} {p:.0f}" for n, p in zip(OBSERVED, pct)))

    print("\n" + "=" * 92)
    print("3. HOW MUCH OF A WINDOW IS ONE TRADE")
    print("=" * 92)
    per = S[S.rk == 1].set_index("date").net.sort_index()
    w = per.rolling(args.window)
    means = w.mean().dropna()
    # drop the single largest absolute contributor from each window
    trimmed = per.rolling(args.window).apply(
        lambda x: np.delete(x, np.argmax(np.abs(x - x.mean()))).mean(), raw=True).dropna()
    print(f"  window mean, as computed:            sd {means.std() * 100:.2f}pp")
    print(f"  window mean, biggest outlier removed: sd {trimmed.std() * 100:.2f}pp")
    print(f"  -> one trade accounts for "
          f"{(1 - trimmed.std() / means.std()) * 100:.0f}% of the window-to-window spread")

    print("\n" + "=" * 92)
    print("4. HOW LONG UNTIL A 2pp EDGE IS DISTINGUISHABLE FROM ZERO")
    print("=" * 92)
    for k in (1, 5):
        r = (S[S.rk == 1].net.to_numpy() if k == 1
             else S[S.rk <= k].groupby("date").net.mean().to_numpy())
        for edge in (0.02, 0.01, 0.005):
            n = (1.96 * r.std() / edge) ** 2
            print(f"  k={k}, to resolve {edge * 100:.1f}pp at 95%: "
                  f"{n:,.0f} sessions ({n / 252:.1f} years of daily trading)")

    print("\n" + "=" * 92)
    print("5. IMPLEMENTATION NOISE: SAME DATA, DIFFERENT SEED")
    print("=" * 92)
    blk = list(la.blocks(d["date"]))[-2]
    a_, tr, te = blk
    outs = []
    for seed in range(5):
        p = scores(A, X, ret, tr, te, seed=seed)
        s = d[te].copy()
        s["p"] = p
        s["net"] = s.ret - la.COST
        k1 = s.sort_values("p", ascending=False).groupby("date").head(1)
        outs.append(k1.net.mean() * 100)
    print(f"  block {a_:%Y-%m}, five seeds, k=1 mean: "
          + "  ".join(f"{o:+.2f}%" for o in outs))
    print(f"  spread {max(outs) - min(outs):.2f}pp -- this is the model, not the market")
    return 0


if __name__ == "__main__":
    sys.exit(main())
