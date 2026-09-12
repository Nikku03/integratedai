"""Projection basis for a trade placed BEFORE the filing exists.

The direction cannot be read from the document, so it has to be forecast, and a
forecast is only worth as much as the base rate behind it. This assembles that
base rate from each company's **own history of earnings reactions** rather than
from a generic assumption:

* past earnings dates come from that issuer's 8-K item 2.02 filings, with the
  acceptance timestamp deciding which session absorbed the news -- exactly the
  convention the backtests use;
* the gap is measured from the last close before acceptance to the next open,
  which is the move a position held across the event actually captures;
* two years of daily bars supply the prices.

What comes out, per name: how often the stock gapped up, how big the typical gap
was, and how big the largest was. That is the honest input to a projection. It is
history, not prediction, and a company that gapped 20% four times running can
still gap 2% on the fifth.

Nothing here uses the upcoming filing, because it does not exist yet.
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


def subs(cik: int, cache: Path) -> dict | None:
    p = cache / f"subs_{cik}.json"
    if not p.exists() or not p.read_text().strip():
        r = subprocess.run(
            ["curl", "-sS", "--compressed", "--max-time", "40",
             "-H", f"User-Agent: {UA}",
             f"https://data.sec.gov/submissions/CIK{cik:010d}.json"],
            capture_output=True, text=True)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        p.write_text(r.stdout)
    return json.loads(p.read_text())


def past_earnings(cik: int, cache: Path) -> list[pd.Timestamp]:
    """Acceptance timestamps of this issuer's past item 2.02 filings."""
    d = subs(cik, cache)
    if not d:
        return []
    rec = d["filings"]["recent"]
    out = []
    for form, items, acc in zip(rec["form"], rec["items"], rec["acceptanceDateTime"]):
        if form == "8-K" and "2.02" in str(items):
            out.append(pd.Timestamp(acc).tz_convert("America/New_York"))
    return sorted(out)


def gaps_for(days: list[str], bars: dict, events: list[pd.Timestamp]) -> list[dict]:
    out = []
    for et in events:
        d = et.date().isoformat()
        mins = et.hour * 60 + et.minute
        pre = [s for s in days if s < d] + ([d] if mins >= 960 and d in days else [])
        post = [s for s in days if s > d] if mins >= 960 else \
               ([d] if mins < 570 and d in days else [s for s in days if s > d])
        if not pre or not post:
            continue
        a, b = bars[max(pre)], bars[min(post)]
        if a["c"] <= 0:
            continue
        out.append(dict(when=str(et)[:16], gap=b["o"] / a["c"] - 1,
                        to_close=b["c"] / a["c"] - 1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--out", default="/tmp/claude-0/opt/live_basis.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "live_cache"
    cache.mkdir(parents=True, exist_ok=True)
    K = pd.read_parquet(work / "live_shortlist.parquet")
    want = [t.strip().upper() for t in args.tickers.split(",")]
    K = K[K.symbol.isin(want)]

    rows = []
    for r in K.itertuples():
        d = api(f"/v2/aggs/ticker/{r.symbol}/range/1/day/2024-09-01/2026-09-11",
                cache, f"hist_{r.symbol}", adjusted="true", limit=1000, sort="asc")
        res = (d or {}).get("results") or []
        if not res:
            print(f"  {r.symbol}: no price history")
            continue
        bars = {pd.Timestamp(x["t"], unit="ms", tz="UTC")
                  .tz_convert("America/New_York").strftime("%Y-%m-%d"): x for x in res}
        days = sorted(bars)
        ev = past_earnings(int(r.cik), work / "cache")
        g = gaps_for(days, bars, ev)
        c = np.array([bars[x]["c"] for x in days], float)
        lr = np.diff(np.log(c[-21:]))
        vol = float(np.std(lr) * np.sqrt(252))
        gp = np.array([x["gap"] for x in g], float)
        rows.append(dict(
            symbol=r.symbol, name=r.name, reportDate=r.reportDate,
            timeOfTheDay=r.timeOfTheDay, close=r.close, mktcap=r.mktcap, ps=r.ps,
            dvol=r.dvol, vol20=vol, n_events=len(g),
            gap_mean_abs=float(np.mean(np.abs(gp))) if len(gp) else np.nan,
            gap_median_abs=float(np.median(np.abs(gp))) if len(gp) else np.nan,
            gap_max_abs=float(np.max(np.abs(gp))) if len(gp) else np.nan,
            up_rate=float((gp > 0).mean()) if len(gp) else np.nan,
            gap_mean=float(np.mean(gp)) if len(gp) else np.nan,
            history=json.dumps(g[-8:])))
        print(f"  {r.symbol:6s} {len(g):>2d} past earnings gaps   "
              f"mean |gap| {np.mean(np.abs(gp)) * 100:>5.1f}%   "
              f"max {np.max(np.abs(gp)) * 100:>5.1f}%   "
              f"up {(gp > 0).mean() * 100:>3.0f}%   vol20 {vol * 100:>3.0f}%", flush=True)

    B = pd.DataFrame(rows)
    B.to_parquet(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
