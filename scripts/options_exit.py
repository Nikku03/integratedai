"""When to close an event straddle: the ceiling, and the rules that reach it.

Selling at the opening print is one choice among many and probably not the best
one. Across the executable set, holding to that afternoon's close moved UAMY
from +55% to +114% and Rigetti from -24% to -4%, while moving Joby from -15% to
-41% and TeraWulf from -16% to -31%. Some events keep running and some fade
within hours, which is exactly the question worth answering.

Two kinds of exit are measured and they must not be confused
------------------------------------------------------------
**The ceiling.** Sell at the single best moment in the window. This is not a
strategy -- it requires knowing the peak before it happens -- and it is reported
only to bound the argument. If perfect timing still loses, no exit rule saves the
trade and the question is closed.

**Rules you could actually follow.** Each uses only information available at the
moment it fires:

* hold to the first close, the second, the third;
* a **trailing stop** -- ride the position and sell once it has given back X% of
  its best value so far. This is the "sell when the trend fades" idea stated so a
  computer can execute it, and unlike the ceiling it never looks forward;
* a **profit target** -- sell the moment the position is up X%.

A straddle has to be valued as one position, so both legs are read at the same
minute. Taking the day's high of the call and the day's high of the put and
adding them is meaningless: they move in opposite directions and never peak
together. Where minute bars exist the path is the sum minute by minute; where
only daily bars exist, a daily-high ceiling is reported separately and flagged
as the fiction it is.
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
HOLD_SESSIONS = 3
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


def stamp(rows, minute=False):
    out = {}
    for x in rows:
        t = pd.Timestamp(x["t"], unit="ms", tz="UTC").tz_convert("America/New_York")
        out[t if minute else t.strftime("%Y-%m-%d")] = x
    return out


def path_for(cache: Path, occ_c: str, occ_p: str, days: list[str]) -> pd.Series:
    """Combined straddle value, minute by minute, over ``days``."""
    legs = []
    for occ in (occ_c, occ_p):
        pts = {}
        for d in days:
            r = api(f"/v2/aggs/ticker/{occ}/range/1/minute/{d}/{d}", cache,
                    f"exmin_{occ}_{d}", adjusted="true", limit=5000, sort="asc")
            for t, x in stamp((r or {}).get("results") or [], minute=True).items():
                if 570 <= t.hour * 60 + t.minute <= 960:
                    pts[t] = float(x["c"])
        legs.append(pd.Series(pts).sort_index())
    if not len(legs[0]) or not len(legs[1]):
        return pd.Series(dtype=float)
    # a straddle is one position: both legs must be read at the same minute,
    # forward-filled from the last trade in each
    idx = legs[0].index.union(legs[1].index)
    return (legs[0].reindex(idx).ffill() + legs[1].reindex(idx).ffill()).dropna()


def rules(path: pd.Series, cost: float) -> dict:
    """Every exit rule, evaluated on one minute-by-minute value path."""
    if not len(path) or cost <= 0:
        return {}
    v = path.to_numpy()
    out = {"ceiling": v.max() / cost - 1, "floor": v.min() / cost - 1,
           "last": v[-1] / cost - 1,
           "peak_at": str(path.index[int(np.argmax(v))].strftime("%m-%d %H:%M"))}
    run = np.maximum.accumulate(v)
    for gb in (10, 20, 30):
        hit = np.where(v <= run * (1 - gb / 100))[0]
        out[f"trail{gb}"] = (v[hit[0]] if len(hit) else v[-1]) / cost - 1
    for tgt in (25, 50, 100):
        hit = np.where(v >= cost * (1 + tgt / 100))[0]
        out[f"target{tgt}"] = (v[hit[0]] if len(hit) else v[-1]) / cost - 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--only-executable", action="store_true")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "wk_cache"

    bars = {}
    for f in sorted(work.glob("grouped_*.json")):
        rows = json.loads(f.read_text()).get("results") or []
        if rows:
            bars[f.stem.split("_")[-1]] = {r["T"]: r for r in rows}
    sessions = sorted(bars)

    T = pd.read_parquet(work / "straddles.parquet")
    T = T[T.skip == ""].copy()
    T["cost"] = T.call_entry + T.put_entry
    T["prevol"] = T[["call_prevol", "put_prevol"]].min(axis=1)
    T["ok"] = ((T.prevol >= 250)
               & (T[["call_preactive", "put_preactive"]].min(axis=1) >= 3)
               & T[["call_entry", "put_entry", "call_exit", "put_exit"]].notna().all(axis=1)
               & (T.cost > 0))
    sel = T[T.ok] if args.only_executable else T[T.cost > 0]
    sel = sel[sel.cost.notna()]
    print(f"  {len(sel)} straddles, holding up to {HOLD_SESSIONS} sessions past the event\n",
          flush=True)

    out = []
    for ev in sel.itertuples():
        i = sessions.index(ev.exit)
        # a contract cannot be held past its own expiry, and a weekly expiring
        # two days after entry runs out well inside the hold window
        days = [d for d in sessions[i:i + HOLD_SESSIONS] if d <= ev.expiry]
        p = path_for(cache, ev.call_occ, ev.put_occ, days)
        rec = dict(ticker=ev.ticker, entry=ev.entry, exit=ev.exit, expiry=ev.expiry,
                   cost=ev.cost, prevol=ev.prevol, ok=bool(ev.ok),
                   open_ret=(ev.call_exit + ev.put_exit) / ev.cost - 1,
                   d1close=(ev.call_exitclose + ev.put_exitclose) / ev.cost - 1,
                   n_minutes=len(p))
        rec.update(rules(p, ev.cost))
        out.append(rec)
        print(f"  {ev.ticker:7s} {len(p):>4d} minutes  open {rec['open_ret'] * 100:>+7.1f}%"
              f"  ceiling {rec.get('ceiling', float('nan')) * 100:>+7.1f}%"
              f"  peak {rec.get('peak_at', '--')}", flush=True)

    R = pd.DataFrame(out)
    R.to_parquet(work / "exits.parquet")
    print(f"\n  {R.n_minutes.gt(0).sum()} of {len(R)} have a usable minute path")
    return 0


if __name__ == "__main__":
    sys.exit(main())
