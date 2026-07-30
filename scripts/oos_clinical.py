"""Out-of-sample test of the clinical-readout rule on months never looked at.

The July result -- positive readouts, trailing exit, mean +9.86% over 11 trades
with a bootstrap CI excluding zero -- has one fatal weakness: the sentiment
patterns were written *after* seeing which July names won. The vocabulary is
generic clinical-trial language and the mechanism was predictable in advance, but
that is an argument, not evidence.

This freezes the rule and runs it on the preceding twelve months.

The frozen rule
---------------
1. 8-K whose text matches the CLINICAL_RESULT category patterns.
2. No toxic-financing signal in the same filing.
3. Readout sentiment POSITIVE: matches the "worked" vocabulary and not the
   "failed" vocabulary.
4. Enter at the next session's open after acceptance.
5. Arm at +8%; before arming, stop at -15%.
6. Once armed, trail 8% off the high-water mark; exit also if no new high for
   ``stall`` sessions.

Nothing above is re-fitted here. The numbers are whatever they are.

Daily bars, and what that costs
-------------------------------
Yahoo caps 1-minute history at roughly 30 days, so a twelve-month test must run on
daily bars. The trail is therefore evaluated on daily highs and lows rather than
minute ones, which makes it **coarser and slightly optimistic**: an intraday spike
through the trail that recovers by the close is invisible here, whereas the July
minute-bar run would have exited. Entry at the next open is, if anything,
conservative -- the July run entered at the first print after T+1min, which for
pre-market readouts was the same open.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from catalyst_extract import CATEGORY_PATTERNS, TOXIC  # noqa: E402
from catalyst_size import TAGS, WS  # noqa: E402

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
EX99 = re.compile(r"ex-?99", re.I)
CLINICAL = dict(CATEGORY_PATTERNS)["CLINICAL_RESULT"]

GOOD = re.compile(
    r"met\s+(?:the\s+)?primary|achiev\w+\s+(?:the\s+)?primary|"
    r"statistically\s+significant|positive\s+(?:topline|top-line|results|data)|"
    r"demonstrat\w+\s+(?:significant|efficacy|clinically\s+meaningful)|"
    r"p\s*[=<]\s*0?\.0|superiority|favorabl|well[- ]tolerated|encouraging", re.I)
BAD = re.compile(
    r"did\s+not\s+(?:meet|achieve|demonstrate)|failed\s+to\s+(?:meet|achieve)|"
    r"discontinu\w+\s+(?:the\s+)?(?:trial|study|development)|"
    r"missed\s+(?:the\s+)?primary|not\s+statistically\s+significant|"
    r"terminat\w+\s+(?:the\s+)?(?:trial|study)|clinical\s+hold|safety\s+signal", re.I)


def sentiment(text: str) -> str:
    t = text[:24000]
    g, b = bool(GOOD.search(t)), bool(BAD.search(t))
    if g and not b:
        return "POSITIVE"
    if b and not g:
        return "NEGATIVE"
    return "MIXED" if g else "SILENT"


#: Pharma / biotech / research SIC codes. A clinical readout cannot come from a
#: bank, and scanning all 5,490 filers means fetching 54,827 documents to find a
#: few hundred. Filtering on the filer's own SIC before touching any document
#: cuts that by roughly an order of magnitude and cannot bias the result, since
#: the excluded industries do not run trials.
BIO_SIC = {"2833", "2834", "2835", "2836", "8731", "8071", "3826", "3841",
           "3845", "8000", "8090"}


def filings_for(client, tkr: str, cik: str, lo, hi) -> list[dict]:
    blob = client.get(SUBMISSIONS.format(cik=cik))
    if str((blob or {}).get("sic", "")).strip() not in BIO_SIC:
        return []
    rec = (blob or {}).get("filings", {}).get("recent", {})
    forms = rec.get("form", [])
    out = []
    for i, form in enumerate(forms):
        if not str(form).startswith("8-K"):
            continue
        raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
        if not raw:
            continue
        ts = pd.Timestamp(raw)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        et = ts.tz_convert("America/New_York")
        if not (lo <= et <= hi):
            continue
        out.append({"ticker": tkr, "cik": cik, "et": et,
                    "accession": rec.get("accessionNumber", [""] * len(forms))[i],
                    "doc": rec.get("primaryDocument", [""] * len(forms))[i]})
    return out


def text_of(client, r: dict) -> str:
    cik, acc = str(int(r["cik"])), r["accession"].replace("-", "")
    txt = ""
    if r["doc"]:
        raw = client.get_bytes(ARCHIVE.format(cik=cik, acc=acc, doc=r["doc"]))
        if raw is not None:
            txt += WS.sub(" ", TAGS.sub(" ", raw.decode("utf-8", errors="ignore")))
    blob = client.get(INDEX.format(cik=cik, acc=acc))
    names = [i.get("name", "")
             for i in (blob.get("directory") or {}).get("item", [])] if blob else []
    for n in [x for x in names
              if EX99.search(x) and x.lower().endswith((".htm", ".html", ".txt"))][:2]:
        b2 = client.get_bytes(ARCHIVE.format(cik=cik, acc=acc, doc=n))
        if b2 is not None:
            txt += " " + WS.sub(" ", TAGS.sub(" ", b2.decode("utf-8", errors="ignore")))
    return txt


def walk_daily(h, l, entry, *, arm=0.08, trail=0.08, init_stop=0.15,
               stall=8) -> tuple[float, str, int]:
    """Same rule as the minute version, evaluated on daily bars."""
    hw, armed, since = entry, False, 0
    for j in range(len(h)):
        hi_, lo_ = float(h[j]), float(l[j])
        if not (np.isfinite(hi_) and np.isfinite(lo_)):
            continue
        if not armed:
            sp = entry * (1 - init_stop)
            if lo_ <= sp:
                return min(sp, lo_) / entry - 1.0, "stop", j
            if hi_ >= entry * (1 + arm):
                armed, hw, since = True, max(hw, hi_), 0
            continue
        tp = hw * (1 - trail)
        if lo_ <= tp:
            return min(tp, lo_) / entry - 1.0, "trail", j
        if hi_ > hw:
            hw, since = hi_, 0
        else:
            since += 1
            if stall and since >= stall:
                return float(l[j]) / entry - 1.0, "stall", j
    j = len(h) - 1
    return float(l[j]) / entry - 1.0, "time", j


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--start", default="2025-06-01")
    ap.add_argument("--end", default="2026-06-30")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--hold-days", type=int, default=25)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources.prices import BROWSER_UA, YAHOO_CHART
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0,
                     ttl_hours=720.0, max_retries=5)
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=12.0,
                     ttl_hours=168.0, max_retries=4)

    lo = pd.Timestamp(args.start, tz="America/New_York")
    hi = pd.Timestamp(args.end, tz="America/New_York")
    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)
    print(f"scanning {len(pool)} filers for 8-Ks in {args.start}..{args.end}",
          flush=True)

    fil = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(filings_for, sec, r.ticker, r.cik, lo, hi)
                for r in pool.itertuples()]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 500 == 0:
                print(f"  submissions {k}/{len(pool)}, {len(fil)} filings", flush=True)
            try:
                fil.extend(fu.result())
            except Exception:                                  # noqa: BLE001
                continue
    print(f"{len(fil)} 8-K filings in window", flush=True)

    def screen(r):
        t = text_of(sec, r)
        if not t or not CLINICAL.search(t[:24000]):
            return None
        if any(rx.search(t[:24000]) for rx in TOXIC.values()):
            return None
        return {**r, "verdict": sentiment(t)}

    hits = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(screen, r) for r in fil]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 2000 == 0:
                print(f"  documents {k}/{len(fil)}, {len(hits)} clinical", flush=True)
            try:
                v = fu.result()
            except Exception:                                  # noqa: BLE001
                v = None
            if v:
                hits.append(v)
    h = pd.DataFrame(hits)
    h.to_parquet(root / "oos_clinical_signals.parquet")
    print(f"\n{len(h)} clinical readouts, non-toxic")
    print(h.verdict.value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
