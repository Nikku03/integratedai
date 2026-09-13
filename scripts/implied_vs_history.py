"""Is the option cheap against what this company's earnings actually do?

Every other angle has been tried and failed for the same reason: on a scheduled
event the premium is priced at the move the market expects, so a typical move
breaks even and a correct direction call buys nothing. The one thing never
tested is whether the market gets that price **wrong for identifiable names**.

The comparison
--------------
An at-the-money straddle costs roughly the move the market implies, so one leg
is about half of it:

    implied move  ~=  2 x (premium / spot)

Against that, each company's **own** history of earnings gaps, built from its
past 8-K item 2.02 filings and measured last-close-before to next-open, exactly
as the trades are.

    cheapness  =  historical mean |gap|  -  implied move

Positive means the option is priced below what this issuer has actually
delivered. If the market prices earnings efficiently, cheapness predicts
nothing. If it anchors too hard on index-level volatility and underprices the
violent reporters, cheapness predicts everything.

Point-in-time, and it matters here more than anywhere
-----------------------------------------------------
Only earnings that occurred **before** the traded event are used. Including the
event's own gap in its own base rate would be circular and would manufacture the
result: a name that gapped 30% would look both cheap and profitable because the
same number appears on both sides.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

BASE = "https://api.polygon.io"
PACE = 13.0
UA = "Naresh Chhillar chhillarnaresh03@gmail.com"
MIN_HISTORY = 3
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


def past_2_02(cik: int, cache: Path, before: str) -> list[pd.Timestamp]:
    """Item 2.02 acceptance stamps strictly before ``before``."""
    p = cache / f"subs_{cik}.json"
    if not p.exists():
        r = subprocess.run(["curl", "-sS", "--compressed", "--max-time", "40",
                            "-H", f"User-Agent: {UA}",
                            f"https://data.sec.gov/submissions/CIK{cik:010d}.json"],
                           capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return []
        p.write_text(r.stdout)
    t = p.read_text()
    if not t.strip():
        return []
    rec = json.loads(t)["filings"]["recent"]
    out = []
    for form, items, acc in zip(rec["form"], rec["items"], rec["acceptanceDateTime"]):
        if form == "8-K" and "2.02" in str(items):
            ts = pd.Timestamp(acc).tz_convert("America/New_York")
            if ts.date().isoformat() < before:
                out.append(ts)
    return sorted(out)


def hist_gaps(days, bars, events):
    out = []
    for et in events:
        d = et.date().isoformat()
        mins = et.hour * 60 + et.minute
        pre = [s for s in days if s < d] + ([d] if mins >= 960 and d in days else [])
        post = ([d] if mins < 570 and d in days else [s for s in days if s > d])
        if not pre or not post:
            continue
        a, b = bars[max(pre)], bars[min(post)]
        if a["c"] > 0:
            out.append(b["o"] / a["c"] - 1)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/cheapness.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "live_cache"
    cache.mkdir(parents=True, exist_ok=True)

    T = pd.read_parquet(work / "q1_sel_trades.parquet")
    T = T[(T.skip == "") & T.opt_buy.notna() & T.opt_sell.notna() & (T.opt_buy > 0)].copy()
    S = pd.read_parquet(work / "q1_prefile.parquet")[["date", "ticker", "cik", "mktcap"]]
    T = T.merge(S, on=["date", "ticker"], how="left")
    print(f"  {len(T)} priced Q1 trades; building each name's prior gap history\n",
          flush=True)

    rows = []
    for r in T.itertuples():
        d = api(f"/v2/aggs/ticker/{r.ticker}/range/1/day/2024-06-01/2026-04-01",
                cache, f"pre_{r.ticker}", adjusted="true", limit=1000, sort="asc")
        res = (d or {}).get("results") or []
        if not res:
            continue
        bars = {pd.Timestamp(x["t"], unit="ms", tz="UTC")
                  .tz_convert("America/New_York").strftime("%Y-%m-%d"): x for x in res}
        days = sorted(bars)
        ev = past_2_02(int(r.cik), work / "cache", r.entry)
        g = hist_gaps(days, bars, ev)
        if len(g) < MIN_HISTORY:
            continue
        g = np.abs(np.array(g))
        prem = r.opt_buy / r.spot_buy
        implied = 2 * prem
        rows.append(dict(ticker=r.ticker, entry=r.entry, side=r.side, dte=r.dte,
                         prem=prem, implied=implied, hist_n=len(g),
                         hist_mean=float(g.mean()), hist_med=float(np.median(g)),
                         cheapness=float(g.mean()) - implied,
                         gap=r.gap, ret=r.opt_sell / r.opt_buy - 1,
                         prevol=r.prevol, mktcap=r.mktcap))
        print(f"  {r.ticker:6s} implied {implied * 100:>5.1f}%  history "
              f"{g.mean() * 100:>5.1f}% over {len(g)} events  -> "
              f"{'CHEAP' if g.mean() > implied else 'rich':>5s} "
              f"by {abs(g.mean() - implied) * 100:.1f}pp", flush=True)

    C = pd.DataFrame(rows)
    C.to_parquet(args.out)
    if not len(C):
        print("\n  no names with enough prior history")
        return 0

    print("\n" + "=" * 92)
    print("DOES CHEAPNESS PREDICT ANYTHING?")
    print("=" * 92)
    C["want"] = np.where(C.side == "call", 1, -1)
    C["realised_vs_implied"] = C.gap.abs() - C.implied
    print(f"  {len(C)} trades with at least {MIN_HISTORY} prior earnings gaps\n")
    print(f"  {'group':26s}{'n':>4s}{'implied':>10s}{'history':>10s}"
          f"{'actual gap':>12s}{'option':>10s}")
    for lab, m in (("option CHEAP vs history", C.cheapness > 0),
                   ("option RICH vs history", C.cheapness <= 0)):
        g = C[m]
        if len(g):
            print(f"  {lab:26s}{len(g):>4d}{g.implied.mean() * 100:>9.1f}%"
                  f"{g.hist_mean.mean() * 100:>9.1f}%{g.gap.abs().mean() * 100:>11.1f}%"
                  f"{g.ret.mean() * 100:>+9.0f}%")
    if C.cheapness.notna().sum() > 3:
        print(f"\n  corr(cheapness, actual |gap| - implied) = "
              f"{np.corrcoef(C.cheapness, C.realised_vs_implied)[0, 1]:+.2f}")
        print(f"  corr(cheapness, option return)          = "
              f"{np.corrcoef(C.cheapness, C.ret)[0, 1]:+.2f}")
        print("\n  The first is the honest test: does an option priced below the")
        print("  issuer's own history go on to deliver more than it charged?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
