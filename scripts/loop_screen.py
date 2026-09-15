"""Apply the original test's screen to the full two-year event set.

The 61.9% was measured on a universe screened to market cap $300M-$20B and
trailing price-to-sales at or above 8.0x. The broad replication drops that screen
and lands at chance, so the screen is the whole question: either the effect is
real and conditional on expensive mid-cap growth, or the screen was one cut among
many and 118 events was small enough for one to look good.

Both the share count and the revenue are point-in-time -- only facts filed before
the entry session are visible -- and revenue comes from ``options_screen._revenue``
with the five corrections documented there.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import options_screen as osc  # noqa: E402


def fetch(cache: Path, cik: int) -> dict | None:
    f = cache / f"facts_{cik}.json"
    if f.exists():
        t = f.read_text()
        return json.loads(t) if t.strip() else None
    r = subprocess.run(["curl", "-sS", "--compressed", "--max-time", "40",
                        "-H", f"User-Agent: {osc.UA}", osc.FACTS.format(cik)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    try:
        d = json.loads(r.stdout)
    except json.JSONDecodeError:
        return None
    if "facts" not in d:
        f.write_text("")
        return None
    f.write_text(r.stdout)
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--features", default="/tmp/claude-0/opt/loop_features.parquet")
    ap.add_argument("--events", default="/tmp/claude-0/opt/loop_events.parquet")
    ap.add_argument("--panel", default="/tmp/claude-0/opt/panel")
    ap.add_argument("--cache", default="/tmp/claude-0/opt/cache")
    ap.add_argument("--out", default="/tmp/claude-0/opt/loop_screened.parquet")
    args = ap.parse_args(argv)
    cache = Path(args.cache)

    F = pd.read_parquet(args.features)
    E = pd.read_parquet(args.events)[["ticker", "entry", "cik"]]
    F = F.merge(E, on=["ticker", "entry"], how="left")
    C = pd.read_parquet(Path(args.panel) / "c.parquet")
    px = {(s, t): v for s, row in C.iterrows()
          for t, v in row.items() if v == v}

    ciks = sorted(F.cik.dropna().astype(int).unique())
    todo = [c for c in ciks if not (cache / f"facts_{c}.json").exists()]
    if todo:
        print(f"  fetching {len(todo)} missing companyfacts", flush=True)
        with ThreadPoolExecutor(5) as ex:
            list(ex.map(lambda c: fetch(cache, c), todo))

    rows, seen = [], 0
    for n, (cik, g) in enumerate(F.groupby(F.cik.astype("Int64")), 1):
        fx = fetch(cache, int(cik)) if cik == cik else None
        if not fx:
            continue
        seen += 1
        for r in g.itertuples():
            when = pd.Timestamp(r.entry)
            sh = float("nan")
            for tax, tag in osc.SHARE_TAGS:
                sh = osc.cc.stock(fx, tax, tag, when)
                if sh == sh and sh > 0:
                    break
            if sh != sh:
                continue
            p = px.get((r.entry, r.ticker))
            if p is None:
                continue
            cap = sh * p
            rev = osc._revenue(fx, when)
            if rev != rev:
                ps = float("nan")
            elif rev >= osc.MIN_MEANINGFUL_REV:
                ps = cap / rev
            elif rev > 0:
                ps = cap / rev
            else:
                ps = float("inf")
            rows.append(dict(r._asdict(), mktcap=cap, ps=ps))
        del fx
        if n % 400 == 0:
            print(f"    ... {n}/{len(ciks)} filers screened", flush=True)

    S = pd.DataFrame(rows).drop(columns=["Index"], errors="ignore")
    S.to_parquet(args.out)
    print(f"\n  XBRL on disk for {seen:,}/{len(ciks):,} filers")
    print(f"  {len(S):,} of {len(F):,} events have a measurable cap")
    inband = S.mktcap.between(osc.MIN_CAP, osc.MAX_CAP)
    rich = S.ps.notna() & (S.ps >= osc.MIN_PS)
    print(f"    in the $300M-$20B band:   {inband.sum():,}")
    print(f"    at P/S >= 8.0x:           {rich.sum():,}")
    print(f"    **both** (the screen):    {(inband & rich).sum():,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
