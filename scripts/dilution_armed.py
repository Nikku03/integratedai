"""Is the company loaded to sell stock into its own catalyst?

Every direction test in this project failed. The only thing that repeatedly
worked was avoiding losers, and the mechanism was always the same: a company
that needs money monetizes good news against the holder. Until now that was
inferred from a burn ratio, which is noisy and backward-looking.

This measures it directly. Before a binary catalyst a company that intends to
raise must have a registration statement *already effective* -- the paperwork
takes weeks and cannot be done after the news. So the filing index itself says
what management plans to do:

| filing | meaning |
|---|---|
| S-3 / S-3ASR | shelf registered; the gun is bought |
| EFFECT | the shelf is live; the gun is loaded |
| 424B5 | a takedown priced; the trigger was pulled |
| S-1 | same, for issuers not S-3 eligible |
| 8-K item 1.01/3.02 | ATM or purchase agreement executed |

An effective shelf days before an FDA action date is not a coincidence and is
not a prediction -- it is a stated intention, filed under oath. It caps the
upside of good news without capping the downside of bad news, which is the
exact asymmetry a catalyst trade is trying to buy.

Nothing here forecasts direction. It answers a narrower question honestly:
if the news is good, does the holder keep it?
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

#: form -> (weight, what it tells you). Weights are ordinal, not fitted; they
#: rank how close the company is to actually selling, nothing more.
ARMED = {
    "424B5": (4, "takedown priced"),
    "EFFECT": (3, "shelf declared effective"),
    "S-3ASR": (3, "automatic shelf filed"),
    "S-3": (2, "shelf filed"),
    "S-3/A": (2, "shelf amended"),
    "S-1": (2, "registration filed"),
    "S-1/A": (2, "registration amended"),
    "424B3": (2, "prospectus supplement"),
    "424B4": (3, "offering priced"),
}
LOOKBACK_DAYS = 120


def history(client, ticker: str, cik: str, asof: pd.Timestamp) -> dict:
    """Registration activity in the LOOKBACK_DAYS before ``asof``."""
    blob = client.get(SUBMISSIONS.format(cik=cik))
    rec = (blob or {}).get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    lo = asof - pd.Timedelta(days=LOOKBACK_DAYS)
    hits, score = [], 0
    for i, form in enumerate(forms):
        f = str(form).strip()
        if f not in ARMED:
            continue
        raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
        if not raw:
            continue
        ts = pd.Timestamp(raw)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        et = ts.tz_convert("America/New_York")
        if not (lo <= et <= asof):
            continue
        w, why = ARMED[f]
        score = max(score, w)
        hits.append({"form": f, "et": et, "why": why})
    hits.sort(key=lambda h: h["et"], reverse=True)
    return {"ticker": ticker, "cik": cik, "armed_score": score,
            "n_filings": len(hits), "recent": hits[:6],
            "sic": str((blob or {}).get("sic", "")).strip()}


def label(score: int) -> str:
    return {0: "CLEAR", 2: "SHELF FILED", 3: "SHELF LIVE", 4: "SELLING"}.get(score, "?")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--tickers", required=True,
                    help="comma-separated names to check")
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD, default today")
    args = ap.parse_args(argv)
    root = Path(args.root)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=8.0,
                     ttl_hours=6.0, max_retries=5)

    asof = (pd.Timestamp(args.asof, tz="America/New_York") if args.asof
            else pd.Timestamp.now(tz="America/New_York"))
    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)
    want = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    sub = pool[pool.ticker.isin(want)]
    missing = sorted(set(want) - set(sub.ticker))
    if missing:
        print(f"not in pool: {', '.join(missing)}")

    print(f"registration activity in the {LOOKBACK_DAYS} days before "
          f"{asof:%Y-%m-%d}\n")
    out = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(history, sec, r.ticker, r.cik, asof): r.ticker
                for r in sub.itertuples()}
        for fu in as_completed(futs):
            try:
                out.append(fu.result())
            except Exception:                                   # noqa: BLE001
                continue

    out.sort(key=lambda d: -d["armed_score"])
    for d in out:
        print(f"{d['ticker']:6s} {label(d['armed_score']):12s} "
              f"({d['n_filings']} registration filings)")
        for h in d["recent"]:
            age = (asof - h["et"]).days
            print(f"         {h['et']:%Y-%m-%d}  {h['form']:8s} "
                  f"{h['why']:26s} {age:>3d}d ago")
        if not d["recent"]:
            print("         none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
