"""Defined-risk selling into a scheduled earnings release.

Everything measured in this repository points here and nothing else is left:

* an **unscheduled** filing cannot be timed -- a near-dated option bleeds ~8.7%
  of premium per quiet session against a ~4% daily chance the filing lands;
* so the event must be **scheduled**, and scheduled events are systematically
  **overpriced** -- 13.7% charged against 9.9% delivered over 2,842 releases,
  and 30 of 30 names priced above their own demonstrated gap history;
* overpriced means the edge is on the **sell** side;
* but naked selling was measured with a **-387%-of-margin** worst trade, 3.9x
  the capital posted, with 1 in 189 losing more than the whole margin.

A short iron butterfly keeps the overpricing edge and converts that unbounded
loss into a known one.

The structure, fixed before pricing
-----------------------------------
* **Sell** the at-the-money call and put, strike nearest the close of the last
  session before acceptance -- the moment the position goes on.
* **Buy** a call and a put as wings at the strikes nearest **K x 1.15** and
  **K x 0.85**. Fifteen percent is chosen because the mean earnings gap measured
  over 2,842 releases is 6.1% and the 90th percentile is 15.0%, so the wings sit
  where the distribution's tail begins rather than inside the body it is meant
  to sell.
* **Enter** at the close before the release, **exit** at the open after, which
  is where the whole move is.

Credit is what the two short legs fetch less what the two wings cost. **Maximum
loss is the wing width less that credit**, and that is also the margin a broker
holds against a defined-risk spread -- so unlike the naked case, return on
margin is bounded and knowable before the trade.

Four contracts means four requests per event against a five-a-minute key, so
this is deliberately run on the names already screened and chained rather than
on a fresh universe.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_straddle import load_bars  # noqa: E402

BASE = "https://api.polygon.io"
PACE = 13.0
WING = 0.15                     # wings at K x (1 +/- WING)
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


def leg(cache: Path, res, exp, strike, side, entry, exit_):
    occ = next((c["ticker"] for c in res if c["expiration_date"] == exp
                and c["strike_price"] == strike and c["contract_type"] == side), None)
    if not occ:
        return None, np.nan, np.nan, 0.0
    d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{entry}/{exit_}", cache,
            f"cs_{occ}_{entry}", adjusted="true", limit=20, sort="asc")
    got = {pd.Timestamp(x["t"], unit="ms", tz="UTC")
             .tz_convert("America/New_York").strftime("%Y-%m-%d"): x
           for x in (d or {}).get("results") or []}
    return (occ, got.get(entry, {}).get("c", np.nan),
            got.get(exit_, {}).get("o", np.nan), got.get(entry, {}).get("v", 0.0))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/condor.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    bars, sessions = load_bars(work)

    T = pd.read_parquet(work / "q1_sel_trades.parquet")
    T = T[T.skip == ""].copy()
    print(f"  {len(T)} scheduled earnings with a weekly chain; four legs each\n",
          flush=True)

    rows = []
    for i, r in enumerate(T.itertuples(), 1):
        ch = cache / f"ch_{r.ticker}_{r.entry}.json"
        if not ch.exists():
            continue
        res = json.loads(ch.read_text()).get("results") or []
        exp = r.expiry
        ks = sorted({c["strike_price"] for c in res if c["expiration_date"] == exp})
        if len(ks) < 5:
            continue
        S0 = r.spot_buy
        k = min(ks, key=lambda s: abs(s - S0))
        kc = min(ks, key=lambda s: abs(s - k * (1 + WING)))
        kp = min(ks, key=lambda s: abs(s - k * (1 - WING)))
        if kc <= k or kp >= k:
            continue
        legs = {}
        bad = False
        for nm, strike, side in (("sc", k, "call"), ("sp", k, "put"),
                                 ("wc", kc, "call"), ("wp", kp, "put")):
            occ, buy, sell, vol = leg(cache, res, exp, strike, side, r.entry, r.exit)
            if buy != buy or sell != sell:
                bad = True
                break
            legs[nm] = (occ, buy, sell, vol)
        if bad:
            print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} incomplete legs", flush=True)
            continue
        credit = legs["sc"][1] + legs["sp"][1] - legs["wc"][1] - legs["wp"][1]
        close_cost = legs["sc"][2] + legs["sp"][2] - legs["wc"][2] - legs["wp"][2]
        width = min(kc - k, k - kp)
        maxloss = width - credit
        pnl = credit - close_cost
        rows.append(dict(ticker=r.ticker, entry=r.entry, exit=r.exit, expiry=exp,
                         dte=r.dte, K=k, Kc=kc, Kp=kp, spot=S0, gap=r.gap,
                         credit=credit, close_cost=close_cost, width=width,
                         maxloss=maxloss, pnl=pnl,
                         ret_margin=pnl / maxloss if maxloss > 0 else np.nan,
                         cred_pct=credit / S0,
                         minvol=min(x[3] for x in legs.values())))
        print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} K={k:g} wings {kp:g}/{kc:g}  "
              f"gap {r.gap * 100:+6.1f}%  credit {credit:.2f}  maxloss {maxloss:.2f}  "
              f"P&L {pnl:+.2f}", flush=True)

    C = pd.DataFrame(rows)
    C.to_parquet(args.out)
    print(f"\n  {len(C)} iron butterflies priced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
