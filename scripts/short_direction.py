"""Does short interest predict direction? The one thing nothing else has.

Direction has failed five independent ways in this repository: the ADRNN
direction head, the separate up/down classifiers in `RESULT_DIRECTIONAL.md`, the
gap/intraday decomposition in `RESULT_WHY_NO_UP.md`, the filing-text arm, and the
blind LLM reading. All landed at or near chance. `RESULT_RAMANUJAN.md` then found
that plain volatility already predicts *magnitude* at AUC 0.815 — so magnitude
was never the problem, and direction is the whole problem.

Short interest is the first genuinely new input since that conclusion, and it is
the one with a directional mechanism rather than a symmetric one. A heavily
shorted name has a buyer of last resort who is contractually obliged to appear:
covering is forced buying, and it is one-sided. If anything in this project is
going to predict direction, it should be this.

Point-in-time, or it is worthless
---------------------------------
Short interest settles on one date and is published about eight business days
later. `short_fetch.py` stamps every row ten business days after settlement and
this joins on that ``available`` date with a backward as-of merge, so a feature
is only ever used once the market could see it. The dataset also starts
2017-12-29, so rows before that carry NaN rather than zero — "no short interest
reported" must not become a learnable property of 2015.

Pass criteria, fixed before running
-----------------------------------
1. **Direction among big movers.** Of candidates that move at least 20% either
   way, predict which way. Every prior attempt sat at 0.50; this must exceed
   **0.55** out of sample to count.
2. **The squeeze effect, univariately.** The top days-to-cover decile must show
   a P(up) at least **3pp** above the bottom decile, with a bootstrap interval
   excluding zero. This is the mechanism stated plainly, and it does not depend
   on any model.
3. **Ranking.** Adding the features to the walk-forward book must improve the
   daily top pick by more than **+0.25pp** per trade, CI excluding zero.

A pass on 2 with a fail on 1 would still be interesting: it would mean the effect
is real but too weak to survive being mixed with 108 other columns.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, build_arrays  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from moonshot_tail import MAX_TRAIN, blocks, scale_fit  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
BIG = 0.20


def attach(panel: pd.DataFrame, si: pd.DataFrame) -> pd.DataFrame:
    """Backward as-of join on the availability date, per ticker.

    ``merge_asof`` with ``direction='backward'`` takes the most recent row whose
    key is <= the panel date, which is exactly "the latest short interest the
    market had seen". Anything else is look-ahead.
    """
    s = si.sort_values("available").copy()
    s = s.rename(columns={"symbolCode": "ticker"})
    keep = ["ticker", "available", "settlementDate", "currentShortPositionQuantity",
            "previousShortPositionQuantity", "averageDailyVolumeQuantity",
            "daysToCoverQuantity", "changePercent"]
    s = s[[c for c in keep if c in s.columns]].dropna(subset=["ticker", "available"])
    s = s.drop_duplicates(subset=["ticker", "available"], keep="last")
    p = panel.sort_values("date").copy()
    # merge_asof refuses to join keys whose dtypes differ even by resolution,
    # and the parquet round-trip can widen one side to datetime64[us]. Coerce
    # both explicitly rather than relying on what pyarrow happened to write.
    p["date"] = pd.to_datetime(p["date"]).astype("datetime64[ns]")
    s["available"] = pd.to_datetime(s["available"]).astype("datetime64[ns]")
    s = s.sort_values("available")
    out = pd.merge_asof(p, s, left_on="date", right_on="available", by="ticker",
                        direction="backward")
    return out


def features(d: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    cur = d["currentShortPositionQuantity"].to_numpy(float)
    prv = d["previousShortPositionQuantity"].to_numpy(float)
    adv = d["averageDailyVolumeQuantity"].to_numpy(float)
    dtc = d["daysToCoverQuantity"].to_numpy(float)
    chg = d["changePercent"].to_numpy(float)
    age = (d["date"] - d["available"]).dt.days.to_numpy(float)

    with np.errstate(divide="ignore", invalid="ignore"):
        log_short = np.where(cur > 0, np.log10(cur), np.nan)
        log_adv = np.where(adv > 0, np.log10(adv), np.nan)
        ratio = np.where(prv > 0, cur / prv - 1.0, np.nan)
    cols = {"si_dtc": dtc,
            "si_log_short": log_short,
            "si_log_adv": log_adv,
            "si_chg_pct": chg,
            "si_chg_ratio": np.clip(ratio, -5, 5),
            "si_age_days": age,
            "si_present": np.isfinite(cur).astype(float)}
    return np.column_stack(list(cols.values())).astype(np.float64), list(cols)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--si", default="/root/.iai/wide2015/short_interest.parquet")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--quantile", type=float, default=0.75)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  HistGradientBoostingRegressor)

    print(__doc__.split("Pass criteria")[1][:900])
    print("=" * 100, flush=True)

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    paths = daily_paths(prices, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    ok = np.isfinite(ret)
    rows, ret = idx[ok], ret[ok]

    panel = pd.DataFrame({"date": pd.to_datetime(d["date"].to_numpy()[rows]),
                          "ticker": d["ticker"].to_numpy()[rows],
                          "ret": ret, "_i": np.arange(len(rows))})
    si = pd.read_parquet(args.si)
    print(f"short interest: {len(si):,} rows, {si.symbolCode.nunique():,} symbols, "
          f"{si.settlementDate.min():%Y-%m} .. {si.settlementDate.max():%Y-%m}")

    m = attach(panel, si).sort_values("_i").reset_index(drop=True)
    F, fcols = features(m)
    cov = np.isfinite(F[:, fcols.index("si_dtc")])
    print(f"{len(m):,} candidates; days-to-cover present on "
          f"{cov.mean() * 100:.1f}%\n", flush=True)

    Xp = X[rows]
    dates = m["date"]
    ret = m["ret"].to_numpy()

    # Everything below runs only where the data exists, so a null cannot be an
    # artefact of comparing a covered arm against an uncovered one.
    sel = cov & (dates >= pd.Timestamp("2018-02-01")).to_numpy()
    print(f"evaluating on {int(sel.sum()):,} covered candidates "
          f"({dates[sel].min():%Y-%m} .. {dates[sel].max():%Y-%m})\n")
    Xs, Fs, rs, ds = Xp[sel], F[sel], ret[sel], dates[sel].reset_index(drop=True)

    # ---- 1. direction among big movers ---------------------------------
    print("=" * 100)
    print("1. DIRECTION AMONG BIG MOVERS -- need AUC > 0.55")
    print("=" * 100)
    big = np.abs(rs) >= BIG
    print(f"  {int(big.sum()):,} of {len(rs):,} candidates move >= {BIG:.0%} "
          f"({big.mean() * 100:.2f}%)")
    yb = (rs[big] > 0).astype(int)
    print(f"  of those, {yb.mean() * 100:.1f}% went up")
    order = np.argsort(ds[big].to_numpy(), kind="stable")
    cut = int(len(order) * 0.6)
    tr, te = order[:cut], order[cut:]
    for name, M in (("price only", Xs[big]), ("+ short int", np.column_stack([Xs[big], Fs[big]])),
                    ("short int only", Fs[big])):
        M = np.nan_to_num(M, nan=0.0, posinf=0.0, neginf=0.0)
        med, sc = scale_fit(M[tr])
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             max_depth=4, random_state=0)
        clf.fit(np.clip((M[tr] - med) / sc, -5, 5), yb[tr])
        p = clf.predict_proba(np.clip((M[te] - med) / sc, -5, 5))[:, 1]
        a = auc(yb[te], p)
        print(f"  {name:16s} AUC {a:.4f}  {'PASS' if a > 0.55 else 'fail'}")

    # ---- 2. the squeeze effect, univariately ---------------------------
    print("\n" + "=" * 100)
    print("2. THE SQUEEZE EFFECT -- top vs bottom days-to-cover decile")
    print("=" * 100)
    dtc = Fs[:, fcols.index("si_dtc")]
    fin = np.isfinite(dtc)
    q = pd.qcut(pd.Series(dtc[fin]).rank(method="first"), 10, labels=False)
    t = pd.DataFrame({"q": q, "r": rs[fin]})
    g = t.groupby("q").agg(n=("r", "size"), mean=("r", lambda s: s.mean() * 100),
                           p_up=("r", lambda s: (s > 0).mean() * 100),
                           p_up20=("r", lambda s: (s >= 0.20).mean() * 100),
                           p_dn20=("r", lambda s: (s <= -0.20).mean() * 100))
    print(g.round(2).to_string())
    lo_up = t[t.q == 0].r.gt(0).mean() * 100
    hi_up = t[t.q == 9].r.gt(0).mean() * 100
    rng = np.random.default_rng(3)
    a0 = t[t.q == 0].r.to_numpy()
    a9 = t[t.q == 9].r.to_numpy()
    bs = np.array([(rng.choice(a9, len(a9), True) > 0).mean()
                   - (rng.choice(a0, len(a0), True) > 0).mean() for _ in range(5000)]) * 100
    lo, hi = np.percentile(bs, [2.5, 97.5])
    print(f"\n  P(up) top decile {hi_up:.2f}% vs bottom {lo_up:.2f}%  "
          f"= {hi_up - lo_up:+.2f}pp   95% CI [{lo:+.2f}, {hi:+.2f}]")
    print(f"  {'PASS' if (hi_up - lo_up) >= 3.0 and lo > 0 else 'FAIL'}")

    # ---- 3. ranking -----------------------------------------------------
    print("\n" + "=" * 100)
    print("3. RANKING -- walk-forward daily top pick (need +0.25pp)")
    print("=" * 100)
    tab = pd.DataFrame({"date": ds, "ret": rs})
    out = {"price only": [], "+ short int": []}
    for b0, b1 in blocks(tab.date.max()):
        itr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        ite = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(itr) < 20_000 or len(ite) < 400:
            continue
        if len(itr) > MAX_TRAIN:
            itr = itr[np.linspace(0, len(itr) - 1, MAX_TRAIN).astype(int)]
        for name, M in (("price only", Xs), ("+ short int", np.column_stack([Xs, Fs]))):
            M = np.nan_to_num(M, nan=0.0, posinf=0.0, neginf=0.0)
            med, sc = scale_fit(M[itr])
            mm = HistGradientBoostingRegressor(loss="quantile", quantile=args.quantile,
                                               max_iter=250, learning_rate=0.05,
                                               max_depth=6, random_state=0)
            mm.fit(np.clip((M[itr] - med) / sc, -5, 5), rs[itr])
            pr = mm.predict(np.clip((M[ite] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": tab.date.to_numpy()[ite], "p": pr, "r": rs[ite]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(1)
            out[name].append(float(pick.r.mean()) - COST)
        print(f"  block {b0:%Y-%m} done", flush=True)
    a = np.array(out["price only"])
    b = np.array(out["+ short int"])
    if len(a) > 1:
        dl = b - a
        rng = np.random.default_rng(11)
        bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"\n  price only  {a.mean() * 100:+7.3f}%   + short int {b.mean() * 100:+7.3f}%")
        print(f"  delta {dl.mean() * 100:+.3f}pp   95% CI [{lo * 100:+.3f}, "
              f"{hi * 100:+.3f}]   P(<=0) = {(bs <= 0).mean():.4f}")
        print(f"  {'PASS' if dl.mean() > 0.0025 and lo > 0 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
