"""What the six option trades did, against what was registered in advance.

Four arms are reported from the same contracts, because pricing both legs of
every name costs nothing extra once the chain has been pulled:

* **directional** -- the requested book. One contract per name, a call on a
  positive reading and a put on a negative one.
* **best only** -- the single highest-scoring name each session, which is the
  trade the design says to actually take.
* **second only** -- the diversification leg, reported separately so H1 can be
  answered rather than asserted.
* **straddle** -- one call and one put at the same strike. This is the arm the
  repository's evidence supports, because the measurement that has held up
  across 160,920 rows is that this gate concentrates dispersion and predicts
  direction badly.

The underlying's own return over the same window is reported beside every
option, since an option that loses money on a stock that moved the right way is
a different failure from one that loses money on a stock that went the wrong way.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def compound(rets, stake=40.0):
    path, eq = [], stake
    for r in rets:
        eq *= (1 + r)
        path.append(eq)
    return path


def arm(T, rets, label, stake=40.0):
    r = np.asarray([x for x in rets if x == x], dtype=float)
    if not len(r):
        print(f"  {label:22s} no trades")
        return
    path = compound(r, stake)
    lg = np.log1p(np.clip(r, -0.999, None))
    print(f"  {label:22s}{len(r):>4d}{r.mean() * 100:>+10.1f}%"
          f"{np.median(r) * 100:>+10.1f}%{(r > 0).mean() * 100:>8.0f}%"
          f"{(np.exp(lg.mean()) - 1) * 100:>+12.1f}%{path[-1]:>10.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)
    T = pd.read_parquet(Path(args.work) / "trades.parquet")

    T["under_ret"] = T.spot_exit / T.spot_open - 1
    T["dir_ret"] = np.where(T.side == "call", T.call_ret, T.put_ret)
    T["dir_entry"] = np.where(T.side == "call", T.call_entry, T.put_entry)
    T["dir_exit"] = np.where(T.side == "call", T.call_exit, T.put_exit)
    T["straddle_entry"] = T.call_entry + T.put_entry
    T["straddle_exit"] = T.call_exit + T.put_exit
    T["straddle_ret"] = T.straddle_exit / T.straddle_entry - 1
    T["rank"] = T.groupby("date").cumcount() + 1

    print("\n" + "=" * 100)
    print("EVERY TRADE")
    print("=" * 100)
    print(f"  {'date':11s}{'tkr':6s}{'rk':>3s}{'judge':>6s}{'side':>6s}{'K':>8s}"
          f"{'entry':>8s}{'exit':>8s}{'option':>10s}{'stock':>9s}  thesis")
    for _, r in T.iterrows():
        print(f"  {r.date:11s}{r.ticker:6s}{r['rank']:>3d}{r.judge:>+6d}{r.side:>6s}"
              f"{r.strike:>8.1f}{r.dir_entry:>8.2f}{r.dir_exit:>8.2f}"
              f"{r.dir_ret * 100:>+9.1f}%{r.under_ret * 100:>+8.1f}%  {r.thesis[:38]}")

    print("\n" + "=" * 100)
    print(f"ARMS  (${args.stake:.0f} compounded trade by trade, in date order)")
    print("=" * 100)
    print(f"  {'arm':22s}{'n':>4s}{'mean':>10s}{'median':>10s}{'win':>8s}"
          f"{'compounds':>12s}{'$40 ->':>10s}")
    S = T.sort_values(["date", "rank"])
    arm(S, S.dir_ret, "directional, both", args.stake)
    arm(S, S[S["rank"] == 1].dir_ret, "best only", args.stake)
    arm(S, S[S["rank"] == 2].dir_ret, "second only", args.stake)
    arm(S, S.straddle_ret, "straddle, both", args.stake)
    arm(S, S.call_ret, "always the call", args.stake)
    arm(S, S.put_ret, "always the put", args.stake)
    arm(S, S.under_ret, "the stock itself", args.stake)

    print("\n" + "=" * 100)
    print("AGAINST THE PRE-REGISTRATION")
    print("=" * 100)
    b = S[S["rank"] == 1].dir_ret.mean()
    s = S[S["rank"] == 2].dir_ret.mean()
    print(f"  H1  best {b * 100:+.1f}% vs second {s * 100:+.1f}%  ->  "
          f"{'PASS' if b > s else 'FAIL'}  (n=3 vs 3; this resolves nothing)")
    neg = S[S.judge < 0]
    pos = S[S.judge > 0]
    if len(neg):
        print(f"  H2  judged negative: option {neg.dir_ret.mean() * 100:+.1f}%, "
              f"stock {neg.under_ret.mean() * 100:+.1f}%  (n={len(neg)})")
    if len(pos):
        print(f"  H3  judged positive: option {pos.dir_ret.mean() * 100:+.1f}%, "
              f"stock {pos.under_ret.mean() * 100:+.1f}%  (n={len(pos)})")
    print(f"  H4  straddle {S.straddle_ret.mean() * 100:+.1f}% vs "
          f"directional {S.dir_ret.mean() * 100:+.1f}%  ->  "
          f"{'PASS' if S.straddle_ret.mean() > S.dir_ret.mean() else 'FAIL'}")

    print("\n" + "=" * 100)
    print("WHAT THE OPTION COST THAT THE STOCK DID NOT")
    print("=" * 100)
    print("  The move the stock made, and what the option did with it. A stock that")
    print("  moved the right way and an option that still lost is time and implied")
    print("  volatility, not a wrong call.\n")
    print(f"  {'tkr':6s}{'stock':>9s}{'right way?':>12s}{'option':>10s}{'gap':>10s}")
    for _, r in S.iterrows():
        want = 1 if r.side == "call" else -1
        right = (np.sign(r.under_ret) == want)
        print(f"  {r.ticker:6s}{r.under_ret * 100:>+8.1f}%{str(right):>12s}"
              f"{r.dir_ret * 100:>+9.1f}%{(r.dir_ret - want * r.under_ret) * 100:>+9.1f}pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
