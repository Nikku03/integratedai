"""What the short vertical returned, and at what bid-ask it stops returning it.

Return is quoted on **margin** -- the width less the credit, which for a defined
-risk spread is both the worst case and the capital a broker holds against it.
It is knowable before the trade rather than discovered after, and comparable
across names of very different price.

The costs are the point of this report, not a footnote to it. Every earlier
number in this repository was gross of the bid-ask spread, and the four-legged
butterfly that looked like +24.3% on margin turned out to break even at $0.063
per leg -- inside the minimum tick. So the net line is computed first and the
gross line is shown beside it for reference, and the quantity actually reported
is the **break-even half-spread**: the per-crossing cost at which the mean P&L
reaches zero. That number can be compared against a real quote screen; a return
gross of costs cannot.

A vertical cannot be worth more than its width. Closing marks that exceed it come
from two prints taken at different moments, not from a position that lost more
than it structurally can, so they are clamped and the clamp is reported.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BUTTERFLY_BREAKEVEN = 0.063     # measured, RESULT_CREDIT_SPREAD.md
TICK = 0.05                     # minimum increment US options quote above $3
LEGS = 4                        # two legs in, two out


def clustered_ci(x: np.ndarray, day: np.ndarray, n: int = 20000) -> tuple:
    """Resample whole sessions. Events on one day share that day's tape."""
    rng = np.random.default_rng(0)
    days = np.unique(day)
    by = {d: x[day == d] for d in days}
    out = np.empty(n)
    for i in range(n):
        pick = rng.choice(days, len(days))
        out[i] = np.concatenate([by[d] for d in pick]).mean()
    return float(np.percentile(out, 2.5)), float(np.percentile(out, 97.5))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trades", default="/tmp/claude-0/opt/vert_trades.parquet")
    ap.add_argument("--cost", type=float, default=TICK)
    args = ap.parse_args(argv)

    D = pd.read_parquet(args.trades)
    n_all = len(D)
    D = D[D[["short_in", "short_out", "long_in", "long_out"]].notna().all(axis=1)].copy()
    print(f"\n  {len(D)} of {n_all} spreads have all four marks\n")
    if D.empty:
        print("  nothing to report")
        return 0

    D["credit"] = D.short_in - D.long_in
    raw = D.short_out - D.long_out
    D["clamped"] = (raw > D.width + 1e-9) | (raw < -1e-9)
    D["close_cost"] = raw.clip(lower=0.0, upper=D.width)
    D["pnl"] = D.credit - D.close_cost
    D["margin"] = D.width - D.credit
    D = D[D.margin > 0].copy()
    D["ret"] = D.pnl / D.margin
    D["gap"] = D.spot_out / D.spot_in - 1
    D["cost_all"] = LEGS * args.cost
    D["pnl_net"] = D.pnl - D.cost_all
    D["ret_net"] = D.pnl_net / D.margin

    print("=" * 104)
    print("EVERY SPREAD  (sold at the close before the release, bought back into the gap)")
    print("=" * 104)
    print(f"  {'tkr':7s}{'entry':12s}{'side':6s}{'strikes':>13s}{'w':>7s}"
          f"{'gap':>8s}{'credit':>8s}{'close':>8s}{'P&L':>8s}"
          f"{'margin':>8s}{'on marg':>9s}{'net':>8s}")
    for _, r in D.sort_values("ret").iterrows():
        print(f"  {r.ticker:7s}{r.entry:12s}{r.side:6s}"
              f"{f'{r.k_short:g}/{r.k_long:g}':>13s}{r.width:>7.1f}"
              f"{r.gap * 100:>+7.1f}%{r.credit:>8.2f}{r.close_cost:>8.2f}"
              f"{r.pnl:>+8.2f}{r.margin:>8.2f}{r.ret * 100:>+8.0f}%"
              f"{r.ret_net * 100:>+7.0f}%")

    x, xn = D.ret.to_numpy(), D.ret_net.to_numpy()
    day = D.entry.to_numpy()
    print("\n" + "=" * 104)
    print("THE RESULT")
    print("=" * 104)
    print(f"  {'':34s}{'gross':>14s}{'net of $%.2f/leg' % args.cost:>20s}")
    print(f"  {'mean return on margin':34s}{x.mean() * 100:>+13.1f}%{xn.mean() * 100:>+19.1f}%")
    print(f"  {'median':34s}{np.median(x) * 100:>+13.1f}%{np.median(xn) * 100:>+19.1f}%")
    print(f"  {'win rate':34s}{(x > 0).mean() * 100:>13.0f}%{(xn > 0).mean() * 100:>19.0f}%")
    print(f"  {'worst single trade':34s}{x.min() * 100:>+13.0f}%{xn.min() * 100:>+19.0f}%")
    print(f"  {'best single trade':34s}{x.max() * 100:>+13.0f}%{xn.max() * 100:>+19.0f}%")
    print(f"  {'total P&L, per share':34s}{D.pnl.sum():>+13.2f}{D.pnl_net.sum():>+19.2f}")
    if len(D) > 2:
        lo, hi = clustered_ci(x, day)
        ln, hn = clustered_ci(xn, day)
        print(f"  {'95% CI on the mean (by session)':34s}"
              f"{f'[{lo * 100:+.0f}, {hi * 100:+.0f}]%':>14s}"
              f"{f'[{ln * 100:+.0f}, {hn * 100:+.0f}]%':>20s}")
        print(f"  {'sessions / trades':34s}{f'{len(np.unique(day))} / {len(D)}':>14s}")

    print("\n" + "=" * 104)
    print("THE NUMBER THAT DECIDES IT: BREAK-EVEN HALF-SPREAD")
    print("=" * 104)
    be = D.pnl.mean() / LEGS
    print(f"  mean gross P&L per spread          {D.pnl.mean():>+8.3f} per share")
    print(f"  crossings paid per spread          {LEGS:>8d}")
    print(f"  break-even cost per crossing       {be:>8.3f}")
    print(f"  the butterfly's, measured          {BUTTERFLY_BREAKEVEN:>8.3f}")
    print(f"  minimum tick above $3              {TICK:>8.3f}")
    if be == be:
        print(f"\n  ratio to the butterfly             {be / BUTTERFLY_BREAKEVEN:>8.2f}x"
              f"   (H3 predicted ~2x)")
        verdict = ("CLEARS the minimum tick" if be > TICK
                   else "does NOT clear the minimum tick")
        print(f"  versus the tick                    {verdict}")

    print("\n" + "=" * 104)
    print("SENSITIVITY: MEAN RETURN ON MARGIN AT EACH ASSUMED HALF-SPREAD")
    print("=" * 104)
    print(f"  {'$/crossing':>12s}{'mean on margin':>18s}{'win rate':>11s}{'total P&L':>12s}")
    for c in (0.00, 0.01, 0.02, 0.03, 0.05, 0.075, 0.10):
        p = D.pnl - LEGS * c
        r = p / D.margin
        print(f"  {c:>12.3f}{r.mean() * 100:>+17.1f}%{(r > 0).mean() * 100:>10.0f}%"
              f"{p.sum():>+12.2f}")

    print("\n" + "=" * 104)
    print("WHAT THE SIGNAL ACTUALLY DID")
    print("=" * 104)
    print(f"  {'':30s}{'n':>5s}{'mean gap':>11s}{'mean on margin':>17s}{'win':>7s}")
    for lab, g in (("sold calls (ran up)", D[D.side == "call"]),
                   ("sold puts (ran down)", D[D.side == "put"])):
        if len(g):
            print(f"  {lab:30s}{len(g):>5d}{g.gap.mean() * 100:>+10.1f}%"
                  f"{g.ret.mean() * 100:>+16.1f}%{(g.ret > 0).mean() * 100:>6.0f}%")
    hit = ((D.side == "call") & (D.gap <= 0)) | ((D.side == "put") & (D.gap >= 0))
    print(f"\n  the gap went the way the signal said on "
          f"{int(hit.sum())} of {len(D)} ({hit.mean() * 100:.0f}%)")
    print(f"  spread finished out of the money on "
          f"{int((D.close_cost < 1e-9).sum())} of {len(D)}")
    if D.clamped.any():
        print(f"\n  {int(D.clamped.sum())} closing marks fell outside [0, width] and were "
              f"clamped ({', '.join(D[D.clamped].ticker)}):")
        print("  two prints from different moments, not a position beyond its bounds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
