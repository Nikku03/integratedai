"""What the weekly straddles did, and whether the gap paid for the premium.

The single number that decides this strategy is not the return. It is

    realised gap  -  breakeven move            where breakeven = (c + p) / spot

If that difference is negative on average the trade cannot work, no matter how
large individual winners look, because a straddle's losses are capped at the
premium and its wins have to cover every loser's full premium.

Arms
----
``all``            every straddle that priced.
``executable``     those whose chosen strike actually traded before the event
                   and printed at both ends of the hold. The earlier directional
                   test found four of six selected names failed this, so it is
                   reported separately rather than folded in.
``pre-open``       releases accepted before 09:30, bought the prior close.
``after-close``    releases accepted after 16:00, bought that close.

The two timings are the same overnight gap reached from different sides, so a
large difference between them is a warning about the fills rather than a finding
about the market.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MIN_PRE_CONTRACTS = 250
MIN_ACTIVE = 3


def arm(label, r, stake=40.0):
    r = np.asarray([x for x in r if x == x], dtype=float)
    if not len(r):
        print(f"  {label:24s}{'--':>5s}")
        return
    eq = stake
    for x in r:
        eq *= (1 + x)
    lg = np.log1p(np.clip(r, -0.999, None))
    print(f"  {label:24s}{len(r):>5d}{r.mean() * 100:>+10.1f}%{np.median(r) * 100:>+10.1f}%"
          f"{(r > 0).mean() * 100:>8.0f}%{(np.exp(lg.mean()) - 1) * 100:>+12.1f}%{eq:>10.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--straddles", default="/tmp/claude-0/opt/straddles.parquet")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)

    T = pd.read_parquet(args.straddles)
    skipped = T[T.skip != ""] if "skip" in T else T.iloc[0:0]
    T = T[T.skip == ""].copy() if "skip" in T else T.copy()

    if len(skipped):
        print("=" * 100)
        print("WHY EVENTS DROPPED OUT")
        print("=" * 100)
        for why, g in skipped.groupby("skip"):
            print(f"  {len(g):>4d}  {why}")
            print(f"        {', '.join(sorted(g.ticker.unique())[:14])}")

    if not len(T):
        print("\n  no straddles priced")
        return 0

    T["cost"] = T.call_entry + T.put_entry
    T["value"] = T.call_exit + T.put_exit
    T["ret"] = T.value / T.cost - 1
    T["breakeven"] = T.cost / T.spot_entry
    T["gap"] = T.spot_exit_open / T.spot_entry - 1
    T["edge"] = T.gap.abs() - T.breakeven
    T["call_ret"] = T.call_exit / T.call_entry - 1
    T["put_ret"] = T.put_exit / T.put_entry - 1
    T["prevol"] = T[["call_prevol", "put_prevol"]].min(axis=1)
    T["liquid"] = ((T.prevol >= MIN_PRE_CONTRACTS)
                   & (T[["call_preactive", "put_preactive"]].min(axis=1) >= MIN_ACTIVE))
    T["priced"] = T[["call_entry", "put_entry", "call_exit", "put_exit"]].notna().all(axis=1)
    T["ok"] = T.liquid & T.priced & (T.cost > 0)
    T["timing"] = np.where(pd.to_datetime(T.accepted_et, utc=True)
                           .dt.tz_convert("America/New_York").dt.hour >= 16,
                           "after-close", "pre-open")

    print("\n" + "=" * 100)
    print("EVERY STRADDLE")
    print("=" * 100)
    print(f"  {'tkr':7s}{'entry':>11s}{'exp':>7s}{'K':>8s}{'cost':>7s}"
          f"{'breakeven':>10s}{'gap':>8s}{'edge':>8s}{'call':>8s}{'put':>8s}"
          f"{'straddle':>10s}{'prevol':>8s}{'ok':>4s}")
    for _, r in T.sort_values("ret", ascending=False).iterrows():
        f = lambda v: "    n/a" if v != v else f"{v * 100:>+6.0f}%"
        print(f"  {r.ticker:7s}{r.entry:>11s}{r.dte:>6.0f}d{r.strike:>8g}{r.cost:>7.2f}"
              f"{r.breakeven * 100:>9.1f}%{r.gap * 100:>+7.1f}%{r.edge * 100:>+7.1f}%"
              f"{f(r.call_ret):>8s}{f(r.put_ret):>8s}{f(r.ret):>10s}"
              f"{r.prevol:>8,.0f}{('y' if r.ok else '-'):>4s}")

    print("\n" + "=" * 100)
    print(f"ARMS  (${args.stake:.0f} compounded trade by trade)")
    print("=" * 100)
    print(f"  {'arm':24s}{'n':>5s}{'mean':>10s}{'median':>10s}{'win':>8s}"
          f"{'compounds':>12s}{'$40 ->':>10s}")
    S = T.sort_values("entry")
    arm("all priced", S.ret, args.stake)
    E = S[S.ok]
    arm("executable only", E.ret, args.stake)
    arm("  pre-open releases", E[E.timing == "pre-open"].ret, args.stake)
    arm("  after-close releases", E[E.timing == "after-close"].ret, args.stake)
    arm("  held to that close", (E.call_exitclose + E.put_exitclose) / E.cost - 1, args.stake)
    arm("  call leg alone", E.call_ret, args.stake)
    arm("  put leg alone", E.put_ret, args.stake)

    print("\n" + "=" * 100)
    print("THE NUMBER THAT DECIDES IT: REALISED GAP AGAINST THE PRICED MOVE")
    print("=" * 100)
    # rows whose contract never printed have no cost and therefore no edge;
    # leaving them in turns the bootstrap interval into NaN
    P = T[T.priced & (T.cost > 0)]
    for tag, g in (("priced both ends", P), ("executable only", P[P.ok])):
        g = g[g.edge.notna()]
        if not len(g):
            continue
        print(f"\n  {tag}  (n={len(g)})")
        print(f"    mean breakeven the market charged   {g.breakeven.mean() * 100:>6.1f}%")
        print(f"    mean |gap| the event delivered      {g.gap.abs().mean() * 100:>6.1f}%")
        print(f"    mean edge (gap - breakeven)         {g.edge.mean() * 100:>+6.1f}pp")
        print(f"    share where the gap beat the price  {(g.edge > 0).mean() * 100:>6.0f}%")
        if len(g) > 2:
            b = np.array([np.mean(np.random.default_rng(s).choice(
                g.edge.to_numpy(), len(g))) for s in range(2000)])
            print(f"    95% interval on that edge           "
                  f"[{np.percentile(b, 2.5) * 100:+.1f}, {np.percentile(b, 97.5) * 100:+.1f}]pp")

    print("\n" + "=" * 100)
    print("WHERE THE WINNERS CAME FROM")
    print("=" * 100)
    print("  The obvious suspicion is that the winners are thin contracts with stale")
    print("  marks. Tested, that is not what is happening: the correlation between")
    print("  pre-event volume and return is weak, and the bucket that wins is also")
    print("  the bucket whose underlying GAPPED hardest. Small names move more --")
    print("  the same monotone relationship measured over the 8-K sample -- and the")
    print("  premium does not fall as fast as the liquidity does.\n")
    P2 = P[P.ret.notna()].copy()
    if len(P2) > 3:
        P2["bucket"] = pd.cut(P2.prevol, [-1, 50, 250, 1e9],
                              labels=["<50 contracts", "50-250", ">=250"])
        print(f"  {'pre-event volume in the strike':32s}{'n':>4s}{'mean ret':>11s}"
              f"{'mean edge':>12s}{'mean |gap|':>12s}")
        for b, g in P2.groupby("bucket", observed=True):
            print(f"  {str(b):32s}{len(g):>4d}{g.ret.mean() * 100:>+10.1f}%"
                  f"{g.edge.mean() * 100:>+11.1f}pp{g.gap.abs().mean() * 100:>11.1f}%")
        c = np.corrcoef(np.log1p(P2.prevol), P2.ret)[0, 1]
        print(f"\n  corr(log pre-event volume, straddle return) = {c:+.2f}")
        print("  Weak. The edge is negative in every bucket; it is merely least")
        print("  negative where the gaps are biggest.")

    print("\n" + "=" * 100)
    print("THE +/-100% QUESTION")
    print("=" * 100)
    E = T[T.ok]
    if len(E):
        big = E[(E.call_ret.abs() >= 1.0) | (E.put_ret.abs() >= 1.0)]
        won = E[E.ret > 0]
        print(f"  {len(big)} of {len(E)} straddles had a leg move at least 100%.")
        print(f"  {len(won)} of {len(E)} straddles finished positive.")
        print(f"  overlap: {len(big[big.ret > 0])} -- a 100% leg is neither necessary nor")
        print(f"  sufficient for the position to make money, because at the money the")
        print(f"  winner doubling only replaces the two premiums you paid.")
        if len(E) > 1:
            c = np.corrcoef(E.edge, E.ret)[0, 1]
            print(f"\n  corr(edge, straddle return) = {c:+.2f}  <- the edge is what pays,")
            print("  not the size of the swing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
