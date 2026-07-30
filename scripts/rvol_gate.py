"""Does the market care? A 180-second relative-volume gate on every catalyst.

The proposition: however clean the filing text is, if the tape does not react in
the first three minutes the move is not coming, and holding on is how the
tail-end losses happen. So measure relative volume in the 180 seconds after the
catalyst and scratch the trade when it is thin.

This is the most testable of the five proposed upgrades and the one most likely to
matter, because it needs no text understanding at all -- only whether volume
showed up.

How RVOL is computed here
-------------------------
Baseline is the name's own median dollar volume per *traded* minute over the
twenty sessions before the filing. Using traded minutes only matters: a quarter of
minute bars in this cache report zero volume, and including them would drag the
baseline down and inflate every RVOL by the same factor, making the gate look
discriminating when it is only rescaled.

RVOL = dollars traded in the first three minutes after acceptance, divided by
three times that baseline. A value of 3.0 means the tape did three times its usual
business in those minutes.

What the gate costs when it fires
---------------------------------
Scratching is not free. The trade is entered at the offer and scratched at the
bid, so the round trip costs the spread whether or not the news was real. That
charge is applied explicitly rather than assumed away -- a gate that fires often
and costs nothing is not a gate, it is an accounting error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

WINDOW = (pd.Timestamp("2026-07-01", tz="America/New_York"),
          pd.Timestamp("2026-07-29", tz="America/New_York"))
BASELINE_SESSIONS = 20
BASELINE_BARS = BASELINE_SESSIONS * 390
GATE_SECONDS = 180


def measure(b: pd.DataFrame, t0: np.datetime64, gate_min: int) -> dict | None:
    tv = b["t_utc"].to_numpy()
    vol = b["volume"].fillna(0).to_numpy()
    close = b["close"].to_numpy(dtype=float)
    traded = vol > 0

    i0 = int(np.searchsorted(tv, t0, "left"))
    prev = np.nonzero(traded[:max(0, i0)])[0]
    if len(prev) < 50:
        return None
    p_pre = float(close[prev[-1]])
    if not np.isfinite(p_pre) or p_pre <= 0:
        return None

    # Baseline: median dollars per TRADED minute over the prior sessions.
    lo = max(0, i0 - BASELINE_BARS)
    win = np.arange(lo, i0)
    win = win[traded[win]]
    if len(win) < 50:
        return None
    base = float(np.median(close[win] * vol[win]))
    if not np.isfinite(base) or base <= 0:
        return None

    # Entry: first print at or after T+1min.
    i1 = int(np.searchsorted(tv, t0 + np.timedelta64(1, "m"), "left"))
    fwd = np.nonzero(traded[i1:])[0]
    if not len(fwd):
        return None
    i_ent = i1 + int(fwd[0])
    entry = float(b["high"].iloc[i_ent])
    if not np.isfinite(entry) or entry <= 0:
        return None

    # RVOL over the gate window measured from acceptance, not from the fill:
    # the question is whether the market reacted to the news, not to us.
    j = int(np.searchsorted(tv, t0 + np.timedelta64(gate_min, "m"), "left"))
    seg = np.arange(i0, max(j, i0 + 1))
    seg = seg[seg < len(b)]
    gate_usd = float((close[seg] * vol[seg]).sum()) if len(seg) else 0.0
    rvol = gate_usd / (base * max(gate_min, 1))

    out = {"p_pre": p_pre, "entry": entry, "baseline_usd_per_min": base,
           "gate_usd": gate_usd, "rvol": rvol,
           "entry_lag_min": float((tv[i_ent] - t0) / np.timedelta64(1, "m")),
           "moved_at_entry": entry / p_pre - 1.0}

    # Forward outcomes from the fill, selling the bid.
    for w, lab in ((15, "r15m"), (60, "r60m"), (390, "r1d"), (1950, "r5d")):
        k = min(i_ent + w, len(b) - 1)
        idx = np.nonzero(traded[i_ent + 1:k + 1])[0]
        out[lab] = (float(b["low"].iloc[i_ent + 1 + idx[-1]]) / entry - 1.0
                    if len(idx) else np.nan)
    # Barrier outcome over five sessions.
    k = min(i_ent + 1950, len(b) - 1)
    seg_t = traded[i_ent + 1:k + 1]
    if seg_t.any():
        hi = np.where(seg_t, b["high"].to_numpy()[i_ent + 1:k + 1] / entry - 1, -np.inf).max()
        lo_ = np.where(seg_t, b["low"].to_numpy()[i_ent + 1:k + 1] / entry - 1, np.inf).min()
        out["fwd_up"], out["fwd_dn"] = float(hi), float(lo_)
    else:
        out["fwd_up"] = out["fwd_dn"] = np.nan
    return out


def build(root: Path, cache: Path, gate_min: int) -> pd.DataFrame:
    f = pd.read_parquet(root / "recent_filings.parquet")
    f["accepted"] = pd.to_datetime(f["accepted"], utc=True, format="mixed")
    f["et"] = f["accepted"].dt.tz_convert("America/New_York")
    f = f[(f.et >= WINDOW[0]) & (f.et <= WINDOW[1])].copy()
    f = f[f.form.isin(["8-K", "8-K/A"])]

    rows = []
    for tkr, grp in f.groupby("ticker"):
        p = cache / f"{tkr}.parquet"
        if not p.exists():
            continue
        b = pd.read_parquet(p)
        if b.empty or "t_utc" not in b.columns:
            continue
        b = b.sort_values("t_utc").reset_index(drop=True)
        for r in grp.itertuples():
            t0 = np.datetime64(r.accepted.tz_convert("UTC").tz_localize(None))
            m = measure(b, t0, gate_min)
            if m and abs(m["moved_at_entry"]) <= 1.0:      # split guard
                rows.append({"ticker": tkr, "et": r.et, "items": r.items, **m})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--cache", default="/root/.iai/minutecache")
    ap.add_argument("--gate-min", type=int, default=3)
    ap.add_argument("--scratch-cost", type=float, default=0.0075)
    args = ap.parse_args(argv)

    d = build(Path(args.root), Path(args.cache), args.gate_min)
    d.to_parquet(Path(args.root) / "rvol_gate.parquet")
    print(f"{len(d):,} 8-K filings with minute bars and a computable RVOL\n")

    print(f"RVOL over the first {args.gate_min} minutes after acceptance:")
    print(f"  median {d.rvol.median():.2f}   p25 {d.rvol.quantile(.25):.2f}   "
          f"p75 {d.rvol.quantile(.75):.2f}   p95 {d.rvol.quantile(.95):.1f}")
    for th in (1.0, 2.0, 3.0, 5.0, 10.0):
        print(f"  RVOL >= {th:4.1f}: {(d.rvol >= th).sum():5d} "
              f"({(d.rvol >= th).mean() * 100:4.1f}%)")

    print("\nOUTCOME BY RVOL BUCKET (return from the fill, selling the bid)")
    d["b"] = pd.cut(d.rvol, [-0.01, 1, 3, 10, 1e9],
                    labels=["<1x", "1-3x", "3-10x", ">10x"])
    g = d.groupby("b", observed=True).agg(
        n=("rvol", "size"), r15m=("r15m", "mean"), r60m=("r60m", "mean"),
        r1d=("r1d", "mean"), r5d=("r5d", "mean"),
        up20=("fwd_up", lambda s: (s >= .20).mean()),
        dn20=("fwd_dn", lambda s: (s <= -.20).mean()))
    for c in ("r15m", "r60m", "r1d", "r5d"):
        g[c] = (g[c] * 100).round(2)
    g["up20"] = (g["up20"] * 100).round(1)
    g["dn20"] = (g["dn20"] * 100).round(1)
    print(g.to_string())

    print(f"\nTHE GATE: enter every filing, scratch at {args.scratch_cost:.2%} "
          f"if RVOL < threshold at {args.gate_min} min")
    print(f"  {'threshold':>10s}{'kept':>7s}{'scratched':>11s}"
          f"{'kept mean 1d':>14s}{'gated mean 1d':>15s}{'ungated':>10s}")
    for th in (0.0, 1.0, 2.0, 3.0, 5.0):
        keep = d[d.rvol >= th]
        drop = d[d.rvol < th]
        if not len(keep):
            continue
        gated = ((keep["r1d"].sum() - len(drop) * args.scratch_cost)
                 / max(len(d), 1))
        print(f"  {th:>10.1f}{len(keep):>7d}{len(drop):>11d}"
              f"{keep.r1d.mean() * 100:>13.2f}%{gated * 100:>14.2f}%"
              f"{d.r1d.mean() * 100:>9.2f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
