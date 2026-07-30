"""Trade the classified catalysts: $80, two slots, compounded, no peeking.

Inputs come from the classification pass, not from prices. Every 8-K in the
last 30 days for small/micro/mid caps was screened for tradability (a print in
the entry minute, price >= $1, a liquid prior session, an entry bar at least
20x the order size, and less than 10% of the move already gone), then read by
an analyst who saw only the filing text -- never the outcome -- and graded it
``trap`` / ``neutral`` / ``positive`` with a low/medium/high impact estimate.
Every medium or high grade was then handed to a second reader instructed to
knock it down.

This script takes those grades as given and asks the only remaining question:
if you had traded them, what would have happened?

Two runs, because the interesting comparison is between them:

``--grades medium,high``
    The filings the analyst thought actually mattered. There are four. That is
    the honest supply of high-conviction events in one month at this cap range,
    and no amount of wanting twenty trades creates more of them.

``--grades medium,high,low``
    Every positive, including the ones graded low-impact. This reaches the
    ~20-trade target, and the per-grade breakdown at the end is the actual
    result: does the grade predict the return, or is the analyst's conviction
    uncorrelated with what the price did?

The exit rule is the corrected one
----------------------------------
Barriers are checked bar by bar starting *after* the entry bar, in order, and
an ambiguous bar resolves against the trade. A stop fills at
``min(stop_level, bar_low)`` so a gap through the stop costs what it costs. No
step reads a bar later than the one it is standing on -- which is what the
first version of this rule got wrong, to the tune of +0.86% per trade.

Usage
-----
    python scripts/catalyst_sim.py --grades medium,high,low
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Position exit levels, unchanged from the paper simulation so the two are
#: comparable: take 6%, cut at 10%, and let go after four hours of bars.
TARGET, STOP, MAX_HOLD_MIN = 0.06, 0.10, 240

#: An ambiguous bar -- one whose range spans both barriers -- is booked as the
#: stop. Intra-minute ordering is unknowable without tick data, so the only
#: defensible reading is the one that costs money.
AMBIGUOUS_RESOLVES_AGAINST_US = True

GRADE_ORDER = {"high": 0, "medium": 1, "low": 2}


def load_candidates(root: Path, grades: set[str]) -> pd.DataFrame:
    """Positives at the requested impact grades, in filing order.

    Traps and neutrals never enter. Order is strictly chronological: ranking
    the month's filings against each other would require knowing the month is
    over, which at the moment of each filing it is not.
    """
    df = pd.read_parquet(root / "classified_final.parquet")
    df = df[(df["final_verdict"] == "positive") & (df["final_impact"].isin(grades))]
    df["filed_utc"] = pd.to_datetime(df["filed_et"], utc=True)
    return df.sort_values("filed_utc").reset_index(drop=True)


def simulate(cands: pd.DataFrame, bars_by: dict, capital: float, slots: int,
             max_trades: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk the filings in time order, holding at most ``slots`` positions.

    A slot frees only when its exit bar is actually reached, so slot contention
    is decided by the calendar rather than by preference. Position size is
    account *equity* over slots -- cash alone would silently halve the second
    concurrent position.
    """
    cash = capital
    open_pos: list[dict] = []
    trades, skipped = [], []

    for f in cands.to_dict("records"):
        t = f["filed_utc"]

        still = []
        for p in open_pos:
            if p["exit_t"] <= t:
                cash += p["proceeds"]
                eq = cash + sum(q["cost"] for q in still)
                trades.append(p["record"] | {"balance_after": eq})
            else:
                still.append(p)
        open_pos = still

        if len(trades) + len(open_pos) >= max_trades:
            skipped.append({**f, "skip_reason": "trade cap reached"})
            continue
        if len(open_pos) >= slots:
            skipped.append({**f, "skip_reason": "no free slot"})
            continue

        bars = bars_by.get(f["ticker"])
        if bars is None or bars.empty:
            skipped.append({**f, "skip_reason": "no minute data"})
            continue

        tv = bars["t_utc"].to_numpy()
        t_naive = np.datetime64(t.tz_convert("UTC").tz_localize(None))
        i_ent = int(np.searchsorted(tv, t_naive + np.timedelta64(1, "m"), "left"))
        if i_ent >= len(bars) or not (float(bars["volume"].iloc[i_ent]) > 0):
            skipped.append({**f, "skip_reason": "no trade at T+1min"})
            continue

        entry = float(bars["high"].iloc[i_ent])       # pay the offer
        if not np.isfinite(entry) or entry <= 0:
            skipped.append({**f, "skip_reason": "no usable entry price"})
            continue

        equity = cash + sum(p["cost"] for p in open_pos)
        size = equity / slots
        if size < 1.0:
            skipped.append({**f, "skip_reason": "insufficient capital"})
            continue
        cash -= size
        shares = size / entry

        up, dn = entry * (1 + TARGET), entry * (1 - STOP)
        last = min(i_ent + MAX_HOLD_MIN, len(bars) - 1)
        exit_i, exit_px, reason = None, None, None
        for j in range(i_ent + 1, last + 1):
            hi, lo = float(bars["high"].iloc[j]), float(bars["low"].iloc[j])
            if not (np.isfinite(hi) and np.isfinite(lo)):
                continue
            hit_dn, hit_up = lo <= dn, hi >= up
            if hit_dn and hit_up and AMBIGUOUS_RESOLVES_AGAINST_US:
                hit_up = False
            if hit_dn:
                exit_i, exit_px, reason = j, min(dn, lo), "stop"
                break
            if hit_up:
                exit_i, exit_px, reason = j, up, "target"
                break
        if exit_i is None:
            exit_i = last
            exit_px = float(bars["low"].iloc[exit_i])  # sell into the bid
            reason = "time"

        exit_t = bars["t"].iloc[exit_i]
        proceeds = shares * exit_px
        open_pos.append({
            "exit_t": exit_t, "proceeds": proceeds, "cost": size,
            "record": {
                "ticker": f["ticker"], "band": f["band"], "items": f["items"],
                "impact": f["final_impact"],
                "paperwork_public_et": pd.Timestamp(f["filed_et"]),
                "entry_t": bars["t"].iloc[i_ent], "entry_px": entry,
                "lag_min": (bars["t"].iloc[i_ent] - t).total_seconds() / 60.0,
                "exit_t": exit_t, "exit_px": float(exit_px), "exit_reason": reason,
                "held_min": (exit_t - bars["t"].iloc[i_ent]).total_seconds() / 60.0,
                "size_usd": size, "ret": float(exit_px) / entry - 1.0,
                "pnl": proceeds - size,
            },
        })

    for p in sorted(open_pos, key=lambda q: q["exit_t"]):
        cash += p["proceeds"]
        trades.append(p["record"] | {"balance_after": cash})

    tr = pd.DataFrame(trades)
    if not tr.empty:
        tr = tr.sort_values("exit_t").reset_index(drop=True)
        # balance_after is stamped as each position settles; recompute it in
        # settlement order so the printed column is a running account curve
        # rather than the order the loop happened to append in.
        bal, eq = [], capital
        for pnl in tr["pnl"]:
            eq += pnl
            bal.append(eq)
        tr["balance_after"] = bal
    return tr, pd.DataFrame(skipped)


def report(tr: pd.DataFrame, sk: pd.DataFrame, capital: float, label: str) -> None:
    print(f"\n{'=' * 78}\n{label}\n{'=' * 78}")
    if tr.empty:
        print("no trades taken")
        return

    cols = ["ticker", "band", "impact", "paperwork_public_et", "entry_t",
            "entry_px", "lag_min", "exit_t", "exit_px", "exit_reason",
            "held_min", "ret", "pnl", "balance_after"]
    disp = tr[cols].copy()
    for c in ("paperwork_public_et", "entry_t", "exit_t"):
        disp[c] = pd.to_datetime(disp[c], utc=True).dt.tz_convert(
            "America/New_York").dt.strftime("%m-%d %H:%M")
    disp["ret"] = (disp["ret"] * 100).round(2)
    for c in ("entry_px", "exit_px", "pnl", "balance_after"):
        disp[c] = disp[c].round(2)
    disp["lag_min"] = disp["lag_min"].round(1)
    disp["held_min"] = disp["held_min"].round(0).astype(int)
    print(disp.to_string(index=False))

    end = float(tr["balance_after"].iloc[-1])
    print(f"\ntrades {len(tr)}   start ${capital:.2f}   end ${end:.2f}   "
          f"total {end / capital - 1:+.2%}")
    print(f"mean {tr['ret'].mean():+.2%}   median {tr['ret'].median():+.2%}   "
          f"win {(tr['ret'] > 0).mean():.0%}   "
          f"held {tr['held_min'].median():.0f}m median")
    n = len(tr)
    if n > 1:
        se = tr["ret"].std(ddof=1) / np.sqrt(n)
        print(f"t on mean return: {tr['ret'].mean() / se:+.2f}  (n={n})")
    print("exits:", tr["exit_reason"].value_counts().to_dict())

    if tr["impact"].nunique() > 1:
        print("\nby impact grade:")
        g = tr.groupby("impact").agg(
            n=("ret", "size"), mean=("ret", "mean"),
            median=("ret", "median"), win=("ret", lambda s: (s > 0).mean()),
            pnl=("pnl", "sum"))
        g = g.reindex([k for k in GRADE_ORDER if k in g.index])
        g["mean"] = (g["mean"] * 100).round(2)
        g["median"] = (g["median"] * 100).round(2)
        g["win"] = (g["win"] * 100).round(0)
        g["pnl"] = g["pnl"].round(2)
        print(g.to_string())

    if tr["band"].nunique() > 1:
        print("\nby cap band:")
        g = tr.groupby("band").agg(n=("ret", "size"), mean=("ret", "mean"),
                                   pnl=("pnl", "sum"))
        g["mean"] = (g["mean"] * 100).round(2)
        g["pnl"] = g["pnl"].round(2)
        print(g.to_string())

    if not sk.empty:
        print("\nnot taken:", sk["skip_reason"].value_counts().to_dict())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--bars", default="/root/.iai/minutecache")
    ap.add_argument("--grades", default="medium,high,low")
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--max-trades", type=int, default=20)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    root, bars_dir = Path(args.root), Path(args.bars)
    grades = {g.strip() for g in args.grades.split(",") if g.strip()}
    cands = load_candidates(root, grades)
    if cands.empty:
        print("no candidates at grades", sorted(grades))
        return 1

    bars_by = {}
    for tkr in cands["ticker"].unique():
        p = bars_dir / f"{tkr}.parquet"
        if p.exists():
            bars_by[tkr] = pd.read_parquet(p)

    tr, sk = simulate(cands, bars_by, args.capital, args.slots, args.max_trades)
    report(tr, sk, args.capital,
           f"grades={','.join(sorted(grades, key=lambda g: GRADE_ORDER[g]))}  "
           f"candidates={len(cands)}")

    if args.out and not tr.empty:
        tr.to_parquet(args.out)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
