"""Test the trained REM residual model on genuinely unseen recent data.

The panel ends 2025-12-31 and everything in `RESULT_REM.md` was walk-forward
inside it. This fetches fresh bars, extends the price series past the panel, and
scores the model on data that did not exist when it was trained.

Two windows, and the difference matters
---------------------------------------
**Scored.** A ten-session label needs ten sessions *after* the entry, so the most
recent fifteen sessions cannot be graded — of the last fifteen bars in any
series, only about five have a complete forward window, and the rest would be
scored on a truncated path that flatters or punishes at random. The scored window
is therefore the last fifteen sessions whose outcome is fully known: entries
ending ten sessions before the latest bar.

**Live.** The most recent fifteen sessions are still reported, with their picks,
but marked unscored. They are predictions, not results.

Why this can be done without rebuilding the panel
-------------------------------------------------
The REM construction reads nothing but OHLCV — `Phi_S` is estimated from closes,
`F_local` from opens, closes and volume, `F_context` from the cross-section. So
arms A, B and C extend to new data directly. Arm D, the gradient booster on the
108 panel features, needs filings, fundamentals and insider data that are not
refetched here, so it is absent from this test and that is stated rather than
papered over.

Fifteen trades is not a result
------------------------------
At one pick a session this is fifteen observations against a strategy whose
per-trade standard deviation is around 20%. The standard error on the mean is
therefore about five percentage points, and nothing short of an enormous move is
distinguishable from zero. This is a smoke test — does the pipeline run on live
data, do the picks look sane, is anything catastrophically broken — not evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adrnn_train import auc, build_arrays  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from moonshot_tail import scale_fit  # noqa: E402
from rem_solver import (compile_shared, context_features, infer,  # noqa: E402
                        local_features)
from rem_train import fit, mlp, predict  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15"


def fetch_recent(tickers, start, end, workers=8):
    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources.prices import YahooPrices
    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=8.0, ttl_hours=6,
                    max_retries=3)
    yp = YahooPrices(cfg, cl, workers=workers)
    return yp.fetch(list(tickers), pd.Timestamp(start), pd.Timestamp(end))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--since", default="2025-07-01",
                    help="fetch from here; needs >60 sessions of run-up for sigma")
    ap.add_argument("--cache", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--min-adv", type=float, default=1e6,
                    help="minimum 20-session average dollar volume")
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import torch
    torch.set_num_threads(4)

    old = pd.read_parquet(root / "w2015_prices.parquet",
                          columns=["date", "ticker", "open", "high", "low",
                                   "close", "volume"])
    old["date"] = pd.to_datetime(old["date"])
    universe = sorted(old.ticker.unique())
    print(f"panel: {len(old):,} bars, {len(universe):,} tickers, "
          f"ends {old.date.max():%Y-%m-%d}", flush=True)

    cache = Path(args.cache)
    if cache.exists():
        new = pd.read_parquet(cache)
        print(f"using cached recent bars: {len(new):,}", flush=True)
    else:
        print(f"fetching fresh bars for {len(universe):,} tickers "
              f"from {args.since}", flush=True)
        new = fetch_recent(universe, args.since, pd.Timestamp.utcnow().normalize())
        new.to_parquet(cache)
    if new.empty:
        print("no recent data came back")
        return 1
    new["date"] = pd.to_datetime(new["date"])
    new = new[["date", "ticker", "open", "high", "low", "close", "volume"]]
    print(f"  {len(new):,} bars, {new.ticker.nunique():,} tickers, "
          f"{new.date.min():%Y-%m-%d} .. {new.date.max():%Y-%m-%d}")
    fresh = new[new.date > old.date.max()]
    print(f"  genuinely new (after the panel): {len(fresh):,} bars on "
          f"{fresh.ticker.nunique():,} tickers, "
          f"{fresh.date.min():%Y-%m-%d} .. {fresh.date.max():%Y-%m-%d}\n", flush=True)

    px = (pd.concat([old, new[new.date > old.date.max()]], ignore_index=True)
            .drop_duplicates(subset=["ticker", "date"], keep="last")
            .sort_values(["ticker", "date"]).reset_index(drop=True))

    print("compiling Phi_S over the extended series", flush=True)
    mu, sig = compile_shared(px)
    yrem_all, Frem_all, qnames = infer(mu, sig, HORIZON)
    Floc_all, lnames = local_features(px)
    Fctx_all, cnames = context_features(px, sig)

    # Eligibility, which the first version of this script omitted and which
    # invalidated it completely. Without a liquidity floor the model selects
    # sub-penny OTC names -- CNBX at $0.0001 on $50 of daily volume, LIPO on
    # zero -- where a single tick is +50% and nothing is executable. The panel's
    # own screen has a 5th-percentile average dollar volume of $1.4m; a $1m
    # floor and a $1 price floor reproduce it closely enough from OHLCV alone.
    from rem_solver import _roll_count, _roll_sum
    c_all = px["close"].to_numpy(float)
    v_all = np.nan_to_num(px["volume"].to_numpy(float), nan=0.0)
    t_all = px["ticker"].to_numpy()
    dv = c_all * v_all
    adv = _roll_sum(dv, t_all, 20) / np.maximum(_roll_count(t_all, 20), 1)
    elig = np.isfinite(sig) & (adv >= args.min_adv) & (c_all >= args.min_price)
    print(f"eligibility: {int(elig.sum()):,} of {len(elig):,} bars pass "
          f"(ADV >= ${args.min_adv:,.0f}, price >= ${args.min_price:.2f})",
          flush=True)
    valid = np.flatnonzero(elig)
    idx = valid[::args.stride]
    paths = daily_paths(px, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    full = np.isfinite(paths[:, HORIZON - 1])
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)

    dates = pd.Series(pd.to_datetime(px["date"].to_numpy()[idx]))
    tick = px["ticker"].to_numpy()[idx]
    yrem = yrem_all[idx]
    pxr, advr = c_all[idx], adv[idx]
    Z = np.column_stack([Frem_all[idx], yrem.reshape(-1, 1),
                         Floc_all[idx], Fctx_all[idx]]).astype(np.float32)

    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    last_bar = sess[-1]
    scored_end = sess[-(HORIZON + 1)]
    scored_win = sess[(sess <= scored_end)][-args.days:]
    live_win = sess[-args.days:]
    print(f"\nlatest bar {last_bar:%Y-%m-%d}")
    print(f"  SCORED window: {scored_win[0]:%Y-%m-%d} .. {scored_win[-1]:%Y-%m-%d}"
          f"  ({len(scored_win)} sessions, outcomes complete)")
    print(f"  LIVE window:   {live_win[0]:%Y-%m-%d} .. {live_win[-1]:%Y-%m-%d}"
          f"  ({len(live_win)} sessions, not yet gradeable)\n", flush=True)

    # train on everything comfortably before the scored window
    cutoff = scored_win[0] - pd.Timedelta(days=HORIZON * 2 + 14)
    tr = np.flatnonzero((dates < cutoff).to_numpy() & np.isfinite(ret))
    if len(tr) > 200_000:
        tr = tr[np.linspace(0, len(tr) - 1, 200_000).astype(int)]
    print(f"training on {len(tr):,} rows dated before {cutoff:%Y-%m-%d}", flush=True)
    med, sc = scale_fit(Z[tr])
    Zt = np.clip((Z[tr] - med) / sc, -5, 5).astype(np.float32)
    yt = ret[tr].astype(np.float32)
    rt = (yt - yrem[tr]).astype(np.float32)
    nb = fit(mlp(Zt.shape[1]), Zt, rt, 40, 0)
    nc = fit(mlp(Zt.shape[1]), Zt, yt, 40, 0)
    print("  trained arm B (residual) and arm C (direct)\n", flush=True)

    def score(win, label, gradeable):
        m = dates.isin(win).to_numpy()
        Ze = np.clip((Z[m] - med) / sc, -5, 5).astype(np.float32)
        pb = yrem[m] + predict(nb, Ze)
        pc = predict(nc, Ze)
        pa = yrem[m]
        t = pd.DataFrame({"date": dates[m].to_numpy(), "ticker": tick[m],
                          "ret": ret[m], "full": full[m], "px": pxr[m],
                          "adv": advr[m], "A": pa, "B": pb, "C": pc})
        print("=" * 96)
        print(f"{label}: {int(m.sum()):,} candidates over {t.date.nunique()} sessions")
        print("=" * 96)
        out = {}
        for arm in ("A", "B", "C"):
            pick = (t.sort_values(arm, ascending=False)
                     .groupby("date").head(args.k).sort_values("date"))
            out[arm] = pick
            if gradeable:
                g = pick[pick["full"] & pick.ret.notna()]
                if len(g):
                    net = g.ret - 2 * (COST / 2)
                    print(f"  arm {arm}: {len(g)} scorable picks   "
                          f"mean {net.mean() * 100:+7.2f}%   "
                          f"median {net.median() * 100:+7.2f}%   "
                          f"win {100 * (net > 0).mean():5.1f}%   "
                          f"best {net.max() * 100:+.1f}%  worst {net.min() * 100:+.1f}%")
        if gradeable:
            uni = t[t["full"] & t.ret.notna()].ret
            print(f"  universe mean over the same window: {uni.mean() * 100:+.2f}% "
                  f"({len(uni):,} candidates)")
        return out

    picks = score(scored_win, "SCORED -- outcomes known", True)
    print("\n  arm B picks, session by session:")
    pb = picks["B"]
    for _, r in pb.iterrows():
        if r["full"] and np.isfinite(r["ret"]):
            print(f"    {r.date:%Y-%m-%d}  {str(r.ticker):8s} "
                  f"${r.px:>8.2f}  ADV ${r.adv/1e6:>6.1f}m  {r.ret * 100:+8.2f}%")
        else:
            print(f"    {r.date:%Y-%m-%d}  {str(r.ticker):8s} "
                  f"${r.px:>8.2f}  ADV ${r.adv/1e6:>6.1f}m   (incomplete)")

    livep = score(live_win, "LIVE -- predictions, not yet gradeable", False)
    print("\n  arm B picks for the live window:")
    for _, r in livep["B"].iterrows():
        print(f"    {r.date:%Y-%m-%d}  {str(r.ticker):8s} ${r.px:>8.2f}  "
              f"ADV ${r.adv/1e6:>6.1f}m  predicted {r.B * 100:+6.2f}%")

    print("\n" + "=" * 96)
    print("WHAT FIFTEEN TRADES CAN AND CANNOT SAY")
    print("=" * 96)
    g = picks["B"]
    g = g[g["full"] & g.ret.notna()]
    if len(g) > 1:
        se = g.ret.std() / np.sqrt(len(g))
        print(f"  arm B: n={len(g)}, mean {g.ret.mean() * 100:+.2f}%, "
              f"standard error {se * 100:.2f}pp")
        print(f"  a 95% interval on that mean is roughly "
              f"[{(g.ret.mean() - 2 * se) * 100:+.2f}%, "
              f"{(g.ret.mean() + 2 * se) * 100:+.2f}%]")
        print("  The walk-forward estimate over 14 blocks was +0.127% per trade.")
        print("  This window cannot confirm or refute that; it can only show the")
        print("  pipeline runs on unseen data and the picks are not absurd.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
