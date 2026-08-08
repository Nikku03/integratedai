"""What does the long-only model look like at twenty trades a month?

Twenty trades a month is roughly one per trading day, which is a different book
from the top-five-per-day version: fewer, more concentrated positions, and far
less diversification to average away a bad pick.

Three things interact and none of them can be chosen independently:

    trades per month  x  hold length  =  concurrent positions

At twenty a month a ten-session hold needs about ten slots open at once; a
five-session hold needs five; a three-session hold needs three. So "twenty a
month" and "four slots" are not two preferences, they are one constraint, and
the hold length is what reconciles them.

Shortening the hold is not free. The model is retrained on each horizon here --
the label *is* the horizon -- rather than trained at ten days and cashed out
early, because a model fitted to a ten-day move and exited at three is being
asked a question it was never shown.

Two selection modes:

**forced**  take the single best name every day, whatever it looks like.
**gated**   take it only if its score clears a threshold set on the *training*
            distribution, so on a day when nothing looks good, nothing is
            bought. This trades fewer times than the forced version and the
            comparison is the point: is a forced daily trade worse than waiting?
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import build_arrays  # noqa: E402
from exit_rules import walk  # noqa: E402

COST = 20.0 / 1e4
VOL_FLOOR = 0.01
BLOCK_MONTHS = 6
FIRST_TEST = "2019-01-01"
MIN_TRAIN_ROWS = 40_000
TRADING_DAYS_PER_MONTH = 21.0


def realised(prices, rows, horizon):
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    l = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    tick = prices["ticker"].to_numpy()
    out = np.full(len(rows), np.nan)
    for a, i in enumerate(rows):
        r, _, _ = walk(o, h, l, c, v, tick, int(i) + 1, horizon,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            out[a] = r
    return out


def blocks(hi):
    out, cur = [], pd.Timestamp(FIRST_TEST)
    hi = pd.Timestamp(hi)
    while cur < hi:
        nxt = cur + pd.DateOffset(months=BLOCK_MONTHS)
        out.append((cur, min(nxt, hi + pd.Timedelta(days=1))))
        cur = nxt
    return out


def evaluate(tab, Xs, horizon, k, gate_pct):
    """Walk-forward for one (horizon, k, gate) configuration."""
    from sklearn.ensemble import HistGradientBoostingRegressor
    rows = []
    for b0, b1 in blocks(tab.date.max()):
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=horizon + 4))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < MIN_TRAIN_ROWS or len(te) < 500:
            continue
        if len(tr) > 200_000:
            tr = tr[np.linspace(0, len(tr) - 1, 200_000).astype(int)]
        y = tab.y.to_numpy()
        fin = np.isfinite(y[tr])
        med = np.median(Xs[tr], axis=0)
        q1, q3 = np.percentile(Xs[tr], [25, 75], axis=0)
        sc = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
        ztr = np.clip((Xs[tr][fin] - med) / sc, -5, 5)
        zte = np.clip((Xs[te] - med) / sc, -5, 5)
        ytr = y[tr][fin]
        m = HistGradientBoostingRegressor(max_iter=250, learning_rate=0.05,
                                          max_depth=6, random_state=0)
        m.fit(ztr, np.clip(ytr, np.percentile(ytr, 0.5), np.percentile(ytr, 99.5)))

        # The gate threshold comes from predictions on TRAINING rows, so it is
        # knowable before the block starts. Taking it from the test block's own
        # distribution would be look-ahead dressed up as a rule.
        thr = -np.inf
        if gate_pct is not None:
            ptr = m.predict(np.clip((Xs[tr][fin] - med) / sc, -5, 5))
            thr = float(np.percentile(ptr, gate_pct))

        sub = tab.iloc[te].assign(pred=m.predict(zte))
        uni = float(sub.ret.mean())
        picks = (sub[sub.groupby("date")["pred"].transform("size") >= k]
                 .sort_values("pred", ascending=False).groupby("date").head(k))
        picks = picks[picks.pred >= thr]
        n_days = sub.date.nunique()
        if picks.empty:
            continue
        rows.append({
            "block": f"{b0:%Y-%m}", "n_trades": len(picks), "n_days": n_days,
            "ret": float(picks.ret.mean()) - COST,
            "universe": uni,
            "excess": float(picks.ret.mean()) - COST - uni,
            "win": float((picks.ret > 0).mean()),
            "med_vol": float(picks.vol.median()),
        })
    return pd.DataFrame(rows)


def summarise(r, horizon, label, stride):
    if r.empty:
        return None
    # Striding thins the *candidates* per day, not the days themselves: the
    # index is ordered by (ticker, date), so taking every Nth row drops
    # ticker-days while leaving nearly every calendar date represented. Trades
    # per day is therefore read directly. It is a conservative estimate of the
    # live rate: live, the model chooses its top name from roughly ten times as
    # many candidates, so its pick can only be better ranked, never worse.
    live_per_day = r.n_trades.sum() / r.n_days.sum()
    per_month = live_per_day * TRADING_DAYS_PER_MONTH
    concurrent = per_month * horizon / TRADING_DAYS_PER_MONTH
    ex = r.excess.to_numpy()
    # Compounding the book: `concurrent` positions each earning `ret` per
    # `horizon` sessions, so the book turns over 21/horizon times a month.
    turns_per_month = TRADING_DAYS_PER_MONTH / horizon
    monthly = (1 + r.ret.mean()) ** turns_per_month - 1
    return {
        "config": label, "H": horizon,
        "trades/mo": round(per_month, 1),
        "slots": round(concurrent, 1),
        "ret/trade%": round(r.ret.mean() * 100, 3),
        "universe%": round(r.universe.mean() * 100, 3),
        "excess%": round(ex.mean() * 100, 3),
        "IR": round(ex.mean() / ex.std(), 2) if ex.std() > 0 else np.nan,
        "blocks": f"{int((ex > 0).sum())}/{len(r)}",
        "win%": round(r.win.mean() * 100, 1),
        "vol%": round(r.med_vol.median() * 100, 2),
        "book/mo%": round(monthly * 100, 2),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    args = ap.parse_args(argv)
    root = Path(args.root)

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    vi = feats.index("vol_20d")
    vol = X[idx, vi]
    dates = pd.to_datetime(d["date"].to_numpy()[idx])

    out = []
    for horizon in (3, 5, 10):
        print(f"\nhorizon {horizon} sessions: computing labels", flush=True)
        ret = realised(prices, idx, horizon)
        ok = np.isfinite(ret) & np.isfinite(vol) & (vol > 0)
        tab = pd.DataFrame({"row": idx, "date": dates, "vol": vol, "ret": ret})[ok]
        tab["y"] = tab.ret / np.maximum(tab.vol, VOL_FLOOR)
        tab = tab.reset_index(drop=True)
        Xs = X[tab.row.to_numpy()]
        for k, gate, label in ((1, None, "top 1/day, forced"),
                               (1, 50.0, "top 1/day, gated p50"),
                               (1, 80.0, "top 1/day, gated p80"),
                               (2, None, "top 2/day, forced"),
                               (5, None, "top 5/day (reference)")):
            r = evaluate(tab, Xs, horizon, k, gate)
            s = summarise(r, horizon, label, args.stride)
            if s:
                out.append(s)
                print(f"  {label:26s} trades/mo {s['trades/mo']:5.1f}  "
                      f"slots {s['slots']:4.1f}  excess {s['excess%']:+.3f}%  "
                      f"IR {s['IR']}  blocks {s['blocks']}", flush=True)

    o = pd.DataFrame(out)
    print("\n" + "=" * 112)
    print("TWENTY TRADES A MONTH: WHAT IT COSTS AND WHAT IT NEEDS")
    print("=" * 112)
    print(o.to_string(index=False))
    print("\n  trades/mo  live rate, corrected for the sampling stride")
    print("  slots      positions open at once = trades/mo x H / 21")
    print("  book/mo%   compounding ret/trade over 21/H turns a month")
    o.to_csv(root / "twenty_a_month.csv", index=False)

    near = o[(o["trades/mo"] >= 12) & (o["trades/mo"] <= 30)]
    if not near.empty:
        print("\n" + "=" * 112)
        print("CONFIGURATIONS LANDING NEAR 20 TRADES A MONTH")
        print("=" * 112)
        print(near.sort_values("IR", ascending=False).to_string(index=False))
    print("\nSurvivorship: no delistings in the panel; excess is the meaningful "
          "column, not the level.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
