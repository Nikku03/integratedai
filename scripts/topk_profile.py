"""Profile the daily top-k picks: how often, how big, how fast, which way.

``RESULT_ADRNN.md`` reported hit rates for the daily top-k. That answers "does
it fire" and nothing else. A shortlist is only usable if you also know how large
the move is, **how long you wait for it**, and which direction it breaks -- and
the waiting time has never been measured anywhere in this project.

Timing is computed from the price panel rather than the label, because the label
only records the extreme over the whole ten-day window and says nothing about
when it arrived. A signal whose median move lands on day 9 is a different
instrument from one that lands on day 2: it ties up a slot five times longer for
the same payoff, and it is exposed to five times as much unrelated news.

Confidence is the model's own predicted probability. Ranking by it and then
checking whether the top-ranked names really do fire more often is a calibration
test, and calibration is where boosted trees on an imbalanced label usually
fall over.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

HORIZON = 10
THRESH = 0.20


def forward_timing(prices: pd.DataFrame, rows: np.ndarray) -> pd.DataFrame:
    """Days until the first +/-20% touch, and the day of the largest excursion.

    ``rows`` index the price panel directly: ``adrnn_dataset`` writes its panel
    from the same (ticker, date)-sorted frame, so row i is the same observation
    in both. The alignment is asserted by the caller rather than assumed.
    """
    o = prices["open"].to_numpy(dtype=np.float64)
    h = prices["high"].to_numpy(dtype=np.float64)
    l = prices["low"].to_numpy(dtype=np.float64)
    tick = prices["ticker"].to_numpy()

    n = len(rows)
    out = {k: np.full(n, np.nan) for k in
           ("entry", "t_up", "t_dn", "t_hit", "t_maxexc", "max_up", "max_dn")}

    for a, i in enumerate(rows):
        j0 = i + 1
        if j0 >= len(o) or tick[j0] != tick[i]:
            continue
        e = o[j0]
        if not np.isfinite(e) or e <= 0:
            continue
        out["entry"][a] = e
        best_exc, best_j = -1.0, np.nan
        t_up = t_dn = np.nan
        mu, md = -np.inf, np.inf
        for step in range(HORIZON):
            j = j0 + step
            if j >= len(o) or tick[j] != tick[i]:
                break
            up = h[j] / e - 1.0
            dn = l[j] / e - 1.0
            if np.isfinite(up):
                mu = max(mu, up)
                if np.isnan(t_up) and up >= THRESH:
                    t_up = step + 1
            if np.isfinite(dn):
                md = min(md, dn)
                if np.isnan(t_dn) and dn <= -THRESH:
                    t_dn = step + 1
            exc = max(abs(up) if np.isfinite(up) else 0.0,
                      abs(dn) if np.isfinite(dn) else 0.0)
            if exc > best_exc:
                best_exc, best_j = exc, step + 1
        out["max_up"][a] = mu if np.isfinite(mu) else np.nan
        out["max_dn"][a] = md if np.isfinite(md) else np.nan
        out["t_up"][a] = t_up
        out["t_dn"][a] = t_dn
        out["t_maxexc"][a] = best_j
        cand = [t for t in (t_up, t_dn) if not np.isnan(t)]
        out["t_hit"][a] = min(cand) if cand else np.nan
    return pd.DataFrame(out)


def profile(d: pd.DataFrame, k: int | None, score: str) -> dict:
    """One row of the summary table for the daily top-k by ``score``."""
    if k is None:
        s = d
        label = "all"
    else:
        # A day offering fewer than k candidates cannot support a top-k;
        # including it would quietly report the base rate as precision.
        big = d.groupby("date")["y_mag"].transform("size") >= k
        s = (d[big].sort_values(score, ascending=False)
                   .groupby("date").head(k))
        label = f"top {k}"
    if s.empty:
        return {"pick": label, "n": 0}

    up20 = s.max_up >= THRESH
    dn20 = s.max_dn <= -THRESH
    both = up20 & dn20
    return {
        "pick": label,
        "days": int(s.date.nunique()),
        "n": int(len(s)),
        "conf": float(s[score].mean()),
        "hit%": float(s.y_mag.mean() * 100),
        "up20%": float(up20.mean() * 100),
        "dn20%": float(dn20.mean() * 100),
        "both%": float(both.mean() * 100),
        "med_up%": float(s.max_up.median() * 100),
        "med_dn%": float(s.max_dn.median() * 100),
        "mean_mag%": float(np.maximum(s.max_up, -s.max_dn).mean() * 100),
        "med_t_hit": float(s.t_hit.median()),
        "med_t_up": float(s.t_up.median()),
        "med_t_dn": float(s.t_dn.median()),
        "med_t_max": float(s.t_maxexc.median()),
        "med_px": float(np.exp(s.log_price.median())),
        "med_vol%": float(s.vol_20d.median() * 100),
        "med_adv_m": float(s.adv_usd.median() / 1e6),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--score", default="s_gb", choices=["s_gb", "s_mag", "s_vol"])
    args = ap.parse_args(argv)
    root = Path(args.root)

    import pyarrow.parquet as pq
    z = np.load(root / "adrnn_test_scores.npz")
    idx = z["idx"]

    meta = pq.read_table(root / "adrnn_panel.parquet",
                         columns=["ticker", "date", "log_price", "vol_20d",
                                  "adv_usd", "y_mag", "y_dir"]).to_pandas()
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    assert len(prices) == len(meta), "panel and prices differ in length"
    same = ((prices["ticker"].to_numpy()[idx[:5000]] == meta["ticker"].to_numpy()[idx[:5000]])
            & (prices["date"].to_numpy()[idx[:5000]] == meta["date"].to_numpy()[idx[:5000]]))
    assert same.all(), "panel and price rows are not aligned"
    print(f"alignment verified on {len(idx):,} test rows")

    print("computing forward timing from prices", flush=True)
    t = forward_timing(prices, idx)

    d = meta.iloc[idx].reset_index(drop=True)
    d["date"] = pd.to_datetime(d["date"])
    for c in t.columns:
        d[c] = t[c].to_numpy()
    d["s_gb"] = z["s_gb"]
    d["s_mag"] = z["s_mag"]
    d["s_vol"] = z["s_vol"]
    d["s_dir"] = z["s_dir"]
    d = d[d.entry.notna()].copy()
    print(f"{len(d):,} rows with a fillable next-day open, "
          f"{d.date.nunique()} sessions\n")

    rows = [profile(d, k, args.score) for k in (1, 2, 3, 5, 10, 20, None)]
    out = pd.DataFrame(rows)

    print("=" * 100)
    print(f"DAILY TOP-K BY CONFIDENCE ({args.score}) -- hit rate and size")
    print("=" * 100)
    a = out[["pick", "days", "n", "conf", "hit%", "up20%", "dn20%", "both%",
             "med_up%", "med_dn%", "mean_mag%"]].copy()
    for c in a.columns:
        if c not in ("pick", "days", "n"):
            a[c] = a[c].round(2)
    print(a.to_string(index=False))

    print("\n" + "=" * 100)
    print("TIMING -- trading days from entry (median)")
    print("=" * 100)
    b = out[["pick", "n", "med_t_hit", "med_t_up", "med_t_dn", "med_t_max",
             "med_px", "med_vol%", "med_adv_m"]].copy()
    for c in b.columns:
        if c not in ("pick", "n"):
            b[c] = b[c].round(2)
    print(b.to_string(index=False))
    print("\n  med_t_hit  sessions to the first +/-20% touch, when there is one")
    print("  med_t_up   sessions to the first +20%;  med_t_dn to the first -20%")
    print("  med_t_max  session carrying the largest excursion")

    print("\n" + "=" * 100)
    print("CALIBRATION -- does a higher score really mean a higher chance?")
    print("=" * 100)
    q = pd.qcut(d[args.score].rank(method="first"), 10, labels=False)
    cal = (d.assign(q=q).groupby("q")
             .agg(n=("y_mag", "size"), mean_conf=(args.score, "mean"),
                  actual=("y_mag", "mean"), mag=("max_up", "median")))
    cal["mean_conf"] = (cal.mean_conf * 100).round(1)
    cal["actual"] = (cal.actual * 100).round(1)
    cal["gap"] = (cal.actual - cal.mean_conf).round(1)
    cal["mag"] = (cal.mag * 100).round(1)
    print(cal.to_string())

    print("\n" + "=" * 100)
    print("DIRECTION WITHIN THE TOP 5 -- the question the model cannot answer")
    print("=" * 100)
    big = d.groupby("date")["y_mag"].transform("size") >= 5
    t5 = d[big].sort_values(args.score, ascending=False).groupby("date").head(5)
    fired = t5[t5.y_mag == 1]
    print(f"  of {len(fired):,} top-5 picks that moved >=20%: "
          f"{(fired.max_up >= -fired.max_dn).mean() * 100:.1f}% broke up")
    print(f"  mean max_up {fired.max_up.mean() * 100:+.1f}%   "
          f"mean max_dn {fired.max_dn.mean() * 100:+.1f}%")
    hi = fired[fired.s_dir >= fired.s_dir.median()]
    lo = fired[fired.s_dir < fired.s_dir.median()]
    print(f"  direction head, upper half: {(hi.max_up >= -hi.max_dn).mean() * 100:.1f}% up "
          f"| lower half: {(lo.max_up >= -lo.max_dn).mean() * 100:.1f}% up")

    d.to_parquet(root / "topk_profile.parquet")
    out.to_csv(root / "topk_summary.csv", index=False)
    print("\nSurvivorship: this panel has zero delistings, so every rate above "
          "is optimistic\nand the up/down split most of all. See "
          "delisting_universe.py for the size of it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
