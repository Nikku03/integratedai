"""Pull FINRA's consolidated short interest for every settlement date, once.

Semi-monthly cross-sections, roughly 16,000 symbols each, 2018 to 2025. That is
192 settlement dates and about 800 paged requests — a few minutes, and free.

Publication lag is the whole game
---------------------------------
Short interest is *settled* on one date and *disseminated* about eight business
days later. Using it on the settlement date would be look-ahead of the most
ordinary and most damaging kind: the model would know a position that the market
could not see for another week and a half, on exactly the illiquid names where
that week matters. So every row carries an ``available`` date set ten business
days after settlement — two more than FINRA's schedule requires, because being
early here is unrecoverable and being late costs only a little signal.

The other trap is the sentinel: ``daysToCoverQuantity`` is 999.99 for names whose
average volume is too small to divide by, which is the 90th percentile of the raw
column. Left in, "days to cover" reads as enormous for precisely the microcaps
this project trades. :mod:`iai.sources.shortinterest` turns it into NaN.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

#: FINRA disseminates about eight business days after settlement. Ten is used so
#: that a schedule change, a holiday week or a revision cannot make the feature
#: available before the market had it.
LAG_BDAYS = 10


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="/root/.iai/wide2015/short_interest.parquet")
    ap.add_argument("--start", default="2017-12-29")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--user-agent", default="integratedai research chhillarnaresh03@gmail.com")
    args = ap.parse_args(argv)
    out = Path(args.out)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources import shortinterest as si

    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=5.0,
                    ttl_hours=24 * 365 * 5, max_retries=4)

    dates = si.settlement_dates(args.start, args.end)
    print(f"{len(dates)} settlement dates", flush=True)
    have = set()
    parts = []
    if out.exists():
        prev = pd.read_parquet(out)
        have = set(prev.settlementDate.dt.strftime("%Y-%m-%d"))
        parts.append(prev)
        print(f"  {len(have)} already fetched, resuming", flush=True)

    for i, d in enumerate(dates, 1):
        if d in have:
            continue
        got = si.for_settlement(cl, d)
        if len(got):
            parts.append(got)
        print(f"  [{i:>3d}/{len(dates)}] {d}: {len(got):>6,} rows", flush=True)
        if i % 24 == 0 and parts:
            pd.concat(parts, ignore_index=True).to_parquet(out)

    if not parts:
        print("nothing fetched")
        return 1
    d = pd.concat(parts, ignore_index=True).drop_duplicates(
        subset=["symbolCode", "settlementDate", "marketClassCode"])
    d["available"] = d["settlementDate"] + pd.offsets.BDay(LAG_BDAYS)
    d.to_parquet(out)

    print(f"\nwrote {out}")
    print(f"  {len(d):,} rows, {d.symbolCode.nunique():,} symbols, "
          f"{d.settlementDate.nunique()} settlements")
    print(f"  {d.settlementDate.min():%Y-%m-%d} .. {d.settlementDate.max():%Y-%m-%d}")
    print(f"  days-to-cover present on {d.daysToCoverQuantity.notna().mean() * 100:.1f}% "
          f"of rows (the rest are the 999.99 sentinel)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
