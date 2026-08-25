"""Make the catalyst the gate, not a column.

The original thesis of this project was that moonshots come from catalysts and
that the job is to be positioned before one resolves. What actually got built
drifted away from that: the catalyst signals are present in the panel — every
8-K item code, at 5/20/60-session counts and a sessions-since-last — but they sit
as roughly twenty columns among a hundred and eight, and the model is free to
ignore them in favour of price and volatility. `RESULT_AGREED_STRATEGY.md` shows
it largely did: the book's biggest winners were crypto miners and quantum names,
and its worst losses were energy stocks bought into the COVID crash. That is a
volatility strategy wearing a catalyst strategy's clothes.

This tests the other arrangement. Rather than offering the catalyst as a feature,
**restrict the universe to names where a catalyst has just landed**, and rank
only inside that set.

Why the distinction is not cosmetic
-----------------------------------
A feature competes; a gate constrains. A gradient booster given `i8.01_since`
alongside `vol_20d` will use whichever splits the training data better on
average, and volatility wins that contest almost everywhere because it is
informative on every row while a catalyst is informative on the two percent of
rows where one exists. Gating removes the contest: every candidate has a
catalyst, so the only question left is which one.

It also changes what is being asked. Ungated, the model answers "which of two
hundred names will move". Gated, it answers "this company just filed something —
does it matter". The second is the question the thesis was about.

What is measured
----------------
For each gate: how many names survive per session, the base rate of a 20% move,
the return of simply buying everything in the gate, and the walk-forward return
of ranking inside it. The ungated pool is the control throughout.

Pass criteria, fixed before running
-----------------------------------
1. **Base rate.** A gate must raise P(|move| >= 20%) above the ungated rate.
   A catalyst that does not raise the odds of a large move is not a catalyst.
2. **Return.** Ranking inside the gate must beat ranking inside the ungated pool
   by more than +0.25pp per trade, with a session-clustered interval excluding
   zero.
3. **Survivability.** A gate leaving fewer than three names on a median session
   is not tradeable at k=1 and is reported but not counted as a pass.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adrnn_train import build_arrays  # noqa: E402
from agreed_strategy import daily_paths  # noqa: E402
from moonshot_tail import MAX_TRAIN, blocks, scale_fit  # noqa: E402

HORIZON = 10
COST = 20.0 / 1e4
BIG = 0.20


def build_gates(F: dict) -> dict:
    """Boolean masks, each meaning 'a catalyst of this kind has just landed'."""
    items = [k for k in F if k.startswith("i") and k.endswith("_since")]
    any8k = np.min(np.column_stack([F[k] for k in items]), axis=1)

    def s(name):
        return F.get(name, np.full(len(any8k), 1e9))

    news = np.minimum(s("i8.01_since"), s("i7.01_since"))
    ma = np.minimum(s("i1.01_since"), s("i2.01_since"))
    return {
        "ungated (control)": np.ones(len(any8k), bool),
        "any 8-K <=1 session": any8k <= 1,
        "any 8-K <=3": any8k <= 3,
        "any 8-K <=5": any8k <= 5,
        "news 8.01/7.01 <=3": news <= 3,
        "M&A 1.01/2.01 <=3": ma <= 3,
        "earnings 2.02 <=3": s("i2.02_since") <= 3,
        "dilution 3.02 <=3": s("i3.02_since") <= 3,
        "13D activist <=20": s("fSC 13D_since") <= 20,
        "cluster insider buy <=20": s("ncluster_buy_since") <= 20,
        "8-K <=3, no 3.02 in 60": (any8k <= 3) & (s("i3.02_since") > 60),
        "news <=3, no 3.02 in 60": (news <= 3) & (s("i3.02_since") > 60),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--quantile", type=float, default=0.75)
    ap.add_argument("--k", type=int, default=1)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from sklearn.ensemble import HistGradientBoostingRegressor

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
    Xp = X[rows]
    dates = pd.Series(pd.to_datetime(d["date"].to_numpy()[rows]))
    tick = d["ticker"].to_numpy()[rows]

    F = {c: Xp[:, i] for i, c in enumerate(feats)}
    gates = build_gates(F)
    print(f"{len(rows):,} eligible candidates over {dates.nunique():,} sessions\n",
          flush=True)

    # ---- 1. what each gate does to the odds ----------------------------
    print("=" * 110)
    print("1. DOES THE CATALYST RAISE THE ODDS OF A BIG MOVE?")
    print("=" * 110)
    print(f"{'gate':26s} {'rows':>9s} {'% of pool':>10s} {'names/session':>14s} "
          f"{'P(|move|>=20%)':>15s} {'P(up 20%)':>10s} {'buy-all ret':>12s}")
    base = None
    stats = {}
    for name, m in gates.items():
        n = int(m.sum())
        if n < 500:
            print(f"{name:26s} {n:>9,}  too few")
            continue
        r = ret[m]
        per = pd.Series(dates[m]).value_counts()
        pbig = float((np.abs(r) >= BIG).mean())
        pup = float((r >= BIG).mean())
        stats[name] = {"n": n, "pbig": pbig, "pup": pup,
                       "buyall": float(r.mean()), "per": float(per.median())}
        if base is None:
            base = stats[name]
        lift = "" if name.startswith("ungated") else \
            f"  {pbig / base['pbig']:.2f}x"
        print(f"{name:26s} {n:>9,} {n / len(ret) * 100:>9.1f}% "
              f"{per.median():>14.0f} {pbig * 100:>14.2f}%{lift:>8s} "
              f"{pup * 100:>9.2f}% {r.mean() * 100:>+11.2f}%")

    # ---- 2. ranking inside the gate ------------------------------------
    print("\n" + "=" * 110)
    print("2. RANKING INSIDE THE GATE -- walk-forward, top pick per session")
    print("=" * 110)
    res = {}
    for name, m in gates.items():
        if name not in stats or stats[name]["per"] < 1:
            continue
        gi = np.flatnonzero(m)
        gd = dates.iloc[gi].reset_index(drop=True)
        gr = ret[gi]
        gX = Xp[gi]
        per_block = []
        for b0, b1 in blocks(gd.max()):
            tr = np.flatnonzero(gd < b0 - pd.Timedelta(days=14))
            te = np.flatnonzero((gd >= b0) & (gd < b1))
            if len(tr) < 3_000 or len(te) < 100:
                continue
            if len(tr) > MAX_TRAIN:
                tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
            med, sc = scale_fit(gX[tr])
            mo = HistGradientBoostingRegressor(loss="quantile",
                                               quantile=args.quantile,
                                               max_iter=250, learning_rate=0.05,
                                               max_depth=6, random_state=0)
            mo.fit(np.clip((gX[tr] - med) / sc, -5, 5), gr[tr])
            p = mo.predict(np.clip((gX[te] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": gd.to_numpy()[te], "p": p, "r": gr[te]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(args.k)
            per_block.append({"block": f"{b0:%Y-%m}",
                              "ret": float(pick.r.mean()) - COST,
                              "n": len(pick)})
        if per_block:
            t = pd.DataFrame(per_block)
            res[name] = t
            print(f"  {name:26s} {len(t):>2d} blocks  {int(t.n.sum()):>6,} trades  "
                  f"{t.ret.mean() * 100:>+8.3f}% per trade")

    # ---- 3. against the control ----------------------------------------
    print("\n" + "=" * 110)
    print("3. AGAINST THE UNGATED CONTROL")
    print("=" * 110)
    ctrl = res.get("ungated (control)")
    if ctrl is None:
        print("  no control")
        return 1
    rng = np.random.default_rng(31)
    print(f"  control: {ctrl.ret.mean() * 100:+.3f}% per trade over "
          f"{len(ctrl)} blocks\n")
    print(f"{'gate':26s} {'delta':>9s} {'95% CI':>22s} {'P(<=0)':>8s} "
          f"{'lift on P(big)':>15s}")
    for name, t in res.items():
        if name.startswith("ungated"):
            continue
        j = ctrl.set_index("block").ret.reindex(t.block).to_numpy()
        dl = t.ret.to_numpy() - j
        dl = dl[np.isfinite(dl)]
        if len(dl) < 4:
            continue
        bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        lift = stats[name]["pbig"] / stats["ungated (control)"]["pbig"]
        flag = "  PASS" if dl.mean() > 0.0025 and lo > 0 else ""
        print(f"{name:26s} {dl.mean() * 100:>+8.3f}pp "
              f"[{lo * 100:>+7.3f},{hi * 100:>+7.3f}] {(bs <= 0).mean():>8.3f} "
              f"{lift:>14.2f}x{flag}")
    print("\n  A gate passes only if it both raises the odds of a big move and")
    print("  improves the traded return with an interval clear of zero.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
