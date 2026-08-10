"""Anatomy of the +50% and +100% touches: what is kept, and who pays for it.

Two numbers were reported without enough scrutiny: conditional on touching +50%
in ten sessions the mean realised return is +44.94%, and on +100% it is +78.07%.
A mean that close to the barrier implies almost no give-back, which is not how
spikes in small caps usually behave, so it is worth taking apart.

Three things it could be, and they have different consequences:

1. **Genuinely sticky moves.** The touch happens and the price holds. Then the
   number means what it appears to.
2. **A few enormous winners dragging the mean.** Most touchers give it all back
   and a handful go to +300%. Then the mean is real but the *median* trade is
   not, and the strategy needs to survive long dry spells to collect.
3. **A selection artifact.** `max_up >= 50%` conditions on the whole ten-session
   window, so a name that touches on day 9 has had no time to give anything back
   before the window closes and its realised return is measured.

The median and the capture ratio separate these. Capture is
`realised / max_up` -- of the move that was available, how much did a
buy-and-hold-to-day-10 position actually keep.

The number that matters for a small account is the last section: **how much of
the strategy's return comes from the moonshots**. If nearly all of it does, the
book is a lottery and the dry spells decide whether you are still solvent when
one lands.
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
from moonshot_tail import blocks, scale_fit  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4


def forward_detail(prices, rows):
    """Realised return, best excursion, and the session the touch happened."""
    o = prices["open"].to_numpy(float)
    h = prices["high"].to_numpy(float)
    c = prices["close"].to_numpy(float)
    v = np.nan_to_num(prices["volume"].to_numpy(float), nan=0.0)
    l = prices["low"].to_numpy(float)
    tick = prices["ticker"].to_numpy()
    n = len(rows)
    ret = np.full(n, np.nan)
    mup = np.full(n, np.nan)
    t50 = np.full(n, np.nan)
    t_peak = np.full(n, np.nan)
    for a, i in enumerate(rows):
        r, _, _ = walk(o, h, l, c, v, tick, int(i) + 1, HORIZON,
                       None, None, None, None, None)
        if np.isfinite(r) and abs(r) <= 3.0:
            ret[a] = r
        j0 = int(i) + 1
        if j0 >= len(o) or tick[j0] != tick[i]:
            continue
        e = o[j0]
        if not (np.isfinite(e) and e > 0):
            continue
        best, bj = -np.inf, np.nan
        for step in range(HORIZON):
            j = j0 + step
            if j >= len(o) or tick[j] != tick[i]:
                break
            if np.isfinite(h[j]):
                up = h[j] / e - 1.0
                if up > best:
                    best, bj = up, step + 1
                if np.isnan(t50[a]) and up >= 0.50:
                    t50[a] = step + 1
        if np.isfinite(best) and best <= 5.0:
            mup[a] = best
            t_peak[a] = bj
    return ret, mup, t50, t_peak


def dist(s: pd.Series, label: str) -> dict:
    return {"bucket": label, "n": len(s),
            "mean%": s.mean() * 100, "median%": s.median() * 100,
            "p25%": s.quantile(.25) * 100, "p75%": s.quantile(.75) * 100,
            "p90%": s.quantile(.90) * 100,
            "neg%": (s < 0).mean() * 100}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=10)
    ap.add_argument("--quantile", type=float, default=0.75)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import HistGradientBoostingRegressor

    d, X, feats, idx = build_arrays(root / "adrnn_panel.parquet", args.stride)
    prices = pd.read_parquet(root / "w2015_prices.parquet",
                             columns=["date", "ticker", "open", "high", "low",
                                      "close", "volume"])
    prices["date"] = pd.to_datetime(prices["date"])
    prices = prices.sort_values(["ticker", "date"]).reset_index(drop=True)

    print("computing forward detail", flush=True)
    ret, mup, t50, tpk = forward_detail(prices, idx)
    vi = feats.index("vol_20d")
    vol = X[idx, vi]
    ok = np.isfinite(ret) & np.isfinite(mup) & np.isfinite(vol) & (vol > 0)
    tab = pd.DataFrame({
        "row": idx, "date": pd.to_datetime(d["date"].to_numpy()[idx]),
        "ticker": d["ticker"].to_numpy()[idx], "vol": vol,
        "ret": ret, "mup": mup, "t50": t50, "t_peak": tpk})[ok].reset_index(drop=True)
    Xs = X[tab.row.to_numpy()]
    print(f"  {len(tab):,} rows\n")

    # ------------------------------------------------------------------
    print("=" * 100)
    print("1. WHAT A TOUCH IS ACTUALLY WORTH (whole universe, not tradeable "
          "-- descriptive only)")
    print("=" * 100)
    rows = []
    for lo, hi, lab in ((0.20, 0.35, "touched 20-35%"),
                        (0.35, 0.50, "touched 35-50%"),
                        (0.50, 1.00, "touched 50-100%"),
                        (1.00, 99.0, "touched 100%+")):
        s = tab[(tab.mup >= lo) & (tab.mup < hi)]
        if len(s) > 20:
            rows.append(dist(s.ret, lab))
    for lo, lab in ((0.20, "touched >=20% (cumulative)"),
                    (0.50, "touched >=50% (cumulative)"),
                    (1.00, "touched >=100% (cumulative)")):
        s = tab[tab.mup >= lo]
        if len(s) > 20:
            rows.append(dist(s.ret, lab))
    r = pd.DataFrame(rows)
    print(r.round(2).to_string(index=False))
    print("\n  The cumulative rows are the ones quoted earlier. Note how far the")
    print("  mean sits above the median in every bucket.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("2. CAPTURE -- of the move that was available, how much is kept to day 10")
    print("=" * 100)
    for lo, lab in ((0.20, ">=20%"), (0.35, ">=35%"), (0.50, ">=50%"), (1.00, ">=100%")):
        s = tab[tab.mup >= lo]
        if len(s) < 20:
            continue
        cap = (s.ret / s.mup).clip(-2, 2)
        print(f"  touched {lab:6s} n={len(s):6,}  capture: median "
              f"{cap.median() * 100:5.1f}%   mean {cap.mean() * 100:5.1f}%   "
              f"share closing below entry {(s.ret < 0).mean() * 100:4.1f}%   "
              f"median touch on session {s.t_peak.median():.0f}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("3. THE SAME NUMBERS FOR THE MODEL'S OWN PICKS (tradeable)")
    print("=" * 100)
    picks = []
    for b0, b1 in blocks(tab.date.max()):
        tr = np.flatnonzero(tab.date < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((tab.date >= b0) & (tab.date < b1))
        if len(tr) < 40_000 or len(te) < 500:
            continue
        if len(tr) > 150_000:
            tr = tr[np.linspace(0, len(tr) - 1, 150_000).astype(int)]
        med, sc = scale_fit(Xs[tr])
        m = HistGradientBoostingRegressor(loss="quantile", quantile=args.quantile,
                                          max_iter=250, learning_rate=0.05,
                                          max_depth=6, random_state=0)
        m.fit(np.clip((Xs[tr] - med) / sc, -5, 5), tab.ret.to_numpy()[tr])
        sub = tab.iloc[te].assign(
            pred=m.predict(np.clip((Xs[te] - med) / sc, -5, 5)))
        picks.append(sub.sort_values("pred", ascending=False)
                        .groupby("date").head(1).assign(block=f"{b0:%Y-%m}"))
    p = pd.concat(picks).reset_index(drop=True)
    p["net"] = p.ret - COST
    print(f"  q{args.quantile:.2f} model, one pick a day, {len(p):,} trades over "
          f"{p.block.nunique()} blocks")
    print(f"  mean {p.net.mean() * 100:+.3f}%   median {p.net.median() * 100:+.3f}%   "
          f"win {(p.net > 0).mean() * 100:.1f}%")
    print()
    rows = []
    for lo, hi, lab in ((1.00, 99.0, "picks touching 100%+"),
                        (0.50, 1.00, "picks touching 50-100%"),
                        (0.20, 0.50, "picks touching 20-50%"),
                        (-99.0, 0.20, "picks touching <20%")):
        s = p[(p.mup >= lo) & (p.mup < hi)]
        if len(s) > 5:
            rows.append({**dist(s.net, lab),
                         "share_of_trades%": len(s) / len(p) * 100,
                         "contrib_pp": s.net.sum() / len(p) * 100})
    q = pd.DataFrame(rows)
    print(q.round(2).to_string(index=False))

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("4. WHERE THE RETURN COMES FROM")
    print("=" * 100)
    tot = p.net.sum()
    for lo, lab in ((1.00, "touched 100%+"), (0.50, "touched >=50%"),
                    (0.20, "touched >=20%")):
        s = p[p.mup >= lo]
        print(f"  {lab:16s} {len(s):4,} trades ({len(s) / len(p) * 100:5.2f}% of the "
              f"book) contribute {s.net.sum() / tot * 100:6.1f}% of total P&L")
    rest = p[p.mup < 0.20]
    print(f"  {'everything else':16s} {len(rest):4,} trades "
          f"({len(rest) / len(p) * 100:5.2f}%) contribute "
          f"{rest.net.sum() / tot * 100:6.1f}%")
    print(f"\n  strategy mean without any pick that touched +50%: "
          f"{p[p.mup < 0.50].net.mean() * 100:+.3f}% per trade")
    print(f"  strategy mean without any pick that touched +100%: "
          f"{p[p.mup < 1.00].net.mean() * 100:+.3f}% per trade")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("5. HOW LONG BETWEEN MOONSHOTS")
    print("=" * 100)
    p2 = p.sort_values("date").reset_index(drop=True)
    for lo, lab in ((0.50, "+50%"), (1.00, "+100%")):
        hit = np.flatnonzero((p2.mup >= lo).to_numpy())
        if len(hit) > 2:
            gaps = np.diff(hit)
            print(f"  {lab}: {len(hit)} in {len(p2):,} trades. Gap between them: "
                  f"median {np.median(gaps):.0f} trades, "
                  f"p90 {np.percentile(gaps, 90):.0f}, max {gaps.max()}")
            print(f"        at ~21 trades a month that is a median "
                  f"{np.median(gaps) / 21:.1f} months, worst "
                  f"{gaps.max() / 21:.1f} months between hits")
    p.to_parquet(root / "tail_anatomy_picks.parquet")
    print("\nSurvivorship: the panel has no delistings, so the upside tail is "
          "overstated\nand the 'everything else' bucket is missing its worst "
          "outcomes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
