"""Weekly option chains for the window's events: which exist, and at what strike.

Split into two stages on purpose. The chain lookup fixes the expiry and the
strike and does not depend on which way the filing is judged, so it runs while
the reading is still happening; only the choice of call or put waits for the
judgement. On a key limited to five requests a minute that ordering is the
difference between one pass and three.

"Weekly" is enforced as what it is actually for: the nearest expiration strictly
after the event must be within ``MAX_DTE`` days. On a name carrying only monthly
options that expiry can be five weeks out, which roughly triples the premium for
the same overnight move -- measured across an expiry ladder, one event returned
+66% on a 7-day contract and +17% on a 42-day one.
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

from options_straddle import load_bars  # noqa: E402

BASE = "https://api.polygon.io"
PACE = 13.0
MAX_DTE = 10
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
    ap.add_argument("--events", default="/tmp/claude-0/opt/win_prefile.parquet")
    ap.add_argument("--out", default="/tmp/claude-0/opt/win_chains.parquet")
    args = ap.parse_args(argv)
    work = Path(args.work)
    cache = work / "win_cache"
    cache.mkdir(parents=True, exist_ok=True)
    bars, sessions = load_bars(work)
    E = pd.read_parquet(args.events)
    print(f"  {len(E)} events, resolving weekly chains at {PACE:.0f}s per request\n",
          flush=True)

    out = []
    for i, r in enumerate(E.itertuples(), 1):
        entry, exit_ = r.entry, r.exit
        spot = bars.get(entry, {}).get(r.ticker, {}).get("o")
        if spot is None:
            out.append(dict(date=r.date, ticker=r.ticker, skip="no entry bar"))
            continue
        ch = api("/v3/reference/options/contracts", cache,
                 f"ch_{r.ticker}_{entry}", underlying_ticker=r.ticker, as_of=entry,
                 limit=1000, **{"expiration_date.gt": exit_,
                                "expiration_date.lte": (pd.Timestamp(entry)
                                                        + pd.Timedelta(days=45)).date().isoformat()})
        res = (ch or {}).get("results") or []
        if not res:
            out.append(dict(date=r.date, ticker=r.ticker, skip="no chain"))
            print(f"  [{i:>3d}/{len(E)}] {r.ticker:6s} {r.date}  no chain", flush=True)
            continue
        exps = sorted({c["expiration_date"] for c in res})
        exp = exps[0]
        dte = (pd.Timestamp(exp) - pd.Timestamp(entry)).days
        n_near = len([e for e in exps
                      if (pd.Timestamp(e) - pd.Timestamp(entry)).days <= 21])
        if dte > MAX_DTE:
            out.append(dict(date=r.date, ticker=r.ticker, dte=dte,
                            skip=f"nearest expiry {dte}d -- no weekly"))
            print(f"  [{i:>3d}/{len(E)}] {r.ticker:6s} {r.date}  "
                  f"nearest expiry {dte}d out -- no weekly", flush=True)
            continue
        ks = sorted({c["strike_price"] for c in res if c["expiration_date"] == exp})
        k = min(ks, key=lambda s: abs(s - spot))
        rec = dict(date=r.date, ticker=r.ticker, entry=entry, exit=exit_,
                   expiry=exp, dte=dte, strike=k, spot_open=spot,
                   n_expiries_within_21d=n_near, skip="")
        for side in ("call", "put"):
            occ = next((c["ticker"] for c in res if c["expiration_date"] == exp
                        and c["strike_price"] == k and c["contract_type"] == side), None)
            rec[f"{side}_occ"] = occ or ""
        out.append(rec)
        print(f"  [{i:>3d}/{len(E)}] {r.ticker:6s} {r.date}  "
              f"K={k:g} exp {exp} ({dte}d)", flush=True)

    C = pd.DataFrame(out)
    C.to_parquet(args.out)
    ok = C[C.skip == ""] if "skip" in C else C
    print(f"\n  {len(ok)} of {len(C)} events have a weekly contract at the money")
    return 0


if __name__ == "__main__":
    sys.exit(main())
