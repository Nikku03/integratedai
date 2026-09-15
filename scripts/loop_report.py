"""Does the twist propagate, and does the original 61.9% survive out of sample?

Every interval here is a **day-clustered** bootstrap over entry sessions. Events
on one session share that session's tape, and treating them as independent
understates the error by a factor of several -- which matters more at 8,000
events than it did at 118, because the number of independent sessions grew far
more slowly than the number of events.

The peer tests are **incremental by construction**. Peers co-move with the filer,
so a naive test shows the peer signal "working" as a noisy copy of the filer's
own run. Each peer signal is therefore residualised against ``own_run_z`` before
it is scored, and the joint fit carrying both is reported beside it.

Three signals x two horizons is six registered cells. All six are printed. The
Bonferroni threshold is 0.05 / 6 = 0.0083 and is applied in the verdict line.
"""

from __future__ import annotations

import argparse
import sys
from math import exp, lgamma, log

import numpy as np
import pandas as pd

GATE, NB, BONF = 0.5, 20000, 0.05 / 6
SIGNALS = (("own_run_z", -1, "reversal"), ("peer_run_z", -1, "reversal"),
           ("peer_gap", +1, "momentum"))


def binom_p(k: int, n: int) -> float:
    """Two-sided binomial tail against p=0.5, in log space.

    The exact sum of binomial coefficients overflows a float above n ~ 1000, and
    this test runs at n in the thousands. Summing exp(log C(n,i) - n log 2)
    instead keeps every term in range.
    """
    k = max(k, n - k)
    lc = lgamma(n + 1)
    terms = [lc - lgamma(i + 1) - lgamma(n - i + 1) - n * log(2.0)
             for i in range(k, n + 1)]
    m = max(terms)
    return min(1.0, 2.0 * exp(m) * sum(exp(t - m) for t in terms))


def clustered(x: np.ndarray, day: np.ndarray, n: int = NB) -> tuple:
    rng = np.random.default_rng(0)
    u = np.unique(day)
    by = {d: x[day == d] for d in u}
    out = np.empty(n)
    for i in range(n):
        out[i] = np.concatenate([by[d] for d in rng.choice(u, len(u))]).mean()
    return (float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5)),
            float((out <= 0).mean()))


def z(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std()


def score(F: pd.DataFrame, sig: str, direction: int, horizon: str, label: str):
    G = F[F[sig].notna() & F[horizon].notna()].copy()
    G["s"] = z(G[sig])
    G = G[G.s.abs() > GATE]
    if len(G) < 30:
        print(f"    {label:34s} too few events ({len(G)})")
        return None
    pred = direction * np.sign(G.s)
    hit = (np.sign(G[horizon]) == pred)
    ret = (pred * G[horizon]).to_numpy()
    day = G.entry.to_numpy()
    lo, hi, p0 = clustered(ret, day)
    bp = binom_p(int(hit.sum()), len(G))
    print(f"    {label:34s} {hit.sum():>5d}/{len(G):<5d} = {hit.mean()*100:5.2f}%  "
          f"P={bp:<9.2}  edge {ret.mean()*100:+6.3f}%  "
          f"[{lo*100:+.2f},{hi*100:+.2f}]  P0={p0:.3f}  ({G.entry.nunique()} sess)")
    return dict(signal=sig, horizon=horizon, n=len(G), acc=hit.mean(), binom_p=bp,
                edge=ret.mean(), lo=lo, hi=hi, p0=p0, sessions=G.entry.nunique())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="/tmp/claude-0/opt/loop_features.parquet")
    args = ap.parse_args(argv)
    F = pd.read_parquet(args.features)
    print(f"\n  {len(F):,} events, {F.entry.nunique()} sessions, "
          f"{F.ticker.nunique():,} names, {F.entry.min()} -> {F.entry.max()}")
    print(f"  mean |gap| {F.gap.abs().mean()*100:.2f}%\n")

    print("=" * 104)
    print("THE REGISTERED GRID  (3 signals x 2 horizons; Bonferroni threshold P < 0.0083)")
    print("=" * 104)
    res = []
    for h in ("gap", "day_ret"):
        print(f"\n  horizon: {'overnight gap' if h == 'gap' else 'the session AFTER the gap'}")
        for sig, d, name in SIGNALS:
            r = score(F, sig, d, h, f"{sig} ({name})")
            if r:
                res.append(r)

    print("\n" + "=" * 104)
    print("H1  DOES THE 61.9% REPLICATE OUT OF SAMPLE?")
    print("=" * 104)
    a = next(r for r in res if r["signal"] == "own_run_z" and r["horizon"] == "gap")
    print(f"  original:  73/118   = 61.86%   one 18-session window")
    print(f"  now:       {a['n']:,} events over {a['sessions']} sessions = "
          f"{a['acc']*100:.2f}%   P = {a['binom_p']:.3}")
    print(f"  verdict:   {'REPLICATES' if a['binom_p'] < BONF and a['acc'] > 0.5 else 'DOES NOT REPLICATE'}"
          f" at the Bonferroni threshold")

    print("\n" + "=" * 104)
    print("H2  DOES THE DOLLAR EDGE CLEAR ZERO?")
    print("=" * 104)
    print(f"  original:  +1.376% per event, day-clustered [-0.59, +2.88], P0 = 0.071")
    print(f"  now:       {a['edge']*100:+.3f}% per event, "
          f"day-clustered [{a['lo']*100:+.2f}, {a['hi']*100:+.2f}], P0 = {a['p0']:.3f}")
    print(f"  verdict:   {'CLEARS zero' if a['p0'] < 0.025 else 'does NOT clear zero'}")

    print("\n" + "=" * 104)
    print("H3  DOES THE PEER SIGNAL ADD ANYTHING THE FILER'S OWN RUN DOES NOT?")
    print("=" * 104)
    for sig, d, name in SIGNALS[1:]:
        G = F[F[sig].notna() & F.own_run_z.notna()].copy()
        if len(G) < 100:
            continue
        b = np.polyfit(G.own_run_z, G[sig], 1)
        G["resid"] = G[sig] - np.polyval(b, G.own_run_z)
        print(f"\n  {sig}:  corr with own_run_z = "
              f"{np.corrcoef(G.own_run_z, G[sig])[0,1]:+.3f}  (n={len(G):,})")
        score(G, "resid", d, "gap", f"  residualised ({name})")
        print(f"    within quintiles of own_run_z:")
        G["q"] = pd.qcut(G.own_run_z, 5, labels=False, duplicates="drop")
        for q in sorted(G.q.dropna().unique()):
            H = G[G.q == q].copy()
            H["s"] = z(H[sig])
            H = H[H.s.abs() > GATE]
            if len(H) < 30:
                continue
            hit = (np.sign(H.gap) == d * np.sign(H.s))
            print(f"      Q{int(q)+1} own_run_z in [{G[G.q==q].own_run_z.min():+.2f},"
                  f"{G[G.q==q].own_run_z.max():+.2f}]  "
                  f"{hit.sum():>4d}/{len(H):<4d} = {hit.mean()*100:5.2f}%")

    print("\n" + "=" * 104)
    print("JOINT FIT  (gap regressed on all three, standard errors clustered by session)")
    print("=" * 104)
    J = F[["gap", "own_run_z", "peer_run_z", "peer_gap", "entry"]].dropna()
    if len(J) > 200:
        X = np.column_stack([np.ones(len(J))] + [z(J[c]).to_numpy()
                            for c in ("own_run_z", "peer_run_z", "peer_gap")])
        y = J.gap.to_numpy()
        beta = np.linalg.lstsq(X, y, rcond=None)[0]
        e = y - X @ beta
        XtX = np.linalg.inv(X.T @ X)
        meat = np.zeros((X.shape[1],) * 2)
        for dd in J.entry.unique():
            m = (J.entry == dd).to_numpy()
            s = X[m].T @ e[m]
            meat += np.outer(s, s)
        se = np.sqrt(np.diag(XtX @ meat @ XtX))
        print(f"  n = {len(J):,} events over {J.entry.nunique()} sessions")
        for nm, b, s in zip(("intercept", "own_run_z", "peer_run_z", "peer_gap"), beta, se):
            t = b / s if s > 0 else np.nan
            print(f"    {nm:12s} {b*100:+8.4f}%  t = {t:+6.2f}"
                  f"   {'*' if abs(t) > 2.64 else ''}")
        print("  (* = |t| > 2.64, the Bonferroni-adjusted two-sided 5% critical value)")

    print("\n" + "=" * 104)
    print("H4  IS THE EFFECT CONFINED TO THE OVERNIGHT SEAM?")
    print("=" * 104)
    for sig, d, name in SIGNALS:
        g = next((r for r in res if r["signal"] == sig and r["horizon"] == "gap"), None)
        dr = next((r for r in res if r["signal"] == sig and r["horizon"] == "day_ret"), None)
        if g and dr:
            print(f"  {sig:12s} gap {g['acc']*100:5.2f}%   next session {dr['acc']*100:5.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
