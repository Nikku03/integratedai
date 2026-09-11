"""Price the selected catalyst trades as listed options, Polygon aggregates.

Entry is the first session that had **not yet opened** when the 8-K was
accepted, so a filing released at 07:10 is traded that morning and one released
at 16:30 the next. Exit is Thursday's close, the last session with data.

Contract rule, fixed before any price was pulled:

* the nearest standard monthly expiration at least five calendar days after
  entry -- 2026-09-18 for every trade here, eight to ten days out;
* the strike nearest the underlying's opening price on the entry session;
* a **call** where the filing was judged positive and a **put** where it was
  judged negative.

Both legs are priced for every name regardless of direction, which costs
nothing extra and makes the straddle arm of the pre-registration measurable.

Fills
-----
The key available here is not entitled to Polygon's NBBO feed, so there are no
bid-ask quotes and **no spread is modelled**. Entry is the first minute bar's
close at or after 09:35 ET, five minutes into the session, chosen so the fill
is a price that actually traded rather than an opening print. Exit is the
contract's closing trade. Every figure this produces is therefore an upper
bound: on single-name options a 2-10% spread is ordinary, and crossing it twice
comes straight off the result.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd

BASE = "https://api.polygon.io"
#: Five requests a minute on this key, measured. Everything is cached to disk so
#: a rerun costs nothing.
PACE = 13.0
EXPIRY = "2026-09-18"
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
    for attempt in range(5):
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
            raise
    return None


def pick_contracts(cache: Path, ticker: str, spot: float, entry: str):
    d = api("/v3/reference/options/contracts", cache, f"chain_{ticker}_{entry}",
            underlying_ticker=ticker, expiration_date=EXPIRY, limit=1000,
            as_of=entry)
    res = (d or {}).get("results") or []
    if not res:
        return None, None, 0
    strikes = sorted({c["strike_price"] for c in res})
    k = min(strikes, key=lambda s: abs(s - spot))
    call = next((c for c in res if c["strike_price"] == k
                 and c["contract_type"] == "call"), None)
    put = next((c for c in res if c["strike_price"] == k
                and c["contract_type"] == "put"), None)
    return call, put, len(res)


def entry_price(cache: Path, occ: str, day: str) -> tuple[float, int, str]:
    """First traded price at or after 09:35 ET on the entry session.

    A thin contract may not print at all after 09:35 -- Hycroft's put traded
    only in the first four minutes. Rather than drop the leg, the fill falls
    back to the first print of the day and the substitution is recorded, so a
    reader can see which fills are the weak ones instead of having to trust
    that none are.
    """
    d = api(f"/v2/aggs/ticker/{occ}/range/1/minute/{day}/{day}", cache,
            f"min_{occ}_{day}", adjusted="true", limit=5000, sort="asc")
    rows = (d or {}).get("results") or []
    if not rows:
        return float("nan"), 0, "no prints"
    t = pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True) \
          .tz_convert("America/New_York")
    mins = t.hour * 60 + t.minute
    ok = [r for r, m in zip(rows, mins) if m >= 575]
    if ok:
        return float(ok[0]["c"]), len(rows), "09:35+"
    return float(rows[0]["c"]), len(rows), "first print only"


def exit_price(cache: Path, occ: str, a: str, b: str):
    d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{a}/{b}", cache,
            f"day_{occ}", adjusted="true", limit=50, sort="asc")
    rows = (d or {}).get("results") or []
    if not rows:
        return float("nan"), []
    return float(rows[-1]["c"]), rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--k", type=int, default=2, help="names traded per session")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "opt_cache"
    cache.mkdir(parents=True, exist_ok=True)

    S = pd.read_parquet(work / "selected.parquet")
    # a market holiday returns status OK with an empty body -- 2026-09-07 was
    # Labor Day. Keeping it would make it a candidate entry session.
    px = {}
    for p in sorted(work.glob("grouped_*.json")):
        rows = json.loads(p.read_text()).get("results") or []
        if rows:
            px[p.stem.split("_")[-1]] = {r["T"]: r for r in rows}
    sess = sorted(px)

    book = S[S.score > 0].groupby("date").head(args.k).reset_index(drop=True)
    out = []
    for _, r in book.iterrows():
        entry = r.entry_session
        if entry is None or entry not in px or entry > EXIT_DAY:
            print(f"  {r.ticker}: filed {r.acc_et}, first tradeable session is "
                  f"{entry or 'beyond the data'} -- no hold inside the window")
            continue
        bar = px.get(entry, {}).get(r.ticker)
        if bar is None:
            print(f"  {r.ticker}: no underlying bar on {entry}")
            continue
        call, put, n = pick_contracts(cache, r.ticker, bar["o"], entry)
        if not call or not put:
            print(f"  {r.ticker}: no {EXPIRY} chain ({n} contracts seen)")
            continue
        side = "call" if r.judge > 0 else "put"
        rec = dict(date=r.date, ticker=r.ticker, judge=int(r.judge),
                   thesis=r.thesis, entry=entry, exit=EXIT_DAY, side=side,
                   strike=call["strike_price"], expiry=EXPIRY,
                   spot_open=bar["o"], spot_exit=px[EXIT_DAY][r.ticker]["c"],
                   n_contracts=n, score=float(r.score))
        for leg, c in (("call", call), ("put", put)):
            occ = c["ticker"]
            ep, nm, how = entry_price(cache, occ, entry)
            xp, days = exit_price(cache, occ, entry, EXIT_DAY)
            rec[f"{leg}_occ"] = occ
            rec[f"{leg}_entry"] = ep
            rec[f"{leg}_exit"] = xp
            rec[f"{leg}_minbars"] = nm
            rec[f"{leg}_fill"] = how
            rec[f"{leg}_daybars"] = len(days)
            rec[f"{leg}_ret"] = (xp / ep - 1) if ep == ep and ep > 0 else float("nan")
        out.append(rec)
        print(f"  {r.ticker} {entry} strike {rec['strike']} "
              f"call {rec['call_entry']}->{rec['call_exit']} "
              f"put {rec['put_entry']}->{rec['put_exit']}", flush=True)

    T = pd.DataFrame(out)
    T.to_parquet(work / "trades.parquet")
    print(f"\n  {len(T)} trades priced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
