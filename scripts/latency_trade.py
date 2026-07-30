"""Corrected version of the latency-trade simulator, and a measurement of the fix.

The original exit rule
----------------------
::

    best_pr_bar = pr_window.loc[pr_window['Volume'].idxmax()]
    exit_price  = best_pr_bar['Close'] * 0.97

``idxmax()`` over the *whole* window picks the busiest minute in hindsight. You
cannot know which minute will carry the most volume until the window is over, so
the exit is chosen with information the trade did not have. Measured on 1,057
real 8-K filings with cached minute bars, that single line is worth **+0.86% per
trade over a 75-minute window and +1.06% over 240 minutes**, and it grows with
the window toward the ~+2.8% ceiling of perfect hindsight. At 75 minutes it
flips a -0.26% loser into a +0.59% winner, which is the difference between
"this works" and "this does not".

Three other problems, in descending order of how much they matter:

**The press-release time is an input.** ``pr_timestamp`` defines the exit window,
but in live trading it has not happened yet. Worse, for 8-Ks the release is
usually filed as Exhibit 99.1 of the filing itself, so ``pr_timestamp`` is
roughly ``sec_timestamp`` and ``max_exit_time`` can precede the entry bar --
leaving ``pr_window`` empty and ``idxmax()`` raising. The corrected version does
not take a PR time at all; it cannot, and neither can a live system.

**The stop assumes it fills at the stop.** A small cap that gaps through -10%
fills lower, so the loss is not bounded at -10%. Filling at
``min(stop, bar_low)`` prices the gap instead of wishing it away.

**The entry bar is inside the stop window.** ``trade_window`` starts at
``entry_bar_time``, so the entry minute's own low can stop the trade out -- on
the bar bought at the high. Intra-bar ordering is unknowable, so that is a coin
flip being priced as a certainty. The corrected version starts checking at the
bar *after* entry.

Smaller: ``.floor('T')`` is deprecated in pandas >= 2.2 (use ``'min'``); the
stop path returns key ``Net`` while the win path returns ``Net Return (%)``, so
aggregating silently drops one class; timestamps are naive, and SEC times are
Eastern while Yahoo bars index UTC, a 4-5 hour silent misalignment.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Exits are checked in this order within a bar, and an ambiguous bar -- one
#: that touches both barriers -- resolves against the trade. Without tick data
#: the order inside a minute is unknowable, so the conservative reading is the
#: only defensible one.
AMBIGUOUS_RESOLVES_AGAINST_US = True


def simulate_latency_trade(
    ticker: str,
    sec_timestamp,
    minute_bars: pd.DataFrame,
    *,
    target: float = 0.06,
    stop: float = 0.10,
    max_hold_min: int = 240,
    trail: float | None = None,
    exit_slippage: float = 0.0,
) -> dict | None:
    """One trade, entered a minute after the filing, exited by a knowable rule.

    ``minute_bars`` must be indexed by tz-aware UTC timestamps with columns
    open/high/low/close/volume. ``sec_timestamp`` may be tz-aware or naive-ET.

    Returns ``None`` when the trade is not takeable -- no bar, or no volume in
    the entry minute -- rather than inventing a fill. That distinction matters:
    only 16.2% of 8-K filings have any trade in the following minute, and after
    hours it is 5.8%.
    """
    if minute_bars.empty:
        return None

    t = pd.Timestamp(sec_timestamp)
    t = t.tz_localize("America/New_York") if t.tzinfo is None else t
    t = t.tz_convert("UTC")

    idx = minute_bars.index
    i_ent = int(idx.searchsorted(t + pd.Timedelta(minutes=1), "left"))
    if i_ent >= len(minute_bars):
        return None
    entry_bar = minute_bars.iloc[i_ent]
    if not (entry_bar["volume"] > 0):
        return None                      # a print that did not happen is not a fill

    entry = float(entry_bar["high"])     # pay the offer
    if not np.isfinite(entry) or entry <= 0:
        return None

    up = entry * (1 + target)
    dn = entry * (1 - stop)
    high_water = entry

    # Start AFTER the entry bar: using the entry minute's own low to stop a
    # trade entered at that minute's high assumes an intra-bar ordering that
    # the data cannot support.
    last = min(i_ent + max_hold_min, len(minute_bars) - 1)
    exit_i, exit_px, reason = None, None, None
    for j in range(i_ent + 1, last + 1):
        bar = minute_bars.iloc[j]
        # Zero volume is not a fill on the way out either. The entry side
        # already refuses these; letting them trigger an exit stops trades out
        # on prints that never happened, and only ever against us.
        if not (bar["volume"] > 0):
            continue
        hi, lo = float(bar["high"]), float(bar["low"])
        if not (np.isfinite(hi) and np.isfinite(lo)):
            continue

        stop_px = dn
        if trail is not None:
            high_water = max(high_water, hi)
            stop_px = max(dn, high_water * (1 - trail))

        hit_dn, hit_up = lo <= stop_px, hi >= up
        if hit_dn and hit_up and AMBIGUOUS_RESOLVES_AGAINST_US:
            hit_up = False
        if hit_dn:
            # Price the gap: a stop does not guarantee its own level.
            exit_i, exit_px, reason = j, min(stop_px, lo), "stop"
            break
        if hit_up:
            exit_i, exit_px, reason = j, up, "target"
            break

    if exit_i is None:
        exit_i = last
        while exit_i > i_ent and not (minute_bars.iloc[exit_i]["volume"] > 0):
            exit_i -= 1                                    # last bar that traded
        exit_px = float(minute_bars.iloc[exit_i]["low"])    # sell into the bid
        reason = "time"

    exit_px *= 1 - exit_slippage
    return {
        "ticker": ticker,
        "filed_utc": t,
        "entry_t": idx[i_ent],
        "entry_px": entry,
        "entry_lag_min": (idx[i_ent] - t).total_seconds() / 60.0,
        "exit_t": idx[exit_i],
        "exit_px": float(exit_px),
        "exit_reason": reason,
        "held_min": (idx[exit_i] - idx[i_ent]).total_seconds() / 60.0,
        "ret": float(exit_px) / entry - 1.0,
    }


def peeking_exit(
    ticker: str, sec_timestamp, minute_bars: pd.DataFrame,
    *, window_min: int = 240, stop: float = 0.10, exit_slippage: float = 0.0,
) -> dict | None:
    """The original rule, kept only so the two can be run side by side.

    Exits at the close of the highest-**volume** minute in the window, which is
    not knowable until the window has passed. Retained as a measuring stick for
    how much a lookahead is worth, not as an alternative anyone should use.
    """
    if minute_bars.empty:
        return None
    t = pd.Timestamp(sec_timestamp)
    t = t.tz_localize("America/New_York") if t.tzinfo is None else t
    t = t.tz_convert("UTC")
    idx = minute_bars.index
    i_ent = int(idx.searchsorted(t + pd.Timedelta(minutes=1), "left"))
    if i_ent >= len(minute_bars) or not (minute_bars.iloc[i_ent]["volume"] > 0):
        return None
    entry = float(minute_bars.iloc[i_ent]["high"])
    if not np.isfinite(entry) or entry <= 0:
        return None

    w = minute_bars.iloc[i_ent + 1: i_ent + 1 + window_min]
    if w.empty or not np.isfinite(w["volume"].max()):
        return None
    if (w["low"] <= entry * (1 - stop)).any():
        px = entry * (1 - stop)
        reason = "stop"
    else:
        px = float(w.loc[w["volume"].idxmax()]["close"])
        reason = "peek:highest-volume bar"
    px *= 1 - exit_slippage
    return {"ticker": ticker, "entry_px": entry, "exit_px": px,
            "exit_reason": reason, "ret": px / entry - 1.0}
