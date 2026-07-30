"""Do FDA approvals, clinical-trial results and DoD contracts explain the movers?

The move census attributed causes from SEC form types only, so anything announced
on a government site rather than filed with the SEC landed in the 38% "no filing"
bucket. That bucket is the largest single category of 20%+ moves, and the obvious
candidates for what is in it are the three sources this project has been circling:
FDA decisions, trial readouts, and defence contract awards.

Two directions, and only the second one can support a conclusion:

**Backward** -- for each 20%+ mover, was there an FDA/trial/DoD event near it?
    Answers "what explains the tail?" but conditions on the move having happened,
    so any return computed this way is selection bias, not edge. Reported as
    attribution only, never as a return.

**Forward** -- for every FDA/trial/DoD event in the window, what did the stock do?
    This is the unbiased test. It is the one that can say whether the source is
    tradable, and it is the one that killed the 8-K.

Name matching is the hard part and the main source of error
----------------------------------------------------------
Government sources name companies, not tickers: "Lockheed Martin Corp.",
"REGENERON PHARMACEUTICALS INC", "Humacyte, Inc.". Matching is done on a
normalised form (lowercased, legal suffixes and punctuation stripped) against SEC
entity names from the cap panel, requiring an exact normalised hit. That is
deliberately conservative -- it misses subsidiaries filing under a parent's name
and any spelling the SEC does not use, so **the match rate is a floor, not an
estimate**. A fuzzy matcher would inflate the attributed share with false
positives, which is the more dangerous error here.

Usage
-----
    python scripts/gov_catalysts.py --fetch
    python scripts/gov_catalysts.py --report
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import urllib.parse
from pathlib import Path

import numpy as np
import pandas as pd
import requests

log = logging.getLogger("gov")

WINDOW = (pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-29"))

OPENFDA_DRUG = "https://api.fda.gov/drug/drugsfda.json"
OPENFDA_PMA = "https://api.fda.gov/device/pma.json"
OPENFDA_510K = "https://api.fda.gov/device/510k.json"
CT_STUDIES = "https://clinicaltrials.gov/api/v2/studies"

#: Legal-form noise stripped before matching. Order matters only in that longer
#: forms must precede their prefixes ("incorporated" before "inc").
SUFFIXES = (
    "incorporated", "corporation", "companies", "company", "holdings", "holding",
    "group", "limited", "pharmaceuticals", "pharmaceutical", "therapeutics",
    "technologies", "technology", "laboratories", "laboratory", "sciences",
    "science", "systems", "solutions", "industries", "international", "inc",
    "corp", "llc", "lp", "plc", "ltd", "sa", "nv", "ag", "co", "the", "usa",
    "us", "america", "american",
)


def norm(name: str) -> str:
    """Normalise a company name for exact matching.

    Aggressive on purpose: the alternative is fuzzy matching, which on 3,500
    tickers produces false positives that would silently inflate every share
    this script reports.
    """
    s = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
    s = re.sub(r"\s+", " ", s).strip()
    for _ in range(3):                     # strip stacked suffixes
        for suf in SUFFIXES:
            s = re.sub(rf"\b{suf}\b", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
    return s


def get_json(url: str, params: dict, tries: int = 3) -> dict:
    """GET with the brackets pre-encoded; openFDA ranges need them literal."""
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='[]:+,')}"
                 for k, v in params.items())
    for k in range(tries):
        try:
            r = requests.get(f"{url}?{q}", timeout=60,
                             headers={"User-Agent": "iai-research"})
            if r.status_code == 404:       # openFDA says 404 for "no matches"
                return {}
            r.raise_for_status()
            return r.json()
        except Exception as e:             # noqa: BLE001
            if k == tries - 1:
                log.warning("%s failed: %s", url, e)
                return {}
    return {}


def fda_drug_approvals() -> pd.DataFrame:
    """Drug approvals whose submission status date falls in the window."""
    lo, hi = WINDOW[0].strftime("%Y%m%d"), WINDOW[1].strftime("%Y%m%d")
    rows, skip = [], 0
    while True:
        blob = get_json(OPENFDA_DRUG, {
            "search": f"submissions.submission_status_date:[{lo}+TO+{hi}]",
            "limit": 100, "skip": skip})
        res = blob.get("results") or []
        if not res:
            break
        for r in res:
            for s in r.get("submissions") or []:
                d = s.get("submission_status_date") or ""
                if not (lo <= d <= hi):
                    continue
                rows.append({
                    "source": "fda_drug",
                    "company": r.get("sponsor_name") or "",
                    "date": pd.Timestamp(d),
                    "detail": f"{s.get('submission_type')} "
                              f"{s.get('submission_status')} "
                              f"{(r.get('products') or [{}])[0].get('brand_name') or ''}",
                    "approval": str(s.get("submission_status")).upper() == "AP",
                })
        skip += 100
        if skip >= 1000:                   # openFDA caps skip at 25k; 1k is plenty
            break
    return pd.DataFrame(rows)


def fda_devices() -> pd.DataFrame:
    lo, hi = WINDOW[0].strftime("%Y-%m-%d"), WINDOW[1].strftime("%Y-%m-%d")
    rows = []
    for url, kind, datefield in ((OPENFDA_PMA, "fda_pma", "decision_date"),
                                 (OPENFDA_510K, "fda_510k", "decision_date")):
        skip = 0
        while True:
            blob = get_json(url, {"search": f"{datefield}:[{lo}+TO+{hi}]",
                                  "limit": 100, "skip": skip})
            res = blob.get("results") or []
            if not res:
                break
            for r in res:
                rows.append({
                    "source": kind,
                    "company": r.get("applicant") or "",
                    "date": pd.Timestamp(r.get(datefield)),
                    "detail": (r.get("trade_name") or r.get("device_name") or "")[:80],
                    "approval": True,
                })
            skip += 100
            if skip >= 2000:
                break
    return pd.DataFrame(rows)


def clinical_trials() -> pd.DataFrame:
    """Studies whose results were first posted, or status changed, in the window."""
    rows = []
    for area, kind in (("ResultsFirstPostDate", "trial_results"),
                       ("LastUpdatePostDate", "trial_update")):
        token = None
        pages = 0
        while pages < 40:
            params = {
                "filter.advanced": f"AREA[{area}]RANGE[{WINDOW[0]:%Y-%m-%d},"
                                   f"{WINDOW[1]:%Y-%m-%d}]",
                "pageSize": 200,
                "fields": "NCTId,LeadSponsorName,OverallStatus,Phase,"
                          f"{area},BriefTitle",
            }
            if token:
                params["pageToken"] = token
            blob = get_json(CT_STUDIES, params)
            studies = blob.get("studies") or []
            if not studies:
                break
            for s in studies:
                p = s.get("protocolSection", {})
                spon = (p.get("sponsorCollaboratorsModule", {})
                         .get("leadSponsor", {}).get("name") or "")
                st = p.get("statusModule", {})
                dt = (st.get("resultsFirstPostDateStruct", {}).get("date")
                      or st.get("lastUpdatePostDateStruct", {}).get("date"))
                if not dt:
                    continue
                ph = p.get("designModule", {}).get("phases") or []
                rows.append({
                    "source": kind, "company": spon, "date": pd.Timestamp(dt),
                    "detail": f"{','.join(ph)} {st.get('overallStatus','')} "
                              f"{p.get('identificationModule',{}).get('nctId','')}",
                    "approval": False,
                })
            token = blob.get("nextPageToken")
            pages += 1
            if not token:
                break
    return pd.DataFrame(rows)


def match_tickers(ev: pd.DataFrame, root: Path) -> pd.DataFrame:
    """Attach a ticker where the normalised company name matches exactly."""
    cap = pd.read_parquet(root / "cap_panel.parquet")
    ent = (cap[["entity", "ticker"]].dropna().drop_duplicates())
    ent["key"] = ent["entity"].map(norm)
    ent = ent[ent["key"].str.len() >= 3]
    # Keep one ticker per name; a name mapping to several tickers is ambiguous
    # and matching it would fabricate a link.
    counts = ent.groupby("key")["ticker"].nunique()
    ent = ent[ent["key"].isin(counts[counts == 1].index)].drop_duplicates("key")
    lut = dict(zip(ent["key"], ent["ticker"]))

    ev = ev.copy()
    ev["key"] = ev["company"].map(norm)
    ev["ticker"] = ev["key"].map(lut)
    return ev


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    root = Path(args.root)

    if args.fetch:
        parts = []
        for fn, label in ((fda_drug_approvals, "FDA drug submissions"),
                          (fda_devices, "FDA device decisions"),
                          (clinical_trials, "ClinicalTrials.gov")):
            df = fn()
            log.info("%s: %d events", label, len(df))
            if len(df):
                parts.append(df)
        ev = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        ev = match_tickers(ev, root)
        ev.to_parquet(root / "gov_events.parquet")
        log.info("%d events, %d matched to a ticker (%.0f%%)", len(ev),
                 ev.ticker.notna().sum(), ev.ticker.notna().mean() * 100)
        return 0

    if args.report:
        report(root)
        return 0

    ap.error("pass --fetch or --report")


def report(root: Path) -> None:
    ev = pd.read_parquet(root / "gov_events.parquet")
    ev = ev[ev.ticker.notna()]
    cen = pd.read_parquet(root / "census_moves.parquet")
    mv = pd.read_parquet(root / "census_attr_20.parquet")

    print(f"\n{len(ev)} government events matched to a ticker "
          f"({ev.ticker.nunique()} names)\n")
    print(ev.groupby("source").agg(events=("ticker", "size"),
                                   names=("ticker", "nunique")).to_string())

    print("\n\nBACKWARD -- of the 20%+ movers, how many had a gov event within 7 days?")
    hits = []
    for r in mv.to_dict("records"):
        w = ev[(ev.ticker == r["ticker"]) &
               (ev.date >= r["move_date"] - pd.Timedelta(days=7)) &
               (ev.date <= r["move_date"] + pd.Timedelta(days=1))]
        if len(w):
            hits.append({"ticker": r["ticker"], "move": r["move_size"],
                         "sec_cause": r["cause"],
                         "gov": ",".join(sorted(set(w.source))),
                         "detail": w.iloc[0]["detail"][:60]})
    h = pd.DataFrame(hits)
    print(f"  {len(h)} of {len(mv)} movers ({len(h) / len(mv) * 100:.0f}%)")
    if len(h):
        print(f"  of the {int((mv.cause == 'no filing').sum())} with NO SEC filing, "
              f"{int((h.sec_cause == 'no filing').sum())} had a gov event")
        print()
        print(h.nlargest(15, "move").assign(
            move=lambda x: (x.move * 100).round(0)).to_string(index=False))

    print("\n\nFORWARD -- the unbiased test: every gov event, what did the stock do?")
    print("(this is the direction that can support a conclusion)")
    px = cen.set_index("ticker")
    rows = []
    for r in ev.to_dict("records"):
        if r["ticker"] not in px.index:
            continue
        rows.append({"source": r["source"], "ticker": r["ticker"],
                     "max_1d": px.loc[r["ticker"], "max_1d"],
                     "max_5d": px.loc[r["ticker"], "max_5d"],
                     "window_ret": px.loc[r["ticker"], "window_ret"]})
    f = pd.DataFrame(rows)
    if f.empty:
        print("  no events matched a screened name")
        return
    base = cen[(cen.min_close >= 1.0) & (cen.median_dollars >= 250_000)]
    print(f"\n  {'source':16s}{'n':>5s}{'median 1d max':>15s}{'>=20% in window':>17s}")
    for s, g in f.groupby("source"):
        print(f"  {s:16s}{len(g):5d}{g.max_1d.median() * 100:+14.1f}%"
              f"{(g.max_5d >= .20).mean() * 100:16.0f}%")
    print(f"  {'ALL SCREENED':16s}{len(base):5d}{base.max_1d.median() * 100:+14.1f}%"
          f"{(base.max_5d >= .20).mean() * 100:16.0f}%   <- base rate")


if __name__ == "__main__":
    sys.exit(main())
