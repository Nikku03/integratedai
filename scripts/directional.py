"""Two directional models: does "up" actually mean up?

The magnitude model answers "will this move 20%". It is deliberately
direction-agnostic, so it cannot answer the question a trader actually has,
which is "if I buy this, does it go up". The direction head does not answer it
either: it was trained on ``max_up >= -max_dn``, meaning *which excursion was
larger*, which is not the same as *did the stock hit +20%*. A stock that runs
+8% and falls -6% scores as "up" under that label and pays nothing.

So this trains the two models that do map onto a trade:

```
y_up = 1 if max_up <= ... >= +20%   over the next ten sessions
y_dn = 1 if max_dn         <= -20%   over the next ten sessions
```

They are separate binary problems, not two classes of one problem, because a
stock can hit both (24.4% of top-1 magnitude picks did) or neither.

The criterion, fixed before running
-----------------------------------
A directional model is only real if it separates direction from volatility.
Both labels correlate with volatility, so a model trained on either will happily
select violent names and score well on AUC while being useless for a trade.

**The test is the asymmetry.** Among the UP model's top-k picks, ``P(up20)``
must exceed ``P(dn20)`` on those same names, and by more than the gap the
magnitude model already produces on its own picks. Symmetrically for DOWN.
If ``P(up20) ~ P(dn20)`` in both, the models have rediscovered volatility twice
and there is no directional signal.

Secondary: the realised ten-day return of the picks, which is what a position
actually earns. Excursion statistics flatter every strategy, because reaching
+20% intraday on day 3 is not the same as being able to sell there.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import (META, SEQ_LEN, auc, build_arrays, robust_scaler,  # noqa: E402
                         split_idx, weekly_boot_diff)

THRESH = 0.20
HORIZON = 10


def forward_close_return(prices: pd.DataFrame, rows: np.ndarray) -> np.ndarray:
    """Realised return from the t+1 open to the close of t+HORIZON.

    This is the number a position earns without a timing rule. The excursion
    columns say what was available; this says what holding delivers.
    """
    o = prices["open"].to_numpy(dtype=np.float64)
    c = prices["close"].to_numpy(dtype=np.float64)
    tick = prices["ticker"].to_numpy()
    out = np.full(len(rows), np.nan)
    for a, i in enumerate(rows):
        j0 = i + 1
        if j0 >= len(o) or tick[j0] != tick[i]:
            continue
        e = o[j0]
        j = min(j0 + HORIZON - 1, len(o) - 1)
        while j > j0 and tick[j] != tick[i]:
            j -= 1
        if np.isfinite(e) and e > 0 and np.isfinite(c[j]):
            out[a] = c[j] / e - 1.0
    return out


def topk(d: pd.DataFrame, score: str, k: int) -> pd.DataFrame:
    big = d.groupby("date")["y_up"].transform("size") >= k
    return d[big].sort_values(score, ascending=False).groupby("date").head(k)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--max-train", type=int, default=250_000)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import pyarrow.parquet as pq
    from sklearn.ensemble import HistGradientBoostingClassifier

    print("loading panel", flush=True)
    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    lab = pq.read_table(root / "adrnn_panel.parquet",
                        columns=["max_up", "max_dn"]).to_pandas()
    mu = lab["max_up"].to_numpy(dtype=np.float64)
    md = lab["max_dn"].to_numpy(dtype=np.float64)
    y_up = (mu >= THRESH).astype(np.float32)
    y_dn = (md <= -THRESH).astype(np.float32)
    y_mag = d["y_mag"].to_numpy(dtype=np.float32)

    tr, va, te = split_idx(d, idx)
    if len(tr) > args.max_train:
        tr = tr[np.linspace(0, len(tr) - 1, args.max_train).astype(int)]
    med, scale = robust_scaler(X, tr)
    print(f"  train {len(tr):,}  test {len(te):,}   "
          f"test base rates: up {y_up[te].mean() * 100:.2f}%  "
          f"dn {y_dn[te].mean() * 100:.2f}%  any {y_mag[te].mean() * 100:.2f}%")

    def flat(rows):
        return (X[rows] - med) / scale

    scores = {}
    for name, y in (("up", y_up), ("dn", y_dn), ("mag", y_mag)):
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                           max_depth=6, random_state=0)
        m.fit(flat(tr), y[tr])
        scores[name] = m.predict_proba(flat(te))[:, 1]
        print(f"  model {name:3s}  test AUC {auc(y[te], scores[name]):.4f}")

    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "close"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    print("\ncomputing realised 10-day returns", flush=True)
    ret = forward_close_return(prices, te)

    t = pd.DataFrame({
        "date": pd.to_datetime(d["date"].to_numpy()[te]),
        "ticker": d["ticker"].to_numpy()[te],
        "y_up": y_up[te], "y_dn": y_dn[te], "y_mag": y_mag[te],
        "max_up": mu[te], "max_dn": md[te], "ret10": ret,
        "s_up": scores["up"], "s_dn": scores["dn"], "s_mag": scores["mag"]})
    t = t[t.ret10.notna()].copy()
    print(f"{len(t):,} test rows with a realised return, "
          f"{t.date.nunique()} sessions")

    print("\n" + "=" * 92)
    print("DOES 'UP' MEAN UP?  daily top-k of each model, scored on both outcomes")
    print("=" * 92)
    print(f"{'model':>6s} {'k':>4s} {'n':>6s} {'P(up20)':>8s} {'P(dn20)':>8s} "
          f"{'edge':>7s} {'meanRet':>8s} {'medRet':>7s} {'win%':>6s}")
    rows = []
    for score, lab_ in (("s_up", "UP"), ("s_dn", "DOWN"), ("s_mag", "MAG")):
        for k in (1, 3, 5, 10, 20):
            s = topk(t, score, k)
            pu, pdn = float(s.y_up.mean()), float(s.y_dn.mean())
            rows.append({"model": lab_, "k": k, "n": len(s), "p_up": pu,
                         "p_dn": pdn, "edge": pu - pdn,
                         "mean_ret": float(s.ret10.mean()),
                         "med_ret": float(s.ret10.median()),
                         "win": float((s.ret10 > 0).mean())})
            print(f"{lab_:>6s} {k:>4d} {len(s):>6,} {pu * 100:7.1f}% "
                  f"{pdn * 100:7.1f}% {(pu - pdn) * 100:+6.1f} "
                  f"{s.ret10.mean() * 100:+7.2f}% {s.ret10.median() * 100:+6.2f}% "
                  f"{(s.ret10 > 0).mean() * 100:5.1f}%")
    base = t
    print(f"{'ALL':>6s} {'-':>4s} {len(base):>6,} {base.y_up.mean() * 100:7.1f}% "
          f"{base.y_dn.mean() * 100:7.1f}% "
          f"{(base.y_up.mean() - base.y_dn.mean()) * 100:+6.1f} "
          f"{base.ret10.mean() * 100:+7.2f}% {base.ret10.median() * 100:+6.2f}% "
          f"{(base.ret10 > 0).mean() * 100:5.1f}%")

    print("\n  edge = P(up20) - P(dn20) on the SAME names. This is the whole test:")
    print("  a model that only found volatility scores ~0 here in both rows.")

    # --- the decisive comparison ------------------------------------------
    print("\n" + "=" * 92)
    print("THE ASYMMETRY TEST")
    print("=" * 92)
    r = pd.DataFrame(rows)
    for k in (1, 3, 5, 10, 20):
        u = r[(r.model == "UP") & (r.k == k)].iloc[0]
        dn = r[(r.model == "DOWN") & (r.k == k)].iloc[0]
        m = r[(r.model == "MAG") & (r.k == k)].iloc[0]
        spread = u.edge - dn.edge
        print(f"  k={k:<3d} UP edge {u.edge * 100:+6.1f}pp | "
              f"DOWN edge {dn.edge * 100:+6.1f}pp | "
              f"MAG edge {m.edge * 100:+6.1f}pp | "
              f"UP-minus-DOWN separation {spread * 100:+6.1f}pp")
    print("\n  If the UP and DOWN models were really directional, the UP row would")
    print("  be strongly positive and the DOWN row strongly negative. The MAG row")
    print("  is the control: whatever tilt exists in the universe anyway.")

    # --- long/short at k=5, the practical version -------------------------
    print("\n" + "=" * 92)
    print("WHAT A POSITION EARNS  (t+1 open to t+10 close, no exit rule, no costs)")
    print("=" * 92)
    for k in (1, 3, 5, 10):
        lu = topk(t, "s_up", k)
        ld = topk(t, "s_dn", k)
        print(f"  k={k:<3d} long the UP picks   {lu.ret10.mean() * 100:+6.2f}%  "
              f"(median {lu.ret10.median() * 100:+6.2f}%, win {(lu.ret10 > 0).mean() * 100:4.1f}%)")
        print(f"       short the DOWN picks {-ld.ret10.mean() * 100:+6.2f}%  "
              f"(median {-ld.ret10.median() * 100:+6.2f}%, win {(ld.ret10 < 0).mean() * 100:4.1f}%)")

    # significance on the k=5 UP edge, week-clustered
    s5 = topk(t, "s_up", 5)
    wk = s5.date.dt.to_period("W").astype(str).to_numpy()
    rng = np.random.default_rng(23)
    uw = np.unique(wk)
    where = {w: np.flatnonzero(wk == w) for w in uw}
    diffs = []
    yu, yd = s5.y_up.to_numpy(), s5.y_dn.to_numpy()
    for _ in range(20000):
        pick = rng.choice(uw, len(uw), replace=True)
        sel = np.concatenate([where[w] for w in pick])
        diffs.append(yu[sel].mean() - yd[sel].mean())
    a = np.array(diffs)
    lo, hi = np.percentile(a, [2.5, 97.5])
    print(f"\n  UP model, k=5: edge {(yu.mean() - yd.mean()) * 100:+.2f}pp   "
          f"week-clustered 95% CI [{lo * 100:+.2f}, {hi * 100:+.2f}]   "
          f"P(<=0) = {(a <= 0).mean():.4f}")
    print(f"  -> {'PASS' if lo > 0 else 'FAIL'} the pre-stated criterion")

    t.to_parquet(root / "directional_test.parquet")
    print("\nSurvivorship: the panel has no delistings, so P(dn20) is understated")
    print("and every long-side number here is flattered. See RESULT_TOPK_AND_DELISTING.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
