"""Long-only, risk-adjusted, walk-forward. The build the diagnosis implies.

Runs `docs/PREREGISTRATION_LONGONLY.md`. Three changes from the previous model,
each aimed at a specific measured defect:

**Target divided by trailing volatility.** `P(|move| >= 20%)` is monotone in
volatility, so the old model ranked by `mean_exc_20d` and nothing else mattered.
Putting volatility in the denominator makes it impossible to win that way -- a
violent name has to earn its volatility back before it scores.

**Regression on realised return, not classification on a barrier touch.** The
label is now the thing the account receives. A name that touches +20% intraday
and closes flat scores zero here, as it should.

**Walk-forward.** Fourteen consecutive six-month out-of-sample blocks, retraining
before each. The top volatility decile returned +1.1% in 2015-2022 and -2.2% in
2024-2025; a single split cannot see that and a rule derived from one side of it
is fitted to a regime.

The benchmark is the equal-weight eligible universe, not zero. Long-only money
that does not beat buying everything has done nothing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import META, SEQ_LEN, build_arrays  # noqa: E402
from exit_rules import walk  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
VOL_FLOOR = 0.01
BLOCK_MONTHS = 6
FIRST_TEST = "2019-01-01"
MIN_TRAIN_ROWS = 40_000

#: Removed in the ablation arm, to test whether anything survives without them.
VOL_FEATURES = ["vol_5d", "vol_20d", "vol_60d", "mean_exc_20d",
                "max_exc_20d", "rvol"]


def realised(prices, rows, tp=None, sl=None):
    """Ten-day return from the t+1 open, optionally under a bracket."""
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    l = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()
    out = np.full(len(rows), np.nan)
    for a, i in enumerate(rows):
        r, _, _ = walk(o, h, l, c, v, tick, int(i) + 1, HORIZON,
                       tp, sl, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            out[a] = r
    return out


def blocks(dates: np.ndarray):
    lo = pd.Timestamp(FIRST_TEST)
    hi = pd.Timestamp(dates.max())
    out = []
    cur = lo
    while cur < hi:
        nxt = cur + pd.DateOffset(months=BLOCK_MONTHS)
        out.append((cur, min(nxt, hi + pd.Timedelta(days=1))))
        cur = nxt
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--max-train", type=int, default=200_000)
    ap.add_argument("--no-vol", action="store_true",
                    help="ablation: drop every volatility/excursion feature")
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import HistGradientBoostingRegressor

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    assert len(prices) == len(d), "panel/prices length mismatch"

    keep = list(range(len(feats)))
    if args.no_vol:
        keep = [i for i, f in enumerate(feats) if f not in VOL_FEATURES]
        print(f"ABLATION: dropped {len(feats) - len(keep)} volatility features")
    vi = feats.index("vol_20d")

    print("computing realised returns for every sampled row", flush=True)
    ret_raw = realised(prices, idx)
    ret_brk = realised(prices, idx, tp=0.20, sl=0.10)
    vol = X[idx, vi]
    dates = pd.to_datetime(d["date"].to_numpy()[idx])

    ok = np.isfinite(ret_raw) & np.isfinite(vol) & (vol > 0)
    print(f"  {ok.sum():,} of {len(idx):,} rows usable")

    tab = pd.DataFrame({
        "row": idx, "date": dates, "vol": vol,
        "ret": ret_raw, "ret_brk": ret_brk,
        "y_sharpe": ret_raw / np.maximum(vol, VOL_FLOOR),
    })[ok].reset_index(drop=True)
    Xs = X[tab.row.to_numpy()][:, keep]

    targets = {"vol-scaled": tab.y_sharpe.to_numpy(),
               "raw return": tab.ret.to_numpy(),
               "bracket return": tab.ret_brk.to_numpy()}

    bl = blocks(tab.date.to_numpy())
    print(f"\n{len(bl)} walk-forward blocks of {BLOCK_MONTHS} months, "
          f"first test {FIRST_TEST}\n")

    results = {name: [] for name in targets}
    bench_rows = []
    for b0, b1 in bl:
        # Embargo. A training row dated b0-1 carries a label that runs ten
        # sessions into the test block, so training on everything up to b0
        # leaks the first two weeks of the thing being predicted. Fourteen
        # calendar days covers a ten-session horizon including weekends.
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < MIN_TRAIN_ROWS or len(te) < 500:
            continue
        if len(tr) > args.max_train:
            tr = tr[np.linspace(0, len(tr) - 1, args.max_train).astype(int)]
        med = np.median(Xs[tr], axis=0)
        q1, q3 = np.percentile(Xs[tr], [25, 75], axis=0)
        sc = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
        ztr = np.clip((Xs[tr] - med) / sc, -5, 5)
        zte = np.clip((Xs[te] - med) / sc, -5, 5)

        sub = tab.iloc[te]
        uni = float(sub.ret.mean())
        bench_rows.append({"block": f"{b0:%Y-%m}", "n": len(te), "universe": uni})

        for name, y in targets.items():
            # Each target has its own missing rows -- the bracket return is NaN
            # wherever the barrier walk rejects a position -- so the training
            # mask is per-target rather than global. Masking globally would
            # silently shrink every target to the intersection.
            fin = np.isfinite(y[tr])
            if fin.sum() < MIN_TRAIN_ROWS // 2:
                continue
            ytr = y[tr][fin]
            m = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05,
                                              max_depth=6, random_state=0)
            m.fit(ztr[fin], np.clip(ytr, np.percentile(ytr, 0.5),
                                    np.percentile(ytr, 99.5)))
            p = m.predict(zte)
            s = sub.assign(pred=p)
            s = s[s.groupby("date")["pred"].transform("size") >= args.k]
            picks = s.sort_values("pred", ascending=False).groupby("date").head(args.k)
            results[name].append({
                "block": f"{b0:%Y-%m}", "n": len(picks),
                "ret": float(picks.ret.mean()) - COST,
                "universe": uni,
                "excess": float(picks.ret.mean()) - COST - uni,
                "win": float((picks.ret > 0).mean()),
                "med_vol": float(picks.vol.median()),
            })

    print("=" * 96)
    print(f"WALK-FORWARD, LONG ONLY, TOP {args.k} PER DAY, NET OF {COST * 1e4:.0f}BPS")
    print("=" * 96)
    bench = pd.DataFrame(bench_rows)
    for name in targets:
        r = pd.DataFrame(results[name])
        if r.empty:
            continue
        print(f"\n--- target: {name} ---")
        show = r.copy()
        for c in ("ret", "universe", "excess", "win"):
            show[c] = (show[c] * 100).round(2)
        show["med_vol"] = (show.med_vol * 100).round(2)
        print(show.to_string(index=False))
        beat = int((r.excess > 0).sum())
        print(f"  pooled mean return {r.ret.mean() * 100:+.3f}%   "
              f"universe {r.universe.mean() * 100:+.3f}%   "
              f"excess {r.excess.mean() * 100:+.3f}%")
        print(f"  beat the universe in {beat}/{len(r)} blocks")

    # ---- primary criterion on the vol-scaled target -----------------------
    name = "vol-scaled"
    r = pd.DataFrame(results[name])
    if not r.empty:
        print("\n" + "=" * 96)
        print("PRIMARY CRITERION  (vol-scaled target)")
        print("=" * 96)
        rng = np.random.default_rng(67)
        ex = r.excess.to_numpy()
        bs = np.array([rng.choice(ex, len(ex), replace=True).mean()
                       for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        beat = int((ex > 0).sum())
        print(f"  excess over universe {ex.mean() * 100:+.3f}% per 10 sessions")
        print(f"  block-bootstrap 95% CI [{lo * 100:+.3f}%, {hi * 100:+.3f}%]  "
              f"P(<=0) = {(bs <= 0).mean():.4f}")
        print(f"  PRIMARY     -> {'PASS' if lo > 0 else 'FAIL'}")
        print(f"  CONSISTENCY -> {'PASS' if beat >= 9 else 'FAIL'} "
              f"({beat}/{len(r)} blocks, needed 9)")
        rr = pd.DataFrame(results["raw return"])
        if not rr.empty:
            print(f"  TERTIARY    -> "
                  f"{'PASS' if r.excess.mean() > rr.excess.mean() else 'FAIL'} "
                  f"(vol-scaled {r.excess.mean() * 100:+.3f}% vs "
                  f"raw {rr.excess.mean() * 100:+.3f}%)")

    out = root / ("longonly_novol.csv" if args.no_vol else "longonly.csv")
    pd.concat([pd.DataFrame(v).assign(target=k) for k, v in results.items()]
              ).to_csv(out, index=False)
    print(f"\nwrote {out}")
    print("Survivorship: no delistings in this panel, so both the strategy and")
    print("the benchmark are inflated; the excess is the meaningful number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
