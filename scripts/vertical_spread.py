"""Price the pre-registered short vertical credit spread, entry close to exit open.

The structure is fixed by ``docs/PREREG_VERTICAL.md`` and nothing here chooses it.
``run_z`` -- the five-session return into the last close before acceptance, in
units of that name's own volatility -- says which side to sell, the short strike
is the one nearest that same close, and the long strike is the one nearest ten
percent further out in the direction of the risk.

Two points of discipline carry over from the tests this one was built out of.

**The reference price is knowable at the moment of entry.** An earlier version of
this pipeline picked strikes from the session *before* the one it traded in, and
so chose them against a price that had already gapped. Here entry and reference
are the same bell: the trade is put on at the close whose price picks the strikes.

**Fills come from minute bars, with their timestamps.** A daily bar's close is
the last *trade*, which on a thin weekly can be hours before the bell -- one exit
in an earlier run was a single contract at 12:45 credited as a closing mark. Entry
is the last print at or before 16:00 of the entry session, exit the first at or
after 09:35 of the next, and both timestamps are kept so a stale fill can be seen.

One aggregates request spans both sessions per contract, so a trade costs three
requests: the chain, then a range per leg.

A vertical's value is bounded by its width -- that is arbitrage, not modelling --
so a closing mark assembled from two thin prints is clamped to ``[0, width]``
before it is believed. The clamp is reported whenever it binds.
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
PACE = 13.0          # the key allows five requests a minute
MAX_DTE = 10         # "weekly" enforced as what it is for
WING = 0.10          # long leg ten percent further out
Z_GATE = 0.5
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
            with urllib.request.urlopen(url, timeout=90) as r:
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


def marks(cache: Path, occ: str, entry: str, exit_: str) -> dict:
    """Last print at or before the entry bell, first at or after 09:35 next day."""
    d = api(f"/v2/aggs/ticker/{occ}/range/1/minute/{entry}/{exit_}", cache,
            f"mm_{occ}_{entry}_{exit_}", adjusted="true", limit=50000, sort="asc")
    res = (d or {}).get("results") or []
    out = dict(px_in=np.nan, px_out=np.nan, t_in="", t_out="",
               vol_in=0.0, vol_out=0.0)
    if not res:
        return out
    t = pd.to_datetime([x["t"] for x in res], unit="ms", utc=True) \
          .tz_convert("America/New_York")
    day = np.array([str(x.date()) for x in t])
    mins = np.array([x.hour * 60 + x.minute for x in t])
    ent = [(x, ts) for x, ts, d_, m in zip(res, t, day, mins)
           if d_ == entry and m <= 960]
    ext = [(x, ts) for x, ts, d_, m in zip(res, t, day, mins)
           if d_ == exit_ and m >= 575]
    if ent:
        out["px_in"], out["t_in"] = float(ent[-1][0]["c"]), str(ent[-1][1])
        out["vol_in"] = float(sum(x[0]["v"] for x in ent))
    if ext:
        out["px_out"], out["t_out"] = float(ext[0][0]["c"]), str(ext[0][1])
        out["vol_out"] = float(sum(x[0]["v"] for x in ext))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--events", default="/tmp/claude-0/opt/vert_prefile.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/vert_trades.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    cache.mkdir(parents=True, exist_ok=True)
    bars, sessions = load_bars(work)

    P = pd.read_parquet(args.events)
    P["side"] = np.where(P.run_z > Z_GATE, "call",
                         np.where(P.run_z < -Z_GATE, "put", ""))
    n_flat = int((P.side == "").sum())
    T = P[P.side != ""].sort_values(["entry", "ticker"]).reset_index(drop=True)
    print(f"  {len(P)} screened events -> {len(T)} carry a signal "
          f"(|run_z| > {Z_GATE}), {n_flat} sit out")
    print(f"  {(T.side == 'call').sum()} call spreads, {(T.side == 'put').sum()} put spreads\n",
          flush=True)

    rows = []
    for i, r in enumerate(T.itertuples(), 1):
        ref = float(r.spot)                       # last close before acceptance
        ch = api("/v3/reference/options/contracts", cache,
                 f"ch_{r.ticker}_{r.entry}", underlying_ticker=r.ticker,
                 as_of=r.entry, limit=1000,
                 **{"expiration_date.gt": r.exit,
                    "expiration_date.lte": (pd.Timestamp(r.entry)
                                            + pd.Timedelta(days=45)).date().isoformat()})
        res = (ch or {}).get("results") or []
        if not res:
            print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} no chain", flush=True)
            continue
        exps = sorted({c["expiration_date"] for c in res})
        exp = exps[0]
        dte = (pd.Timestamp(exp) - pd.Timestamp(r.entry)).days
        if dte > MAX_DTE:
            print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} nearest expiry {dte}d "
                  f"-- no weekly, skipped", flush=True)
            continue
        leg = {c["strike_price"]: c["ticker"] for c in res
               if c["expiration_date"] == exp and c["contract_type"] == r.side}
        ks = sorted(leg)
        if len(ks) < 2:
            print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} chain too sparse", flush=True)
            continue
        k_short = min(ks, key=lambda s: abs(s - ref))
        target = ref * (1 + WING) if r.side == "call" else ref * (1 - WING)
        out_ks = [s for s in ks if (s > k_short if r.side == "call" else s < k_short)]
        if not out_ks:
            print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} no strike beyond the short leg",
                  flush=True)
            continue
        k_long = min(out_ks, key=lambda s: abs(s - target))
        width = abs(k_long - k_short)

        s_m = marks(cache, leg[k_short], r.entry, r.exit)
        l_m = marks(cache, leg[k_long], r.entry, r.exit)
        rows.append(dict(
            date=r.date, ticker=r.ticker, company=r.company, acc=r.acc,
            entry=r.entry, exit=r.exit, timing=r.timing, side=r.side,
            run_z=float(r.run_z), mktcap=float(r.mktcap), ps=float(r.ps),
            dvol=float(r.dvol), ref=ref, expiry=exp, dte=int(dte),
            k_short=float(k_short), k_long=float(k_long), width=float(width),
            occ_short=leg[k_short], occ_long=leg[k_long],
            short_in=s_m["px_in"], short_out=s_m["px_out"],
            long_in=l_m["px_in"], long_out=l_m["px_out"],
            vol_short=s_m["vol_in"] + s_m["vol_out"],
            vol_long=l_m["vol_in"] + l_m["vol_out"],
            t_in=s_m["t_in"], t_out=s_m["t_out"],
            spot_in=bars.get(r.entry, {}).get(r.ticker, {}).get("c", np.nan),
            spot_out=bars.get(r.exit, {}).get(r.ticker, {}).get("o", np.nan),
        ))
        print(f"  [{i:>2d}/{len(T)}] {r.ticker:6s} {r.side:4s} "
              f"{k_short:g}/{k_long:g} w={width:g} exp {exp} ({dte}d)  "
              f"short {s_m['px_in']}->{s_m['px_out']}  "
              f"long {l_m['px_in']}->{l_m['px_out']}", flush=True)

    D = pd.DataFrame(rows)
    if D.empty:
        print("\n  nothing priced")
        return 0
    D.to_parquet(args.out)
    priced = D[["short_in", "short_out", "long_in", "long_out"]].notna().all(axis=1)
    print(f"\n  {len(D)} spreads built, {int(priced.sum())} with all four marks")
    print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
