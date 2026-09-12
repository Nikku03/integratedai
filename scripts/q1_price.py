"""Price both legs of every Q1 candidate, for a position opened before the event.

The trade is pre-positioned, so the strike must be at the money at the moment of
purchase -- the **close of the last session before acceptance** -- not the open
of that session and not the price after the gap. The chain lookup ran earlier
against the session's open because it had to run before the rule was applied;
the strike is re-selected here from the cached chain, which already contains
every strike and so costs no requests.

Both the call and the put are priced for every name regardless of which way the
rule points. That is deliberate: the momentum and reversal arms are mirrors, and
pricing only the side one of them chose would make the other unmeasurable.

One request per contract covers the whole span. A single daily-aggregate call
from a week before entry through the exit session yields the pre-event volume
used for the liquidity gate, the entry close, and the exit open.
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


def by_day(rows):
    return {pd.Timestamp(x["t"], unit="ms", tz="UTC")
              .tz_convert("America/New_York").strftime("%Y-%m-%d"): x for x in rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/q1_trades.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    bars, sessions = load_bars(work)

    P = pd.read_parquet(work / "q1_prefile.parquet")
    C = pd.read_parquet(work / "q1_chains.parquet")
    C = C[C.skip == ""] if "skip" in C else C
    M = P.merge(C[["date", "ticker", "expiry", "dte"]], on=["date", "ticker"], how="inner")
    print(f"  {len(M)} events have a weekly chain; pricing both legs\n", flush=True)

    rows = []
    for i, r in enumerate(M.itertuples(), 1):
        buy_px = bars.get(r.entry, {}).get(r.ticker, {}).get("c")
        sell_bar = bars.get(r.exit, {}).get(r.ticker)
        if buy_px is None or sell_bar is None:
            continue
        ch = cache / f"ch_{r.ticker}_{r.entry}.json"
        if not ch.exists():
            continue
        res = json.loads(ch.read_text()).get("results") or []
        ks = sorted({c["strike_price"] for c in res if c["expiration_date"] == r.expiry})
        if not ks:
            continue
        k = min(ks, key=lambda s: abs(s - buy_px))   # at the money at purchase
        lo = sessions[max(0, sessions.index(r.entry) - LOOKBACK)]
        rec = dict(date=r.date, ticker=r.ticker, entry=r.entry, exit=r.exit,
                   expiry=r.expiry, dte=int(r.dte), strike=k, spot_buy=buy_px,
                   spot_open=sell_bar["o"], spot_close=sell_bar["c"],
                   run_z=r.run_z, run_z1=r.run_z1, pre_run5=r.pre_run5,
                   already_priced=bool(r.already_priced), vol20=r.vol20,
                   timing=r.timing, mktcap=r.mktcap, ps=r.ps, dvol=r.dvol)
        ok = True
        for side in ("call", "put"):
            occ = next((c["ticker"] for c in res if c["expiration_date"] == r.expiry
                        and c["strike_price"] == k and c["contract_type"] == side), None)
            if not occ:
                ok = False
                break
            d = api(f"/v2/aggs/ticker/{occ}/range/1/day/{lo}/{r.exit}", cache,
                    f"q1_{occ}_{r.entry}", adjusted="true", limit=60, sort="asc")
            rowsd = by_day((d or {}).get("results") or [])
            pre = [v for day, v in rowsd.items() if day < r.entry]
            rec[f"{side}_occ"] = occ
            rec[f"{side}_prevol"] = float(sum(v["v"] for v in pre))
            rec[f"{side}_preactive"] = len(pre)
            rec[f"{side}_buy"] = rowsd.get(r.entry, {}).get("c", np.nan)
            rec[f"{side}_sell"] = rowsd.get(r.exit, {}).get("o", np.nan)
        if not ok:
            continue
        rows.append(rec)
        gap = sell_bar["o"] / buy_px - 1
        print(f"  [{i:>3d}/{len(M)}] {r.ticker:6s} {r.entry} K={k:g} {r.dte}d  "
              f"gap {gap * 100:+6.1f}%  c {rec.get('call_buy')}->{rec.get('call_sell')}  "
              f"p {rec.get('put_buy')}->{rec.get('put_sell')}", flush=True)

    T = pd.DataFrame(rows)
    T.to_parquet(args.out)
    print(f"\n  {len(T)} events priced on both legs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
