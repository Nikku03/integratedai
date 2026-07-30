"""Two different latencies, and the gap between them decides everything.

"How long until the stock responds" is actually two questions that have been
tangled together in every earlier measurement here:

**Information latency** -- how long after EDGAR accepts the filing does the price
    actually move? This is what the thesis is about: if the crowd is slow, there
    is a window.

**Liquidity latency** -- how long until the tape prints at all, so an order can
    be filled? This is what the market imposes, and outside regular hours it is
    the binding one.

If information latency is *longer* than liquidity latency, there is a real window:
you can be filled before the price moves. If it is *shorter*, the move happens
while you are still waiting for a counterparty and you buy the top of it.

The order does not vanish
-------------------------
Earlier work here recorded "not fillable at T+1min" and dropped the filing. That
is wrong in the direction that flatters the strategy. A market order placed one
minute after the filing and finding no counterparty does not disappear -- it rests
and fills at the first print, whatever that print costs. So every filing gets a
fill here, and filings that waited get the price they waited into. That is the
honest model of "we sent the order but were not sure of the liquidity."

Prices are taken as the bar's **high** on entry, since a market order pays the
offer and minute bars carry no quotes. Bars with zero volume are ignored
throughout: 23.7% of minute bars in this cache report no trades, many with wide
stale ranges, and treating one as a fill invents a trade that did not happen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Session boundaries in ET minutes-from-midnight.
PRE_OPEN, RTH_OPEN, RTH_CLOSE, POST_CLOSE = 240, 570, 960, 1200

#: Price-move thresholds at which the stock is judged to have "responded".
THRESHOLDS = (0.01, 0.02, 0.05)


def session_of(ts_et: pd.Timestamp) -> str:
    m = ts_et.hour * 60 + ts_et.minute
    if RTH_OPEN <= m < RTH_CLOSE:
        return "regular"
    if PRE_OPEN <= m < RTH_OPEN:
        return "pre-market"
    if RTH_CLOSE <= m < POST_CLOSE:
        return "after-hours"
    return "closed"


def measure(bars: pd.DataFrame, t0_utc: np.datetime64) -> dict | None:
    """Latencies and fill for one filing.

    ``bars`` must carry a naive-UTC ``t_utc`` column and be sorted. Only bars
    that traded are considered -- a zero-volume bar is a quote, not a fill.
    """
    b = bars[bars["volume"].fillna(0) > 0]
    if len(b) < 10:
        return None
    tv = b["t_utc"].to_numpy()

    i_pre = int(np.searchsorted(tv, t0_utc, "left")) - 1
    if i_pre < 0:
        return None
    p_pre = float(b["close"].iloc[i_pre])
    if not np.isfinite(p_pre) or p_pre <= 0:
        return None

    # The order is sent one minute after acceptance and fills at the first print
    # at or after that instant -- immediately if the tape is running, later if not.
    i_fill = int(np.searchsorted(tv, t0_utc + np.timedelta64(1, "m"), "left"))
    if i_fill >= len(b):
        return None
    fill_px = float(b["high"].iloc[i_fill])
    if not np.isfinite(fill_px) or fill_px <= 0:
        return None
    liq_lat = (tv[i_fill] - t0_utc) / np.timedelta64(1, "m")

    out = {
        "p_pre": p_pre, "fill_px": fill_px,
        "liq_latency_min": float(liq_lat),
        "filled_immediately": bool(liq_lat <= 2.0),
        "already_moved_at_fill": fill_px / p_pre - 1.0,
    }

    # Information latency: first traded bar whose close has moved by each
    # threshold away from the last pre-filing price.
    fwd = b.iloc[i_pre + 1:]
    if fwd.empty:
        return None
    move = (fwd["close"].to_numpy(dtype=float) / p_pre) - 1.0
    ftv = fwd["t_utc"].to_numpy()
    for th in THRESHOLDS:
        hit = np.nonzero(np.abs(move) >= th)[0]
        key = f"info_latency_{int(th * 100)}pct"
        if len(hit):
            out[key] = float((ftv[hit[0]] - t0_utc) / np.timedelta64(1, "m"))
            out[f"responded_{int(th * 100)}pct"] = True
        else:
            out[key] = np.nan
            out[f"responded_{int(th * 100)}pct"] = False
    return out


def build(root: Path, cache: Path) -> pd.DataFrame:
    f = pd.read_parquet(root / "recent_filings.parquet")
    f["accepted"] = pd.to_datetime(f["accepted"], utc=True, format="mixed")
    e8 = f[f.form.isin(["8-K", "8-K/A"])].copy()
    e8["et"] = e8.accepted.dt.tz_convert("America/New_York")
    e8 = e8[(e8.et >= pd.Timestamp("2026-07-01", tz="America/New_York")) &
            (e8.et <= pd.Timestamp("2026-07-29", tz="America/New_York"))]

    rows = []
    for tkr, grp in e8.groupby("ticker"):
        p = cache / f"{tkr}.parquet"
        if not p.exists():
            continue
        bars = pd.read_parquet(p)
        if bars.empty or "t_utc" not in bars.columns:
            continue
        bars = bars.sort_values("t_utc").reset_index(drop=True)
        for r in grp.itertuples():
            t0 = np.datetime64(r.accepted.tz_convert("UTC").tz_localize(None))
            m = measure(bars, t0)
            if m:
                rows.append({"ticker": tkr, "accepted": r.accepted,
                             "session": session_of(r.et), "items": r.items, **m})
    return pd.DataFrame(rows)


def q(s, p):
    return s.quantile(p) if len(s.dropna()) else np.nan


def report(d: pd.DataFrame) -> None:
    print(f"{len(d):,} 8-K filings across {d.ticker.nunique():,} names, "
          f"1-29 July 2026, with minute bars\n")

    print("WHEN THE ORDER ACTUALLY FILLS (sent at acceptance + 1 min)")
    print(f"  {'session':13s}{'n':>6s}{'share':>7s}{'filled <=2min':>15s}"
          f"{'median wait':>13s}{'p90 wait':>11s}")
    for s in ("regular", "pre-market", "after-hours", "closed"):
        g = d[d.session == s]
        if not len(g):
            continue
        print(f"  {s:13s}{len(g):>6d}{len(g) / len(d) * 100:>6.0f}%"
              f"{g.filled_immediately.mean() * 100:>14.0f}%"
              f"{g.liq_latency_min.median():>12.0f}m"
              f"{q(g.liq_latency_min, .90):>10.0f}m")
    print(f"  {'ALL':13s}{len(d):>6d}{100:>6.0f}%"
          f"{d.filled_immediately.mean() * 100:>14.0f}%"
          f"{d.liq_latency_min.median():>12.0f}m"
          f"{q(d.liq_latency_min, .90):>10.0f}m")

    print("\nWHEN THE PRICE RESPONDS (first traded print moved this far from pre-filing)")
    print(f"  {'threshold':13s}{'responded':>11s}{'median lag':>13s}"
          f"{'p25':>8s}{'p75':>9s}")
    for th in THRESHOLDS:
        k = f"info_latency_{int(th * 100)}pct"
        r = d[f"responded_{int(th * 100)}pct"]
        v = d.loc[r, k]
        print(f"  move >= {th:.0%}{'':4s}{r.mean() * 100:>10.0f}%"
              f"{v.median():>12.0f}m{q(v, .25):>7.0f}m{q(v, .75):>8.0f}m")

    print("\nTHE GAP -- did we get filled before or after the price moved?")
    for th in THRESHOLDS:
        k = f"info_latency_{int(th * 100)}pct"
        sub = d[d[f"responded_{int(th * 100)}pct"]].copy()
        if not len(sub):
            continue
        beat = (sub[k] > sub.liq_latency_min)
        print(f"  at {th:.0%}: filled BEFORE the move in {beat.mean() * 100:.0f}% "
              f"of the {len(sub):,} filings that moved   "
              f"(median gap {(sub[k] - sub.liq_latency_min).median():+.0f} min)")

    print("\nWHAT WE PAY FOR THE WAIT")
    am = d.already_moved_at_fill
    print(f"  price already moved by the time we filled: median "
          f"{am.median() * 100:+.2f}%, mean {am.mean() * 100:+.2f}%")
    for lo, hi, lab in ((-np.inf, 2.0, "filled within 2 min"),
                        (2.0, 60.0, "waited 2-60 min"),
                        (60.0, np.inf, "waited over an hour")):
        g = d[(d.liq_latency_min > lo) & (d.liq_latency_min <= hi)]
        if not len(g):
            continue
        print(f"  {lab:22s} n={len(g):>5d}  already moved "
              f"{g.already_moved_at_fill.median() * 100:+6.2f}% (median), "
              f"{g.already_moved_at_fill.mean() * 100:+6.2f}% (mean)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--cache", default="/root/.iai/minutecache")
    args = ap.parse_args(argv)
    d = build(Path(args.root), Path(args.cache))
    if d.empty:
        print("no filings with usable minute bars")
        return 1
    d.to_parquet(Path(args.root) / "latency_split.parquet")
    report(d)
    return 0


if __name__ == "__main__":
    sys.exit(main())
