"""Why the model can see crashes coming and not rallies.

The directional test was unambiguous: the DOWN model's top pick hits -20% 67.1%
of the time, while the UP model's top pick hits -20% *more often* than +20%.
That asymmetry is large and stable, so it has a cause worth finding rather than
apologising for.

Four candidate explanations, each with a test that can kill it:

**H1 -- up arrives as a gap, down arrives as a grind.** A crash is often the
visible end of a deterioration that took weeks; a rally is usually an
announcement. Anything delivered as an overnight jump is unpredictable by
construction, because the information did not exist at the previous close. Test:
decompose each move into overnight and intraday components and compare.

**H2 -- the features only measure distress.** Burn, runway, dilution, insider
selling, falling price, rising volatility. Almost every feature in the panel is
a symptom of trouble. There is nearly nothing that could indicate *impending
good news*, because good news is exogenous. Test: permutation importance for the
two models, and whether they lean on the same columns.

**H3 -- the leverage effect.** Volatility and returns are negatively correlated
as a matter of long-standing empirical fact, so any model that selects on
volatility inherits a short bias for free. Test: forward return by volatility
decile.

**H4 -- the two models are the same model.** If UP and DOWN rank names almost
identically, there is one signal here, not two, and it points down. Test: rank
correlation and overlap of their daily shortlists.

H1 is the one that matters. If up-moves are concentrated in overnight gaps then
no feature set fixes this, and the correct conclusion is that the target was
never predictable in the first place.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import auc, build_arrays, robust_scaler, split_idx  # noqa: E402

THRESH = 0.20
HORIZON = 10


def decompose(prices: pd.DataFrame, rows: np.ndarray) -> pd.DataFrame:
    """Split each forward move into overnight-gap and intraday components.

    For every observation, walk the ten sessions after entry and accumulate the
    two channels separately:

        gap[j]      = open[j]  / close[j-1] - 1     (information arriving while
                                                     the market was shut)
        intraday[j] = close[j] / open[j]    - 1     (information arriving, or
                                                     being traded, during hours)

    The question is which channel carries the extreme. A move that lives in the
    gap channel cannot be forecast from the previous close, because whatever
    caused it had not happened yet.
    """
    o = prices["open"].to_numpy(dtype=np.float64)
    c = prices["close"].to_numpy(dtype=np.float64)
    h = prices["high"].to_numpy(dtype=np.float64)
    l = prices["low"].to_numpy(dtype=np.float64)
    tick = prices["ticker"].to_numpy()

    n = len(rows)
    out = {k: np.full(n, np.nan) for k in
           ("gap_sum", "intra_sum", "max_1d_gap", "max_1d_intra",
            "best_day_share", "n_days_to_ext", "max_up", "max_dn", "ret10")}

    for a, i in enumerate(rows):
        j0 = i + 1
        if j0 >= len(o) or tick[j0] != tick[i]:
            continue
        e = o[j0]
        if not (np.isfinite(e) and e > 0):
            continue
        gaps, intras, days = [], [], []
        mu, md = -np.inf, np.inf
        ext_day, ext_val = np.nan, 0.0
        last_c = np.nan
        for step in range(HORIZON):
            j = j0 + step
            if j >= len(o) or tick[j] != tick[i]:
                break
            prev_c = c[j - 1] if (j - 1) >= 0 and tick[j - 1] == tick[i] else np.nan
            if np.isfinite(prev_c) and prev_c > 0 and np.isfinite(o[j]):
                gaps.append(o[j] / prev_c - 1.0)
            if np.isfinite(o[j]) and o[j] > 0 and np.isfinite(c[j]):
                intras.append(c[j] / o[j] - 1.0)
            if np.isfinite(prev_c) and prev_c > 0 and np.isfinite(c[j]):
                days.append(c[j] / prev_c - 1.0)
            if np.isfinite(h[j]):
                mu = max(mu, h[j] / e - 1.0)
            if np.isfinite(l[j]):
                md = min(md, l[j] / e - 1.0)
            if np.isfinite(c[j]):
                last_c = c[j]
            cur = max(abs(h[j] / e - 1.0) if np.isfinite(h[j]) else 0.0,
                      abs(l[j] / e - 1.0) if np.isfinite(l[j]) else 0.0)
            if cur > ext_val:
                ext_val, ext_day = cur, step + 1
        if not days:
            continue
        out["gap_sum"][a] = float(np.nansum(gaps))
        out["intra_sum"][a] = float(np.nansum(intras))
        out["max_1d_gap"][a] = float(np.nanmax(np.abs(gaps))) if gaps else np.nan
        out["max_1d_intra"][a] = float(np.nanmax(np.abs(intras))) if intras else np.nan
        tot = float(np.nansum(np.abs(days)))
        out["best_day_share"][a] = (float(np.nanmax(np.abs(days))) / tot
                                    if tot > 0 else np.nan)
        out["n_days_to_ext"][a] = ext_day
        out["max_up"][a] = mu if np.isfinite(mu) else np.nan
        out["max_dn"][a] = md if np.isfinite(md) else np.nan
        out["ret10"][a] = last_c / e - 1.0 if np.isfinite(last_c) else np.nan
    return pd.DataFrame(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--max-train", type=int, default=150_000)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import pyarrow.parquet as pq
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    lab = pq.read_table(root / "adrnn_panel.parquet",
                        columns=["max_up", "max_dn"]).to_pandas()
    mu_all = lab["max_up"].to_numpy(dtype=np.float64)
    md_all = lab["max_dn"].to_numpy(dtype=np.float64)
    y_up = (mu_all >= THRESH).astype(np.float32)
    y_dn = (md_all <= -THRESH).astype(np.float32)
    tr, va, te = split_idx(d, idx)
    if len(tr) > args.max_train:
        tr = tr[np.linspace(0, len(tr) - 1, args.max_train).astype(int)]
    med, scale = robust_scaler(X, tr)

    def flat(rows):
        return (X[rows] - med) / scale

    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low", "close"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    # ==================================================================
    print("=" * 88)
    print("H1  DOES 'UP' ARRIVE AS A GAP AND 'DOWN' AS A GRIND?")
    print("=" * 88)
    sub = te[np.linspace(0, len(te) - 1, min(30000, len(te))).astype(int)]
    dec = decompose(prices, sub)
    dec["is_up"] = y_up[sub] == 1
    dec["is_dn"] = y_dn[sub] == 1
    g = dec[dec.is_up & ~dec.is_dn]
    b = dec[dec.is_dn & ~dec.is_up]
    print(f"  clean up-moves {len(g):,}   clean down-moves {len(b):,}   "
          f"(both-ways excluded)")
    print(f"\n  {'':28s} {'UP moves':>12s} {'DOWN moves':>12s}")
    for lab_, col in (("sum of overnight gaps", "gap_sum"),
                      ("sum of intraday moves", "intra_sum"),
                      ("largest 1-day gap |x|", "max_1d_gap"),
                      ("largest 1-day intraday |x|", "max_1d_intra"),
                      ("biggest day / total move", "best_day_share"),
                      ("sessions to the extreme", "n_days_to_ext")):
        f = 100 if col != "n_days_to_ext" else 1
        u = g[col].median() * f
        dn = b[col].median() * f
        unit = "%" if f == 100 else ""
        print(f"  {lab_:28s} {u:11.2f}{unit} {dn:11.2f}{unit}")

    share_u = (g.gap_sum.abs() / (g.gap_sum.abs() + g.intra_sum.abs())).median()
    share_d = (b.gap_sum.abs() / (b.gap_sum.abs() + b.intra_sum.abs())).median()
    print(f"\n  share of the move carried by OVERNIGHT GAPS:")
    print(f"    up-moves   {share_u * 100:.1f}%")
    print(f"    down-moves {share_d * 100:.1f}%")
    print(f"  one-day concentration (biggest day as a share of total travel):")
    print(f"    up-moves   {g.best_day_share.median() * 100:.1f}%")
    print(f"    down-moves {b.best_day_share.median() * 100:.1f}%")
    print("\n  A move delivered overnight cannot be forecast from the prior close:")
    print("  whatever caused it had not happened yet.")

    # ==================================================================
    print("\n" + "=" * 88)
    print("H2  DO THE TWO MODELS LEAN ON THE SAME FEATURES?")
    print("=" * 88)
    imps = {}
    models = {}
    for nm, y in (("UP", y_up), ("DOWN", y_dn)):
        m = HistGradientBoostingClassifier(max_iter=150, learning_rate=0.06,
                                           max_depth=6, random_state=0)
        m.fit(flat(tr), y[tr])
        models[nm] = m
        ev = te[np.linspace(0, len(te) - 1, min(12000, len(te))).astype(int)]
        r = permutation_importance(m, flat(ev), y[ev], n_repeats=3,
                                   random_state=0, scoring="roc_auc", n_jobs=2)
        imps[nm] = pd.Series(r.importances_mean, index=feats)
        print(f"\n  {nm} model, top 12 features by permutation AUC drop:")
        for k, v in imps[nm].nlargest(12).items():
            print(f"    {k:24s} {v:+.4f}")

    common = set(imps["UP"].nlargest(15).index) & set(imps["DOWN"].nlargest(15).index)
    print(f"\n  overlap of the two top-15 lists: {len(common)}/15 -> "
          f"{sorted(common)}")

    # ==================================================================
    print("\n" + "=" * 88)
    print("H3  THE LEVERAGE EFFECT -- does volatility itself lean short?")
    print("=" * 88)
    full = decompose(prices, sub)
    vi = feats.index("vol_20d")
    v = X[sub, vi]
    q = pd.qcut(pd.Series(v).rank(method="first"), 10, labels=False)
    t = pd.DataFrame({"q": q, "ret": full.ret10, "up": y_up[sub], "dn": y_dn[sub],
                      "vol": v}).dropna()
    tab = t.groupby("q").agg(n=("ret", "size"), vol=("vol", "median"),
                             mean_ret=("ret", "mean"), med_ret=("ret", "median"),
                             p_up=("up", "mean"), p_dn=("dn", "mean"))
    tab["vol"] = (tab.vol * 100).round(2)
    for c in ("mean_ret", "med_ret", "p_up", "p_dn"):
        tab[c] = (tab[c] * 100).round(2)
    tab["up_minus_dn"] = (tab.p_up - tab.p_dn).round(2)
    print(tab.to_string())
    print("\n  If the top volatility decile has p_dn > p_up and a negative mean")
    print("  return, then selecting on volatility is selecting a short, and any")
    print("  'up' model built on these features inherits that.")

    # ==================================================================
    print("\n" + "=" * 88)
    print("H4  ARE THE UP AND DOWN MODELS ACTUALLY THE SAME MODEL?")
    print("=" * 88)
    su = models["UP"].predict_proba(flat(te))[:, 1]
    sd = models["DOWN"].predict_proba(flat(te))[:, 1]
    rho = pd.Series(su).corr(pd.Series(sd), method="spearman")
    print(f"  rank correlation of the two scores: rho = {rho:.4f}")
    dd = pd.DataFrame({"date": pd.to_datetime(d["date"].to_numpy()[te]),
                       "su": su, "sd": sd})
    ov = []
    for _, s in dd.groupby("date"):
        if len(s) < 5:
            continue
        a = set(s.nlargest(5, "su").index)
        bset = set(s.nlargest(5, "sd").index)
        ov.append(len(a & bset) / 5)
    print(f"  daily top-5 overlap: {np.mean(ov) * 100:.1f}% of names appear on "
          f"both lists")
    print(f"  AUC of the UP score on the DOWN label: {auc(y_dn[te], su):.4f}")
    print(f"  AUC of the DOWN score on the UP label: {auc(y_up[te], sd):.4f}")
    print("\n  Near-identical rankings mean there is one signal here, not two.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
