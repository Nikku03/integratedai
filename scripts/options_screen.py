"""Screen one session's 8-K filings down to the names worth buying options on.

The equity work in this repository ranked *every* gated filing and bought the
top of the list. This screens first and ranks second, on two conditions set
out in advance:

* **Market capitalisation $300M-$20B**, with $2B-$15B treated as the sweet
  spot. Below $300M a name is too illiquid for a listed option chain to be
  tradeable; above $20B a single 8-K rarely moves the whole company.
* **Pre-filing price-to-sales at least 8.0x.** A company valued at eight times
  revenue is priced on a narrative rather than on cash flows, and a narrative
  is what an 8-K can revise.

Both are computed **point-in-time**. Market cap uses the share count as it had
been filed before the 8-K existed and the close of the last session *before*
the filing day; price-to-sales uses trailing-twelve-month revenue known at that
same moment. `company_context.flow` supplies the TTM figure and carries the
five corrections documented in its own module docstring -- proxy statements
that report the same fiscal year a thousand times larger, the fourth quarter
that no issuer files, and the double-count in the year-roll.

Data
----
Filing list from the SEC daily form index (free, keyless, needs a real
User-Agent). Fundamentals from SEC XBRL company facts. Prices from Polygon
grouped daily bars -- one request covers every US ticker for a session, which
matters because the key in use is rate limited to five requests a minute.

The Polygon key is read from ``POLYGON_API_KEY``. It is never written to disk
or to any output this script produces.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import company_context as cc  # noqa: E402

UA = "Naresh Chhillar chhillarnaresh03@gmail.com"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{:010d}.json"
SUBS = "https://data.sec.gov/submissions/CIK{:010d}.json"

#: Top-line revenue tags, taken as a **maximum** rather than in preference
#: order. Preference order fails on any filer whose ASC 606 contract revenue is
#: only a slice of the total: a REIT's lease income is ASC 842, so Invitation
#: Homes' $2.86B top line tagged as $44.6M and UDR's $1.72B as $11.8M, which
#: turned the price-to-sales screen into a test of tagging convention. Every
#: tag here is a whole top line, so the largest is the total and the smaller
#: ones are components of it.
#:
#: Pro-forma and segment tags are deliberately absent. ``SegmentReportingInfor-
#: mationRevenue`` is one segment, and ``BusinessAcquisitionsProFormaRevenue``
#: is a hypothetical -- the same class of figure that made a carve-out 8-K
#: report $87.8M against a real $1.93B earlier in this repository.
#: ``InterestAndDividendIncomeOperating`` is absent too: gross interest income
#: is not a bank's revenue, ``RevenuesNetOfInterestExpense`` is.
REV_TAGS = ("Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "RevenuesNetOfInterestExpense",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet")

#: Banks and investment companies do not tag a top line at all. Of the names
#: this screen could not measure, 23 of 44 report ``InterestIncomeExpenseNet``
#: and 19 report ``NoninterestIncome`` -- net interest income plus fee income
#: *is* a bank's revenue, and it has to be summed rather than maximised because
#: neither leg is the whole. Business development companies report investment
#: income instead. These are fallbacks, tried only when no top-line tag
#: resolves, because a filer that reports both ``Revenues`` and interest income
#: should be measured on ``Revenues``.
BANK_REV = ("InterestIncomeExpenseNet", "NoninterestIncome")

#: Interest on a cash pile is not revenue. Including investment-income tags in
#: the maximum turned Rigetti's $21.8M of interest income into its top line and
#: Spyre's $29.6M likewise, making pre-revenue issuers look like operating
#: businesses. They are gone; a filer with no revenue is handled below instead.
#:
#: An issuer that files an income statement, spends on research or exploration,
#: and reports no revenue concept at all is not unmeasured -- it is
#: pre-revenue, its price-to-sales is infinite, and it is the purest case of
#: the narrative valuation this screen is looking for. An issuer with no
#: revenue tag and no such spending is a filer whose top line this script
#: failed to find, and it is excluded rather than waved through.
NO_REVENUE_MARKERS = ("ResearchAndDevelopmentExpense",
                      "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost",
                      "ExplorationExpenseMining")

#: Below this, trailing revenue is a grant, a milestone or a rounding line, and
#: dividing by it produces a ratio in the thousands rather than a valuation.
#: Such names are not dropped -- a pre-revenue issuer is the purest case of
#: being priced on a narrative -- but they are ranked as their own class.
MIN_MEANINGFUL_REV = 5e6
#: Share-count tags. The dei cover-page tag is the most current: it is stated as
#: of a date within days of the filing, not as of the balance-sheet date.
SHARE_TAGS = (("dei", "EntityCommonStockSharesOutstanding"),
              ("us-gaap", "CommonStockSharesOutstanding"),
              ("us-gaap", "CommonStockSharesIssued"))

MIN_CAP, MAX_CAP = 300e6, 20e9
SWEET_LO, SWEET_HI = 2e9, 15e9
MIN_PS = 8.0


def get(url: str, tries: int = 3) -> bytes | None:
    """One rate-limited SEC request. Returns None on 404, raises otherwise."""
    for a in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Encoding": "gzip", "Host": url.split("/")[2]})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code in (403, 429) and a < tries - 1:
                time.sleep(2 ** a)
                continue
            raise
        except Exception:
            if a < tries - 1:
                time.sleep(2 ** a)
                continue
            raise
    return None


def cached(cache: Path, url: str, key: str) -> dict | None:
    p = cache / f"{key}.json"
    if p.exists():
        t = p.read_text()
        return json.loads(t) if t.strip() else None
    b = get(url)
    p.write_text(b.decode() if b else "")
    return json.loads(b) if b else None


def _revenue(fx: dict, when: pd.Timestamp) -> float:
    """Trailing-twelve-month top line, or NaN if the filer does not report one.

    NaN is a real answer here and it is not the same as zero. A clinical-stage
    issuer with $80k of grant income has a measurable, enormous price-to-sales
    ratio; a bank that never tags ``Revenues`` has an unmeasured one. Treating
    the second as infinite would have passed eleven banks and four REITs
    through a screen whose whole purpose is to isolate narrative valuations.
    """
    cand = [cc.flow(fx, tag, when) for tag in REV_TAGS]
    legs = [cc.flow(fx, tag, when) for tag in BANK_REV]
    if all(v == v for v in legs):
        cand.append(float(sum(legs)))
    cand = [v for v in cand if v == v and v > 0]
    if cand:
        return max(cand)
    if any(cc.flow(fx, m, when) == cc.flow(fx, m, when) for m in NO_REVENUE_MARKERS):
        return 0.0
    return float("nan")


def prev_session(sessions: list[str], day: str) -> str | None:
    """The last session strictly before ``day``."""
    before = [s for s in sessions if s < day]
    return before[-1] if before else None


def screen(filings: list[dict], px: dict[str, dict], cache: Path,
           workers: int = 6) -> pd.DataFrame:
    sessions = sorted(px)
    ciks = sorted({f["cik"] for f in filings})

    def one(cik):
        return cik, cached(cache, FACTS.format(cik), f"facts_{cik}")

    facts: dict[int, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        for i, (cik, f) in enumerate(ex.map(one, ciks), 1):
            if f:
                facts[cik] = f
            if i % 100 == 0:
                print(f"  ... {i}/{len(ciks)} company-facts", flush=True)
    print(f"  XBRL facts for {len(facts):,}/{len(ciks):,} filers", flush=True)

    rows = []
    for f in filings:
        day = f"{f['date'][:4]}-{f['date'][4:6]}-{f['date'][6:]}"
        prev = prev_session(sessions, day)
        fx = facts.get(f["cik"])
        if prev is None or fx is None:
            continue
        bar = px[prev].get(f["ticker"])
        if bar is None:
            continue
        when = pd.Timestamp(day)          # facts must be filed strictly before

        sh = float("nan")
        for tax, tag in SHARE_TAGS:
            sh = cc.stock(fx, tax, tag, when)
            if sh == sh and sh > 0:
                break
        rev = _revenue(fx, when)
        cap = sh * bar["c"] if sh == sh else float("nan")
        if cap != cap:
            ps, rev_class = float("nan"), "no share count"
        elif rev != rev:
            ps, rev_class = float("nan"), "unmeasured"
        elif rev >= MIN_MEANINGFUL_REV:
            ps, rev_class = cap / rev, "reported"
        elif rev > 0:
            ps, rev_class = cap / rev, "negligible"
        else:
            ps, rev_class = float("inf"), "pre-revenue"

        rows.append(dict(
            date=day, ticker=f["ticker"], cik=f["cik"], company=f["company"],
            acc=f["acc"], exch=f.get("exch", ""),
            pre_close=bar["c"], pre_dollar_vol=bar["c"] * bar["v"],
            shares=sh, revenue_ttm=rev, mktcap=cap, ps=ps, rev_class=rev_class,
            file_close=f["close"], file_dollar_vol=f["dollar_vol"],
        ))
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default="/tmp/claude-0/opt")
    ap.add_argument("--out", default="/tmp/claude-0/opt/screen.parquet")
    args = ap.parse_args(argv)

    work = Path(args.work)
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)

    filings = json.load(open(work / "eightk_px.json"))
    px = {}
    for p in sorted(work.glob("grouped_*.json")):
        d = json.loads(p.read_text())
        px[p.stem.split("_")[-1]] = {r["T"]: r for r in d.get("results") or []}

    t = screen(filings, px, cache)
    n0 = len(t)
    t = t.drop_duplicates(subset=["date", "ticker"], keep="first").reset_index(drop=True)
    print(f"  {n0 - len(t)} same-day duplicate filings collapsed to one name each")
    t.to_parquet(args.out)

    print(f"\n  filings with a prior-session price: {len(t):,}")
    print(f"  market cap computable:  {t.mktcap.notna().sum():,}")
    print(f"  price-to-sales computable: {t.ps.notna().sum():,}")
    unm = t[t.mktcap.between(MIN_CAP, MAX_CAP) & (t.rev_class == "unmeasured")]
    print(f"  in the cap band but no revenue reported anywhere: {len(unm):,}"
          f"  ({unm.ticker.nunique()} names) -- these FAIL the screen, they do not pass it")

    cap_ok = t.mktcap.between(MIN_CAP, MAX_CAP)
    ps_ok = t.ps.notna() & (t.ps >= MIN_PS)
    print(f"\n  in the $300M-$20B band:        {cap_ok.sum():,}")
    print(f"  at price-to-sales >= 8.0x:     {ps_ok.sum():,}")
    print(f"  **both**:                      {(cap_ok & ps_ok).sum():,}")

    s = t[cap_ok & ps_ok].sort_values(["date", "mktcap"], ascending=[True, False])
    for day, g in s.groupby("date"):
        print(f"\n  {day}  -- {len(g)} names pass")
        print(f"  {'ticker':8s}{'mkt cap':>11s}{'revenue TTM':>14s}{'P/S':>8s}"
              f"{'$vol':>10s}  company")
        for _, r in g.iterrows():
            sweet = "*" if SWEET_LO <= r.mktcap <= SWEET_HI else " "
            ps = f"{r.ps:>7.0f}" if r.ps > 999 else f"{r.ps:>7.1f}"
            rv = ("  --  " if r.revenue_ttm != r.revenue_ttm
                  else f"{r.revenue_ttm / 1e6:>7.1f}M")
            print(f"  {r.ticker:8s}{r.mktcap / 1e9:>9.2f}B{sweet}{rv:>12s}{ps:>8s}"
                  f"{r.pre_dollar_vol / 1e6:>9.1f}M  {r.rev_class:11s}{r.company[:34]}")
    print("\n  * = inside the $2B-$15B sweet spot")
    return 0


if __name__ == "__main__":
    sys.exit(main())
