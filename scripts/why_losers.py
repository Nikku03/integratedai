"""Why does the model pick trades that lose?

Two-thirds of the picks lose an average of 9.21%. That could mean three very
different things, and they call for different responses:

**We pick badly.** A winner was sitting in that day's candidate list and the
model took something else. Then there is skill left on the table and the model
should be improved.

**The pool was bad.** Nothing in that day's list was going to work and the model
took the best of nothing. Then the fix is to *not trade* on those days, and the
question becomes whether bad days are identifiable in advance.

**Winners and losers are indistinguishable beforehand.** The same features
precede a +50% and a −20%. Then the losses are structural, no screen removes
them, and the only lever is size.

Four measurements separate these.

1. **Separability.** Train a classifier on the picks alone to predict win versus
   loss. If it cannot beat 0.5 out of sample, the two populations are the same
   population.
2. **Selection percentile.** Where did our pick land among all of that day's
   candidates, ranked by what actually happened? 50% means the model chose at
   random from its own shortlist; higher means real selection.
3. **Oracle gap.** What did the best available name that day return, against what
   we took? This bounds how much is recoverable by picking better.
4. **Bad-day detectability.** On days the pick lost, was the *whole* candidate
   list bad, and was that visible in the predicted scores at the time?
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, build_arrays  # noqa: E402
from exit_rules import walk  # noqa: E402
from moonshot_tail import blocks, scale_fit  # noqa: E402

COST = 20.0 / 1e4
HORIZON = 10


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--quantile", type=float, default=0.75)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  HistGradientBoostingRegressor)

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    l = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()

    print("computing outcomes for every candidate", flush=True)
    ret = np.full(len(idx), np.nan)
    for a, i in enumerate(idx):
        r, _, _ = walk(o, h, l, c, v, tick, int(i) + 1, HORIZON,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            ret[a] = r
    ok = np.isfinite(ret)
    tab = pd.DataFrame({"row": idx, "date": pd.to_datetime(d["date"].to_numpy()[idx]),
                        "ticker": d["ticker"].to_numpy()[idx],
                        "ret": ret})[ok].reset_index(drop=True)
    Xs = X[tab.row.to_numpy()]
    print(f"  {len(tab):,} candidates over {tab.date.nunique():,} sessions "
          f"({len(tab) / tab.date.nunique():.0f} per session)\n")

    # ---- score every candidate, walk-forward -------------------------
    preds = np.full(len(tab), np.nan)
    for b0, b1 in blocks(tab.date.max()):
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < 40_000 or len(te) < 500:
            continue
        if len(tr) > 150_000:
            tr = tr[np.linspace(0, len(tr) - 1, 150_000).astype(int)]
        med, sc = scale_fit(Xs[tr])
        m = HistGradientBoostingRegressor(loss="quantile", quantile=args.quantile,
                                          max_iter=250, learning_rate=0.05,
                                          max_depth=6, random_state=0)
        m.fit(np.clip((Xs[tr] - med) / sc, -5, 5), tab.ret.to_numpy()[tr])
        preds[te] = m.predict(np.clip((Xs[te] - med) / sc, -5, 5))
    tab["pred"] = preds
    ev = tab[tab.pred.notna()].copy()
    ev["net"] = ev.ret - COST
    picks = ev.sort_values("pred", ascending=False).groupby("date").head(1).copy()
    print(f"scored {len(ev):,} candidates; {len(picks):,} picks "
          f"(one per session)\n")

    # ---- 1. separability ---------------------------------------------
    print("=" * 92)
    print("1. CAN WINNERS AND LOSERS AMONG THE PICKS BE TOLD APART BEFOREHAND?")
    print("=" * 92)
    pk = picks.sort_values("date").reset_index(drop=True)
    Xp = X[pk.row.to_numpy()]
    y = (pk.net > 0).astype(int).to_numpy()
    cut = int(len(pk) * 0.6)
    med, sc = scale_fit(Xp[:cut])
    clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                         max_depth=4, random_state=0)
    clf.fit(np.clip((Xp[:cut] - med) / sc, -5, 5), y[:cut])
    a_out = auc(y[cut:], clf.predict_proba(np.clip((Xp[cut:] - med) / sc, -5, 5))[:, 1])
    a_in = auc(y[:cut], clf.predict_proba(np.clip((Xp[:cut] - med) / sc, -5, 5))[:, 1])
    print(f"  train on the first {cut} picks, test on the last {len(pk) - cut}")
    print(f"  in-sample AUC  {a_in:.4f}")
    print(f"  OUT-OF-SAMPLE AUC {a_out:.4f}   "
          f"({'informative' if a_out > 0.55 else 'NO BETTER THAN A COIN'})")

    # ---- 2. where did the pick land among that day's candidates -------
    print("\n" + "=" * 92)
    print("2. WHERE DOES OUR PICK LAND AMONG THAT DAY'S CANDIDATES?")
    print("=" * 92)
    ev["out_pct"] = ev.groupby("date")["ret"].rank(pct=True)
    pk_pct = ev.sort_values("pred", ascending=False).groupby("date").head(1)
    print(f"  outcome percentile of our pick within its own day:")
    print(f"    mean {pk_pct.out_pct.mean() * 100:.1f}%   "
          f"median {pk_pct.out_pct.median() * 100:.1f}%   "
          f"(50% = choosing at random from the day's list)")
    print(f"    picked the single best name that day: "
          f"{(pk_pct.out_pct >= 0.999).mean() * 100:.1f}% of sessions")
    print(f"    landed in the bottom quartile of the day: "
          f"{(pk_pct.out_pct <= 0.25).mean() * 100:.1f}% of sessions")

    # ---- 3. oracle gap -------------------------------------------------
    print("\n" + "=" * 92)
    print("3. WHAT WAS AVAILABLE THAT DAY VERSUS WHAT WE TOOK")
    print("=" * 92)
    day = ev.groupby("date").agg(best=("ret", "max"), worst=("ret", "min"),
                                 med=("ret", "median"), n=("ret", "size"))
    day["ours"] = pk_pct.set_index("date")["ret"]
    day = day.dropna()
    print(f"  per session, across {len(day):,} sessions:")
    print(f"    best available   mean {day.best.mean() * 100:+7.2f}%   "
          f"median {day.best.median() * 100:+7.2f}%")
    print(f"    our pick         mean {day.ours.mean() * 100:+7.2f}%   "
          f"median {day.ours.median() * 100:+7.2f}%")
    print(f"    day's median     mean {day.med.mean() * 100:+7.2f}%   "
          f"median {day.med.median() * 100:+7.2f}%")
    print(f"    worst available  mean {day.worst.mean() * 100:+7.2f}%")
    lose = day[day.ours < 0]
    print(f"\n  on the {len(lose):,} sessions our pick lost "
          f"({len(lose) / len(day) * 100:.0f}% of them):")
    print(f"    best name available that day averaged "
          f"{lose.best.mean() * 100:+.2f}% (median {lose.best.median() * 100:+.2f}%)")
    print(f"    the day's median name returned "
          f"{lose.med.mean() * 100:+.2f}%")
    print(f"    sessions where NOTHING was positive: "
          f"{(lose.best <= 0).mean() * 100:.1f}%")

    # ---- 4. were bad days visible in advance --------------------------
    print("\n" + "=" * 92)
    print("4. WERE THE BAD DAYS VISIBLE IN THE SCORES AT THE TIME?")
    print("=" * 92)
    pk2 = pk_pct.copy()
    pk2["q"] = pd.qcut(pk2["pred"].rank(method="first"), 5, labels=False)
    g = pk2.groupby("q").agg(n=("ret", "size"),
                             mean=("ret", lambda s: s.mean() * 100),
                             median=("ret", lambda s: s.median() * 100),
                             win=("ret", lambda s: (s > 0).mean() * 100))
    print("  picks bucketed by the model's own predicted score (1 = lowest):")
    print(g.round(2).to_string())
    rho = pk2[["pred", "ret"]].corr(method="spearman").iloc[0, 1]
    print(f"\n  rank correlation between predicted score and realised return: "
          f"{rho:+.4f}")
    print("  If this is near zero, the absolute score carries no information about")
    print("  how good the day is -- only the within-day ranking does.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
