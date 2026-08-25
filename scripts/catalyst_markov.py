"""A Markov chain over catalyst sequences, with the catalyst still the driver.

`catalyst_driver.py` established that a catalyst raises the odds of a large move
— 1.2x for any 8-K, 1.6x for an M&A item, 3.5x for a 3.02 unregistered issuance —
and that almost none of that lift survives excluding 3.02, which means the
"catalyst causes big moves" effect is largely "dilution causes big moves down".
A single flag saying *an 8-K happened* is evidently too coarse.

Companies do not file in isolation. They file in **sequences**:

    S-3  ->  424B5  ->  3.02          a shelf being registered, then drawn down
    8.01 ->  1.01   ->  2.01          data, then a deal, then a closing
    3.01 ->  5.03   ->  reverse split  a listing deficiency being papered over

The state a company is in, and the transition it has just made, carries
information that neither event alone does. A 3.02 arriving after an S-3 is a
plan executing; a 3.02 arriving out of nowhere is a company that has run out of
money. Those should not be the same feature, and to a flag they are.

The chain
---------
State = the most recent catalyst type. Previous state = the second most recent,
recovered from the per-type sessions-since columns. The transition matrix

    P(j | i) = count(i -> j) / count(i)

is the shared operator: estimated **once per training block**, then reused for
every query about any row in that block — how likely this transition was, how
often it preceded a large move, what it returned on average. That is the same
compute-once-reuse-many structure as the REM work, with a Markov transition in
place of a diffusion.

Leakage is the entire risk here
-------------------------------
Every statistic attached to a transition — its probability, its historical
big-move rate, its mean return — is estimated on the **training rows of that
block only** and then applied to the test rows. Estimating them on the full
sample would hand the model the answer: "this transition tends to be followed by
+40%" is a fact about the future when computed over data that includes the
future. The per-block re-estimation is not a nicety, it is the whole reason the
numbers can be believed.
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
PRIOR = 30.0

#: The alphabet. Column name in the panel -> readable state.
ALPHABET = {
    "i3.02_since": "3.02 issuance",
    "f424B5_since": "424B5 takedown",
    "fS-3_since": "S-3 shelf",
    "i1.01_since": "1.01 agreement",
    "i2.01_since": "2.01 completion",
    "i2.02_since": "2.02 earnings",
    "i2.03_since": "2.03 debt",
    "i3.01_since": "3.01 listing",
    "i5.02_since": "5.02 officer",
    "i5.03_since": "5.03 charter",
    "i5.07_since": "5.07 vote",
    "i7.01_since": "7.01 regFD",
    "i8.01_since": "8.01 other",
    "i9.01_since": "9.01 exhibit",
    "fSC 13D_since": "13D activist",
    "fSC 13G_since": "13G passive",
    "f10-K_since": "10-K",
    "f10-Q_since": "10-Q",
    "ncluster_buy_since": "cluster buy",
    "nsell_since": "insider sell",
}


def states(F: dict, feats: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, list]:
    """Current and previous catalyst state per row, from the sessions-since columns.

    The smallest ``_since`` is the most recent event and the second smallest is
    the one before it. That is an approximation — two events on the same day tie,
    and a type that fired twice hides its own earlier occurrence — but it needs
    no data the panel does not already carry.
    """
    cols = [c for c in ALPHABET if c in feats]
    names = [ALPHABET[c] for c in cols]
    M = np.column_stack([F[c] for c in cols]).astype(float)
    M = np.where(np.isfinite(M), M, 1e9)
    order = np.argsort(M, axis=1)
    cur = order[:, 0]
    prv = order[:, 1]
    cur_since = np.take_along_axis(M, cur[:, None], 1).ravel()
    prv_since = np.take_along_axis(M, prv[:, None], 1).ravel()
    # "nothing recent" is its own state rather than a stale event
    NONE = len(names)
    cur = np.where(cur_since <= 5, cur, NONE)
    prv = np.where(prv_since <= 60, prv, NONE)
    return cur, prv, np.column_stack([cur_since, prv_since]), names + ["none"]


def chain(cur, prv, ret, tr, n_states):
    """Estimate the transition matrix and its payoff table on training rows only."""
    k = n_states
    cnt = np.zeros((k, k))
    big = np.zeros((k, k))
    tot = np.zeros((k, k))
    up = np.zeros((k, k))
    np.add.at(cnt, (prv[tr], cur[tr]), 1.0)
    np.add.at(big, (prv[tr], cur[tr]), (np.abs(ret[tr]) >= BIG).astype(float))
    np.add.at(tot, (prv[tr], cur[tr]), ret[tr])
    np.add.at(up, (prv[tr], cur[tr]), (ret[tr] > 0).astype(float))

    row = cnt.sum(axis=1, keepdims=True)
    P = (cnt + 1e-3) / np.maximum(row + 1e-3 * k, 1e-9)
    # shrink the payoff tables toward the global mean; a transition seen twice
    # must not be allowed to claim a 40% expected return
    g_big = float((np.abs(ret[tr]) >= BIG).mean())
    g_ret = float(ret[tr].mean())
    g_up = float((ret[tr] > 0).mean())
    B = (big + PRIOR * g_big) / (cnt + PRIOR)
    R = (tot + PRIOR * g_ret) / (cnt + PRIOR)
    U = (up + PRIOR * g_up) / (cnt + PRIOR)
    ent = -(P * np.log(P + 1e-12)).sum(axis=1)
    return P, B, R, U, cnt, ent


def features(cur, prv, sinces, P, B, R, U, cnt, ent):
    i, j = prv, cur
    return np.column_stack([
        np.log(P[i, j] + 1e-9),            # how surprising this transition is
        B[i, j],                            # historical P(|move| >= 20%)
        R[i, j],                            # historical mean return
        U[i, j],                            # historical P(up)
        np.log1p(cnt[i, j]),                # how much evidence stands behind it
        ent[i],                             # how predictable the current state was
        sinces[:, 0], sinces[:, 1],
    ]).astype(np.float32)


FNAMES = ["mk_logp", "mk_hist_big", "mk_hist_ret", "mk_hist_up",
          "mk_log_count", "mk_entropy", "mk_since_cur", "mk_since_prev"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--quantile", type=float, default=0.75)
    ap.add_argument("--gate", default="8k3", choices=["none", "8k3", "8k1"])
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
    F = {c: Xp[:, i] for i, c in enumerate(feats)}

    cur, prv, sinces, names = states(F, feats)
    K = len(names)
    print(f"{len(rows):,} candidates, {K} catalyst states", flush=True)

    if args.gate != "none":
        lim = 3 if args.gate == "8k3" else 1
        items = [c for c in ALPHABET if c.startswith("i") and c in feats]
        any8k = np.min(np.column_stack([F[c] for c in items]), axis=1)
        m = any8k <= lim
        print(f"gating to an 8-K within {lim} session(s): "
              f"{int(m.sum()):,} rows ({m.mean() * 100:.1f}%)", flush=True)
        cur, prv, sinces = cur[m], prv[m], sinces[m]
        Xp, ret = Xp[m], ret[m]
        dates = dates[m].reset_index(drop=True)

    # ---- what the chain looks like, estimated on the first 60% ---------
    order = np.argsort(dates.to_numpy(), kind="stable")
    cut = int(len(order) * 0.6)
    P, B, R, U, cnt, ent = chain(cur, prv, ret, order[:cut], K)
    print("\n" + "=" * 104)
    print("THE CHAIN -- transitions ranked by historical return (train 60% only)")
    print("=" * 104)
    tab = []
    for i in range(K):
        for j in range(K):
            if cnt[i, j] >= 200:
                tab.append((names[i], names[j], int(cnt[i, j]), R[i, j],
                            B[i, j], U[i, j]))
    t = pd.DataFrame(tab, columns=["from", "to", "n", "ret", "p_big", "p_up"])
    t = t.sort_values("ret", ascending=False)
    print(f"  {len(t)} transitions with >=200 training observations\n")
    print(f"  {'from':18s} -> {'to':18s} {'n':>7s} {'mean ret':>9s} "
          f"{'P(big)':>8s} {'P(up)':>7s}")
    for _, r in t.head(8).iterrows():
        print(f"  {r['from']:18s} -> {r['to']:18s} {r.n:>7,} "
              f"{r.ret * 100:>+8.2f}% {r.p_big * 100:>7.2f}% {r.p_up * 100:>6.2f}%")
    print("  ...")
    for _, r in t.tail(8).iterrows():
        print(f"  {r['from']:18s} -> {r['to']:18s} {r.n:>7,} "
              f"{r.ret * 100:>+8.2f}% {r.p_big * 100:>7.2f}% {r.p_up * 100:>6.2f}%")

    # ---- walk-forward, re-estimating the chain each block ---------------
    print("\n" + "=" * 104)
    print("WALK-FORWARD -- chain re-estimated on each block's training rows")
    print("=" * 104)
    arms = {"panel only": [], "+ markov": [], "markov only": []}
    aucs = {k: [] for k in arms}
    for b0, b1 in blocks(dates.max()):
        tr = np.flatnonzero(dates < b0 - pd.Timedelta(days=14))
        te = np.flatnonzero((dates >= b0) & (dates < b1))
        if len(tr) < 5_000 or len(te) < 200:
            continue
        if len(tr) > MAX_TRAIN:
            tr = tr[np.linspace(0, len(tr) - 1, MAX_TRAIN).astype(int)]
        P, B, R, U, cnt, ent = chain(cur, prv, ret, tr, K)
        Mk = features(cur, prv, sinces, P, B, R, U, cnt, ent)
        for name, A in (("panel only", Xp),
                        ("+ markov", np.column_stack([Xp, Mk])),
                        ("markov only", Mk)):
            A = np.nan_to_num(A, nan=0.0, posinf=0.0, neginf=0.0)
            med, sc = scale_fit(A[tr])
            mo = HistGradientBoostingRegressor(loss="quantile",
                                               quantile=args.quantile,
                                               max_iter=250, learning_rate=0.05,
                                               max_depth=6, random_state=0)
            mo.fit(np.clip((A[tr] - med) / sc, -5, 5), ret[tr])
            p = mo.predict(np.clip((A[te] - med) / sc, -5, 5))
            s = pd.DataFrame({"d": dates.to_numpy()[te], "p": p, "r": ret[te]})
            pick = s.sort_values("p", ascending=False).groupby("d").head(1)
            arms[name].append(float(pick.r.mean()) - COST)
            aucs[name].append(auc((ret[te] > 0).astype(int), p))
        print(f"  block {b0:%Y-%m} done", flush=True)

    print(f"\n  {'arm':14s} {'blocks':>7s} {'per trade':>11s} {'dir AUC':>9s}")
    for name in arms:
        a = np.array(arms[name])
        if len(a):
            print(f"  {name:14s} {len(a):>7d} {a.mean() * 100:>+10.3f}% "
                  f"{np.mean(aucs[name]):>9.4f}")
    a = np.array(arms["panel only"])
    b = np.array(arms["+ markov"])
    if len(a) > 3:
        dl = b - a
        rng = np.random.default_rng(41)
        bs = np.array([rng.choice(dl, len(dl), True).mean() for _ in range(20000)])
        lo, hi = np.percentile(bs, [2.5, 97.5])
        print(f"\n  markov minus panel-only: {dl.mean() * 100:+.3f}pp   "
              f"95% CI [{lo * 100:+.3f}, {hi * 100:+.3f}]   "
              f"P(<=0) = {(bs <= 0).mean():.4f}")
        print(f"  {'PASS' if dl.mean() > 0.0025 and lo > 0 else 'FAIL'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
