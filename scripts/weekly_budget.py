"""Three trades a week instead of one a day, and the look-ahead trap in doing it.

Taking "the best three names of the week" is not a strategy you can run. On
Monday you do not know whether Thursday will offer something better, so pooling
the week and keeping its top three quietly uses the future to decide which days
to trade. On a payoff this skewed that is not a small edge — it is close to
picking the winners.

The causal version is a **budget with a threshold**. Each session, score the
gated names; trade any that clear a bar set from the *training* distribution,
first come first served, until the week's three slots are gone. Some weeks fill
by Tuesday, some never fill at all, and that is exactly what a real book does.
The threshold is chosen so the expected fill rate is about three a week — never
by looking at the test period.

Both are reported. The gap between them is the size of the look-ahead, and it is
worth seeing rather than assuming.

Why the historical run matters more than the live one
------------------------------------------------------
Fifteen sessions is three weeks, which at three trades a week is **nine trades**.
That cannot evaluate anything — the previous two live tests flipped sign when k
changed. The seven-year walk-forward gives roughly a thousand trades under the
same rule, and that is where the question is actually answered. The live window
is reported as a smoke test and nothing more.
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
PER_WEEK = 3


def weekly_causal(t: pd.DataFrame, thresh: float, budget: int) -> pd.DataFrame:
    """Trade anything over the bar, first come first served, `budget` a week.

    Sessions are walked in order and the week's slots are consumed as they fill,
    so a name on Monday can use a slot that a better name on Thursday then
    cannot. That is the cost of not knowing the future, and it is the point.
    """
    t = t.sort_values(["date", "p"], ascending=[True, False])
    week = t["date"].dt.isocalendar()
    t = t.assign(_wk=week.year.astype(int) * 100 + week.week.astype(int))
    keep = []
    for _, g in t.groupby("_wk", sort=True):
        left = budget
        for _, r in g.iterrows():
            if left <= 0:
                break
            if r["p"] >= thresh:
                keep.append(r)
                left -= 1
    return pd.DataFrame(keep) if keep else t.iloc[:0]


def weekly_lookahead(t: pd.DataFrame, budget: int) -> pd.DataFrame:
    """The week's top `budget` by score. Uses the whole week to choose. Not tradeable."""
    week = t["date"].dt.isocalendar()
    t = t.assign(_wk=week.year.astype(int) * 100 + week.week.astype(int))
    return t.sort_values("p", ascending=False).groupby("_wk").head(budget)


def summarise(name, sel, uni_day, out, per_week=None):
    if sel is None or not len(sel):
        out.append((name, 0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan))
        return
    day = sel.groupby("date").ret.mean()
    common = day.index.intersection(uni_day.index)
    ex = (day.loc[common] - uni_day.loc[common]).to_numpy()
    rng = np.random.default_rng(71)
    bs = np.array([rng.choice(ex, len(ex), True).mean() for _ in range(20000)])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    out.append((name, len(sel), sel.ret.mean() * 100 - COST * 100,
                (sel.ret > 0).mean() * 100, ex.mean() * 100, lo * 100, hi * 100,
                per_week if per_week is not None else np.nan))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--recent", default="/root/.iai/wide2015/recent_prices.parquet")
    ap.add_argument("--from-year", type=int, default=2018)
    ap.add_argument("--gate-days", type=int, default=3)
    ap.add_argument("--per-week", type=int, default=PER_WEEK)
    ap.add_argument("--days", type=int, default=15)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--min-adv", type=float, default=1e6)
    ap.add_argument("--min-price", type=float, default=1.0)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from sklearn.ensemble import HistGradientBoostingRegressor
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

    print("building the EDGAR gate", flush=True)
    f = eightks(cl, args.from_year, 2026)
    m = cik_map(cl)
    f["ticker"] = f["cik"].map(m)
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
    live_ok = np.isfinite(ret) & full & gated
    print(f"  {int(gated.sum()):,} gated candidates of {len(idx):,}\n", flush=True)

    # =================== historical walk-forward =========================
    print("=" * 104)
    print(f"HISTORICAL WALK-FORWARD -- {args.per_week} trades a week vs daily k")
    print("=" * 104)
    rules = {f"weekly {args.per_week}, causal": [],
             f"weekly {args.per_week}, LOOK-AHEAD": [],
             "daily k=1": [], "daily k=3": [], "universe": []}
    counts = {k: 0 for k in rules}
    for b0, b1 in blocks(pd.Timestamp("2025-12-31")):
        tr = np.flatnonzero((dates < b0 - pd.Timedelta(days=14)).to_numpy() & live_ok)
        te = np.flatnonzero(((dates >= b0) & (dates < b1)).to_numpy() & live_ok)
        if len(tr) < 20_000 or len(te) < 500:
            continue
        if len(tr) > 200_000:
            tr = tr[np.linspace(0, len(tr) - 1, 200_000).astype(int)]
        med, sc = scale_fit(A[tr])
        mo = HistGradientBoostingRegressor(loss="quantile", quantile=0.75,
                                           max_iter=250, learning_rate=0.05,
                                           max_depth=6, random_state=0)
        mo.fit(np.clip((A[tr] - med) / sc, -5, 5), ret[tr])
        ptr = mo.predict(np.clip((A[tr] - med) / sc, -5, 5))
        # threshold from TRAINING scores only, set to fill about the budget
        wk_tr = dates.iloc[tr].dt.isocalendar()
        n_weeks = len(set(zip(wk_tr.year, wk_tr.week)))
        want = args.per_week * n_weeks
        thresh = float(np.quantile(ptr, max(0.0, 1.0 - want / max(len(ptr), 1))))

        p = mo.predict(np.clip((A[te] - med) / sc, -5, 5))
        t = pd.DataFrame({"date": dates.to_numpy()[te], "ticker": tick[te],
                          "ret": ret[te], "p": p})
        wk = t["date"].dt.isocalendar()
        nwk = len(set(zip(wk.year, wk.week)))
        sel = {
            f"weekly {args.per_week}, causal": weekly_causal(t, thresh, args.per_week),
            f"weekly {args.per_week}, LOOK-AHEAD": weekly_lookahead(t, args.per_week),
            "daily k=1": t.sort_values("p", ascending=False).groupby("date").head(1),
            "daily k=3": t.sort_values("p", ascending=False).groupby("date").head(3),
            "universe": t,
        }
        for name, s in sel.items():
            if len(s):
                rules[name].append(float(s.ret.mean()) - COST)
                counts[name] += len(s)
        print(f"  block {b0:%Y-%m}  {nwk} weeks  causal filled "
              f"{len(sel[f'weekly {args.per_week}, causal'])}", flush=True)

    print(f"\n  {'rule':26s} {'blocks':>7s} {'trades':>8s} {'per trade':>11s} "
          f"{'vs universe':>12s}")
    uni = np.array(rules["universe"])
    for name, v in rules.items():
        a = np.array(v)
        if not len(a):
            continue
        print(f"  {name:26s} {len(a):>7d} {counts[name]:>8,} "
              f"{a.mean() * 100:>+10.3f}% {(a.mean() - uni.mean()) * 100:>+11.3f}pp")

    # =================== live window =====================================
    sess = pd.DatetimeIndex(sorted(px.date.unique()))
    win = sess[sess <= sess[-(HORIZON + 1)]][-args.days:]
    cutoff = win[0] - pd.Timedelta(days=HORIZON * 2 + 14)
    tr = np.flatnonzero((dates < cutoff).to_numpy() & live_ok)
    if len(tr) > 250_000:
        tr = tr[np.linspace(0, len(tr) - 1, 250_000).astype(int)]
    med, sc = scale_fit(A[tr])
    mo = HistGradientBoostingRegressor(loss="quantile", quantile=0.75,
                                       max_iter=250, learning_rate=0.05,
                                       max_depth=6, random_state=0)
    mo.fit(np.clip((A[tr] - med) / sc, -5, 5), ret[tr])
    ptr = mo.predict(np.clip((A[tr] - med) / sc, -5, 5))
    wk_tr = dates.iloc[tr].dt.isocalendar()
    n_weeks = len(set(zip(wk_tr.year, wk_tr.week)))
    thresh = float(np.quantile(ptr, max(0.0, 1.0 - args.per_week * n_weeks / len(ptr))))

    inwin = dates.isin(win).to_numpy() & np.isfinite(ret) & full
    tu = pd.DataFrame({"date": dates[inwin].to_numpy(), "ticker": tick[inwin],
                       "ret": ret[inwin], "gated": gated[inwin],
                       "p": mo.predict(np.clip((A[inwin] - med) / sc, -5, 5))})
    tg = tu[tu.gated].copy()
    uni_day = tu.groupby("date").ret.mean()
    nweeks_live = tg["date"].dt.isocalendar().apply(
        lambda r: f"{r.year}-{r.week}", axis=1).nunique()

    print("\n" + "=" * 104)
    print(f"LIVE {win[0]:%Y-%m-%d} .. {win[-1]:%Y-%m-%d}  "
          f"({len(win)} sessions = {nweeks_live} weeks) -- SMOKE TEST ONLY")
    print("=" * 104)
    out = []
    summarise("universe (control)", tu, uni_day, out)
    summarise(f"weekly {args.per_week}, causal",
              weekly_causal(tg, thresh, args.per_week), uni_day, out)
    summarise(f"weekly {args.per_week}, LOOK-AHEAD",
              weekly_lookahead(tg, args.per_week), uni_day, out)
    summarise("daily k=1", tg.sort_values("p", ascending=False).groupby("date").head(1),
              uni_day, out)
    summarise("daily k=3", tg.sort_values("p", ascending=False).groupby("date").head(3),
              uni_day, out)
    print(f"  {'rule':26s} {'n':>4s} {'mean':>9s} {'win':>7s} {'vs uni':>9s} "
          f"{'95% CI (day-clustered)':>24s}")
    for nm, n, mr, wr, ex, lo, hi, _ in out:
        if not n:
            print(f"  {nm:26s}    0   (no trades cleared the bar)")
            continue
        print(f"  {nm:26s} {n:>4d} {mr:>+8.2f}% {wr:>6.1f}% {ex:>+8.2f}pp "
              f"  [{lo:>+6.2f}, {hi:>+6.2f}]pp")

    sel = weekly_causal(tg, thresh, args.per_week)
    if len(sel):
        print(f"\n  the {len(sel)} trades the causal rule actually took:")
        for _, r in sel.sort_values("date").iterrows():
            print(f"    {r.date:%Y-%m-%d}  {str(r.ticker):8s} "
                  f"score {r.p * 100:>+6.2f}   realised {r.ret * 100:>+8.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
