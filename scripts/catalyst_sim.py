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

#: Position exit levels: take 6%, cut at 10%.
TARGET, STOP = 0.06, 0.10

#: Two separate caps on how long a position is held, because they are not the
#: same thing and conflating them was a real defect. ``bars`` counts *rows of
#: the bar series*, which only advance while the tape is running -- 240 of them
#: is four trading hours but spans nights, weekends and holidays, and on one
#: thin name it ran fourteen calendar days. ``wall`` caps elapsed clock time
#: from entry, so an overnight hold can be forbidden outright. Whichever binds
#: first ends the trade; ``wall=0`` means no clock cap.
MAX_HOLD_BARS, MAX_HOLD_WALL_MIN = 240, 0

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
             max_trades: int, max_bars: int = MAX_HOLD_BARS,
             max_wall_min: int = MAX_HOLD_WALL_MIN,
             ) -> tuple[pd.DataFrame, pd.DataFrame]:
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
        last = min(i_ent + max_bars, len(bars) - 1)
        if max_wall_min > 0:
            # Clip to the last bar within the clock window. searchsorted on the
            # naive twin, because a tz-aware Series gives an object array that
            # will not compare against datetime64.
            deadline = tv[i_ent] + np.timedelta64(int(max_wall_min), "m")
            last = min(last, max(i_ent, int(np.searchsorted(tv, deadline, "right")) - 1))
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


#: Hold rules swept by ``--grid``, as (label, bars, wall_minutes).
HOLD_RULES = [
    ("30 bars",          30, 0),
    ("60 bars",          60, 0),
    ("120 bars",        120, 0),
    ("240 bars",        240, 0),
    ("240b, same day",  240, 390),
    ("240b, <=24h",     240, 1440),
]


def grid(cands: pd.DataFrame, bars_by: dict, args) -> None:
    """Sweep slots x hold and print every cell.

    Both knobs were changed *after* seeing a result, which means the cell that
    looks best is selected on the same data it is measured on and its return is
    not evidence of anything. The whole surface is the only honest way to show
    it: if the sign flips across neighbouring cells, the parameter is doing the
    work rather than the catalysts, and that is worth more than any single
    number the sweep produces.
    """
    print(f"\n{'=' * 96}")
    print("PARAMETER SWEEP -- both knobs chosen after seeing a result. Read the "
          "spread, not the best cell.")
    print(f"{'=' * 96}")
    print(f"{'hold rule':16s} {'slots':>5s} {'trades':>6s} {'skipped':>7s} "
          f"{'end $':>7s} {'total':>8s} {'mean':>7s} {'median':>7s} "
          f"{'win':>4s} {'t':>6s} {'held med':>9s}")
    rows = []
    for label, bars_cap, wall_cap in HOLD_RULES:
        for slots in (2, 3, 4):
            tr, sk = simulate(cands, bars_by, args.capital, slots,
                              args.max_trades, bars_cap, wall_cap)
            if tr.empty:
                continue
            n = len(tr)
            se = tr["ret"].std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
            t = tr["ret"].mean() / se if se and se == se and se > 0 else np.nan
            end = float(tr["balance_after"].iloc[-1])
            rows.append({"hold": label, "slots": slots, "n": n,
                         "end": end, "total": end / args.capital - 1,
                         "mean": tr["ret"].mean(), "t": t})
            print(f"{label:16s} {slots:5d} {n:6d} {len(sk):7d} "
                  f"{end:7.2f} {end / args.capital - 1:+7.2%} "
                  f"{tr['ret'].mean():+6.2%} {tr['ret'].median():+6.2%} "
                  f"{(tr['ret'] > 0).mean():4.0%} "
                  f"{t:+6.2f} {tr['held_min'].median():8.0f}m")

    g = pd.DataFrame(rows)
    print(f"\n{len(g)} cells. mean return across cells {g['mean'].mean():+.2%}, "
          f"range {g['mean'].min():+.2%} to {g['mean'].max():+.2%}, "
          f"{(g['mean'] > 0).mean():.0%} positive.")
    print(f"t ranges {g['t'].min():+.2f} to {g['t'].max():+.2f}; "
          f"{(g['t'] > 2).sum()} of {len(g)} cells clear t>2, which is what "
          "you would expect from noise at this many looks.")


def cohorts(all83: pd.DataFrame, bars_by: dict, args, n_perm: int = 20000) -> None:
    """Do the grader's labels separate returns? The test that needs no portfolio.

    Every one of the 83 filings is traded at a fixed $40 with enough slots that
    nothing is ever refused one, so all three cohorts face an identical rule and
    the only thing varying is the label a reader assigned from the filing text.
    That removes the portfolio parameters from the question entirely -- slots,
    compounding and the trade cap cannot flatter or punish one cohort over
    another when none of them binds.

    It is also implicitly market-neutral: positives and neutrals are drawn from
    the same 30 days and the same cap bands, so a July that was simply kind to
    small caps lifts both and cancels in the spread.

    Three confounds are addressed rather than assumed away: cap-band composition
    (by demeaning within band), repeated tickers (by collapsing to one
    observation per name), and good-or-bad days (by permuting labels *within*
    calendar day, so the null preserves the day's realised return).
    """
    from scipy import stats

    slots = max(8, len(all83))
    tr = simulate(all83.sort_values("filed_utc").reset_index(drop=True), bars_by,
                  40.0 * slots, slots, 10 ** 6, args.max_bars, args.max_wall_min)[0]
    key = all83[["ticker", "filed_et", "final_verdict"]].copy()
    key["paperwork_public_et"] = pd.to_datetime(key["filed_et"])
    r = tr.merge(key[["ticker", "paperwork_public_et", "final_verdict"]],
                 on=["ticker", "paperwork_public_et"], how="left")

    print(f"\n{'=' * 78}\nCOHORT TEST -- {len(r)} filings, $40 each, no slot "
          f"contention, {args.max_bars}-bar hold\n{'=' * 78}")
    print(r.groupby("final_verdict")["ret"].agg(
        n="size", mean="mean", median="median",
        win=lambda s: (s > 0).mean()).round(4).to_string())

    sub = r[r["final_verdict"].isin(["positive", "neutral"])].copy()
    sub["pos"] = (sub["final_verdict"] == "positive").astype(float)
    p, n = sub.loc[sub.pos == 1, "ret"], sub.loc[sub.pos == 0, "ret"]
    obs = p.mean() - n.mean()
    t, pv = stats.ttest_ind(p, n, equal_var=False)
    print(f"\npositive - neutral = {obs * 100:+.2f}pp   Welch t={t:+.2f} p={pv:.3f}"
          f"   (n={len(p)} vs {len(n)}, {sub.ticker.nunique()} names)")
    print(f"Mann-Whitney one-sided p="
          f"{stats.mannwhitneyu(p, n, alternative='greater').pvalue:.3f}")

    print("\nwithin cap band (composition cannot explain it):")
    for b in ("micro", "small", "mid"):
        g = sub[sub.band == b]
        gp, gn = g.loc[g.pos == 1, "ret"], g.loc[g.pos == 0, "ret"]
        if len(gp) > 1 and len(gn) > 1:
            bt, _ = stats.ttest_ind(gp, gn, equal_var=False)
            print(f"  {b:6s} pos n={len(gp):2d} {gp.mean() * 100:+.2f}%   "
                  f"neu n={len(gn):2d} {gn.mean() * 100:+.2f}%   "
                  f"spread {(gp.mean() - gn.mean()) * 100:+.2f}pp  t={bt:+.2f}")

    sub["ret_dm"] = sub["ret"] - sub.groupby("band")["ret"].transform("mean")
    dt, dp = stats.ttest_ind(sub.loc[sub.pos == 1, "ret_dm"],
                             sub.loc[sub.pos == 0, "ret_dm"], equal_var=False)
    print(f"band-demeaned spread  t={dt:+.2f}  p={dp:.3f}")

    g = sub.groupby("ticker").agg(pos=("pos", "mean"), ret=("ret", "mean"))
    g = g[g.pos.isin([0.0, 1.0])]      # names that sit wholly in one cohort
    ct, cp = stats.ttest_ind(g.loc[g.pos == 1, "ret"], g.loc[g.pos == 0, "ret"],
                             equal_var=False)
    print(f"one obs per ticker    t={ct:+.2f}  p={cp:.3f}  "
          f"({int((g.pos == 1).sum())} vs {int((g.pos == 0).sum())} names)")

    rng = np.random.default_rng(11)
    sub["d"] = pd.to_datetime(sub.entry_t, utc=True).dt.tz_convert(
        "America/New_York").dt.date
    null = []
    for _ in range(n_perm):
        s = sub.groupby("d")["pos"].transform(
            lambda x: pd.Series(rng.permutation(x.values), index=x.index))
        if s.sum() in (0, len(s)):
            continue
        null.append(sub.ret[s == 1].mean() - sub.ret[s == 0].mean())
    null = np.array(null)
    print(f"within-day label permutation ({len(null)} draws): p="
          f"{(null >= obs).mean():.4f}, null sd {null.std() * 100:.2f}pp")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--bars", default="/root/.iai/minutecache")
    ap.add_argument("--grades", default="medium,high,low")
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--max-trades", type=int, default=20)
    ap.add_argument("--max-bars", type=int, default=MAX_HOLD_BARS,
                    help="hold cap in bars (trading minutes)")
    ap.add_argument("--max-wall-min", type=int, default=MAX_HOLD_WALL_MIN,
                    help="hold cap in elapsed clock minutes; 0 = unlimited")
    ap.add_argument("--grid", action="store_true",
                    help="sweep slots x hold instead of running one config")
    ap.add_argument("--cohorts", action="store_true",
                    help="test whether the grader's labels separate returns")
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

    if args.cohorts:
        all83 = pd.read_parquet(root / "classified_final.parquet")
        all83["filed_utc"] = pd.to_datetime(all83["filed_et"], utc=True)
        for tkr in all83["ticker"].unique():
            p = bars_dir / f"{tkr}.parquet"
            if tkr not in bars_by and p.exists():
                bars_by[tkr] = pd.read_parquet(p)
        cohorts(all83, bars_by, args)
        return 0

    if args.grid:
        grid(cands, bars_by, args)
        return 0

    tr, sk = simulate(cands, bars_by, args.capital, args.slots, args.max_trades,
                      args.max_bars, args.max_wall_min)
    report(tr, sk, args.capital,
           f"grades={','.join(sorted(grades, key=lambda g: GRADE_ORDER[g]))}  "
           f"candidates={len(cands)}  slots={args.slots}  "
           f"hold={args.max_bars}bars/{args.max_wall_min or '-'}wall")

    if args.out and not tr.empty:
        tr.to_parquet(args.out)
        print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
