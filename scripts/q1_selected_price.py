"""Price only the leg the rule actually buys, on the names that can carry a weekly.

Pricing every strike of every candidate costs 374 requests against a key limited
to five a minute. The rule buys one contract per event, and only liquid names
carry a weekly chain at all, so this prices exactly that: the most liquid events
the rule trades, one leg each, chain and price in a single pass.

The cost is that the **momentum arm's option return is not measured** -- it is
the mirror of the reversal arm in direction but not in price, and measuring it
would double the request count. Its direction accuracy is known exactly
(1 minus reversal's) and its P&L is not. That is stated rather than glossed.

The strike is at the money at the moment of purchase, which for a pre-positioned
trade is the **close of the last session before acceptance** -- not that
session's open, and not the price after the gap.
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
MAX_DTE = 10
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--events", default="/tmp/claude-0/opt/q1_selected.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/q1_sel_trades.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    cache.mkdir(parents=True, exist_ok=True)
    bars, sessions = load_bars(work)
    S = pd.read_parquet(args.events)
    print(f"  {len(S)} selected events, one leg each\n", flush=True)

    rows = []
    for i, r in enumerate(S.itertuples(), 1):
        buy_px = bars.get(r.entry, {}).get(r.ticker, {}).get("c")
        sell = bars.get(r.exit, {}).get(r.ticker)
        if buy_px is None or sell is None:
            continue
        ch = api("/v3/reference/options/contracts", cache, f"ch_{r.ticker}_{r.entry}",
                 underlying_ticker=r.ticker, as_of=r.entry, limit=1000,
                 **{"expiration_date.gt": r.exit,
                    "expiration_date.lte": (pd.Timestamp(r.entry)
                                            + pd.Timedelta(days=45)).date().isoformat()})
        res = (ch or {}).get("results") or []
        gap = sell["o"] / buy_px - 1
        base = dict(date=r.date, ticker=r.ticker, entry=r.entry, exit=r.exit,
                    side=r.side, run_z=r.run_z, pre_run5=r.pre_run5,
                    spot_buy=buy_px, spot_open=sell["o"], spot_close=sell["c"],
                    gap=gap, dvol=r.dvol, vol20=r.vol20, timing=r.timing)
        if not res:
            rows.append(dict(base, skip="no chain"))
            print(f"  [{i:>2d}/{len(S)}] {r.ticker:6s} no chain", flush=True)
            continue
        exps = sorted({c["expiration_date"] for c in res})
        exp = exps[0]
        dte = (pd.Timestamp(exp) - pd.Timestamp(r.entry)).days
        if dte > MAX_DTE:
            rows.append(dict(base, dte=dte, skip=f"nearest expiry {dte}d"))
            print(f"  [{i:>2d}/{len(S)}] {r.ticker:6s} nearest expiry {dte}d -- no weekly",
                  flush=True)
            continue
        ks = sorted({c["strike_price"] for c in res
                     if c["expiration_date"] == exp and c["contract_type"] == r.side})
        if not ks:
            rows.append(dict(base, skip=f"no {r.side} chain"))
            continue
        k = min(ks, key=lambda s: abs(s - buy_px))
        occ = next(c["ticker"] for c in res if c["expiration_date"] == exp
                   and c["strike_price"] == k and c["contract_type"] == r.side)
        lo = sessions[max(0, sessions.index(r.entry) - LOOKBACK)]
        d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{lo}/{r.exit}", cache,
                f"q1s_{occ}_{r.entry}", adjusted="true", limit=60, sort="asc")
        got = {pd.Timestamp(x["t"], unit="ms", tz="UTC")
                 .tz_convert("America/New_York").strftime("%Y-%m-%d"): x
               for x in (d or {}).get("results") or []}
        pre = [v for day, v in got.items() if day < r.entry]
        rec = dict(base, expiry=exp, dte=dte, strike=k, occ=occ, skip="",
                   prevol=float(sum(v["v"] for v in pre)), preactive=len(pre),
                   opt_buy=got.get(r.entry, {}).get("c", np.nan),
                   opt_sell=got.get(r.exit, {}).get("o", np.nan))
        rows.append(rec)
        ret = (rec["opt_sell"] / rec["opt_buy"] - 1) if rec["opt_buy"] else np.nan
        print(f"  [{i:>2d}/{len(S)}] {r.ticker:6s} {r.side:4s} K={k:g} {dte}d  "
              f"gap {gap * 100:+6.1f}%  {rec['opt_buy']}->{rec['opt_sell']}  "
              f"{'' if ret != ret else f'{ret * 100:+.0f}%'}", flush=True)

    T = pd.DataFrame(rows)
    T.to_parquet(args.out)
    ok = T[(T.skip == "") & T.opt_buy.notna()] if "skip" in T else T
    print(f"\n  {len(ok)} of {len(T)} priced on a weekly contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
