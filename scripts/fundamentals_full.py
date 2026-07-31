"""Balance sheet, burn and dilution history, so outcomes can be explained.

Revenue alone cannot say why one filing produces +150% and another −59%. The
hypothesis worth testing is that the *company's financial position* conditions
the reaction: a biotech with three months of cash must dilute into good news, so
the market sells it; one with three years of runway can bank the news.

Concepts pulled from the SEC XBRL **frames** API, one request per concept ×
period returning every filer:

| field | why it should matter |
|---|---|
| cash | the denominator of runway |
| R&D expense | the burn that consumes it |
| operating cash flow | actual burn, better than R&D when available |
| net income | profitability, and the sign of the business |
| shares outstanding | dilution history when differenced across periods |
| total liabilities | leverage, which forces financing decisions |
| stockholders equity | solvency, and going-concern proximity |

Every value is annual or point-in-time from filings that predate the events being
explained, so nothing here is contemporaneous with an outcome. Tagging is
inconsistent across filers, so several concept aliases are tried per field and the
most recent non-null wins.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

FRAMES = "https://data.sec.gov/api/xbrl/frames/us-gaap/{concept}/USD/{period}.json"

#: field -> concept aliases, best-tagged first.
FIELDS = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "opcf": ["NetCashProvidedByUsedInOperatingActivities",
             "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "liabilities": ["Liabilities", "LiabilitiesCurrent"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "opex": ["OperatingExpenses", "CostsAndExpenses"],
}
#: Instant concepts need I-suffixed periods; duration concepts do not.
INSTANT = {"cash", "liabilities", "equity"}
DUR_PERIODS = ["CY2025", "CY2024"]
INST_PERIODS = ["CY2025Q4I", "CY2025Q3I", "CY2025Q2I", "CY2024Q4I"]


def fetch(ua: str, cache: Path, concept: str, period: str) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / f"{concept}_{period}.json"
    if not p.exists():
        try:
            r = requests.get(FRAMES.format(concept=concept, period=period),
                             timeout=90, headers={"User-Agent": ua})
        except Exception as e:                                # noqa: BLE001
            print(f"  {concept} {period}: {e}")
            return []
        time.sleep(0.12)
        if r.status_code != 200:
            return []
        p.write_text(r.text)
    try:
        return (json.loads(p.read_text()).get("data") or [])
    except Exception:                                          # noqa: BLE001
        return []


def build(ua: str, cache: Path) -> pd.DataFrame:
    frames = []
    for field, concepts in FIELDS.items():
        periods = INST_PERIODS if field in INSTANT else DUR_PERIODS
        rows = []
        for ci, concept in enumerate(concepts):
            for pi, period in enumerate(periods):
                data = fetch(ua, cache, concept, period)
                if data:
                    print(f"  {field:12s} {concept[:44]:44s} {period:10s} "
                          f"{len(data):>6,}")
                for d in data:
                    if d.get("val") is None:
                        continue
                    rows.append({"cik": str(d["cik"]).zfill(10),
                                 field: float(d["val"]),
                                 "_r": ci * 10 + pi, "_p": period})
        if not rows:
            continue
        f = pd.DataFrame(rows).sort_values(["cik", "_r"])
        f = f.drop_duplicates("cik", keep="first")[["cik", field]]
        frames.append(f.set_index("cik"))

    # Share count across two periods, to measure dilution rather than level.
    sh = []
    for period in ["CY2025Q4I", "CY2024Q4I"]:
        for d in fetch(ua, cache, "CommonStockSharesOutstanding", period):
            if d.get("val"):
                sh.append({"cik": str(d["cik"]).zfill(10),
                           "period": period, "shares": float(d["val"])})
    if sh:
        s = pd.DataFrame(sh).pivot_table(index="cik", columns="period",
                                         values="shares", aggfunc="last")
        if {"CY2025Q4I", "CY2024Q4I"} <= set(s.columns):
            s["share_growth"] = s["CY2025Q4I"] / s["CY2024Q4I"] - 1.0
            frames.append(s[["share_growth"]])

    out = pd.concat(frames, axis=1).reset_index().rename(columns={"index": "cik"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    args = ap.parse_args(argv)
    root = Path(args.root)

    print("fetching XBRL frames:")
    f = build(args.user_agent, root / "xbrl_cache")

    base = pd.read_parquet(root / "fundamentals.parquet")
    base["cik"] = base["cik"].astype(str).str.zfill(10)
    d = base.merge(f, on="cik", how="left")

    # Derived measures. Burn is taken from operating cash flow where available
    # (it is the money that actually left) and R&D otherwise.
    burn = d["opcf"].where(d["opcf"] < 0).abs()
    d["burn_annual"] = burn.fillna(d["rnd"])
    d["runway_years"] = d["cash"] / d["burn_annual"].replace(0, np.nan)
    d["cash_per_cap"] = d["cash"] / d["market_cap"]
    d["liab_per_cash"] = d["liabilities"] / d["cash"].replace(0, np.nan)
    d["equity_per_cap"] = d["equity"] / d["market_cap"]
    d["is_profitable"] = d["net_income"] > 0
    d["pre_revenue"] = (d["revenue"].fillna(0) < 1e6)
    d.to_parquet(root / "fundamentals_full.parquet")

    print(f"\n{len(d):,} tickers")
    for c in ("cash", "rnd", "opcf", "net_income", "liabilities", "equity",
              "share_growth", "runway_years"):
        if c in d:
            print(f"  {c:14s} coverage {d[c].notna().mean() * 100:5.1f}%")
    ok = d.dropna(subset=["runway_years"])
    print(f"\nrunway (years): median {ok.runway_years.median():.2f}   "
          f"p10 {ok.runway_years.quantile(.10):.2f}   "
          f"p90 {ok.runway_years.quantile(.90):.2f}   n={len(ok):,}")
    if "share_growth" in d:
        s = d.dropna(subset=["share_growth"])
        print(f"share growth YoY: median {s.share_growth.median() * 100:+.1f}%   "
              f"p90 {s.share_growth.quantile(.90) * 100:+.0f}%   n={len(s):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
