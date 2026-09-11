"""Does this name have an option market, measured before the filing exists?

The first run of this test selected six names and discovered afterwards that
four of them had no tradeable at-the-money option: Disc Medicine traded 480,869
shares on 09-10 and not one contract, and Tyra's $20 call printed nine contracts
in a session its stock moved 24%. Reporting that after the fact is not the same
as refusing to select them, so the measurement moves in front of the choice.

Point-in-time, and it matters here
----------------------------------
Option volume **on the filing day** is partly caused by the filing. Gating on it
would admit exactly the names whose chains only wake up for an event, which is
the opposite of knowing you could have got filled. The window is therefore the
five sessions ending on the last session that closed *before* the filing was
accepted, and the strike is the one nearest that session's close -- not the one
nearest the entry price, which is not knowable yet.

What is measured
----------------
One strike, on the side the reading would actually trade: the at-the-money call
where the filing is judged positive, the put where it is judged negative. A
single strike is a noisy proxy for a whole chain, and a wider probe would be
better, but each contract costs one request against a key limited to five a
minute. The bar is set low enough that the noise does not decide anything:
a name that cannot clear 250 contracts across five sessions does not have an
option market, whatever the neighbouring strikes are doing.
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

import pandas as pd

BASE = "https://api.polygon.io"
PACE = 13.0
EXPIRY = "2026-09-18"
#: Contracts in the at-the-money strike across the five pre-filing sessions.
#: 250 is 25,000 shares of exposure over a week -- a deliberately low bar,
#: chosen so that clearing it means "a market exists", not "a market is deep".
MIN_PRE_CONTRACTS = 250
#: ...spread over at least this many sessions, so one block trade does not
#: qualify a chain that is otherwise silent.
MIN_ACTIVE_SESSIONS = 3
PRE_SESSIONS = 5
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--min-dollar-vol", type=float, default=25e6)
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "opt_cache"
    cache.mkdir(parents=True, exist_ok=True)

    S = pd.read_parquet(work / "selected.parquet")
    bars = {}
    for f in sorted(work.glob("grouped_*.json")):
        rows = json.loads(f.read_text()).get("results") or []
        if rows:
            bars[f.stem.split("_")[-1]] = {r["T"]: r for r in rows}
    days = sorted(bars)

    # every name the reading gives a view on and that trades enough stock to be
    # worth asking about. Judge-0 names are never traded, so never probed.
    cand = S[(S.judge != 0) & (S.dvol >= args.min_dollar_vol)]
    print(f"  probing {len(cand)} candidates "
          f"({cand.ticker.nunique()} tickers) at {PACE:.0f}s per request\n")

    out = []
    for _, r in cand.iterrows():
        lp = r.last_pre
        spot = bars.get(lp, {}).get(r.ticker, {}).get("c")
        if spot is None:
            continue
        ch = api("/v3/reference/options/contracts", cache,
                 f"chain_{r.ticker}_{lp}", underlying_ticker=r.ticker,
                 expiration_date=EXPIRY, limit=1000, as_of=lp)
        res = (ch or {}).get("results") or []
        side = "call" if r.judge > 0 else "put"
        strikes = sorted({c["strike_price"] for c in res
                          if c["contract_type"] == side})
        if not strikes:
            out.append(dict(date=r.date, ticker=r.ticker, occ="", pre_vol=0.0,
                            active=0, eligible=False, note="no chain"))
            print(f"  {r.ticker:6s} {r.date}  no {EXPIRY} {side} chain")
            continue
        k = min(strikes, key=lambda s: abs(s - spot))
        occ = next(c["ticker"] for c in res
                   if c["strike_price"] == k and c["contract_type"] == side)
        idx = days.index(lp)
        lo = days[max(0, idx - PRE_SESSIONS + 1)]
        d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{lo}/{lp}", cache,
                f"preday_{occ}_{lp}", adjusted="true", limit=50, sort="asc")
        rows = (d or {}).get("results") or []
        vol = float(sum(x["v"] for x in rows))
        active = len(rows)
        ok = vol >= MIN_PRE_CONTRACTS and active >= MIN_ACTIVE_SESSIONS
        out.append(dict(date=r.date, ticker=r.ticker, occ=occ, strike=k,
                        pre_vol=vol, active=active, eligible=bool(ok),
                        note=""))
        print(f"  {r.ticker:6s} {r.date}  {side:4s} K={k:<7g} "
              f"{lo}..{lp}  {vol:>9,.0f} contracts over {active}/{PRE_SESSIONS} "
              f"sessions  ->  {'ELIGIBLE' if ok else 'no market'}", flush=True)

    L = pd.DataFrame(out)
    L.to_parquet(work / "optliq.parquet")
    print(f"\n  {int(L.eligible.sum())} of {len(L)} candidates have a tradeable "
          f"option market before the filing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
