"""Does an exit rule convert the +20% touch into realised money?

The directional tilt replicated out of sample; the profit did not. The gap is
that these tests held to the tenth close with no exit rule, so a stock that
touched +20% on day 3 and gave it all back counted as a loss. This asks whether
a rule that actually sells into the touch closes that gap.

Two structural decisions, both of which cost the strategy money and are made
deliberately.

**Same-day ambiguity resolves against the position.** Daily OHLC cannot say
whether the high or the low came first. If a bar touches both the target and the
stop, this assumes the **stop** filled -- unless the bar *opened* through one of
them, in which case that one is known to be first. Assuming the favourable
ordering is the single most common way a barrier backtest invents returns that
do not exist.

**Phantom bars cannot fill.** This panel contains bars with a wide range and
zero volume; earlier in this project one of them turned a +170% ceiling into a
+2.6% result by stopping a winner at a price nobody traded. A barrier is only
honoured on a bar with positive volume.

Protocol against the post-hoc problem
-------------------------------------
The volatility band was found on the test period, which makes it suspect. The
first thing this script does is check whether the same decile inversion is
present in the **training** period, where it could have been found without
touching anything reserved. If it is, the band is legitimate and the only
question left is the exit.

The exit rule is then selected on **validation** and reported once on **test**.
That ordering matters: choosing the exit on test and reporting it there is how
every dead strategy in this repository was born.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import build_arrays, robust_scaler, split_idx  # noqa: E402

HORIZON = 10
COST_BPS = 20.0  # round-trip, in basis points

#: Pre-registered grid. Fixed before any exit result was seen.
#: (take_profit, stop_loss, arm, trail, time_stop) -- None means "not used".
GRID = [
    ("hold to close", None, None, None, None, None),
    ("TP +10%", 0.10, None, None, None, None),
    ("TP +15%", 0.15, None, None, None, None),
    ("TP +20%", 0.20, None, None, None, None),
    ("TP +30%", 0.30, None, None, None, None),
    ("TP +20% / SL -10%", 0.20, 0.10, None, None, None),
    ("TP +20% / SL -15%", 0.20, 0.15, None, None, None),
    ("TP +15% / SL -10%", 0.15, 0.10, None, None, None),
    ("TP +30% / SL -15%", 0.30, 0.15, None, None, None),
    ("SL -10% only", None, 0.10, None, None, None),
    ("SL -15% only", None, 0.15, None, None, None),
    ("trail: arm +8%, trail 8%", None, 0.15, 0.08, 0.08, None),
    ("trail: arm +10%, trail 10%", None, 0.15, 0.10, 0.10, None),
    ("trail: arm +15%, trail 10%", None, 0.15, 0.15, 0.10, None),
    ("time stop day 3", None, None, None, None, 3),
    ("time stop day 5", None, None, None, None, 5),
    ("TP +20% / SL -10% / day 5", 0.20, 0.10, None, None, 5),
]


def walk(o, h, l, c, v, tick, i0: int, n: int, tp, sl, arm, trail, tstop):
    """Simulate one position from the open of ``i0`` over ``n`` bars.

    ``tick`` is required, not optional. The panel is one contiguous block sorted
    by (ticker, date), so a window that runs off the end of one ticker walks
    straight into the next one's prices -- a $2 name followed by a $500 name
    reads as a 250x return. That produced a mean of +293% with a median of
    -4.56% before it was caught.

    Returns (gross_return, exit_reason, bars_held).
    """
    if i0 >= len(o):
        return np.nan, "no entry", 0
    entry = o[i0]
    if not (np.isfinite(entry) and entry > 0):
        return np.nan, "no entry", 0
    who = tick[i0]
    hw = entry
    armed = arm is None
    for step in range(n):
        j = i0 + step
        if j >= len(o) or tick[j] != who:
            break
        if not np.isfinite(c[j]):
            break
        tradeable = v[j] > 0
        oj, hj, lj = o[j], h[j], l[j]

        stop_px = entry * (1 - sl) if sl is not None else None
        targ_px = entry * (1 + tp) if tp is not None else None
        if armed and trail is not None:
            t_px = hw * (1 - trail)
            stop_px = max(stop_px, t_px) if stop_px is not None else t_px

        if tradeable:
            # A gap through a barrier at the open settles the ordering.
            if stop_px is not None and np.isfinite(oj) and oj <= stop_px:
                return oj / entry - 1.0, "stop@open", step + 1
            if targ_px is not None and np.isfinite(oj) and oj >= targ_px:
                return oj / entry - 1.0, "target@open", step + 1

            hit_stop = stop_px is not None and np.isfinite(lj) and lj <= stop_px
            hit_targ = targ_px is not None and np.isfinite(hj) and hj >= targ_px
            # Both touched intrabar: assume the stop came first.
            if hit_stop:
                return stop_px / entry - 1.0, "stop", step + 1
            if hit_targ:
                return targ_px / entry - 1.0, "target", step + 1

            if arm is not None and not armed and np.isfinite(hj) \
                    and hj >= entry * (1 + arm):
                armed = True
                hw = max(hw, hj)
            elif armed and np.isfinite(hj):
                hw = max(hw, hj)

        if tstop is not None and (step + 1) >= tstop:
            return c[j] / entry - 1.0, "time", step + 1

    # Ran out of window: mark out at the last bar that actually traded.
    j = min(i0 + n - 1, len(o) - 1)
    while j > i0 and tick[j] != who:
        j -= 1
    while j > i0 and not (np.isfinite(c[j]) and v[j] > 0):
        j -= 1
    return (c[j] / entry - 1.0, "close", n) if np.isfinite(c[j]) else (np.nan, "none", n)


def run_grid(picks: pd.DataFrame, arrays, cost_bps: float) -> pd.DataFrame:
    o, h, l, c, v, tick = arrays
    rows = []
    for name, tp, sl, arm, trail, tstop in GRID:
        rets, reasons, held = [], [], []
        for i0 in picks["i0"].to_numpy():
            r, why, nb = walk(o, h, l, c, v, tick, int(i0), HORIZON,
                              tp, sl, arm, trail, tstop)
            # Reverse splits in unadjusted bars produce impossible returns; the
            # label carries the same guard, so keep the two consistent.
            if np.isfinite(r) and abs(r) <= 3.0:
                rets.append(r - cost_bps / 1e4)
                reasons.append(why)
                held.append(nb)
        a = np.array(rets)
        if not len(a):
            continue
        rows.append({
            "rule": name, "n": len(a), "mean%": a.mean() * 100,
            "median%": np.median(a) * 100, "win%": (a > 0).mean() * 100,
            "std%": a.std() * 100,
            "sharpe_per_trade": a.mean() / a.std() if a.std() > 0 else np.nan,
            "med_bars": float(np.median(held)),
            "p_target": float(np.mean([x.startswith("target") for x in reasons]) * 100),
            "p_stop": float(np.mean([x.startswith("stop") for x in reasons]) * 100),
        })
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--max-train", type=int, default=150_000)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--cost-bps", type=float, default=COST_BPS)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import pyarrow.parquet as pq
    from sklearn.ensemble import HistGradientBoostingClassifier

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    lab = pq.read_table(root / "adrnn_panel.parquet",
                        columns=["max_up", "max_dn"]).to_pandas()
    y_up = (lab.max_up.to_numpy(float) >= 0.20).astype(np.float32)
    y_dn = (lab.max_dn.to_numpy(float) <= -0.20).astype(np.float32)
    tr, va, te = split_idx(d, idx)
    tr_full = tr.copy()
    if len(tr) > args.max_train:
        tr = tr[np.linspace(0, len(tr) - 1, args.max_train).astype(int)]
    med, scale = robust_scaler(X, tr)

    def flat(rows):
        return (X[rows] - med) / scale

    vi = feats.index("vol_20d")

    # ------------------------------------------------------------------
    print("=" * 90)
    print("IS THE VOLATILITY INVERSION VISIBLE IN THE TRAINING PERIOD?")
    print("=" * 90)
    print("The band was found on test. If the same shape is in train, it was")
    print("discoverable without touching anything reserved.\n")
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
    arrays = (o, h, l, c, v, tick)

    def hold_ret(rows):
        out = np.full(len(rows), np.nan)
        for a, i in enumerate(rows):
            j0 = i + 1
            if j0 >= len(o) or tick[j0] != tick[i]:
                continue
            j = min(j0 + HORIZON - 1, len(o) - 1)
            while j > j0 and tick[j] != tick[i]:
                j -= 1
            if np.isfinite(o[j0]) and o[j0] > 0 and np.isfinite(c[j]):
                out[a] = c[j] / o[j0] - 1.0
        return out

    for nm, rows in (("TRAIN 2015-2022", tr_full), ("TEST 2024-07..2025-12", te)):
        r = hold_ret(rows)
        q = pd.qcut(pd.Series(X[rows, vi]).rank(method="first"), 10, labels=False)
        t = pd.DataFrame({"q": q, "ret": r, "up": y_up[rows], "dn": y_dn[rows]}).dropna()
        g = t.groupby("q").agg(mean_ret=("ret", "mean"), p_up=("up", "mean"),
                               p_dn=("dn", "mean"))
        g["edge_pp"] = ((g.p_up - g.p_dn) * 100).round(2)
        g["mean_ret"] = (g.mean_ret * 100).round(2)
        print(f"  {nm}:  edge by vol decile (pp)")
        print("    " + "  ".join(f"d{i}:{g.edge_pp.iloc[i]:+.1f}" for i in range(10)))
        print("    " + "  ".join(f"r{i}:{g.mean_ret.iloc[i]:+.1f}%" for i in range(10)))
        print(f"    top decile inverts? "
              f"{'YES' if g.edge_pp.iloc[9] < g.edge_pp.iloc[8] else 'no'}"
              f"   (d8 {g.edge_pp.iloc[8]:+.2f}pp -> d9 {g.edge_pp.iloc[9]:+.2f}pp)")

    # ------------------------------------------------------------------
    mup = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                         max_depth=6, random_state=0).fit(flat(tr), y_up[tr])
    mdn = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.06,
                                         max_depth=6, random_state=0).fit(flat(tr), y_dn[tr])
    lo_q, hi_q = np.quantile(X[tr, vi], [0.6, 0.9])
    print(f"\nvol band from TRAIN quantiles: [{lo_q:.4f}, {hi_q:.4f})")

    def picks_for(rows, k):
        su = mup.predict_proba(flat(rows))[:, 1]
        sd = mdn.predict_proba(flat(rows))[:, 1]
        t = pd.DataFrame({"i": rows, "i0": rows + 1,
                          "date": pd.to_datetime(d["date"].to_numpy()[rows]),
                          "net": su - sd, "vol": X[rows, vi]})
        t = t[(t.vol >= lo_q) & (t.vol < hi_q)]
        t = t[t.groupby("date")["net"].transform("size") >= k]
        return t.sort_values("net", ascending=False).groupby("date").head(k)

    print("\n" + "=" * 90)
    print(f"EXIT GRID ON VALIDATION  (selection set, k={args.k}, "
          f"{args.cost_bps:.0f}bps round trip)")
    print("=" * 90)
    pv = picks_for(va, args.k)
    gv = run_grid(pv, arrays, args.cost_bps).sort_values("mean%", ascending=False)
    print(gv.round(2).to_string(index=False))

    best = gv.iloc[0]["rule"]
    print(f"\nSELECTED ON VALIDATION: {best!r}  "
          f"(mean {gv.iloc[0]['mean%']:+.2f}%)")
    print(f"Grid size {len(GRID)}; a Bonferroni-adjusted alpha for this many "
          f"rules is {0.05 / len(GRID):.4f}.")

    print("\n" + "=" * 90)
    print("THE SAME GRID ON TEST  (reported for completeness; only the selected "
          "row counts)")
    print("=" * 90)
    pt = picks_for(te, args.k)
    gt = run_grid(pt, arrays, args.cost_bps)
    gt["selected"] = gt.rule == best
    print(gt.round(2).to_string(index=False))

    row = gt[gt.rule == best]
    if len(row):
        rets = []
        for i0 in pt["i0"].to_numpy():
            spec = next(x for x in GRID if x[0] == best)
            r, _, _ = walk(o, h, l, c, v, tick, int(i0), HORIZON, *spec[1:])
            if np.isfinite(r) and abs(r) <= 3.0:
                rets.append(r - args.cost_bps / 1e4)
        a = np.array(rets)
        wk = pt["date"].dt.to_period("W").astype(str).to_numpy()[:len(a)]
        rng = np.random.default_rng(53)
        uw = np.unique(wk)
        where = {w: np.flatnonzero(wk == w) for w in uw}
        bs = np.array([a[np.concatenate([where[w] for w in
                       rng.choice(uw, len(uw), True)])].mean()
                       for _ in range(20000)])
        lo_ci, hi_ci = np.percentile(bs, [2.5, 97.5])
        print(f"\nOUT-OF-SAMPLE RESULT for the validation-selected rule:")
        print(f"  {best}")
        print(f"  n={len(a):,}  mean {a.mean() * 100:+.2f}%  "
              f"median {np.median(a) * 100:+.2f}%  win {(a > 0).mean() * 100:.1f}%")
        print(f"  week-clustered 95% CI [{lo_ci * 100:+.2f}%, {hi_ci * 100:+.2f}%]  "
              f"P(<=0) = {(bs <= 0).mean():.4f}")
        print(f"  -> {'PASS' if lo_ci > 0 else 'FAIL'} at the unadjusted 5% level")

    print("\ncost sensitivity on the selected rule (test):")
    for bps in (0, 10, 20, 40, 80):
        g2 = run_grid(pt, arrays, bps)
        r2 = g2[g2.rule == best]
        if len(r2):
            print(f"  {bps:3.0f}bps round trip -> mean {r2['mean%'].iloc[0]:+.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
