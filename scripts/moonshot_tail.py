"""Target the right tail directly, instead of the mean that keeps avoiding it.

Every model in this project so far has optimised a central tendency. The
classifiers asked `P(|move| >= 20%)`, which at an 8% base rate is common enough
to be a volatility question. The regressor asked for expected return. **Both
objectives actively push away from moonshots**, because a lottery ticket has a
mediocre mean and a fat right tail, and any estimator minimising squared error
will rank it below a steady name with the same expectation.

That is a defect of the objective, not evidence that the tail is unpredictable.
This tests the distinction properly.

Four families, all walk-forward on the same panel and splits:

**quantile regression** -- predict the 75th/90th/95th conditional percentile of
the forward return rather than its mean. `HistGradientBoostingRegressor` with a
pinball loss does this directly. Ranking by predicted q95 asks "which name has
the best *good case*", which is the actual question behind a moonshot.

**high-threshold classification** -- `P(max_up >= 35%)`, `>= 50%`, `>= 100%`.
The 20% threshold was never a moonshot; it was a volatility proxy. If the far
tail is a different phenomenon it should show different feature importances and
a different achievable AUC.

**mean regression** -- the current vol-scaled model, as the control.

**a ceiling test** -- fit the 50% classifier *in sample* and report its training
AUC. That is not a result, it is an upper bound: if a model cannot separate the
tail even when allowed to memorise, no honest model will, and the answer to "we
have all the data needed" is measurably no.

Scored on what a moonshot hunter actually cares about, which is not win rate:
the frequency of +50% and +100% outcomes among the picks, and the mean return
including those tails.
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

HORIZON = 10
COST = 20.0 / 1e4
BLOCK_MONTHS = 6
FIRST_TEST = "2019-01-01"
MIN_TRAIN = 40_000
MAX_TRAIN = 150_000


def forward(prices, rows, horizon=HORIZON):
    """Realised return, and the best/worst excursion, over the window."""
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    l = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()
    ret = np.full(len(rows), np.nan)
    mup = np.full(len(rows), np.nan)
    for a, i in enumerate(rows):
        r, _, _ = walk(o, h, l, c, v, tick, int(i) + 1, horizon,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            ret[a] = r
        j0 = int(i) + 1
        if j0 >= len(o) or tick[j0] != tick[i]:
            continue
        e = o[j0]
        if not (np.isfinite(e) and e > 0):
            continue
        best = -np.inf
        for step in range(horizon):
            j = j0 + step
            if j >= len(o) or tick[j] != tick[i]:
                break
            if np.isfinite(h[j]):
                best = max(best, h[j] / e - 1.0)
        if np.isfinite(best) and best <= 5.0:
            mup[a] = best
    return ret, mup


def blocks(hi):
    out, cur = [], pd.Timestamp(FIRST_TEST)
    hi = pd.Timestamp(hi)
    while cur < hi:
        nxt = cur + pd.DateOffset(months=BLOCK_MONTHS)
        out.append((cur, min(nxt, hi + pd.Timedelta(days=1))))
        cur = nxt
    return out


def scale_fit(Xtr):
    med = np.median(Xtr, axis=0)
    q1, q3 = np.percentile(Xtr, [25, 75], axis=0)
    sc = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
    return med, sc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--k", type=int, default=5)
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

    print("computing forward returns and excursions", flush=True)
    ret, mup = forward(prices, idx)
    vi = feats.index("vol_20d")
    vol = X[idx, vi]
    ok = np.isfinite(ret) & np.isfinite(mup) & np.isfinite(vol) & (vol > 0)
    tab = pd.DataFrame({"row": idx, "date": pd.to_datetime(d["date"].to_numpy()[idx]),
                        "vol": vol, "ret": ret, "mup": mup})[ok].reset_index(drop=True)
    Xs = X[tab.row.to_numpy()]
    print(f"  {len(tab):,} usable rows")

    print("\n" + "=" * 92)
    print("HOW RARE IS A MOONSHOT, AND IS IT EVEN A DIFFERENT ANIMAL?")
    print("=" * 92)
    for thr in (0.20, 0.35, 0.50, 1.00):
        n = int((tab.mup >= thr).sum())
        print(f"  P(max_up >= {thr:4.0%} in {HORIZON}d) = {n / len(tab) * 100:6.3f}%  "
              f"({n:,} events)   mean 10d return of those: "
              f"{tab.loc[tab.mup >= thr, 'ret'].mean() * 100:+6.2f}%")

    # ---------------- ceiling test ------------------------------------
    print("\n" + "=" * 92)
    print("CEILING TEST -- can ANY model separate the 50% tail, even in sample?")
    print("=" * 92)
    y50 = (tab.mup >= 0.50).astype(int).to_numpy()
    n_fit = min(120_000, len(tab))
    sel = np.linspace(0, len(tab) - 1, n_fit).astype(int)
    med, sc = scale_fit(Xs[sel])
    z = np.clip((Xs[sel] - med) / sc, -5, 5)
    deep = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.1,
                                          max_depth=None, max_leaf_nodes=63,
                                          min_samples_leaf=5, l2_regularization=0.0,
                                          random_state=0)
    deep.fit(z, y50[sel])
    in_auc = auc(y50[sel], deep.predict_proba(z)[:, 1])
    print(f"  in-sample AUC for P(max_up >= 50%), deliberately overfit: {in_auc:.4f}")
    print("  This is an upper bound, not a result. A model that cannot separate")
    print("  the tail while memorising will never separate it honestly.")

    # ---------------- walk-forward comparison -------------------------
    CONFIGS = [
        ("mean (vol-scaled)", "reg", None),
        ("quantile q75", "quant", 0.75),
        ("quantile q90", "quant", 0.90),
        ("quantile q95", "quant", 0.95),
        ("P(up >= 20%)", "clf", 0.20),
        ("P(up >= 35%)", "clf", 0.35),
        ("P(up >= 50%)", "clf", 0.50),
    ]
    rows = {name: [] for name, _, _ in CONFIGS}

    for b0, b1 in blocks(tab.date.max()):
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < MIN_TRAIN or len(te) < 500:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        med, sc = scale_fit(Xs[tr])
        ztr = np.clip((Xs[tr] - med) / sc, -5, 5)
        zte = np.clip((Xs[te] - med) / sc, -5, 5)
        sub = tab.iloc[te]
        uni = float(sub.ret.mean())

        for name, kind, param in CONFIGS:
            if kind == "reg":
                y = (tab.ret / np.maximum(tab.vol, 0.01)).to_numpy()
                m = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05,
                                                  max_depth=6, random_state=0)
                ytr = np.clip(y[tr], np.percentile(y[tr], 0.5),
                              np.percentile(y[tr], 99.5))
                m.fit(ztr, ytr)
                p = m.predict(zte)
            elif kind == "quant":
                y = tab.ret.to_numpy()
                m = HistGradientBoostingRegressor(
                    loss="quantile", quantile=param, max_iter=250,
                    learning_rate=0.05, max_depth=6, random_state=0)
                m.fit(ztr, y[tr])
                p = m.predict(zte)
            else:
                y = (tab.mup >= param).astype(int).to_numpy()
                if y[tr].sum() < 200:
                    continue
                m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05,
                                                   max_depth=6, random_state=0)
                m.fit(ztr, y[tr])
                p = m.predict_proba(zte)[:, 1]

            s = sub.assign(pred=p)
            s = s[s.groupby("date")["pred"].transform("size") >= args.k]
            picks = s.sort_values("pred", ascending=False).groupby("date").head(args.k)
            if picks.empty:
                continue
            rows[name].append({
                "block": f"{b0:%Y-%m}", "n": len(picks),
                "ret": float(picks.ret.mean()) - COST,
                "excess": float(picks.ret.mean()) - COST - uni,
                "p50": float((picks.mup >= 0.50).mean()),
                "p100": float((picks.mup >= 1.00).mean()),
                "p20": float((picks.mup >= 0.20).mean()),
                "best": float(picks.ret.max()),
                "win": float((picks.ret > 0).mean()),
            })
        print(f"  block {b0:%Y-%m} done", flush=True)

    print("\n" + "=" * 108)
    print(f"RANKING BY EACH OBJECTIVE -- daily top {args.k}, walk-forward, "
          f"net {COST * 1e4:.0f}bps")
    print("=" * 108)
    print(f"{'objective':22s} {'blocks':>7s} {'ret/trade%':>11s} {'excess%':>9s} "
          f"{'P(+20%)':>9s} {'P(+50%)':>9s} {'P(+100%)':>9s} {'best trade':>11s} "
          f"{'win%':>6s}")
    base = {"p20": (tab.mup >= 0.20).mean(), "p50": (tab.mup >= 0.50).mean(),
            "p100": (tab.mup >= 1.00).mean()}
    summary = []
    for name, _, _ in CONFIGS:
        r = pd.DataFrame(rows[name])
        if r.empty:
            continue
        summary.append({"objective": name, "ret": r.ret.mean(),
                        "excess": r.excess.mean(), "p50": r.p50.mean(),
                        "p100": r.p100.mean(), "blocks_won": int((r.excess > 0).sum()),
                        "n_blocks": len(r)})
        print(f"{name:22s} {int((r.excess > 0).sum()):>3d}/{len(r):<3d} "
              f"{r.ret.mean() * 100:+11.3f} {r.excess.mean() * 100:+9.3f} "
              f"{r.p20.mean() * 100:8.2f}% {r.p50.mean() * 100:8.2f}% "
              f"{r.p100.mean() * 100:8.2f}% {r.best.mean() * 100:+10.1f}% "
              f"{r.win.mean() * 100:5.1f}")
    print(f"{'universe base rate':22s} {'-':>7s} {'-':>11s} {'-':>9s} "
          f"{base['p20'] * 100:8.2f}% {base['p50'] * 100:8.2f}% "
          f"{base['p100'] * 100:8.2f}%")

    s = pd.DataFrame(summary)
    if not s.empty:
        best_tail = s.loc[s.p50.idxmax()]
        best_ret = s.loc[s.ret.idxmax()]
        print(f"\n  most +50% hits : {best_tail.objective!r} at "
              f"{best_tail.p50 * 100:.2f}% (base {base['p50'] * 100:.2f}%, "
              f"lift {best_tail.p50 / max(base['p50'], 1e-9):.2f}x)")
        print(f"  most return    : {best_ret.objective!r} at "
              f"{best_ret.ret * 100:+.3f}% per trade")
        s.to_csv(root / "moonshot_tail.csv", index=False)
    print("\nSurvivorship: no delistings, so tail frequencies on the upside are "
          "overstated\nrelative to a real universe.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
