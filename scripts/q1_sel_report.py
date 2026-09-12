"""What the reversal rule earned once it had to pay for an option.

Direction accuracy and profit are different questions and this separates them.
The rule's edge was established on the underlying -- 61.9% of 118 gaps called
correctly, day-clustered interval [53.2, 69.7]. Whether that survives the
premium is what these trades answer.

Only the leg the rule buys was priced, so the momentum arm appears here by its
direction accuracy alone; its option P&L was not measured and is not guessed at.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

MIN_VOL = 100


def arm(label, r, stake=40.0):
    r = np.asarray([x for x in r if x == x], float)
    if not len(r):
        print(f"  {label:32s}{'--':>5s}")
        return
    eq = stake
    for x in r:
        eq *= (1 + x)
    print(f"  {label:32s}{len(r):>5d}{r.mean() * 100:>+10.1f}%{np.median(r) * 100:>+10.1f}%"
          f"{(r > 0).mean() * 100:>8.0f}%{eq:>10.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)
    T = pd.read_parquet(Path(args.work) / "q1_sel_trades.parquet")

    drop = T[T.skip != ""]
    if len(drop):
        print("=" * 96)
        print("WHY EVENTS DROPPED OUT")
        print("=" * 96)
        for why, g in drop.groupby("skip"):
            print(f"  {len(g):>3d}  {why:28s}{', '.join(sorted(g.ticker))[:52]}")

    T = T[(T.skip == "") & T.opt_buy.notna() & T.opt_sell.notna() & (T.opt_buy > 0)].copy()
    T["ret"] = T.opt_sell / T.opt_buy - 1
    T["want"] = np.where(T.side == "call", 1, -1)
    T["right"] = np.sign(T.gap) == T.want
    T["prem_pct"] = T.opt_buy / T.spot_buy
    T["edge"] = T.gap.abs() - T.prem_pct
    T["ok"] = T.prevol >= MIN_VOL

    print("\n" + "=" * 96)
    print("EVERY TRADE  (bought at the last close before the release, sold into the gap)")
    print("=" * 96)
    print(f"  {'tkr':7s}{'entry':12s}{'side':5s}{'dte':>4s}{'run5':>8s}{'gap':>8s}"
          f"{'right':>6s}{'premium':>9s}{'option':>9s}{'prevol':>9s}")
    for _, r in T.sort_values("ret", ascending=False).iterrows():
        print(f"  {r.ticker:7s}{r.entry:12s}{r.side:5s}{r.dte:>4.0f}"
              f"{r.pre_run5 * 100:>+7.1f}%{r.gap * 100:>+7.1f}%"
              f"{('yes' if r.right else 'no'):>6s}{r.prem_pct * 100:>8.1f}%"
              f"{r.ret * 100:>+8.0f}%{r.prevol:>9,.0f}")

    print("\n" + "=" * 96)
    print(f"ARMS  (${args.stake:.0f} compounded)")
    print("=" * 96)
    print(f"  {'arm':32s}{'n':>5s}{'mean':>10s}{'median':>10s}{'win':>8s}{'$40 ->':>10s}")
    arm("REVERSAL, all priced", T.ret, args.stake)
    E = T[T.ok]
    arm("REVERSAL, tradeable contract", E.ret, args.stake)
    arm("  where direction was right", E[E.right].ret, args.stake)
    arm("  where direction was wrong", E[~E.right].ret, args.stake)
    arm("  the underlying, bet direction", E.gap * E.want, args.stake)

    print("\n" + "=" * 96)
    print("DIRECTION versus PROFIT")
    print("=" * 96)
    n = len(E)
    acc = E.right.mean()
    se = np.sqrt(acc * (1 - acc) / max(n, 1))
    print(f"  on these {n} priced trades the rule called direction right "
          f"{acc * 100:.1f}%  [{(acc - 1.96 * se) * 100:.0f}, {(acc + 1.96 * se) * 100:.0f}]")
    print(f"  on the full 118-event underlying sample it was 61.9%  [53.2, 69.7]")
    if len(E[E.right]) and len(E[~E.right]):
        up, dn = E[E.right].ret.mean(), E[~E.right].ret.mean()
        need = -dn / (up - dn)
        print(f"\n  a right call paid {up * 100:+.1f}%   a wrong one {dn * 100:+.1f}%")
        print(f"  break-even accuracy on these actual prices: **{need * 100:.1f}%**")
        print(f"  the rule delivered {acc * 100:.1f}%  ->  shortfall "
              f"{(acc - need) * 100:+.1f} percentage points")

    print("\n" + "=" * 96)
    print("WHY BEING RIGHT WAS NOT ENOUGH")
    print("=" * 96)
    print("  The gap has to clear the premium, not merely point the right way.\n")
    print(f"  mean premium paid               {E.prem_pct.mean() * 100:>6.1f}% of spot")
    print(f"  mean |gap| delivered            {E.gap.abs().mean() * 100:>6.1f}%")
    print(f"  mean edge (|gap| - premium)     {E.edge.mean() * 100:>+6.1f}pp")
    print(f"  gap cleared the premium in      {(E.edge > 0).mean() * 100:>5.0f}% of trades")
    R = E[E.right]
    if len(R):
        print(f"\n  among the {len(R)} where direction was RIGHT:")
        print(f"    mean gap in your favour       {R.gap.abs().mean() * 100:>6.1f}%")
        print(f"    mean premium paid             {R.prem_pct.mean() * 100:>6.1f}%")
        print(f"    {(R.ret < 0).sum()} of {len(R)} still lost money")
    return 0


if __name__ == "__main__":
    sys.exit(main())
