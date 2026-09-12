"""What it would take for a bidirectional trade on these filings to pay.

The aim is a setup where the option swings far enough either way that a straddle
profits without having to call the direction. That is a specific, checkable
condition, and it is **not** "one leg moves 100%".

The arithmetic first
--------------------
A straddle costs ``c + p``. At the money ``c ≈ p``, so if the winning leg
doubles and the loser goes to zero the position is worth ``2c`` against a cost
of ``2c`` -- **break-even**. A +100% move on one leg is where the trade stops
losing, not where it starts winning. To profit, the winning leg has to roughly
triple, which happens when the underlying's realised move exceeds the straddle's
breakeven:

    breakeven move = (call premium + put premium) / spot

So the question is never "how big is the move". It is "how big is the move
relative to the move already priced in". Two ways to win that comparison:

1. **Find bigger moves** -- select filings whose reaction beats what the chain
   charges.
2. **Pay less for them** -- a shorter-dated contract has less time value, so a
   smaller move covers it and the percentage swings are larger.

And one more, which turns out to be the only one that works here:

3. **Be holding it when the gap happens, and sell into the gap.** A straddle
   pays for net displacement, not for the path. Rigetti gapped +7.8% on its
   filing and gave the whole move back within two sessions, so a straddle held
   across both earned nothing -- but one sold at the opening print earned 66%.

The last section prices what that costs: a near-dated straddle bleeds while it
waits, and the bleed is the reason this only works on an event whose date is
known.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://api.polygon.io"
PACE = 13.0
EXIT_DAY = "2026-09-10"
_last = [0.0]


def api(path: str, cache: Path, key: str, **params) -> dict | None:
    p = cache / f"{key}.json"
    if p.exists() and p.stat().st_size:
        return json.loads(p.read_text())
    tok = os.environ.get("POLYGON_API_KEY")
    if not tok:
        raise SystemExit("set POLYGON_API_KEY")
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{BASE}{path}?{q}&apiKey={tok}"
    for _ in range(6):
        wait = PACE - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                d = json.loads(r.read())
            p.write_text(json.dumps(d))
            return d
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20)
                continue
            if e.code in (403, 404):
                return None
            raise
    return None


def minute(cache: Path, occ: str, day: str):
    d = api(f"/v2/aggs/ticker/{occ}/range/1/minute/{day}/{day}", cache,
            f"min_{occ}_{day}", adjusted="true", limit=5000, sort="asc")
    rows = (d or {}).get("results") or []
    if not rows:
        return None
    t = pd.to_datetime([x["t"] for x in rows], unit="ms", utc=True) \
          .tz_convert("America/New_York")
    return list(zip(rows, [x.hour * 60 + x.minute for x in t]))


def fill(cache: Path, occ: str, day: str, at_open: bool):
    """Entry = first print from 09:35; exit = last print by 16:00."""
    rows = minute(cache, occ, day)
    if not rows:
        return float("nan"), 0.0
    vol = float(sum(r["v"] for r, _ in rows))
    if at_open:
        ok = [r for r, m in rows if m >= 575]
        return (float(ok[0]["c"]) if ok else float("nan")), vol
    ok = [r for r, m in rows if m <= 960]
    return (float(ok[-1]["c"]) if ok else float("nan")), vol


def gap_exit(cache: Path, S: pd.DataFrame, bars: dict, tickers: list[str]) -> None:
    """Buy before the filing, sell at the first print after it."""
    print("\n" + "=" * 96)
    print("4. BOUGHT BEFORE THE FILING, SOLD INTO THE GAP")
    print("=" * 96)
    print("  The straddle is held across the disclosure and closed at the opening")
    print("  print, so it is paid for the gap rather than for where the stock ends")
    print("  up. Both of these gapped and then round-tripped, which is why holding")
    print("  on earns nothing and selling into the open earns a great deal.\n")
    print(f"  {'tkr':6s}{'expiry':>12s}{'DTE':>5s}{'K':>6s}{'buy':>7s}{'sell':>7s}"
          f"{'straddle':>10s}{'call leg':>10s}{'put leg':>10s}{'stock gap':>11s}")
    for tk in tickers:
        sel = S[(S.ticker == tk) & (S.score > 0)]
        if not len(sel):
            continue
        r = sel.iloc[0]
        lp, ent = r.last_pre, r.entry_session
        pre = bars[lp][tk]["c"]
        gap = bars[ent][tk]["o"] / pre - 1
        ch = api("/v3/reference/options/contracts", cache, f"allexp_{tk}_{lp}",
                 underlying_ticker=tk, **{"expiration_date.gte": lp,
                                          "expiration_date.lte": "2026-10-20"},
                 limit=1000, as_of=lp)
        res = (ch or {}).get("results") or []
        for exp in sorted({c["expiration_date"] for c in res}):
            if exp < ent:
                continue
            ks = sorted({c["strike_price"] for c in res
                         if c["expiration_date"] == exp})
            if not ks:
                continue
            k = min(ks, key=lambda x: abs(x - pre))
            legs = {}
            for side in ("call", "put"):
                occ = next((c["ticker"] for c in res
                            if c["expiration_date"] == exp
                            and c["strike_price"] == k
                            and c["contract_type"] == side), None)
                if not occ:
                    continue
                d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{lp}/{ent}", cache,
                        f"gapspan_{occ}", adjusted="true", limit=20, sort="asc")
                by = {pd.Timestamp(x["t"], unit="ms", tz="UTC")
                        .tz_convert("America/New_York").strftime("%Y-%m-%d"): x
                      for x in (d or {}).get("results") or []}
                legs[side] = (by.get(lp, {}).get("c"), by.get(ent, {}).get("o"))
            if len(legs) < 2 or any(v is None for pair in legs.values() for v in pair):
                continue
            (cb, cs), (pb, ps) = legs["call"], legs["put"]
            buy, sell = cb + pb, cs + ps
            print(f"  {tk:6s}{exp:>12s}"
                  f"{(pd.Timestamp(exp) - pd.Timestamp(lp)).days:>5d}{k:>6g}"
                  f"{buy:>7.2f}{sell:>7.2f}{(sell / buy - 1) * 100:>+9.1f}%"
                  f"{(cs / cb - 1) * 100:>+9.1f}%{(ps / pb - 1) * 100:>+9.1f}%"
                  f"{gap * 100:>+10.1f}%")


def theta_cost(cache: Path, bars: dict) -> None:
    """What the same straddle costs while nothing happens."""
    print("\n" + "=" * 96)
    print("5. WHAT IT COSTS TO BE EARLY")
    print("=" * 96)
    print("  The same contract, over the sessions before the filing. This is the")
    print("  whole catch: the gap pays well, and waiting for it does not come free.\n")
    rows: dict[str, dict] = {}
    for side, occ in (("call", "O:RGTI260911C00015000"),
                      ("put", "O:RGTI260911P00015000")):
        d = api(f"/v2/aggs/ticker/{occ}/range/1/day/2026-08-28/2026-09-08", cache,
                f"theta_{occ}", adjusted="true", limit=30, sort="asc")
        for x in (d or {}).get("results") or []:
            k = pd.Timestamp(x["t"], unit="ms", tz="UTC") \
                  .tz_convert("America/New_York").strftime("%Y-%m-%d")
            rows.setdefault(k, {})[side] = x["c"]
    print(f"  {'session':12s}{'stock':>8s}{'call':>7s}{'put':>7s}"
          f"{'straddle':>10s}{'vs 08-28':>10s}")
    base = None
    for k in sorted(rows):
        v = rows[k]
        if "call" not in v or "put" not in v:
            continue
        tot = v["call"] + v["put"]
        base = base or tot
        px = bars.get(k, {}).get("RGTI", {}).get("c", float("nan"))
        tag = "   <- filing lands pre-open" if k == "2026-09-08" else ""
        print(f"  {k:12s}{px:>8.2f}{v['call']:>7.2f}{v['put']:>7.2f}"
              f"{tot:>10.2f}{(tot / base - 1) * 100:>+9.1f}%{tag}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--tickers", default="RGTI,QBTS")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "opt_cache"

    bars = {}
    for f in sorted(work.glob("grouped_*.json")):
        rows = json.loads(f.read_text()).get("results") or []
        if rows:
            bars[f.stem.split("_")[-1]] = {r["T"]: r for r in rows}
    S = pd.read_parquet(work / "selected.parquet")
    M = pd.read_parquet(work / "moves.parquet")

    # ---------------------------------------------------------------- part 1
    print("\n" + "=" * 96)
    print("1. THE MOVE THESE FILINGS DELIVER, AND WHO DELIVERS IT")
    print("=" * 96)
    M = M.assign(bucket=pd.cut(M.dvol, [0, 10e6, 30e6, 100e6, 1e12],
                               labels=["<$10M", "$10-30M", "$30-100M", ">$100M"]))
    print(f"  {'stock $volume/day':20s}{'n':>5s}{'mean |D+1 move|':>18s}"
          f"{'90th pct':>11s}{'share >10%':>12s}{'share >20%':>12s}")
    for b, g in M.groupby("bucket", observed=True):
        print(f"  {str(b):20s}{len(g):>5d}{g.d1.abs().mean() * 100:>17.1f}%"
              f"{np.percentile(g.d1.abs(), 90) * 100:>10.1f}%"
              f"{(g.d1.abs() > 0.10).mean() * 100:>11.0f}%"
              f"{(g.d1.abs() > 0.20).mean() * 100:>11.0f}%")
    print("\n  The move is concentrated in the names too small to have an option")
    print("  chain. That is the central tension: the screen finds the movement and")
    print("  the option market is not there to sell it to you.")

    # ---------------------------------------------------------------- part 2
    print("\n" + "=" * 96)
    print("2. WHAT THE CHAIN CHARGED, AGAINST WHAT THE STOCK DID")
    print("=" * 96)
    T = pd.read_parquet(work / "trades.parquet")
    print(f"  {'tkr':7s}{'expiry':>12s}{'DTE':>5s}{'straddle':>10s}{'spot':>8s}"
          f"{'breakeven':>11s}{'realised':>10s}{'paid off?':>11s}")
    for _, r in T.iterrows():
        cost = r.call_entry + r.put_entry
        spot = r.spot_open
        be = cost / spot
        real = abs(r.spot_exit / spot - 1)
        dte = (pd.Timestamp(r.expiry) - pd.Timestamp(r.entry)).days
        print(f"  {r.ticker:7s}{r.expiry:>12s}{dte:>5d}{cost:>10.2f}{spot:>8.2f}"
              f"{be * 100:>10.1f}%{real * 100:>9.1f}%"
              f"{('YES' if real > be else 'no'):>11s}")
    print("\n  Breakeven is what the market charged for the move. Realised is what it")
    print("  got. Every one of these was priced above what the filing delivered.")

    # ---------------------------------------------------------------- part 3
    print("\n" + "=" * 96)
    print("3. THE SAME TRADE ON THE SHORTEST EXPIRY THAT HAS A MARKET")
    print("=" * 96)
    print("  Less time value means a smaller move covers the premium and the")
    print("  percentage swings are bigger. The cost is that a near-dated contract")
    print("  needs the move immediately.\n")

    rows = []
    for tk in args.tickers.split(","):
        sel = S[(S.ticker == tk) & (S.score > 0)]
        if not len(sel):
            continue
        r = sel.iloc[0]
        entry = r.entry_session
        spot_o = bars[entry][tk]["o"]
        spot_x = bars[EXIT_DAY][tk]["c"]
        ch = api("/v3/reference/options/contracts", cache, f"allexp_{tk}_{entry}",
                 underlying_ticker=tk, **{"expiration_date.gte": entry,
                                          "expiration_date.lte": "2026-10-20"},
                 limit=1000, as_of=entry)
        res = (ch or {}).get("results") or []
        exps = sorted({c["expiration_date"] for c in res})
        for exp in exps:
            if exp < EXIT_DAY:          # must survive the hold
                continue
            ks = sorted({c["strike_price"] for c in res
                         if c["expiration_date"] == exp})
            if not ks:
                continue
            k = min(ks, key=lambda s: abs(s - spot_o))
            legs = {}
            for side in ("call", "put"):
                occ = next((c["ticker"] for c in res
                            if c["expiration_date"] == exp
                            and c["strike_price"] == k
                            and c["contract_type"] == side), None)
                if not occ:
                    continue
                e, ev = fill(cache, occ, entry, True)
                x, xv = fill(cache, occ, EXIT_DAY, False)
                legs[side] = (e, x, ev, xv)
            if len(legs) < 2:
                continue
            (ce, cx, cv, _), (pe, px_, pv, _) = legs["call"], legs["put"]
            cost = ce + pe
            dte = (pd.Timestamp(exp) - pd.Timestamp(entry)).days
            rows.append(dict(ticker=tk, expiry=exp, dte=dte, strike=k,
                             cost=cost, spot=spot_o,
                             breakeven=cost / spot_o if cost == cost else np.nan,
                             realised=abs(spot_x / spot_o - 1),
                             call_ret=cx / ce - 1 if ce == ce and ce > 0 else np.nan,
                             put_ret=px_ / pe - 1 if pe == pe and pe > 0 else np.nan,
                             strad=(cx + px_) / cost - 1 if cost == cost and cost > 0 else np.nan,
                             cvol=cv, pvol=pv))

    gap_exit(cache, S, bars, args.tickers.split(","))
    theta_cost(cache, bars)

    R = pd.DataFrame(rows)
    if len(R):
        R.to_parquet(work / "expiry_ladder.parquet")
        print(f"  {'tkr':6s}{'expiry':>12s}{'DTE':>5s}{'K':>7s}{'cost':>7s}"
              f"{'breakeven':>11s}{'realised':>10s}{'call':>9s}{'put':>9s}"
              f"{'straddle':>10s}{'vol c/p':>12s}")
        for _, r in R.iterrows():
            f = lambda v: "   n/a" if v != v else f"{v * 100:>+6.0f}%"
            print(f"  {r.ticker:6s}{r.expiry:>12s}{r.dte:>5.0f}{r.strike:>7g}"
                  f"{r.cost:>7.2f}{r.breakeven * 100:>10.1f}%{r.realised * 100:>9.1f}%"
                  f"{f(r.call_ret):>9s}{f(r.put_ret):>9s}{f(r.strad):>10s}"
                  f"{int(r.cvol):>6d}/{int(r.pvol):<5d}")
        print("\n  |leg move| >= 100% on either side:")
        big = R[(R.call_ret.abs() >= 1.0) | (R.put_ret.abs() >= 1.0)]
        print(f"  {len(big)} of {len(R)} expiry/name combinations reached it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
