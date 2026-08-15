"""Is direction really at chance? A single split said 0.63 and that needs checking.

`short_direction.py` ran a direction classifier as its control arm and the
price-only baseline came back at **AUC 0.6277** on which way a big mover moves.
That contradicts five previous results in this repository, all of which put
direction at or near chance. One of the two is wrong and it matters which, so
this pulls the claim apart along every axis that could explain it.

Three candidate explanations, each testable
-------------------------------------------
**The target changed.** Earlier work predicted ``y_dir`` — whether the upward
excursion exceeded the downward one. `short_direction.py` predicted the sign of
the realised ten-session return. Those are different questions: a name can spike
+30% intraday and close the window down. Terminal sign may simply be easier.

**The sample changed.** The short-interest arm ran only on rows FINRA covers,
which is exchange-listed names liquid enough to appear in the consolidated file,
from 2018 on. That is a cleaner, larger, more liquid universe than the full
panel of 3,662 including the illiquid tail.

**The split changed.** A single chronological 60/40 split can be lucky in a way
fourteen walk-forward blocks cannot. This is the explanation to want to rule out
first, because it is the most boring and the most likely.

So: both targets, both samples, single-split against walk-forward, all on the
same code path. Whichever way it falls, one published conclusion needs amending.
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
BIG = 0.20


def run(X, y, dates, label, walk_forward: bool):
    from sklearn.ensemble import HistGradientBoostingClassifier
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
    if not walk_forward:
        order = np.argsort(dates.to_numpy(), kind="stable")
        cut = int(len(order) * 0.6)
        tr, te = order[:cut], order[cut:]
        med, sc = scale_fit(X[tr])
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             max_depth=4, random_state=0)
        clf.fit(np.clip((X[tr] - med) / sc, -5, 5), y[tr])
        p = clf.predict_proba(np.clip((X[te] - med) / sc, -5, 5))[:, 1]
        return auc(y[te], p), [auc(y[te], p)]

    per = []
    preds = np.full(len(y), np.nan)
    for b0, b1 in blocks(dates.max()):
        tr = np.flatnonzero(dates < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((dates >= b0) & (dates < b1))
        if len(tr) < 5_000 or len(te) < 300 or len(set(y[tr])) < 2 or len(set(y[te])) < 2:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        med, sc = scale_fit(X[tr])
        clf = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05,
                                             max_depth=4, random_state=0)
        clf.fit(np.clip((X[tr] - med) / sc, -5, 5), y[tr])
        p = clf.predict_proba(np.clip((X[te] - med) / sc, -5, 5))[:, 1]
        preds[te] = p
        per.append(auc(y[te], p))
    live = np.isfinite(preds)
    pooled = auc(y[live], preds[live]) if live.sum() and len(set(y[live])) > 1 else np.nan
    return pooled, per


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--si", default="/root/.iai/wide2015/short_interest.parquet")
    ap.add_argument("--stride", type=int, default=10)
    args = ap.parse_args(argv)
    root = Path(args.root)

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

    # the excursion-based target the earlier work used
    mu = d["max_up"].to_numpy()[rows].astype(float)
    md = d["max_dn"].to_numpy()[rows].astype(float)
    ydir = (mu >= -md).astype(int)
    ymag = np.isfinite(mu) & np.isfinite(md) & (np.maximum(mu, -md) >= BIG)

    si = pd.read_parquet(args.si)
    covered = pd.DataFrame({"ticker": tick, "date": dates}).merge(
        si[["symbolCode"]].drop_duplicates().rename(columns={"symbolCode": "ticker"}),
        on="ticker", how="left", indicator=True)["_merge"].eq("both").to_numpy().copy()
    covered &= (dates >= pd.Timestamp("2018-02-01")).to_numpy()

    print(f"{len(rows):,} candidates, {covered.sum():,} in the FINRA-covered subset\n")
    print("=" * 104)
    print("DIRECTION AUC -- every combination of target, sample and split")
    print("=" * 104)
    print(f"{'target':28s} {'sample':18s} {'split':14s} {'n':>9s} {'base up%':>9s} "
          f"{'AUC':>7s} {'blocks':>7s}")

    big_ret = np.abs(ret) >= BIG
    cases = []
    for tname, y_all, mask_all in (
            ("sign of 10d return", (ret > 0).astype(int), big_ret),
            ("y_dir (excursion)", ydir, ymag)):
        for sname, samp in (("all rows", np.ones(len(ret), bool)),
                            ("FINRA-covered", covered)):
            m = mask_all & samp
            if m.sum() < 2000:
                continue
            for wf in (False, True):
                a, per = run(Xp[m], y_all[m], dates[m].reset_index(drop=True),
                             tname, wf)
                cases.append((tname, sname, "walk-forward" if wf else "single 60/40",
                              int(m.sum()), y_all[m].mean() * 100, a, len(per)))
                print(f"{tname:28s} {sname:18s} "
                      f"{'walk-forward' if wf else 'single 60/40':14s} "
                      f"{int(m.sum()):>9,} {y_all[m].mean() * 100:>8.1f}% "
                      f"{a:>7.4f} {len(per):>7d}", flush=True)

    print("\n" + "=" * 104)
    print("READING")
    print("=" * 104)
    tab = pd.DataFrame(cases, columns=["target", "sample", "split", "n", "up", "auc", "k"])
    wf = tab[tab.split == "walk-forward"]
    ss = tab[tab.split == "single 60/40"]
    print(f"  walk-forward AUCs range {wf.auc.min():.4f} to {wf.auc.max():.4f}")
    print(f"  single-split AUCs range {ss.auc.min():.4f} to {ss.auc.max():.4f}")
    for t in tab.target.unique():
        s = tab[tab.target == t]
        print(f"  {t:28s} mean AUC {s.auc.mean():.4f}")
    best = tab.loc[tab.auc.idxmax()]
    print(f"\n  strongest: {best.target} / {best['sample']} / {best.split} "
          f"-> {best.auc:.4f}")
    print("  If the walk-forward numbers collapse toward 0.50 while the single")
    print("  split stays high, the split was the explanation and direction is")
    print("  still unsolved. If they hold, five earlier conclusions need amending.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
