"""Company fundamentals, so a catalyst can be sized against the company it hits.

A $7m contract is transformative for a $30m company and invisible for a $14bn
one. Every earlier attempt here graded catalysts on what they *were* -- item code,
verdict, qualitative "impact" -- and never on how big they were relative to the
business. This assembles the denominator.

Revenue comes from the SEC's XBRL **frames** API, which returns every filer for a
concept and period in one request rather than one request per company. Several
concepts and periods are tried because US-GAAP tagging is not consistent:
``Revenues`` is the older concept, ``RevenueFromContractWithCustomerExcluding
AssessedTax`` the post-ASC-606 one, and a given filer may use either. The most
recent non-null value per CIK wins.

Market cap comes from the cap panel already built from shares outstanding and
price. It is stale -- the panel ends 2026-01-09 -- which is stated wherever it is
used rather than quietly ignored: a cap six months old is fine for deciding
whether a contract is 1% or 100% of a company, and useless for anything finer.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

FRAMES = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json"

#: Tried in order; earlier entries win when a CIK appears in several.
CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
]
PERIODS = ["CY2025", "CY2024", "CY2025Q3I", "CY2025Q2I"]


def fetch_frames(ua: str, cache: Path) -> pd.DataFrame:
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for concept in CONCEPTS:
        for period in PERIODS:
            p = cache / f"{concept}_{period}.json"
            if not p.exists():
                url = FRAMES.format(concept=concept, period=period)
                try:
                    r = requests.get(url, timeout=90,
                                     headers={"User-Agent": ua})
                except Exception as e:                       # noqa: BLE001
                    print(f"  {concept} {period}: {e}")
                    continue
                time.sleep(0.15)                              # stay under 10/s
                if r.status_code != 200:
                    print(f"  {concept} {period}: HTTP {r.status_code}")
                    continue
                p.write_text(r.text)
            try:
                blob = json.loads(p.read_text())
            except Exception:                                 # noqa: BLE001
                continue
            data = blob.get("data") or []
            print(f"  {concept:56s} {period:10s} {len(data):>6,} filers")
            for d in data:
                v = d.get("val")
                if v is None:
                    continue
                rows.append({"cik": str(d["cik"]).zfill(10),
                             "entity": d.get("entityName", ""),
                             "revenue": float(v),
                             "concept": concept, "period": period})
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["c_rank"] = df["concept"].map({c: i for i, c in enumerate(CONCEPTS)})
    df["p_rank"] = df["period"].map({p: i for i, p in enumerate(PERIODS)})
    # Best-tagged, most recent value per company.
    df = (df.sort_values(["cik", "p_rank", "c_rank"])
            .drop_duplicates("cik", keep="first"))
    return df[["cik", "entity", "revenue", "concept", "period"]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    args = ap.parse_args(argv)
    root = Path(args.root)

    print("fetching XBRL frames (one request per concept x period, all filers):")
    rev = fetch_frames(args.user_agent, root / "xbrl_cache")
    if rev.empty:
        print("no revenue data retrieved")
        return 1

    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)
    cap = pd.read_parquet(root / "cap_panel.parquet")
    cap["cik"] = cap["cik"].astype(str).str.zfill(10)
    cap = (cap.sort_values("as_of").drop_duplicates("cik", keep="last")
              [["cik", "ticker", "market_cap", "as_of"]])

    f = pool[["ticker", "cik"]].merge(rev, on="cik", how="left")
    f = f.merge(cap[["cik", "market_cap", "as_of"]], on="cik", how="left")
    f["rev_per_cap"] = f["revenue"] / f["market_cap"]
    f.to_parquet(root / "fundamentals.parquet")

    print(f"\n{len(f):,} tickers; revenue for {f.revenue.notna().sum():,} "
          f"({f.revenue.notna().mean() * 100:.0f}%), market cap for "
          f"{f.market_cap.notna().sum():,} ({f.market_cap.notna().mean() * 100:.0f}%)")
    both = f.dropna(subset=["revenue", "market_cap"])
    print(f"both: {len(both):,}")
    print(f"\nrevenue ($m): median {both.revenue.median() / 1e6:,.0f}  "
          f"p10 {both.revenue.quantile(.10) / 1e6:,.1f}  "
          f"p90 {both.revenue.quantile(.90) / 1e6:,.0f}")
    print(f"market cap ($m): median {both.market_cap.median() / 1e6:,.0f}  "
          f"p10 {both.market_cap.quantile(.10) / 1e6:,.1f}  "
          f"p90 {both.market_cap.quantile(.90) / 1e6:,.0f}")
    print(f"revenue/market cap: median {both.rev_per_cap.median():.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
