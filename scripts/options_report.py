"""What the six option trades did, against what was registered in advance.

Four arms are reported from the same contracts, because pricing both legs of
every name costs nothing extra once the chain has been pulled:

* **directional** -- the requested book. One contract per name, a call on a
  positive reading and a put on a negative one.
* **best only** -- the single highest-scoring name each session, which is the
  trade the design says to actually take.
* **second only** -- the diversification leg, reported separately so H1 can be
  answered rather than asserted.
* **executable only** -- the trades whose contract actually traded enough to
  be taken. This turns out to be the arm that matters: four of the six selected
  names had an at-the-money chain that printed between zero and thirty-nine
  contracts on the day, and a backtest that fills those is describing a trade
  nobody could have made.
* **straddle** -- one call and one put at the same strike. This is the arm the
  repository's evidence supports, because the measurement that has held up
  across 160,920 rows is that this gate concentrates dispersion and predicts
  direction badly.

The underlying's own return over the same window is reported beside every
option, since an option that loses money on a stock that moved the right way is
a different failure from one that loses money on a stock that went the wrong way.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


#: Contracts traded in the at-the-money strike on the entry session, below which
#: the fill is not a trade anyone could have taken. One contract is 100 shares,
#: so this is 10,000 shares of exposure -- a deliberately low bar that four of
#: the six selected names still fail.
MIN_CONTRACTS = 100


def liquidity(T: pd.DataFrame, cache: Path) -> pd.DataFrame:
    """Attach how much each contract actually traded, and when the fill printed."""
    for leg in ("call", "put"):
        vols, times = [], []
        for _, r in T.iterrows():
            occ = r[f"{leg}_occ"]
            d = cache / f"day_{occ}.json"
            res = json.loads(d.read_text()).get("results") or [] if d.exists() else []
            vols.append(float(res[0]["v"]) if res else 0.0)
            m = cache / f"min_{occ}_{r.entry}.json"
            rows = json.loads(m.read_text()).get("results") or [] if m.exists() else []
            t = pd.to_datetime([x["t"] for x in rows], unit="ms", utc=True) \
                  .tz_convert("America/New_York") if rows else []
            mins = [x.hour * 60 + x.minute for x in t]
            at = [x for x in t if x.hour * 60 + x.minute >= 575]
            times.append((at[0] if at else (t[0] if len(t) else pd.NaT)))
        T[f"{leg}_vol"] = vols
        T[f"{leg}_filltime"] = times
    return T


def why(r, v) -> str:
    if r.exec_ok:
        return "YES"
    if v == 0:
        return "no -- never traded"
    bits = []
    if v < MIN_CONTRACTS:
        bits.append(f"{int(v)} contracts all session")
    if r.fill_min == r.fill_min and r.fill_min > 630:
        bits.append("entry print at the bell")
    if r.exit_min != r.exit_min:
        bits.append("no exit print")
    elif r.exit_min < 930:
        bits.append(f"exit mark {int(960 - r.exit_min)} min stale")
    return "no -- " + ", ".join(bits)


def compound(rets, stake=40.0):
    path, eq = [], stake
    for r in rets:
        eq *= (1 + r)
        path.append(eq)
    return path


def arm(T, rets, label, stake=40.0):
    r = np.asarray([x for x in rets if x == x], dtype=float)
    if not len(r):
        print(f"  {label:22s} no trades")
        return
    path = compound(r, stake)
    lg = np.log1p(np.clip(r, -0.999, None))
    print(f"  {label:22s}{len(r):>4d}{r.mean() * 100:>+10.1f}%"
          f"{np.median(r) * 100:>+10.1f}%{(r > 0).mean() * 100:>8.0f}%"
          f"{(np.exp(lg.mean()) - 1) * 100:>+12.1f}%{path[-1]:>10.2f}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--stake", type=float, default=40.0)
    args = ap.parse_args(argv)
    work = Path(args.work)
    T = pd.read_parquet(work / "trades.parquet")
    sess, bars = {}, {}
    for f in sorted(work.glob("grouped_*.json")):
        rows = json.loads(f.read_text()).get("results") or []
        if rows:
            bars[f.stem.split("_")[-1]] = {x["T"]: x for x in rows}
    days = sorted(bars)
    px_prev = {}
    for _, r in T.iterrows():
        before = [d for d in days if d < r.entry]
        if before and r.ticker in bars[before[-1]]:
            px_prev[(r.date, r.ticker)] = bars[before[-1]][r.ticker]["c"]
    T = liquidity(T, work / "opt_cache")

    T["under_ret"] = T.spot_exit / T.spot_open - 1
    T["dir_ret"] = np.where(T.side == "call", T.call_ret, T.put_ret)
    T["dir_entry"] = np.where(T.side == "call", T.call_entry, T.put_entry)
    T["dir_exit"] = np.where(T.side == "call", T.call_exit, T.put_exit)
    T["straddle_entry"] = T.call_entry + T.put_entry
    T["straddle_exit"] = T.call_exit + T.put_exit
    T["straddle_ret"] = T.straddle_exit / T.straddle_entry - 1
    T["dir_vol"] = np.where(T.side == "call", T.call_vol, T.put_vol)
    T["dir_filltime"] = np.where(T.side == "call", T.call_filltime, T.put_filltime)
    T["dir_exittime"] = np.where(T.side == "call", T.call_exittime, T.put_exittime)
    # Executable means two things, and the volume of the leg you did NOT trade
    # is neither of them. Tyra's put printed 2,024 contracts while its call --
    # the leg the positive reading called for -- printed nine, and the only one
    # of those after 09:35 was at 15:59. A fill struck near the closing bell is
    # not an entry on the morning of the news.
    ft = pd.to_datetime(T.dir_filltime)
    T["fill_min"] = ft.dt.hour * 60 + ft.dt.minute
    xt = pd.to_datetime(T.dir_exittime)
    T["exit_min"] = xt.dt.hour * 60 + xt.dt.minute
    # A mark is only a mark if something traded near it. Core Scientific's call
    # last printed at 12:45 -- one contract, stock near its high -- and treating
    # that as a 16:00 close credited a 30% gain on a day the stock fell 1.4%.
    T["exec_ok"] = ((T.dir_vol >= MIN_CONTRACTS) & (T.fill_min <= 630)
                    & (T.exit_min >= 930))
    T["straddle_ok"] = ((T[["call_vol", "put_vol"]].min(axis=1) >= MIN_CONTRACTS)
                        & (T.fill_min <= 630) & (T.exit_min >= 930))
    T["rank"] = T.groupby("date").cumcount() + 1

    print("\n" + "=" * 100)
    print("EVERY TRADE")
    print("=" * 100)
    print(f"  {'date':11s}{'tkr':6s}{'rk':>3s}{'judge':>6s}{'side':>6s}{'K':>7s}"
          f"{'entry':>7s}{'exit':>7s}{'option':>9s}{'stock':>8s}"
          f"{'contracts':>11s}{'in at':>7s}{'out at':>8s}  tradeable?")
    for _, r in T.iterrows():
        v, ft = r.dir_vol, pd.Timestamp(r.dir_filltime)
        ret = "     n/a" if r.dir_ret != r.dir_ret else f"{r.dir_ret * 100:>+8.1f}%"
        ep = "    n/a" if r.dir_entry != r.dir_entry else f"{r.dir_entry:>7.2f}"
        xp = "    n/a" if r.dir_exit != r.dir_exit else f"{r.dir_exit:>7.2f}"
        print(f"  {r.date:11s}{r.ticker:6s}{r['rank']:>3d}{r.judge:>+6d}{r.side:>6s}"
              f"{r.strike:>7.1f}{ep}{xp}{ret}{r.under_ret * 100:>+7.1f}%"
              f"{v:>11,.0f}{(ft.strftime('%H:%M') if ft == ft else '  --  '):>7s}"
              f"{(pd.Timestamp(r.dir_exittime).strftime('%H:%M') if r.dir_exittime == r.dir_exittime else '  --  '):>8s}"
              f"  {why(r, v)}")
    thin = int((T.dir_vol < MIN_CONTRACTS).sum())
    stale = int(((T.dir_vol >= MIN_CONTRACTS) & ~T.exec_ok).sum())
    print(f"\n  Contract counts are the whole session's volume in that strike; one")
    print(f"  contract is 100 shares. Of {len(T)} selected names, {thin} traded fewer")
    print(f"  than {MIN_CONTRACTS} contracts and a further {stale} traded enough but had no")
    print(f"  print near one end of the hold, so the mark is not a price anyone")
    print(f"  could have transacted at. {int(T.exec_ok.sum())} survive both tests.")

    liq = Path(args.work) / "optliq.parquet"
    if liq.exists():
        L = {(str(r.date), str(r.ticker)): r
             for _, r in pd.read_parquet(liq).iterrows()}
        print("\n" + "=" * 100)
        print("WHAT THE LIQUIDITY GATE CLEARED, AND WHAT WAS ACTUALLY TRADED")
        print("=" * 100)
        print("  The gate is measured before the filing, on the strike nearest the")
        print("  pre-filing close. A gap moves the money to a different strike, and the")
        print("  liquidity does not necessarily follow it.\n")
        print(f"  {'tkr':6s}{'gate strike':>13s}{'pre-filing vol':>16s}"
              f"{'traded strike':>15s}{'entry-day vol':>15s}")
        for _, r in T.iterrows():
            row = L.get((str(r.date), str(r.ticker)))
            if row is None or "strike" not in row:
                continue
            print(f"  {r.ticker:6s}{row.strike:>13g}{row.pre_vol:>16,.0f}"
                  f"{r.strike:>15g}{r.dir_vol:>15,.0f}")

    print("\n" + "=" * 100)
    print(f"ARMS  (${args.stake:.0f} compounded trade by trade, in date order)")
    print("=" * 100)
    print(f"  {'arm':22s}{'n':>4s}{'mean':>10s}{'median':>10s}{'win':>8s}"
          f"{'compounds':>12s}{'$40 ->':>10s}")
    S = T.sort_values(["date", "rank"])
    arm(S, S.dir_ret, "directional, both", args.stake)
    arm(S, S[S["rank"] == 1].dir_ret, "best only", args.stake)
    arm(S, S[S["rank"] == 2].dir_ret, "second only", args.stake)
    arm(S, S.straddle_ret, "straddle, both", args.stake)
    arm(S[S.exec_ok], S[S.exec_ok].dir_ret, "EXECUTABLE only", args.stake)
    arm(S[S.straddle_ok], S[S.straddle_ok].straddle_ret,
        "EXECUTABLE straddle", args.stake)
    arm(S, S.call_ret, "always the call", args.stake)
    arm(S, S.put_ret, "always the put", args.stake)
    arm(S, S.under_ret, "the stock itself", args.stake)

    print("\n" + "=" * 100)
    print("AGAINST THE PRE-REGISTRATION")
    print("=" * 100)
    b = S[S["rank"] == 1].dir_ret.mean()
    s = S[S["rank"] == 2].dir_ret.mean()
    print(f"  H1  best {b * 100:+.1f}% vs second {s * 100:+.1f}%  ->  "
          f"{'PASS' if b > s else 'FAIL'}  (n=3 vs 3; this resolves nothing)")
    neg = S[S.judge < 0]
    pos = S[S.judge > 0]
    if len(neg):
        print(f"  H2  judged negative: option {neg.dir_ret.mean() * 100:+.1f}%, "
              f"stock {neg.under_ret.mean() * 100:+.1f}%  (n={len(neg)})")
    if len(pos):
        print(f"  H3  judged positive: option {pos.dir_ret.mean() * 100:+.1f}%, "
              f"stock {pos.under_ret.mean() * 100:+.1f}%  (n={len(pos)})")
    print(f"  H4  straddle {S.straddle_ret.mean() * 100:+.1f}% vs "
          f"directional {S.dir_ret.mean() * 100:+.1f}%  ->  "
          f"{'PASS' if S.straddle_ret.mean() > S.dir_ret.mean() else 'FAIL'}")

    print("\n" + "=" * 100)
    print("WHERE THE REACTION ACTUALLY HAPPENED")
    print("=" * 100)
    print("  A filing released before the bell is priced into the opening print. An")
    print("  entry at that open buys the stock after the news, not before it. The gap")
    print("  is what the market did with the filing; the hold is all the strategy can")
    print("  reach.\n")
    print(f"  {'tkr':6s}{'judge':>6s}{'prev close':>12s}{'entry open':>12s}"
          f"{'the gap':>10s}{'the hold':>10s}{'both':>9s}")
    for _, r in S.iterrows():
        prev = px_prev.get((r.date, r.ticker))
        if prev is None:
            continue
        gap = r.spot_open / prev - 1
        print(f"  {r.ticker:6s}{r.judge:>+6d}{prev:>12.2f}{r.spot_open:>12.2f}"
              f"{gap * 100:>+9.1f}%{r.under_ret * 100:>+9.1f}%"
              f"{((1 + gap) * (1 + r.under_ret) - 1) * 100:>+8.1f}%")

    print("\n" + "=" * 100)
    print("WHAT THE OPTION COST THAT THE STOCK DID NOT")
    print("=" * 100)
    print("  The move the stock made, and what the option did with it. A stock that")
    print("  moved the right way and an option that still lost is time and implied")
    print("  volatility, not a wrong call.\n")
    print(f"  {'tkr':6s}{'stock':>9s}{'right way?':>12s}{'option':>10s}{'gap':>10s}")
    for _, r in S.iterrows():
        want = 1 if r.side == "call" else -1
        right = (np.sign(r.under_ret) == want)
        print(f"  {r.ticker:6s}{r.under_ret * 100:>+8.1f}%{str(right):>12s}"
              f"{r.dir_ret * 100:>+9.1f}%{(r.dir_ret - want * r.under_ret) * 100:>+9.1f}pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
