"""Selling the event straddle instead of buying it.

Every measurement so far says the buyer overpays: the straddles cost 11.3% of
spot on the executable set and the events delivered 6.2%, an edge of -5.1pp.
A negative edge for the buyer is a positive one for the seller, so this tests
the other side.

The accounting cannot simply be flipped
---------------------------------------
Reporting a short straddle as "minus the buyer's return" is arithmetically true
and financially misleading. The buyer stakes the premium and cannot lose more
than it. The seller **receives** the premium, stakes margin, and has no cap on
the loss: in the 2,842 earnings releases measured here the worst overnight gap
was **132.6%**, which against an 11% premium is roughly ten times the whole
credit on a single trade.

So three denominators are reported, and they answer different questions:

* **per contract, in dollars** -- what actually happened;
* **as a share of the premium collected** -- the mirror of the buyer's return,
  useful only for comparing the two sides;
* **as a share of margin** -- the number that decides whether the strategy is
  fundable, since margin and not premium is the capital at risk. Reg T on a
  short straddle is approximately the greater leg's naked requirement plus the
  other leg's premium; at the money that is close to 20% of the underlying plus
  the credit, which is what ``margin_for`` uses. Brokers differ and portfolio
  margin differs more, so it is an estimate, labelled as one.

Assignment is a real hazard this cannot price. One leg of an at-the-money
straddle is in the money the moment the stock gaps, and an American option can
be exercised against you overnight. The backtest closes both legs at a market
price and never gets assigned, which flatters the seller slightly.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Reg T short-option requirement on the naked leg, as a share of the underlying.
NAKED_PCT = 0.20


def margin_for(spot: float, premium: float) -> float:
    """Approximate Reg T initial margin for one short at-the-money straddle."""
    return NAKED_PCT * spot + premium


def summarise(label, pnl, prem, marg, stake=None):
    pnl = np.asarray(pnl, float)
    keep = np.isfinite(pnl)
    pnl, prem, marg = pnl[keep], np.asarray(prem, float)[keep], np.asarray(marg, float)[keep]
    if not len(pnl):
        print(f"  {label:28s}    --")
        return
    on_prem = pnl / prem
    on_marg = pnl / marg
    print(f"  {label:28s}{len(pnl):>4d}{pnl.sum() * 100:>+11.0f}{on_prem.mean() * 100:>+11.1f}%"
          f"{on_marg.mean() * 100:>+11.1f}%{(pnl > 0).mean() * 100:>8.0f}%"
          f"{pnl.min() * 100:>+11.0f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    args = ap.parse_args(argv)
    work = Path(args.work)

    T = pd.read_parquet(work / "straddles.parquet")
    T = T[T.skip == ""].copy()
    T["prem"] = T.call_entry + T.put_entry
    T["buyback_open"] = T.call_exit + T.put_exit
    T["buyback_close"] = T.call_exitclose + T.put_exitclose
    T["prevol"] = T[["call_prevol", "put_prevol"]].min(axis=1)
    T["ok"] = ((T.prevol >= 250)
               & (T[["call_preactive", "put_preactive"]].min(axis=1) >= 3)
               & T[["call_entry", "put_entry", "call_exit", "put_exit"]].notna().all(axis=1)
               & (T.prem > 0))
    T = T[T.prem.notna() & (T.prem > 0)]
    T["margin"] = [margin_for(s, p) for s, p in zip(T.spot_entry, T.prem)]
    T["pnl_open"] = T.prem - T.buyback_open
    T["pnl_close"] = T.prem - T.buyback_close
    T["gap"] = T.spot_exit_open / T.spot_entry - 1

    print("\n" + "=" * 104)
    print("SELLING THE STRADDLE: EVERY TRADE  (per one contract, dollars = x100)")
    print("=" * 104)
    print(f"  {'tkr':7s}{'spot':>8s}{'premium':>9s}{'margin':>8s}{'gap':>8s}"
          f"{'buy back':>10s}{'P&L':>8s}{'on prem':>9s}{'on margin':>11s}{'liq':>5s}")
    for _, r in T.sort_values("pnl_open").iterrows():
        print(f"  {r.ticker:7s}{r.spot_entry:>8.2f}{r.prem:>9.2f}{r.margin:>8.2f}"
              f"{r.gap * 100:>+7.1f}%{r.buyback_open:>10.2f}{r.pnl_open:>+8.2f}"
              f"{r.pnl_open / r.prem * 100:>+8.1f}%{r.pnl_open / r.margin * 100:>+10.1f}%"
              f"{('y' if r.ok else '-'):>5s}")

    print("\n" + "=" * 104)
    print("THE SHORT SIDE, SUMMARISED")
    print("=" * 104)
    print(f"  {'set / exit':28s}{'n':>4s}{'total $':>11s}{'on premium':>11s}"
          f"{'on margin':>11s}{'win':>8s}{'worst $':>11s}")
    E = T[T.ok]
    summarise("all priced, buy back at open", T.pnl_open, T.prem, T.margin)
    summarise("all priced, at that close", T.pnl_close, T.prem, T.margin)
    summarise("executable, buy back at open", E.pnl_open, E.prem, E.margin)
    summarise("executable, at that close", E.pnl_close, E.prem, E.margin)

    print("\n  'on margin' is the honest return: margin is the capital at risk,")
    print("  premium is only the credit received. 'worst' is a single trade.")

    print("\n" + "=" * 104)
    print("WHAT THE TAIL LOOKS LIKE ON 2,842 EARNINGS RELEASES")
    print("=" * 104)
    ex = work / "exits.parquet"
    if ex.exists():
        R = pd.read_parquet(ex)
        print("\n" + "=" * 104)
        print("WHEN THE SELLER SHOULD BUY IT BACK  (the mirror of the buyer's exit study)")
        print("=" * 104)
        print(f"  {'buy the position back at':32s}{'n':>4s}{'on premium':>13s}{'win':>8s}")
        for c, lab in (("open_ret", "the opening print"),
                       ("d1close", "that afternoon's close"),
                       ("last", "the end of the hold window"),
                       ("ceiling", "the buyer's best minute")):
            if c not in R:
                continue
            v = (-R[c].dropna()).to_numpy()
            if not len(v):
                continue
            print(f"  {lab:32s}{len(v):>4d}{v.mean() * 100:>+12.1f}%"
                  f"{(v > 0).mean() * 100:>7.0f}%")
        print("\n  The best of these is holding to the end of the window, which is the")
        print("  mirror of the buyer decaying from the opening bell -- but the ordering")
        print("  is not monotone and five trades cannot establish it. What it does show")
        print("  is that the edge is an AT-EXPIRY quantity: closing early hands most of")
        print("  it back, and closing early is also the only way to cap the tail.")

    G = pd.read_parquet(work / "gaps.parquet")
    g = G.gap.abs()
    for prem in (0.113, 0.137):
        # at expiry a short straddle keeps premium minus the move; before expiry
        # it keeps less, so this is the optimistic bound on the same distribution
        pl = prem - g
        loss = pl[pl < 0]
        print(f"\n  premium {prem * 100:.1f}% of spot, held to expiry (optimistic):")
        print(f"    mean P&L                 {pl.mean() * 100:>+6.2f}% of spot")
        print(f"    win rate                 {(pl > 0).mean() * 100:>6.1f}%")
        print(f"    average loss when wrong  {loss.mean() * 100:>+6.2f}% of spot "
              f"({loss.mean() / prem * 100:>+.0f}% of the credit)")
        print(f"    worst single trade       {pl.min() * 100:>+6.1f}% of spot "
              f"({pl.min() / prem * 100:>+.0f}% of the credit)")
        print(f"    trades that lose >1x the credit  {(g > 2 * prem).mean() * 100:>5.1f}%")
        print(f"    one bad trade wipes out          "
              f"{abs(pl.min()) / pl[pl > 0].mean():>5.0f} average winners")

    print("\n" + "=" * 104)
    print("THE SAME TAIL, ON THE CAPITAL YOU ACTUALLY POST")
    print("=" * 104)
    print("  Premium is the credit received; margin is what is at risk. Dividing by")
    print("  margin is the only framing in which a short option book can be compared")
    print("  to anything else.\n")
    for prem in (0.113, 0.137):
        marg = NAKED_PCT + prem
        pl = (prem - g) / marg
        win = pl[pl > 0]
        ruin = (pl < -1).mean() * 100
        print(f"  premium {prem * 100:.1f}% of spot, margin about {marg * 100:.1f}% of spot")
        print(f"    mean return on margin, per trade   {pl.mean() * 100:>+8.1f}%")
        print(f"    a typical winner                   {win.mean() * 100:>+8.1f}%")
        print(f"    the 1-in-100 trade                 {np.percentile(pl, 1) * 100:>+8.1f}%")
        print(f"    the worst trade in 2,842           {pl.min() * 100:>+8.1f}%"
              f"   ({abs(pl.min()):.1f}x the capital posted)")
        print(f"    winners erased by that one         {abs(pl.min()) / win.mean():>8.0f}")
        print(f"    trades losing more than the margin {ruin:>8.2f}%"
              f"   (about 1 in {100 / max(ruin, 1e-9):.0f})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
