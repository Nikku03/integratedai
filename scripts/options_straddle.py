"""Long weekly straddle across a scheduled event, sold into the opening print.

The directional version of this strategy failed for a reason that was measured
rather than guessed: entered *after* a filing, the breakeven move implied by the
premium was 8-22% while the median post-filing move was 4.0%. The straddle only
works when it is already on the books when the news lands, and only when it is
closed into the gap -- both names studied gapped 7% and then round-tripped to
roughly flat, so holding across the event earned nothing while selling into the
open earned 66% and 82%.

That requires a date known in advance, which an 8-K does not have and an
earnings release does. This runs the trade on scheduled events only.

Timing, from the acceptance stamp rather than the index date
------------------------------------------------------------
A release accepted **after 16:00 ET** on day D is bought at D's close and sold
at D+1's open. One accepted **before 09:30 ET** on day D is bought at D-1's
close and sold at D's open. Either way the position is held across exactly one
event and one overnight, which is what keeps the decay bill small: the same
contract was measured bleeding ~8.7% of premium per quiet session.

An event that lands **during** the session is skipped. There is no way to be
positioned before it and out of it at the open without intraday data this key is
not entitled to, and pretending otherwise would be the whole result.

Only weeklies
-------------
The expiry is the nearest listed expiration strictly after the event, and it is
required to be within ``MAX_DTE`` days. On a name with only monthly options that
nearest expiry can be five weeks out, which triples the premium for the same
gap: measured across the ladder, the same event returned +66% on a 7-day contract
and +17% on a 42-day one. Requiring a short expiry *is* the requirement to trade
weeklies, expressed as the thing that actually matters.

One request, three measurements
-------------------------------
Polygon allows five requests a minute here, so each contract is fetched once
over a span that starts before the event and ends after it. That single response
yields the pre-event volume for the liquidity gate, the entry close and the exit
open -- rather than three separate calls for the same contract.
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
#: The expiry must be no further out than this, which is what "weekly" buys you.
MAX_DTE = 10
#: Contracts traded in the chosen strike over the sessions before entry.
MIN_PRE_CONTRACTS = 250
MIN_ACTIVE_SESSIONS = 3
#: Sessions of history pulled before entry, to measure that pre-event volume.
LOOKBACK = 7
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


def load_bars(work: Path) -> tuple[dict, list[str]]:
    bars = {}
    for f in sorted(work.glob("grouped_*.json")):
        rows = json.loads(f.read_text()).get("results") or []
        if rows:                       # a market holiday returns OK with no body
            bars[f.stem.split("_")[-1]] = {r["T"]: r for r in rows}
    return bars, sorted(bars)


def legs_for(sessions: list[str], et: pd.Timestamp) -> tuple[str | None, str | None]:
    """(entry session, exit session) for a release accepted at ``et``."""
    d = et.date().isoformat()
    mins = et.hour * 60 + et.minute
    if mins >= 960:                                  # after the close on d
        entry = d if d in sessions else None
        later = [s for s in sessions if s > d]
        return entry, (later[0] if later else None)
    if mins < 570:                                   # before the open on d
        before = [s for s in sessions if s < d]
        return (before[-1] if before else None), (d if d in sessions else None)
    return None, None                                # intraday: not tradeable here


def by_day(rows) -> dict:
    return {pd.Timestamp(x["t"], unit="ms", tz="UTC")
              .tz_convert("America/New_York").strftime("%Y-%m-%d"): x
            for x in rows}


def run_one(cache: Path, bars: dict, sessions: list[str], ev) -> dict | None:
    et = pd.Timestamp(ev.accepted_et)
    if et.tzinfo is None:
        et = et.tz_localize("America/New_York")
    entry, exit_ = legs_for(sessions, et)
    if entry is None or exit_ is None:
        return dict(ticker=ev.ticker, date=ev.date, skip="not held across one bell")
    if ev.ticker not in bars.get(entry, {}) or ev.ticker not in bars.get(exit_, {}):
        return dict(ticker=ev.ticker, date=ev.date, skip="no underlying bar")

    spot = bars[entry][ev.ticker]["c"]
    lo = sessions[max(0, sessions.index(entry) - LOOKBACK)]

    ch = api("/v3/reference/options/contracts", cache, f"wk_{ev.ticker}_{entry}",
             underlying_ticker=ev.ticker, as_of=entry, limit=1000,
             **{"expiration_date.gt": exit_,
                "expiration_date.lte": (pd.Timestamp(entry)
                                        + pd.Timedelta(days=MAX_DTE * 3)).date().isoformat()})
    res = (ch or {}).get("results") or []
    if not res:
        return dict(ticker=ev.ticker, date=ev.date, skip="no chain")

    exps = sorted({c["expiration_date"] for c in res})
    if not exps:
        return dict(ticker=ev.ticker, date=ev.date, skip="no expiry after the event")
    exp = exps[0]
    dte = (pd.Timestamp(exp) - pd.Timestamp(entry)).days
    weekly = len([e for e in exps
                  if (pd.Timestamp(e) - pd.Timestamp(entry)).days <= 21]) >= 2
    if dte > MAX_DTE:
        return dict(ticker=ev.ticker, date=ev.date, dte=dte, weekly=weekly,
                    skip=f"nearest expiry is {dte}d out -- no weekly")

    ks = sorted({c["strike_price"] for c in res if c["expiration_date"] == exp})
    k = min(ks, key=lambda s: abs(s - spot))
    out = dict(ticker=ev.ticker, date=ev.date, accepted_et=str(et), entry=entry,
               exit=exit_, expiry=exp, dte=dte, strike=k, weekly=weekly,
               spot_entry=spot, spot_exit_open=bars[exit_][ev.ticker]["o"],
               spot_exit_close=bars[exit_][ev.ticker]["c"], skip="")
    for side in ("call", "put"):
        occ = next((c["ticker"] for c in res if c["expiration_date"] == exp
                    and c["strike_price"] == k and c["contract_type"] == side), None)
        if not occ:
            out["skip"] = f"no {side} at {k}"
            return out
        d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{lo}/{exit_}", cache,
                f"wkspan_{occ}_{entry}", adjusted="true", limit=60, sort="asc")
        rows = by_day((d or {}).get("results") or [])
        pre = [v for day, v in rows.items() if day < entry]
        out[f"{side}_occ"] = occ
        out[f"{side}_prevol"] = float(sum(v["v"] for v in pre))
        out[f"{side}_preactive"] = len(pre)
        out[f"{side}_entry"] = rows.get(entry, {}).get("c", float("nan"))
        out[f"{side}_exit"] = rows.get(exit_, {}).get("o", float("nan"))
        out[f"{side}_exitclose"] = rows.get(exit_, {}).get("c", float("nan"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--events", default="/tmp/claude-0/opt/events.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/straddles.parquet")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "wk_cache"
    cache.mkdir(parents=True, exist_ok=True)

    bars, sessions = load_bars(work)
    E = pd.read_parquet(args.events)
    print(f"  {len(E)} scheduled events, {len(sessions)} sessions of tape\n", flush=True)

    rows = []
    for i, ev in enumerate(E.head(args.limit).itertuples(), 1):
        r = run_one(cache, bars, sessions, ev)
        if r:
            rows.append(r)
            tag = r.get("skip") or (f"K={r['strike']:g} {r['dte']}d "
                                    f"c {r.get('call_entry')}->{r.get('call_exit')} "
                                    f"p {r.get('put_entry')}->{r.get('put_exit')}")
            print(f"  [{i:>3d}/{min(len(E), args.limit)}] {r['ticker']:6s} {r['date']}  {tag}",
                  flush=True)
    T = pd.DataFrame(rows)
    T.to_parquet(args.out)
    ok = T[T.skip == ""] if "skip" in T else T
    print(f"\n  {len(ok)} straddles priced of {len(T)} events attempted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
