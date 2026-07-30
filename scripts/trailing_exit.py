"""Arm at +8%, ride the move, leave when it stops going up.

The fixed +25%/-10% barrier threw away the best trades in the clinical cohort:
AGEN dipped 19% and then ran +51%, ARMP dipped 19% and ran +28%. A symmetric
barrier assumes the move is symmetric. It is not -- when a readout is good the
stock trends, and the right exit is one that follows the trend rather than
guessing where it ends.

The rule
--------
1. **Before arming** a wide initial stop protects against the readout being bad.
   This is the only place a fixed level appears, and it exists because a failed
   trial does not dip, it gaps.
2. **Arm at +8%.** Once reached, the trade is presumed working and the initial
   stop is replaced by a trailing one.
3. **Trail from the high-water mark.** Exit on the first close-enough dip off the
   running high. With an 8% arm and an 8% trail the worst armed outcome is
   roughly breakeven, which is the "no greed" property: a winner never becomes a
   loser.
4. **Stall exit.** If the position makes no new high for ``stall`` minutes it has
   stopped trending, so leave rather than wait for the trail to be hit on the way
   down.

Causality and intra-bar ambiguity
---------------------------------
The high-water mark only ever uses bars already seen. Within a single bar it is
unknowable whether the new high or the trail breach came first, so **the trail is
checked before the high-water is updated** -- the reading that costs money. Bars
with no volume can neither trigger an exit nor set a high, for the same reason
they cannot fill an order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def walk_trailing(hi: np.ndarray, lo: np.ndarray, traded: np.ndarray,
                  entry: float, *, arm: float = 0.08, trail: float = 0.08,
                  init_stop: float = 0.15, stall_bars: int = 0,
                  ) -> tuple[float, str, int]:
    """Return (exit_return, reason, bar_index) for one trade.

    ``stall_bars`` counts *traded* bars without a new high; 0 disables it.
    """
    hw = entry
    armed = False
    since_high = 0
    n = len(hi)
    last = n - 1
    for j in range(n):
        if not traded[j]:
            continue
        h, l = hi[j], lo[j]
        if not (np.isfinite(h) and np.isfinite(l)):
            continue

        if not armed:
            stop_px = entry * (1 - init_stop)
            if l <= stop_px:
                return min(stop_px, l) / entry - 1.0, "stop", j
            if h >= entry * (1 + arm):
                armed = True
                hw = max(hw, h)
                since_high = 0
                continue
            continue

        # Armed. Trail is checked before the high-water updates, so a bar that
        # both breaches the trail and prints a new high resolves against us.
        trail_px = hw * (1 - trail)
        if l <= trail_px:
            return min(trail_px, l) / entry - 1.0, "trail", j
        if h > hw:
            hw = h
            since_high = 0
        else:
            since_high += 1
            if stall_bars and since_high >= stall_bars:
                return l / entry - 1.0, "stall", j
    # Ran out of window: sell into the bid on the last bar that traded.
    j = last
    while j > 0 and not traded[j]:
        j -= 1
    return lo[j] / entry - 1.0, "time", j


def load_paths(sel: pd.DataFrame, cache, horizon_bars: int = 1950) -> list:
    """(ticker, entry, hi, lo, traded, times, fill_time) per signal."""
    out = []
    for r in sel.itertuples():
        p = cache / f"{r.ticker}.parquet"
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        if b.empty or "t_utc" not in b.columns:
            continue
        b = b.sort_values("t_utc").reset_index(drop=True)
        tv = b["t_utc"].to_numpy()
        tr = b["volume"].fillna(0).to_numpy() > 0
        hi = b["high"].to_numpy(dtype=float)
        lo = b["low"].to_numpy(dtype=float)
        t0 = np.datetime64(r.et.tz_convert("UTC").tz_localize(None))
        i0 = int(np.searchsorted(tv, t0 + np.timedelta64(1, "m"), "left"))
        f = np.nonzero(tr[i0:])[0]
        if not len(f):
            continue
        i = i0 + int(f[0])
        e = float(hi[i])
        if not np.isfinite(e) or e < 1.0:
            continue
        j = min(i + horizon_bars, len(b) - 1)
        out.append((r.ticker, e, hi[i + 1:j + 1], lo[i + 1:j + 1],
                    tr[i + 1:j + 1], b["t"].to_numpy()[i + 1:j + 1],
                    b["t"].iloc[i]))
    return out


def simulate(paths: list, **kw) -> pd.DataFrame:
    rows = []
    for tkr, e, hi, lo, tr, ts, t_in in paths:
        if not len(hi):
            continue
        ret, why, j = walk_trailing(hi, lo, tr, e, **kw)
        rows.append({"ticker": tkr, "fill": t_in, "exit_t": ts[min(j, len(ts) - 1)],
                     "entry": e, "ret": ret, "why": why})
    return pd.DataFrame(rows)


def book(t: pd.DataFrame, capital: float = 80.0, slots: int = 2) -> float:
    """Chronological compounding; proceeds credited when the trade exits."""
    if t.empty:
        return capital
    t = t.sort_values("fill")
    cash, open_pos = capital, []
    for r in t.itertuples():
        still = []
        for xt, cost, proceeds in open_pos:
            if xt <= r.fill:
                cash += proceeds
            else:
                still.append((xt, cost, proceeds))
        open_pos = still
        if len(open_pos) >= slots:
            continue
        eq = cash + sum(c for _, c, _ in open_pos)
        size = eq / slots
        if size < 0.5:
            continue
        cash -= size
        open_pos.append((r.exit_t, size, size * (1 + r.ret)))
    for _, _, proceeds in open_pos:
        cash += proceeds
    return cash
