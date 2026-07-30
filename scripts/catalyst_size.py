"""How big is the catalyst, relative to the company it happened to?

The idea this tests: a $7m contract is transformative for a $30m company and
invisible for a $14bn one, so the dollar magnitude of a catalyst divided by the
company's revenue or market cap should separate the movers from the noise. Every
earlier grading here scored catalysts on what they *were* -- item code, verdict,
a qualitative "impact" label -- and never on how big they were.

Three stages, all mechanical and reproducible:

1. **Get the document.** EDGAR submissions give accession and primary document
   per filing; the document itself is fetched from the Archives.
2. **Extract dollar amounts.** Every ``$N million/billion`` and bare ``$N,NNN,NNN``
   in the text, filtered against boilerplate.
3. **Divide by the company.** Materiality = amount / revenue, and amount / market
   cap, from `fundamentals.py`.

Why the extraction is deliberately crude
----------------------------------------
A filing mentions many numbers: the contract value, a buyback authorisation, par
value of $0.001, the registration fee table. Picking "the" figure needs judgement,
and judgement applied to 2,400 filings by hand is not reproducible.

So this takes the **largest** amount that survives a boilerplate filter, and
records how many amounts were found. That is wrong on individual filings -- a
buyback will outrank the contract that actually mattered -- but it is wrong in a
way that does not depend on the outcome, which is what matters for a forward test.
Where it fails it should add noise, not bias, and if materiality carries signal it
should survive the noise.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"

#: "$12.5 million", "$1.2 billion", "$900 thousand"
SCALED = re.compile(
    r"\$\s?([\d,]+(?:\.\d+)?)\s*(thousand|million|billion|trillion)\b", re.I)
#: Bare "$1,234,567" -- at least six digits so "$1,200" of postage is excluded.
BARE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?)")
MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}

#: Contexts where a dollar figure is boilerplate rather than the news.
NOISE = re.compile(
    r"par\s+value|registration\s+fee|aggregate\s+offering\s+price|"
    r"maximum\s+aggregate|fee\s+table|per\s+share|stated\s+value|"
    r"exercise\s+price", re.I)

#: Balance-sheet and scale figures that are not the catalyst. Without this the
#: largest number in a bank's earnings release is its total assets, which for a
#: $587m bank is $790m of *deposits* -- read as a 1,346x "materiality". Every one
#: of the ten most material filings on the first pass was an error of this kind,
#: including a $220bn figure extracted for a $40m ad-tech company.
BALANCE = re.compile(
    r"total\s+assets|total\s+deposits|deposits\s+(of|were|totall?ed)|"
    r"loan\s+portfolio|loans?\s+(held|receivable|outstanding)|"
    r"assets\s+under\s+management|\bAUM\b|net\s+asset\s+value|book\s+value|"
    r"total\s+equity|stockholders.{0,3}\s+equity|total\s+liabilit|"
    r"investment\s+portfolio|impressions|market\s+size|addressable\s+market|"
    r"total\s+capital|risk-weighted|securities\s+portfolio", re.I)

#: The amount must sit near language describing a *transaction*. This is what
#: makes it a catalyst magnitude rather than any large number in the document.
DEAL = re.compile(
    r"award|contract|agreement|acquir|acquisition|merger|purchase|"
    r"offering|proceeds|financ|note|facility|credit|loan\s+agreement|"
    r"repurchase|buyback|dividend|milestone|upfront|royalt|"
    r"revenue|guidance|backlog|order|investment|raise|placement|"
    r"consideration|transaction|deal|grant|funding", re.I)

TAGS = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")


def amounts(text: str, *, require_deal: bool = True) -> list[float]:
    """Dollar figures that plausibly describe a transaction.

    Each candidate is judged on the ~180 characters around it: rejected if that
    window is boilerplate or balance-sheet language, and (by default) required to
    sit near transaction language. Context is what separates "a $7.0 million
    contract" from "$7.0 million of goodwill".
    """
    out = []
    for rx, scaled in ((SCALED, True), (BARE, False)):
        for m in rx.finditer(text):
            lo, hi = max(0, m.start() - 120), m.end() + 60
            ctx = text[lo:hi]
            if NOISE.search(ctx) or BALANCE.search(ctx):
                continue
            if require_deal and not DEAL.search(ctx):
                continue
            try:
                v = (float(m.group(1).replace(",", "")) * MULT[m.group(2).lower()]
                     if scaled else float(m.group(1).replace(",", "")))
            except (ValueError, KeyError):
                continue
            out.append(v)
    # Anything above a trillion is a parse error, not a company event.
    return [v for v in out if 1e4 <= v <= 1e12]


def get_docs(client, ciks: dict, forms: set[str], lo: pd.Timestamp,
             hi: pd.Timestamp, workers: int = 8) -> pd.DataFrame:
    """Accession + primary document for every matching filing in the window."""
    def one(item):
        tkr, cik = item
        blob = client.get(SUBMISSIONS.format(cik=cik))
        rec = (blob or {}).get("filings", {}).get("recent", {})
        fl = rec.get("form", [])
        out = []
        for i, form in enumerate(fl):
            if form not in forms:
                continue
            raw = rec.get("acceptanceDateTime", [None] * len(fl))[i]
            if not raw:
                continue
            ts = pd.Timestamp(raw)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            et = ts.tz_convert("America/New_York")
            if not (lo <= et <= hi):
                continue
            out.append({"ticker": tkr, "cik": cik, "form": form, "accepted": ts,
                        "et": et,
                        "items": rec.get("items", [""] * len(fl))[i] or "",
                        "accession": rec.get("accessionNumber", [""] * len(fl))[i],
                        "doc": rec.get("primaryDocument", [""] * len(fl))[i]})
        return out

    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, it) for it in ciks.items()]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 300 == 0:
                print(f"  submissions {k}/{len(ciks)}", flush=True)
            try:
                rows.extend(fu.result())
            except Exception:                              # noqa: BLE001
                continue
    return pd.DataFrame(rows)


def fetch_text(client, r: dict) -> dict | None:
    if not r["doc"] or not r["accession"]:
        return None
    url = ARCHIVE.format(cik=str(int(r["cik"])),
                         acc=r["accession"].replace("-", ""), doc=r["doc"])
    blob = client.get_bytes(url) if hasattr(client, "get_bytes") else None
    if blob is None:
        return None
    try:
        text = blob.decode("utf-8", errors="ignore")
    except Exception:                                      # noqa: BLE001
        return None
    text = WS.sub(" ", TAGS.sub(" ", text))
    vals = amounts(text)
    return {"accession": r["accession"], "n_amounts": len(vals),
            "max_amount": max(vals) if vals else np.nan,
            "med_amount": float(np.median(vals)) if vals else np.nan,
            "doc_chars": len(text)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0,
                     ttl_hours=720.0, max_retries=5)

    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)
    # Only names that actually filed an 8-K in July, to keep the crawl bounded.
    fil = pd.read_parquet(root / "recent_filings.parquet")
    want = set(fil.loc[fil.form.isin(["8-K", "8-K/A"]), "ticker"])
    ciks = {r.ticker: r.cik for r in pool.itertuples() if r.ticker in want}
    print(f"{len(ciks)} 8-K filers to crawl")

    docs = get_docs(sec, ciks, {"8-K", "8-K/A"},
                    pd.Timestamp("2026-07-01", tz="America/New_York"),
                    pd.Timestamp("2026-07-29", tz="America/New_York"),
                    args.workers)
    print(f"{len(docs)} filings with an accession")
    docs.to_parquet(root / "filing_docs.parquet")

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(fetch_text, sec, r) for r in docs.to_dict("records")]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 300 == 0:
                print(f"  documents {k}/{len(docs)}", flush=True)
            try:
                v = fu.result()
            except Exception:                              # noqa: BLE001
                v = None
            if v:
                rows.append(v)
    amt = pd.DataFrame(rows)
    print(f"{len(amt)} documents parsed, "
          f"{amt.max_amount.notna().sum()} with a dollar amount")

    d = docs.merge(amt, on="accession", how="left")
    fund = pd.read_parquet(root / "fundamentals.parquet")
    d = d.merge(fund[["ticker", "revenue", "market_cap"]], on="ticker", how="left")
    d["mat_rev"] = d["max_amount"] / d["revenue"]
    d["mat_cap"] = d["max_amount"] / d["market_cap"]
    d.to_parquet(root / "catalyst_size.parquet")

    ok = d.dropna(subset=["max_amount", "market_cap"])
    print(f"\n{len(ok):,} filings with both an amount and a market cap")
    print(f"  amount ($m): median {ok.max_amount.median() / 1e6:,.1f}  "
          f"p90 {ok.max_amount.quantile(.90) / 1e6:,.0f}")
    print(f"  amount / market cap: median {ok.mat_cap.median():.3f}  "
          f"p90 {ok.mat_cap.quantile(.90):.2f}  "
          f">100% of cap: {(ok.mat_cap > 1).mean() * 100:.1f}%")
    okr = d.dropna(subset=["max_amount", "revenue"])
    print(f"  amount / revenue: median {okr.mat_rev.median():.3f}  "
          f"p90 {okr.mat_rev.quantile(.90):.2f}   (n={len(okr):,})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
