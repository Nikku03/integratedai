"""Does any of the Ramanujan construction beat what the panel already has?

Pre-registered, because the whole point of this repository is that plausible
ideas mostly fail and the way to find out is to say what would count as success
before looking.

The prediction, written before running
--------------------------------------
**The partition features will add nothing.** log p(n) ~ pi sqrt(2n/3) is a
strictly increasing function of n, and n here is the move in ATR units. A
gradient-boosted tree splits on order, not on value, so it is invariant to any
monotone transform of a single feature: handing it sqrt-of-volatility when it
already has volatility is handing it the same column twice. If the Spearman
correlation between `hr_ent` and `vol_20d` comes back near 1, that is not a
subtle finding, it is arithmetic, and the ranking test should then show nothing.

**The restricted-partition and specific-heat features are the only candidates.**
p(n, k) depends on how a move was distributed across sessions, not only on its
size, and the Boltzmann specific heat C(beta) = beta^2 Var_beta(r) peaks where
the trailing return distribution is closest to bimodal -- a name poised between
two regimes rather than merely a volatile one. Neither is a monotone function of
volatility, so neither is ruled out in advance.

Pass criteria, fixed now
------------------------
1. **Separability.** Adding the features must move the win-versus-lose AUC by
   at least +0.010 over the price-only arm on identical rows. The panel-only
   number to beat is around 0.53, which is where every previous attempt landed.
2. **Ranking.** The walk-forward daily top pick must improve by more than
   +0.25pp per trade with a bootstrap interval excluding zero.
3. **Tipping point.** The criticality measure must separate large absolute
   moves from small ones better than volatility does -- AUC on |move| >= 20%
   strictly above the vol-only AUC, on the same rows.

Anything less is a null and is reported as one.
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
from ramanujan import (_roll, log_hardy_ramanujan, partitions,  # noqa: E402
                       restricted_partitions, rolling_moments, shanks)

HORIZON = 10
COST = 20.0 / 1e4
WINDOW = 60
BETAS = (-50.0, -20.0, -10.0, -5.0, 5.0, 10.0, 20.0, 50.0)
MAX_N = 400


def build_features(prices: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """The Ramanujan-derived columns, one row per price bar."""
    c = prices["close"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    lo = prices["low"].to_numpy(float)
    tick = prices["ticker"].to_numpy()
    n = len(c)

    prev = np.r_[np.nan, c[:-1]]
    same = np.r_[False, tick[1:] == tick[:-1]]
    r = np.where(same, c / prev - 1.0, np.nan)

    # true range in return units, as the quantum a move is counted in
    tr = np.where(same, np.maximum(h - lo, np.abs(c - prev)) / np.maximum(prev, 1e-9),
                  np.nan)
    atr = _roll(np.nan_to_num(tr, nan=0.0), tick, WINDOW) / WINDOW
    atr = np.where(atr > 1e-6, atr, np.nan)

    # ---- 1. partition entropy of the trailing move ----------------------
    cum = _roll(np.nan_to_num(r, nan=0.0), tick, WINDOW)
    units = np.abs(cum) / atr
    nq = np.clip(np.nan_to_num(units, nan=0.0), 0, MAX_N).astype(int)
    hr_tab = np.array([log_hardy_ramanujan(i) for i in range(MAX_N + 1)])
    ex_tab = np.array([float(np.log(float(partitions(i)))) if i > 0 else 0.0
                       for i in range(MAX_N + 1)])
    hr_ent = hr_tab[nq]
    hr_err = ex_tab[nq] - hr_ent

    # ---- 2. restricted partitions: how the move was distributed ---------
    # k = sessions in the window that actually carried the move
    active = _roll((np.abs(np.nan_to_num(r, nan=0.0)) > atr * 0.5).astype(float),
                   tick, WINDOW)
    k = np.clip(np.nan_to_num(active, nan=1.0), 1, WINDOW).astype(int)
    # p(n, k) is expensive; tabulate on a coarse grid and look up
    ks = np.array([1, 2, 3, 5, 8, 12, 18, 25, 35, 60])
    ns = np.arange(0, MAX_N + 1, 4)
    tab = np.zeros((len(ns), len(ks)))
    for i, nn in enumerate(ns):
        for j, kk in enumerate(ks):
            v = restricted_partitions(int(nn), int(kk))
            tab[i, j] = np.log(float(v)) if v > 0 else 0.0
    ni = np.clip(np.searchsorted(ns, nq), 0, len(ns) - 1)
    kj = np.clip(np.searchsorted(ks, k), 0, len(ks) - 1)
    rp = tab[ni, kj]
    part_frac = np.where(hr_ent > 1e-9, rp / hr_ent, 0.0)

    # ---- 3. Boltzmann specific heat: the tipping-point measure ----------
    _, _, var0 = rolling_moments(r, tick, WINDOW, 0.0)
    cmax = np.zeros(n)
    bcrit = np.zeros(n)
    for b in BETAS:
        _, _, v = rolling_moments(r, tick, WINDOW, b)
        cb = (b * b) * np.nan_to_num(v, nan=0.0)
        better = cb > cmax
        bcrit = np.where(better, b, bcrit)
        cmax = np.where(better, cb, cmax)
    base = np.nan_to_num(var0, nan=0.0)
    c_ratio = np.where(base > 1e-12, cmax / (base * 1e4), 0.0)

    # ---- 4. Shanks extrapolation: is the level converging? --------------
    s_gap = np.full(n, np.nan)
    ok = np.r_[False, False, tick[2:] == tick[:-2]] & same
    a0, a1, a2 = np.r_[np.nan, np.nan, c[:-2]], np.r_[np.nan, c[:-1]], c
    den = a2 - 2.0 * a1 + a0
    est = np.where(np.abs(den) > 1e-9, (a2 * a0 - a1 * a1) / den, np.nan)
    s_gap = np.where(ok, (est - c) / np.maximum(c * atr, 1e-9), np.nan)
    s_gap = np.clip(np.nan_to_num(s_gap, nan=0.0), -50, 50)
    s_unstable = (np.abs(den) < np.abs(c) * 1e-4).astype(float)

    cols = {"ram_units": np.nan_to_num(units, nan=0.0),
            "ram_hr_ent": hr_ent,
            "ram_hr_err": hr_err,
            "ram_part_frac": np.nan_to_num(part_frac, nan=0.0),
            "ram_active_k": k.astype(float),
            "ram_c_max": np.nan_to_num(cmax, nan=0.0),
            "ram_beta_crit": bcrit,
            "ram_c_ratio": np.clip(np.nan_to_num(c_ratio, nan=0.0), 0, 1e3),
            "ram_shanks_gap": s_gap,
            "ram_shanks_unstable": s_unstable}
    return np.column_stack(list(cols.values())).astype(np.float32), list(cols)


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

    print(__doc__.split("Pass criteria")[0].strip()[-700:])
    print("\n" + "=" * 100, flush=True)

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    assert len(prices) == len(d), "panel and price rows are not aligned"

    print("building Ramanujan features", flush=True)
    R, rcols = build_features(prices)
    print(f"  {R.shape[1]} columns over {R.shape[0]:,} bars")

    paths = daily_paths(prices, idx, HORIZON)
    ret = np.nanprod(1.0 + np.nan_to_num(paths, nan=0.0), axis=1) - 1.0
    ret = np.where(np.isfinite(paths[:, 0]) & (np.abs(ret) <= 3.0), ret, np.nan)
    good = np.isfinite(ret)
    rows = idx[good]
    ret = ret[good]
    Xp, Rp = X[rows], R[rows]
    dates = pd.to_datetime(d["date"].to_numpy()[rows])
    vol = Xp[:, feats.index("vol_20d")]
    print(f"  {len(rows):,} candidates with a realised return\n", flush=True)

    # ---- the arithmetic check ------------------------------------------
    print("=" * 100)
    print("0. IS THE PARTITION ENTROPY JUST VOLATILITY? (predicted: yes)")
    print("=" * 100)
    fin = np.isfinite(vol) & (vol > 0)
    for c in ("ram_units", "ram_hr_ent", "ram_part_frac", "ram_c_ratio",
              "ram_c_max", "ram_shanks_gap"):
        v = Rp[:, rcols.index(c)]
        m = fin & np.isfinite(v)
        rho = pd.Series(v[m]).corr(pd.Series(vol[m]), method="spearman")
        note = "  <- monotone in vol, cannot add" if abs(rho) > 0.9 else ""
        print(f"  spearman({c:20s}, vol_20d) = {rho:+.4f}{note}")

    # ---- 1. separability -----------------------------------------------
    print("\n" + "=" * 100)
    print("1. SEPARABILITY -- winners vs losers (need +0.010 to pass)")
    print("=" * 100)
    y = (ret - COST > 0).astype(int)
    order = np.argsort(dates.to_numpy(), kind="stable")
    cut = int(len(order) * 0.6)
    tr, te = order[:cut], order[cut:]
    res = {}
    for name, M in (("price only", Xp), ("+ ramanujan", np.column_stack([Xp, Rp])),
                    ("ramanujan only", Rp)):
        M = np.nan_to_num(M, nan=0.0, posinf=0.0, neginf=0.0)
        med, sc = scale_fit(M[tr])
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             max_depth=4, random_state=0)
        clf.fit(np.clip((M[tr] - med) / sc, -5, 5), y[tr])
        p = clf.predict_proba(np.clip((M[te] - med) / sc, -5, 5))[:, 1]
        res[name] = auc(y[te], p)
        print(f"  {name:16s} AUC {res[name]:.4f}")
    delta = res["+ ramanujan"] - res["price only"]
    print(f"\n  delta {delta:+.4f}   "
          f"{'PASS' if delta >= 0.010 else 'FAIL (needed +0.0100)'}")

    # ---- 2. ranking -----------------------------------------------------
    print("\n" + "=" * 100)
    print("2. RANKING -- walk-forward daily top pick (need +0.25pp)")
    print("=" * 100)
    tab = pd.DataFrame({"date": dates, "ret": ret})
    out = {"price only": [], "+ ramanujan": []}
    for b0, b1 in blocks(tab.date.max()):
        itr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        ite = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(itr) < 40_000 or len(ite) < 500:
            continue
        if len(itr) > MAX_TRAIN:
            itr = itr[np.linspace(0, len(itr) - 1, MAX_TRAIN).astype(int)]
        for name, M in (("price only", Xp), ("+ ramanujan", np.column_stack([Xp, Rp]))):
            M = np.nan_to_num(M, nan=0.0, posinf=0.0, neginf=0.0)
            med, sc = scale_fit(M[itr])
            m = HistGradientBoostingRegressor(loss="quantile", quantile=args.quantile,
                                              max_iter=250, learning_rate=0.05,
                                              max_depth=6, random_state=0)
            m.fit(np.clip((M[itr] - med) / sc, -5, 5), ret[itr])
            pr = m.predict(np.clip((M[ite] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": tab.date.to_numpy()[ite], "p": pr,
                              "r": ret[ite]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(1)
            out[name].append(float(pick.r.mean()) - COST)
        print(f"  block {b0:%Y-%m} done", flush=True)
    a = np.array(out["price only"])
    b = np.array(out["+ ramanujan"])
    print(f"\n  price only   {a.mean() * 100:+7.3f}% per trade over {len(a)} blocks")
    print(f"  + ramanujan  {b.mean() * 100:+7.3f}%")
    dl = b - a
    rng = np.random.default_rng(5)
    bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
    los, his = np.percentile(bs, [2.5, 97.5])
    print(f"  delta {dl.mean() * 100:+.3f}pp   95% CI [{los * 100:+.3f}, "
          f"{his * 100:+.3f}]   P(<=0) = {(bs <= 0).mean():.4f}")
    print(f"  {'PASS' if dl.mean() > 0.0025 and los > 0 else 'FAIL'}")

    # ---- 3. the tipping point -------------------------------------------
    print("\n" + "=" * 100)
    print("3. TIPPING POINT -- does criticality beat volatility on |move|>=20%?")
    print("=" * 100)
    big = (np.abs(ret) >= 0.20).astype(int)
    print(f"  {big.mean() * 100:.2f}% of candidates move 20% or more in {HORIZON} sessions")
    cands = {"vol_20d (baseline)": vol,
             "ram_c_max": Rp[:, rcols.index("ram_c_max")],
             "ram_c_ratio": Rp[:, rcols.index("ram_c_ratio")],
             "ram_hr_ent": Rp[:, rcols.index("ram_hr_ent")],
             "ram_part_frac": Rp[:, rcols.index("ram_part_frac")],
             "ram_shanks_gap": np.abs(Rp[:, rcols.index("ram_shanks_gap")])}
    base = None
    for name, v in cands.items():
        v = np.nan_to_num(v, nan=0.0, posinf=0.0, neginf=0.0)
        a_ = auc(big[te], v[te])
        a_ = max(a_, 1 - a_)
        if base is None:
            base = a_
        flag = ""
        if name != "vol_20d (baseline)":
            flag = "  BEATS VOL" if a_ > base else ""
        print(f"  {name:22s} AUC {a_:.4f}{flag}")
    print(f"\n  {'PASS' if any(True for _ in []) else 'see above'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
