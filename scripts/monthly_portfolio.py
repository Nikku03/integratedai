"""Month-by-month balance for an $80 account taking the model's signals.

The model emits about 22 signals a month. Two $40 slots with a 7-day average hold
absorb about six of them. This walks the signal stream in date order and reports
what the account was worth at the start and end of every month.

Causal throughout, and the two places that matters:

**Slot contention is resolved by the calendar, not by hindsight.** A signal is
considered when it arrives. If both slots are full it is skipped -- never deferred
to a better moment, because knowing a better moment is coming is exactly the peek
this is meant to exclude.

**Ties on the same day break on expected value**, which is knowable at that
moment, rather than on the realised return, which is not.

Returns are net of the run's own cost model (``ret - cost_rt``), so nothing is
charged twice and nothing is free. Position size is account *equity* over slots,
so the account compounds; sizing off idle cash would silently halve the second
concurrent position.

Read the survivorship warning at the bottom of the output before believing any
number here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def simulate(trades: pd.DataFrame, capital: float, slots: int) -> pd.DataFrame:
    """Chronological portfolio over the signal stream."""
    t = trades.sort_values(["entry_date", "ev"], ascending=[True, False]).copy()
    cash, open_pos, taken, skipped = capital, [], [], 0

    for r in t.to_dict("records"):
        d = r["entry_date"]
        still = []
        for p in open_pos:
            if p["exit_date"] <= d:
                cash += p["proceeds"]
            else:
                still.append(p)
        open_pos = still

        if len(open_pos) >= slots:
            skipped += 1
            continue

        equity = cash + sum(p["cost"] for p in open_pos)
        size = equity / slots
        if size < 0.01:
            skipped += 1
            continue
        cash -= size
        net = r["ret"] - r["cost_rt"]
        open_pos.append({"exit_date": r["exit_date"], "cost": size,
                         "proceeds": size * (1.0 + net)})
        taken.append({"entry_date": d, "exit_date": r["exit_date"],
                      "ticker": r["ticker"], "net": net, "size": size,
                      "pnl": size * net})

    for p in sorted(open_pos, key=lambda q: q["exit_date"]):
        cash += p["proceeds"]

    out = pd.DataFrame(taken)
    out.attrs["skipped"] = skipped
    out.attrs["final_cash"] = cash
    return out


def monthly(taken: pd.DataFrame, capital: float) -> pd.DataFrame:
    """Balance at the start and end of each calendar month.

    Equity is credited when a position *closes*, so a month's end balance
    reflects only trades actually settled by then. Open positions are carried at
    cost, which is the conservative reading -- an unrealised gain is not money.
    """
    t = taken.sort_values("exit_date").reset_index(drop=True)
    t["month"] = t["exit_date"].dt.to_period("M")
    eq, rows, bal = capital, [], capital
    curve = []
    for r in t.to_dict("records"):
        bal += r["pnl"]
        curve.append({"month": r["month"], "bal": bal})
    c = pd.DataFrame(curve)

    months = pd.period_range(t["month"].min(), t["month"].max(), freq="M")
    start = capital
    for m in months:
        g = c[c["month"] == m]
        end = float(g["bal"].iloc[-1]) if len(g) else start
        n = int((t["month"] == m).sum())
        rows.append({"month": str(m), "trades": n, "start": round(start, 2),
                     "end": round(end, 2),
                     "ret_pct": round((end / start - 1) * 100, 2) if start else np.nan})
        start = end
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selected",
                    default="/root/.iai/store/w2015_moonshot_selected.parquet")
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    args = ap.parse_args(argv)

    s = pd.read_parquet(args.selected)
    for c in ("entry_date", "exit_date"):
        s[c] = pd.to_datetime(s[c])

    taken = simulate(s, args.capital, args.slots)
    m = monthly(taken, args.capital)

    print(f"$80 account, {args.slots} slots, model signals, net of the run's own "
          f"cost model\n")
    print(f"signal stream      : {len(s):,} trades over "
          f"{s.entry_date.min():%Y-%m} to {s.exit_date.max():%Y-%m}")
    print(f"actually taken     : {len(taken):,} "
          f"({len(taken) / len(s) * 100:.0f}% of the stream); "
          f"{taken.attrs['skipped']:,} skipped for no free slot")
    print(f"trades per month   : {len(taken) / len(m):.1f}")

    print(f"\n{'month':>9s}{'trades':>7s}{'start $':>10s}{'end $':>10s}{'ret %':>8s}")
    for r in m.to_dict("records"):
        print(f"{r['month']:>9s}{r['trades']:>7d}{r['start']:>10.2f}"
              f"{r['end']:>10.2f}{r['ret_pct']:>8.2f}")

    first, last = m["start"].iloc[0], m["end"].iloc[-1]
    yrs = len(m) / 12.0
    print(f"\nFULL PERIOD  ${first:.2f} -> ${last:.2f}  "
          f"({last / first - 1:+.2%} over {len(m)} months / {yrs:.1f} years)")
    if last > 0:
        print(f"CAGR         {(last / first) ** (1 / yrs) - 1:+.2%}")

    r = m["ret_pct"]
    print(f"\nA TYPICAL MONTH (the answer to 'for a month'):")
    print(f"  median month   ${args.capital:.2f} -> "
          f"${args.capital * (1 + r.median() / 100):.2f}   ({r.median():+.2f}%)")
    print(f"  mean month     ${args.capital:.2f} -> "
          f"${args.capital * (1 + r.mean() / 100):.2f}   ({r.mean():+.2f}%)")
    print(f"  best month     {r.max():+.2f}%     worst month {r.min():+.2f}%")
    print(f"  months up      {int((r > 0).sum())} of {len(r)} ({(r > 0).mean() * 100:.0f}%)")
    print(f"  monthly sd     {r.std():.2f}%")
    se = r.std() / np.sqrt(len(r))
    print(f"  t on mean monthly return: {r.mean() / se:+.2f}  "
          f"-> {'significant' if abs(r.mean() / se) > 2 else 'indistinguishable from zero'}")

    curve = np.concatenate([[args.capital], m["end"].to_numpy()])
    dd = float((curve / np.maximum.accumulate(curve) - 1).min())
    print(f"  max drawdown   {dd * 100:.1f}%")

    print("\n" + "=" * 74)
    print("SURVIVORSHIP: the panel behind these signals contains 5,394 of 5,395")
    print("tickers still listed at the end of it. An unbiased 11-year panel would")
    print("show roughly half the names ending early through delisting. Every")
    print("company that died between 2015 and 2025 is missing, and this strategy")
    print("selects exactly the kind of name that dies. These balances are")
    print("therefore an OPTIMISTIC bound, not an estimate.")
    print("=" * 74)

    m.to_csv("/root/.iai/store/monthly_portfolio.csv", index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
