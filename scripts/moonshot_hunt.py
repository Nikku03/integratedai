"""Six trades in two weeks, chosen to catch the biggest moves rather than the best mean.

Two changes from `weekly_budget.py`, both asked for and both material.

**The budget must fill.** The previous rule used a fixed bar from the training
distribution and simply declined when nothing cleared it — three trades in four
weeks instead of twelve. A quota rule fills instead: with `r` slots left and `s`
sessions left in the week, the acceptance bar is the quantile that would fill `r`
of `s`, so it starts selective on Monday and relaxes as Friday approaches. On the
last session with slots outstanding it takes the best name available. Causal
throughout — nothing looks past the current session — and it fills.

**The objective changes.** Everything so far optimised a q75 quantile of return,
which is a good middle-of-the-tail target and a poor moonshot hunter. Catching
the biggest moves means asking for them directly, so five objectives are run:

    q75   the incumbent
    q90   further into the upper tail
    q95   further still
    P50   classify P(return >= +50%)
    P100  classify P(return >= +100%)

and they are scored on what was actually asked: how many moonshots were caught,
how big the biggest was, and only then the mean.

The metric change matters as much as the objective
--------------------------------------------------
A rule that returns +2% per trade with no move above +30% and a rule that returns
+2% with one +300% and a string of small losses are the same number and
completely different strategies. `RESULT_WHY_LOSERS.md` showed this book already
lives on the second shape — 47th outcome percentile, profitable anyway — so the
count and size of the tail is the honest scoreboard here, not the average.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agreed_strategy import daily_paths  # noqa: E402
from catalyst_pipeline import surge_features  # noqa: E402
from gate_live_test import UA, cik_map, eightks, since_matrix  # noqa: E402
from moonshot_tail import blocks, scale_fit  # noqa: E402
from rem_solver import _roll_count, _roll_sum, compile_shared, infer  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4


def quota_fill(t: pd.DataFrame, budget: int, sess_per_week: int = 5) -> pd.DataFrame:
    """Fill `budget` slots a week, causally, relaxing the bar as the week runs out.

    On each session the bar is the score quantile that would fill the remaining
    slots over the remaining sessions, computed from *that session's* candidates
    only. Monday is picky, Friday takes what is there. Nothing consults a later
    session, so this is runnable in real time.
    """
    t = t.sort_values(["date", "p"], ascending=[True, False]).copy()
    wk = t["date"].dt.isocalendar()
    t["_wk"] = wk.year.astype(int) * 100 + wk.week.astype(int)
    keep = []
    for _, g in t.groupby("_wk", sort=True):
        days = list(dict.fromkeys(g["date"]))
        left = budget
        for i, day in enumerate(days):
            if left <= 0:
                break
            sess_left = len(days) - i
            cand = g[g["date"] == day]
            if sess_left <= 1:
                take = min(left, len(cand))
            else:
                # how many of today's names should clear, to be on pace
                take = int(np.floor(left / sess_left))
                if np.random.default_rng(int(day.value) % 2**31).random() < (
                        left / sess_left - take):
                    take += 1
                take = min(take, left, len(cand))
            if take > 0:
                keep.append(cand.head(take))
                left -= take
    return pd.concat(keep, ignore_index=True) if keep else t.iloc[:0]


def tail_stats(sel: pd.DataFrame) -> dict:
    if sel is None or not len(sel):
        return {}
    r = sel["ret"].to_numpy()
    return {"n": len(r), "mean": r.mean() * 100 - COST * 100,
            "median": np.median(r) * 100,
            "p20": (r >= 0.20).mean() * 100, "p50": (r >= 0.50).mean() * 100,
            "p100": (r >= 1.00).mean() * 100, "best": r.max() * 100,
            "worst": r.min() * 100, "win": (r > 0).mean() * 100}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--per-week", type=int, default=3)
    ap.add_argument("--weeks", type=int, default=2)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  HistGradientBoostingRegressor)
    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=6.0, ttl_hours=24 * 365)

    old = pd.read_parquet(root / "w2015_prices.parquet",
                          columns=["date", "ticker", "open", "high", "low",
                                   "close", "volume"])
    old["date"] = pd.to_datetime(old["date"])
    new = pd.read_parquet(args.recent)
    new["date"] = pd.to_datetime(new["date"])
    new = new[["date", "ticker", "open", "high", "low", "close", "volume"]]
    px = (pd.concat([old, new[new.date > old.date.max()]], ignore_index=True)
            .drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"]).reset_index(drop=True))

    print("building the EDGAR catalyst gate", flush=True)
    f = eightks(cl, args.from_year, 2026)
    f["ticker"] = f["cik"].map(cik_map(cl))
    f = f.dropna(subset=["ticker"])
    f = f[f.ticker.isin(set(px.ticker.unique()))]
    since = since_matrix(px, f)

    c_all = px["close"].to_numpy(float)
    v_all = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t_all = px["ticker"].to_numpy()
    adv = _roll_sum(c_all * v_all, t_all, 20) / np.maximum(_roll_count(t_all, 20), 1)
    mu, sig = compile_shared(px)
    yrem, Frem, _ = infer(mu, sig, HORIZON)
    SG, _ = surge_features(px, since)
    elig = np.isfinite(sig) & (adv >= args.min_adv) & (c_all >= args.min_price)

    idx = np.flatnonzero(elig)[:: args.stride]
    paths = daily_paths(px, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    dates = pd.Series(pd.to_datetime(px["date"].to_numpy()[idx]))
    tick = px["ticker"].to_numpy()[idx]
    A = np.column_stack([Frem[idx], yrem[idx].reshape(-1, 1), SG[idx]]).astype(np.float32)
    gated = (since[idx] >= 1) & (since[idx] <= args.gate_days)
    usable = np.isfinite(ret) & full & gated
    print(f"  {int(usable.sum()):,} usable gated candidates\n", flush=True)

    OBJ = ["q75", "q90", "q95", "P50", "P100"]

    def train(A_tr, y_tr, obj):
        if obj.startswith("q"):
            m = HistGradientBoostingRegressor(
                loss="quantile", quantile=float(obj[1:]) / 100.0,
                max_iter=250, learning_rate=0.05, max_depth=6, random_state=0)
            m.fit(A_tr, y_tr)
            return lambda Z: m.predict(Z)
        thr = 0.50 if obj == "P50" else 1.00
        lab = (y_tr >= thr).astype(int)
        if lab.sum() < 40:
            return None
        m = HistGradientBoostingClassifier(max_iter=250, learning_rate=0.05,
                                           max_depth=6, random_state=0)
        m.fit(A_tr, lab)
        return lambda Z: m.predict_proba(Z)[:, 1]

    # =============== historical: which objective catches tails ===========
    print("=" * 112)
    print(f"HISTORICAL -- {args.per_week}/week quota fill, walk-forward, "
          f"scored on the tail")
    print("=" * 112)
    hist = {o: [] for o in OBJ}
    for b0, b1 in blocks(pd.Timestamp("2025-12-31")):
        tr = np.flatnonzero((dates < b0 - pd.Timedelta(days=14)).to_numpy() & usable)
        te = np.flatnonzero(((dates >= b0) & (dates < b1)).to_numpy() & usable)
        if len(tr) < 20_000 or len(te) < 500:
            continue
        if len(tr) > 200_000:
            tr = tr[np.linspace(0, len(tr) - 1, 200_000).astype(int)]
        med, sc = scale_fit(A[tr])
        Ztr = np.clip((A[tr] - med) / sc, -5, 5)
        Zte = np.clip((A[te] - med) / sc, -5, 5)
        for o in OBJ:
            fn = train(Ztr, ret[tr], o)
            if fn is None:
                continue
            t = pd.DataFrame({"date": dates.to_numpy()[te], "ticker": tick[te],
                              "ret": ret[te], "p": fn(Zte)})
            hist[o].append(quota_fill(t, args.per_week))
        print(f"  block {b0:%Y-%m} done", flush=True)

    print(f"\n  {'objective':10s} {'trades':>7s} {'mean':>8s} {'median':>8s} "
          f"{'win':>6s} {'P>=20%':>7s} {'P>=50%':>7s} {'P>=100%':>8s} {'best':>9s}")
    for o in OBJ:
        if not hist[o]:
            continue
        s = tail_stats(pd.concat(hist[o], ignore_index=True))
        print(f"  {o:10s} {s['n']:>7,} {s['mean']:>+7.2f}% {s['median']:>+7.2f}% "
              f"{s['win']:>5.1f}% {s['p20']:>6.2f}% {s['p50']:>6.2f}% "
              f"{s['p100']:>7.2f}% {s['best']:>+8.1f}%")
    base = pd.DataFrame({"ret": ret[usable]})
    b = tail_stats(base)
    print(f"  {'(gated pool)':10s} {b['n']:>7,} {b['mean']:>+7.2f}% "
          f"{b['median']:>+7.2f}% {b['win']:>5.1f}% {b['p20']:>6.2f}% "
          f"{b['p50']:>6.2f}% {b['p100']:>7.2f}% {b['best']:>+8.1f}%")

    # =============== live: the last two weeks ============================
    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    win = sess[sess <= sess[-(HORIZON + 1)]][-(args.weeks * 5):]
    cutoff = win[0] - pd.Timedelta(days=HORIZON * 2 + 14)
    tr = np.flatnonzero((dates < cutoff).to_numpy() & usable)
    if len(tr) > 250_000:
        tr = tr[np.linspace(0, len(tr) - 1, 250_000).astype(int)]
    med, sc = scale_fit(A[tr])
    Ztr = np.clip((A[tr] - med) / sc, -5, 5)
    inwin = dates.isin(win).to_numpy() & usable
    Zte = np.clip((A[inwin] - med) / sc, -5, 5)

    print("\n" + "=" * 112)
    print(f"LIVE {win[0]:%Y-%m-%d} .. {win[-1]:%Y-%m-%d}  "
          f"({len(win)} sessions, {args.weeks} weeks, {args.per_week}/week)")
    print("=" * 112)
    uni = ret[dates.isin(win).to_numpy() & np.isfinite(ret) & full]
    print(f"  universe over the window: {uni.mean() * 100:+.2f}% mean, "
          f"{(uni >= 0.20).mean() * 100:.2f}% moved +20%, "
          f"{(uni >= 0.50).mean() * 100:.2f}% moved +50%  ({len(uni):,} names)\n")
    picks = {}
    for o in OBJ:
        fn = train(Ztr, ret[tr], o)
        if fn is None:
            continue
        t = pd.DataFrame({"date": dates[inwin].to_numpy(), "ticker": tick[inwin],
                          "ret": ret[inwin], "p": fn(Zte)})
        sel = quota_fill(t, args.per_week).sort_values("date")
        picks[o] = sel
        s = tail_stats(sel)
        print(f"  {o:5s} {s['n']} trades   mean {s['mean']:+7.2f}%   "
              f"best {s['best']:+7.1f}%   worst {s['worst']:+7.1f}%   "
              f"+20%: {int(round(s['p20'] * s['n'] / 100))}   "
              f"+50%: {int(round(s['p50'] * s['n'] / 100))}")
    for o, sel in picks.items():
        print(f"\n  {o} picks:")
        for _, r in sel.iterrows():
            star = "  <-- moonshot" if r.ret >= 0.50 else (
                "  <-- +20%" if r.ret >= 0.20 else "")
            print(f"    {r.date:%Y-%m-%d}  {str(r.ticker):8s} "
                  f"{r.ret * 100:>+8.2f}%{star}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
