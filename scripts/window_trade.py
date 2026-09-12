"""Buy one weekly option on the judged direction, and see what it does.

A call where the filing was judged positive, a put where it was judged negative,
nothing at all where it was judged zero. The trade is opened on the first session
that OPENS after the filing was accepted -- you cannot trade on news before the
market is open to receive it -- and the pre-registered exit is the close of that
same session.

The strike is chosen against the price you actually buy at
---------------------------------------------------------
The chain lookup ran before the readings, keyed to the session before the event,
and it picked its strike from that session's opening price. That is the wrong
reference: the purchase happens the following morning, after a gap. The strike is
re-selected here from the purchase session's own open, using the cached chain
responses -- every strike is already in them, so this costs no requests. Using
the open rather than any later price keeps it knowable at the moment of purchase.

Fills come from minute bars
---------------------------
A daily bar's open and close are the first and last *trades*, which on a thin
weekly can be hours from the bell. Entry is the first print at or after 09:35 and
the exit the last at or before 16:00, and both timestamps are recorded so a stale
fill can be excluded rather than believed. One request per contract covers both,
because entry and primary exit fall on the same session.
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
    ap.add_argument("--out", default="/tmp/claude-0/opt/win_trades.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    bars, sessions = load_bars(work)

    J = pd.read_parquet(work / "win_judged.parquet")
    C = pd.read_parquet(work / "win_chains.parquet")
    C = C[C.skip == ""] if "skip" in C else C
    M = J.merge(C[["date", "ticker", "expiry", "dte", "n_expiries_within_21d"]],
                on=["date", "ticker"], how="inner")
    M = M[M.direction != 0].reset_index(drop=True)
    print(f"  {len(M)} events have both a weekly chain and a directional call\n", flush=True)

    rows = []
    for i, r in enumerate(M.itertuples(), 1):
        buy_day = r.exit                       # first session opening after the filing
        b = bars.get(buy_day, {}).get(r.ticker)
        if b is None:
            continue
        spot = b["o"]
        ch = cache / f"ch_{r.ticker}_{r.entry}.json"
        if not ch.exists():
            continue
        res = json.loads(ch.read_text()).get("results") or []
        side = "call" if r.direction > 0 else "put"
        ks = sorted({c["strike_price"] for c in res
                     if c["expiration_date"] == r.expiry and c["contract_type"] == side})
        if not ks:
            continue
        k = min(ks, key=lambda s: abs(s - spot))   # at the money at the moment of purchase
        occ = next(c["ticker"] for c in res if c["expiration_date"] == r.expiry
                   and c["strike_price"] == k and c["contract_type"] == side)
        d = api(f"/v2/aggs/ticker/{occ}/range/1/minute/{buy_day}/{buy_day}", cache,
                f"m_{occ}_{buy_day}", adjusted="true", limit=5000, sort="asc")
        mr = (d or {}).get("results") or []
        entry_px = exit_px = float("nan")
        t_in = t_out = None
        vol = float(sum(x["v"] for x in mr))
        if mr:
            t = pd.to_datetime([x["t"] for x in mr], unit="ms", utc=True) \
                  .tz_convert("America/New_York")
            mins = t.hour * 60 + t.minute
            after = [(x, ts) for x, ts, m in zip(mr, t, mins) if m >= 575]
            before = [(x, ts) for x, ts, m in zip(mr, t, mins) if m <= 960]
            if after:
                entry_px, t_in = float(after[0][0]["c"]), after[0][1]
            if before:
                exit_px, t_out = float(before[-1][0]["c"]), before[-1][1]
        rows.append(dict(
            date=r.date, ticker=r.ticker, acc=r.acc, direction=int(r.direction),
            side=side, event_type=r.event_type, materiality=r.materiality,
            is_news=bool(r.is_news), confidence=r.confidence,
            already_priced=bool(r.already_priced), run_z=r.run_z, run_z1=r.run_z1,
            buy_day=buy_day, expiry=r.expiry, dte=int(r.dte), strike=k, occ=occ,
            spot_open=spot, spot_close=b["c"], spot_high=b["h"], spot_low=b["l"],
            opt_entry=entry_px, opt_exit=exit_px, opt_vol=vol,
            t_in=str(t_in) if t_in is not None else "",
            t_out=str(t_out) if t_out is not None else "",
            rationale=r.rationale))
        print(f"  [{i:>3d}/{len(M)}] {r.ticker:6s} {buy_day} {side:4s} K={k:g} "
              f"{entry_px}->{exit_px}  vol {vol:,.0f}", flush=True)

    T = pd.DataFrame(rows)
    T.to_parquet(args.out)
    print(f"\n  {T.opt_entry.notna().sum()} of {len(T)} priced")
    return 0


if __name__ == "__main__":
    sys.exit(main())
