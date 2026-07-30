"""Were there 10%+ moves, and did the exit rule forbid catching them?

A 6% target caps every winner at exactly 6%. That is not a finding about the
market, it is arithmetic about the rule, so "we caught no moonshots" needs
separating into two questions that have different answers:

1. **Was a 10%+ move available?** Hindsight ceiling: the highest price that
   printed after the entry bar. Not achievable -- nobody sells the top -- but it
   bounds what any exit rule could have taken.
2. **Would a rule you could actually run have taken it?** A trailing stop gives
   back a fixed fraction of the peak and needs no foresight, so it is the honest
   version of "let winners run".

The scan reports both, per cohort, so the cost of the trap screen is visible:
if the moonshots are concentrated in the filings a reader flagged as traps, then
avoiding traps and catching moonshots are the same decision made in opposite
directions, and the screen is not free.

Every price here comes from minute bars, which carry no quotes. On a $2.68 name
whose entire daily tape is $240k, the printed high and the price at which $40
could have left are not the same number, and nothing in this file pretends
otherwise -- see ``liquidity_at_peak``.

Usage
-----
    python scripts/moonshot_scan.py --max-hold-bars 3900
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Exit rules compared. ``target=None`` means "no profit target, let it run".
#: ``trail`` is the fraction given back from the running high-water mark.
RULES = [
    ("6% target / 10% stop", 0.06, 0.10, None),
    ("no target / 10% stop", None, 0.10, None),
    ("trail 10%",            None, 0.10, 0.10),
    ("trail 15%",            None, 0.15, 0.15),
    ("trail 20%",            None, 0.20, 0.20),
    ("trail 25%",            None, 0.25, 0.25),
]


def walk(bars: pd.DataFrame, i_ent: int, entry: float, target, stop, trail,
         max_bars: int) -> tuple[float, str, int]:
    """One trade's exit, decided bar by bar with no bar read before its turn.

    The trailing stop ratchets off the running high of bars *already seen*, so
    it never uses a peak that has not happened yet. A stop fills at
    ``min(level, bar_low)`` so a gap through it costs what it cost.

    **A bar with zero volume cannot trigger anything.** 23.7% of minute bars in
    this cache report no trades, and 22,180 of those still carry a high-low
    range wider than 2% of price -- stale or phantom quotes in thin pre- and
    post-market sessions, ranging up to 84%. Letting one fill an order invents a
    trade that did not happen, and it does so asymmetrically: a phantom low
    stops a winner out while a phantom high never has to be honoured. On AMIX a
    single zero-volume bar (high 3.70, low 2.75, volume 0) turned a +170%
    ceiling into a +2.6% exit.
    """
    up = entry * (1 + target) if target is not None else np.inf
    hw = entry
    last = min(i_ent + max_bars, len(bars) - 1)
    for j in range(i_ent + 1, last + 1):
        if not (float(bars["volume"].iloc[j]) > 0):
            continue
        hi, lo = float(bars["high"].iloc[j]), float(bars["low"].iloc[j])
        if not (np.isfinite(hi) and np.isfinite(lo)):
            continue
        level = entry * (1 - stop)
        if trail is not None:
            level = max(level, hw * (1 - trail))
        hit_dn, hit_up = lo <= level, hi >= up
        if hit_dn:                       # ambiguity resolves against the trade
            return min(level, lo), "stop", j
        if hit_up:
            return up, "target", j
        hw = max(hw, hi)                 # ratchet only after this bar resolved

    # Time exit must also land on a bar that traded; walk back to the last one.
    j = last
    while j > i_ent and not (float(bars["volume"].iloc[j]) > 0):
        j -= 1
    return float(bars["low"].iloc[j]), "time", j


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--bars", default="/root/.iai/minutecache")
    ap.add_argument("--max-hold-bars", type=int, default=3900)   # ~10 sessions
    ap.add_argument("--order-usd", type=float, default=40.0)
    args = ap.parse_args(argv)

    root, bd = Path(args.root), Path(args.bars)
    m = pd.read_parquet(root / "classified_final.parquet")
    m["filed_utc"] = pd.to_datetime(m["filed_et"], utc=True)

    recs = []
    for f in m.to_dict("records"):
        p = bd / f"{f['ticker']}.parquet"
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        tv = b["t_utc"].to_numpy()
        t = np.datetime64(f["filed_utc"].tz_convert("UTC").tz_localize(None))
        i = int(np.searchsorted(tv, t + np.timedelta64(1, "m"), "left"))
        if i >= len(b) or not (float(b["volume"].iloc[i]) > 0):
            continue
        e = float(b["high"].iloc[i])
        if not np.isfinite(e) or e <= 0:
            continue

        seg = b.iloc[i + 1: min(i + args.max_hold_bars, len(b) - 1) + 1]
        seg = seg[seg["volume"].fillna(0) > 0]   # a price nobody traded at is not a price
        if seg.empty:
            continue
        k = seg["high"].idxmax()
        # What the tape could absorb in the minute the top printed. At $40 this
        # is the difference between a number and a fill.
        peak_bar_usd = float(b.loc[k, "close"] * b.loc[k, "volume"])

        r = {"ticker": f["ticker"], "band": f["band"],
             "verdict": f["final_verdict"], "impact": f["final_impact"],
             "entry": e,
             "ceiling": float(seg["high"].max()) / e - 1.0,
             "trough": float(seg["low"].min()) / e - 1.0,
             "peak_et": pd.to_datetime(b.loc[k, "t"], utc=True).tz_convert(
                 "America/New_York"),
             "liquidity_at_peak": peak_bar_usd}
        for label, tgt, stp, trl in RULES:
            px, why, _ = walk(b, i, e, tgt, stp, trl, args.max_hold_bars)
            r[label] = px / e - 1.0
            r[label + " :why"] = why
        recs.append(r)

    d = pd.DataFrame(recs)
    d.to_parquet(root / "moonshot_rules.parquet")
    print(f"{len(d)} filings with a usable entry, hold cap "
          f"{args.max_hold_bars} bars\n")

    print("HINDSIGHT CEILING -- highest price printed after entry (not achievable):")
    c = d["ceiling"]
    print(f"  median {c.median() * 100:+.2f}%   >=10%: {(c >= .10).sum()} "
          f"({(c >= .10).mean() * 100:.0f}%)   >=20%: {(c >= .20).sum()}   "
          f"max {c.max() * 100:+.1f}%")
    print("\n  by cohort:")
    print(d.groupby("verdict").apply(lambda g: pd.Series({
        "n": len(g), "pct>=10%": (g.ceiling >= .10).mean() * 100,
        "median ceiling": g.ceiling.median() * 100,
        "median trough": g.trough.median() * 100}),
        include_groups=False).round(1).to_string())

    print("\n\nWHAT AN IMPLEMENTABLE RULE TAKES (mean % per filing):")
    hdr = f"{'rule':22s}{'all 83':>9s}{'positive':>10s}{'neutral':>9s}{'trap':>9s}" \
          f"{'>=10% caught':>13s}{'best':>8s}"
    print(hdr)
    for label, *_ in RULES:
        row = d[label]
        print(f"{label:22s}{row.mean() * 100:+8.2f}%"
              f"{d.loc[d.verdict == 'positive', label].mean() * 100:+9.2f}%"
              f"{d.loc[d.verdict == 'neutral', label].mean() * 100:+8.2f}%"
              f"{d.loc[d.verdict == 'trap', label].mean() * 100:+8.2f}%"
              f"{(row >= .10).sum():>10d}   {row.max() * 100:+7.1f}%")

    print("\n\nTHE MOONSHOTS -- every filing whose ceiling cleared +10%:")
    big = d[d.ceiling >= .10].sort_values("ceiling", ascending=False)
    print(f"{'tkr':6s}{'band':7s}{'verdict':9s}{'ceiling':>9s}{'trough':>8s}"
          f"{'6%tgt':>7s}{'trail20':>8s}{'peak ET':>13s}{'$ at peak':>11s}")
    for _, r in big.iterrows():
        print(f"{r.ticker:6s}{r.band:7s}{r.verdict:9s}{r.ceiling * 100:+8.1f}%"
              f"{r.trough * 100:+7.1f}%{r['6% target / 10% stop'] * 100:+6.1f}%"
              f"{r['trail 20%'] * 100:+7.1f}%"
              f"{r.peak_et.strftime('%m-%d %H:%M'):>13s}"
              f"{r.liquidity_at_peak:>10,.0f}")

    thin = big[big.liquidity_at_peak < 20 * args.order_usd]
    print(f"\n{len(thin)} of {len(big)} peaks printed in a minute that traded less "
          f"than {20 * args.order_usd:,.0f} dollars -- at a ${args.order_usd:.0f} "
          "order those tops are quotes, not exits.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
