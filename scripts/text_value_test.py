"""Does knowing what the filing said actually help?

`RESULT_WHY_LOSERS.md` put a number on the ceiling of the existing inputs: a
classifier separating winning picks from losing ones reached **0.5302** out of
sample on 108 numeric features. If catalyst text carries information the panel
did not have, that number should move. If it does not move, text is not the
missing piece and the search continues elsewhere.

The comparison is like-for-like or it is worthless
--------------------------------------------------
Text covers 70 tickers out of 3,662. Comparing a text model on those 70 against
a no-text model on all 3,662 would compare universes, not feature sets. So
**every arm runs on exactly the same covered rows**, and the only thing that
changes between arms is which columns the model may look at:

* ``price only``  the original 108 features
* ``+ text``      those plus the 96 text columns
* ``text only``   the text columns alone, to see whether they stand up unaided

Two questions, because they are not the same question
-----------------------------------------------------
1. **Ranking.** Does adding text improve the walk-forward return of the daily
   top pick? This is what the account cares about.
2. **Separability.** Does it move the win-versus-lose AUC off 0.53? This is the
   diagnostic that said the features were exhausted, and it is the cleaner test
   because it is not mediated by a selection rule.

Seventy tickers is a small universe and the confidence intervals will be wide.
That is a real limit of a 10% sample and is reported rather than hidden.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import META, SEQ_LEN, auc  # noqa: E402
from exit_rules import walk  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
BLOCK_MONTHS = 6
FIRST_TEST = "2019-01-01"
VOL_FLOOR = 0.01

TEXT_MARKERS = ("cat_", "tox_", "tone_", "binding", "nonbinding", "txt_",
                "log_value", "log_deal_value", "has_deal_value", "text_days_since",
                "has_text", "n_filings")


def is_text_col(c: str) -> bool:
    return any(c.startswith(m) or c == m for m in TEXT_MARKERS)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--quantile", type=float, default=0.75)
    args = ap.parse_args(argv)
    root = Path(args.root)

    import pyarrow.parquet as pq
    from sklearn.ensemble import (HistGradientBoostingClassifier,
                                  HistGradientBoostingRegressor)

    path = root / "adrnn_panel_text.parquet"
    all_cols = [f.name for f in pq.ParquetFile(path).schema_arrow]
    feats = [c for c in all_cols if c not in META]
    text_cols = [c for c in feats if is_text_col(c)]
    base_cols = [c for c in feats if not is_text_col(c)]
    print(f"{len(base_cols)} price/filing features, {len(text_cols)} text features")

    # Only 1.8% of the panel has text, so reading all 8M rows by 210 columns
    # into pandas is both wasteful and fatal -- it is roughly thirteen gigabytes
    # and gets the process killed. Scan in arrow batches, keep only covered
    # rows, and carry the absolute row index so the price walk still lines up.
    keep = ["ticker", "date", "eligible", "has_text", "vol_20d"] + feats
    keep = list(dict.fromkeys(keep))
    src = pq.ParquetFile(path)
    parts, offsets, off = [], [], 0
    for batch in src.iter_batches(batch_size=500_000, columns=keep):
        b = batch.to_pandas()
        idx = np.arange(off, off + len(b))
        m = (b["has_text"].to_numpy() > 0) & b["eligible"].to_numpy(dtype=bool)
        if m.any():
            parts.append(b.loc[m])
            offsets.append(idx[m])
        off += len(b)
    t = pd.concat(parts, ignore_index=True)
    abs_row = np.concatenate(offsets)
    t["date"] = pd.to_datetime(t["date"])
    print(f"covered eligible rows {len(t):,} on {t.ticker.nunique()} tickers")

    # Panel order is (ticker, date); row i in the panel is row i in prices.
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)
    assert len(prices) == off, "panel/prices length mismatch"
    chk = min(2000, len(t))
    assert (prices["ticker"].to_numpy()[abs_row[:chk]] == t["ticker"].to_numpy()[:chk]).all(), \
        "panel and price rows are not aligned"

    sel = np.arange(len(t))[:: args.stride]
    t = t.iloc[sel].reset_index(drop=True)
    rows = abs_row[sel]
    print(f"{len(rows):,} samples after stride {args.stride}")

    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    l = prices["low"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    pt = prices["ticker"].to_numpy()
    ret = np.full(len(rows), np.nan)
    for a, i in enumerate(rows):
        r, _, _ = walk(o, h, l, c, v, pt, int(i) + 1, HORIZON,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            ret[a] = r
    good = np.isfinite(ret)
    ret = ret[good]
    print(f"{int(good.sum()):,} with a realised return\n")

    dates = t["date"].to_numpy()[good]
    vol = t["vol_20d"].to_numpy()[good]
    Xall = {c: t[c].to_numpy(dtype=np.float32)[good] for c in feats}
    del t, parts

    def mat(cols):
        return np.nan_to_num(np.column_stack([Xall[c] for c in cols]),
                             nan=0.0, posinf=0.0, neginf=0.0)

    ARMS = {"price only": base_cols,
            "+ text": base_cols + text_cols,
            "text only": text_cols}

    def blocks():
        out, cur = [], pd.Timestamp(FIRST_TEST)
        hi = pd.Timestamp(dates.max())
        while cur < hi:
            nxt = cur + pd.DateOffset(months=BLOCK_MONTHS)
            out.append((cur, min(nxt, hi + pd.Timedelta(days=1))))
            cur = nxt
        return out

    # ---------------- 1. ranking ---------------------------------------
    print("=" * 96)
    print("1. RANKING -- walk-forward, daily top pick, same rows for every arm")
    print("=" * 96)
    res = {k: [] for k in ARMS}
    y_sharpe = ret / np.maximum(vol, VOL_FLOOR)
    for b0, b1 in blocks():
        tr = np.flatnonzero(dates < np.datetime64(b0 - pd.Timedelta(days=14)))
        te = np.flatnonzero((dates >= np.datetime64(b0)) & (dates < np.datetime64(b1)))
        if len(tr) < 3000 or len(te) < 200:
            continue
        uni = float(ret[te].mean())
        for name, cols in ARMS.items():
            X = mat(cols)
            med = np.median(X[tr], axis=0)
            q1, q3 = np.percentile(X[tr], [25, 75], axis=0)
            sc = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
            m = HistGradientBoostingRegressor(loss="quantile",
                                              quantile=args.quantile,
                                              max_iter=250, learning_rate=0.05,
                                              max_depth=6, random_state=0)
            m.fit(np.clip((X[tr] - med) / sc, -5, 5), y_sharpe[tr])
            p = m.predict(np.clip((X[te] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": dates[te], "p": p, "r": ret[te]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(1)
            res[name].append({"block": f"{b0:%Y-%m}", "n": len(pick),
                              "ret": float(pick.r.mean()) - COST,
                              "excess": float(pick.r.mean()) - COST - uni})
    for name in ARMS:
        r = pd.DataFrame(res[name])
        if r.empty:
            continue
        ex = r.excess.to_numpy()
        print(f"  {name:12s} ret/trade {r.ret.mean() * 100:+7.3f}%   "
              f"excess {ex.mean() * 100:+7.3f}%   "
              f"blocks {int((ex > 0).sum())}/{len(r)}   "
              f"IR {ex.mean() / ex.std():5.2f}" if ex.std() > 0 else "")
    a, b = pd.DataFrame(res["price only"]), pd.DataFrame(res["+ text"])
    if not a.empty and not b.empty:
        d = b.excess.to_numpy() - a.excess.to_numpy()
        rng = np.random.default_rng(97)
        bs = np.array([rng.choice(d, len(d), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"\n  text minus no-text, per block: {d.mean() * 100:+.3f}pp   "
              f"95% CI [{lo * 100:+.3f}, {hi * 100:+.3f}]   "
              f"P(<=0) = {(bs <= 0).mean():.4f}")

    # ---------------- 2. separability ----------------------------------
    print("\n" + "=" * 96)
    print("2. SEPARABILITY -- can winners be told from losers? (0.5302 was the "
          "no-text number)")
    print("=" * 96)
    y = (ret - COST > 0).astype(int)
    order = np.argsort(dates, kind="stable")
    cut = int(len(order) * 0.6)
    tr, te = order[:cut], order[cut:]
    for name, cols in ARMS.items():
        X = mat(cols)
        med = np.median(X[tr], axis=0)
        q1, q3 = np.percentile(X[tr], [25, 75], axis=0)
        sc = np.where((q3 - q1) > 1e-8, (q3 - q1) / 1.349, 1.0)
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             max_depth=4, random_state=0)
        clf.fit(np.clip((X[tr] - med) / sc, -5, 5), y[tr])
        p = clf.predict_proba(np.clip((X[te] - med) / sc, -5, 5))[:, 1]
        print(f"  {name:12s} out-of-sample AUC {auc(y[te], p):.4f}")
    print("\n  (this arm uses all eligible covered rows, not only picks, so it is")
    print("   not numerically identical to the 0.5302 -- the comparison that")
    print("   matters is price-only against +text on these same rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
