"""Prove the free data sources still work, from this machine, right now.

A list of APIs in a document rots. This runs each one and reports what actually
came back, so `docs/DATA_SOURCES.md` can be checked rather than believed. Every
source here was selected by probing the catalogue at
<https://github.com/public-apis/public-apis> plus a few that are not in it, and
keeping only the ones that returned real data with **no credential of any kind**.

The one that matters most is the negative: every price vendor tested — Tiingo,
Polygon, Alpaca, Finnhub, Alpha Vantage, Twelve Data, Marketstack, FMP, EODHD —
refuses unauthenticated access, and the published demo keys are whitelisted to a
handful of mega-caps. Survivorship-free *prices* remain unavailable for free.
Survivorship-free *membership* and *short interest* do not, and those are worth
more than they sound.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

UA = "integratedai research chhillarnaresh03@gmail.com"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default="/root/.iai/wide2015/w2015_prices.parquet")
    args = ap.parse_args(argv)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    from iai.sources import catalysts, shortinterest, universe

    cfg = Config.load()
    cl = HttpClient(cfg.data.cache_dir, UA, rate_per_sec=5.0, ttl_hours=24 * 7)
    ok, bad = [], []

    def check(name, fn):
        try:
            msg = fn()
            ok.append(name)
            print(f"  PASS  {name:34s} {msg}", flush=True)
        except Exception as e:                                   # noqa: BLE001
            bad.append(name)
            print(f"  FAIL  {name:34s} {type(e).__name__}: {str(e)[:90]}", flush=True)

    print("=" * 96)
    print("FREE, NO-CREDENTIAL SOURCES")
    print("=" * 96)

    d = {}

    def _uni():
        d["u"] = universe.fetch(cl)
        dead = universe.deaths(d["u"])
        return (f"{len(d['u']):,} rows, {len(dead):,} US-listed stocks died "
                f"2015-2025 with >=1yr history")
    check("Tiingo ticker universe", _uni)

    def _si():
        s = shortinterest.for_symbol(cl, "ZGNX")
        if s.empty:
            raise RuntimeError("no rows for a known dead ticker")
        last = s.settlementDate.max()
        dtc = s.loc[s.settlementDate == last, "daysToCoverQuantity"].iloc[0]
        return (f"{len(s)} settlements for a DEAD ticker, last {last:%Y-%m-%d}, "
                f"days-to-cover {dtc}")
    check("FINRA consolidated short int.", _si)

    def _ctg():
        t = catalysts.studies(cl, sponsor="Zogenix", page_size=20)
        if t.empty:
            raise RuntimeError("no studies")
        ph = t.phase.replace("", pd.NA).dropna()
        return (f"{len(t)} trials, {t.primary_completion.notna().sum()} with a "
                f"primary completion date, phases {sorted(set(ph))[:3]}")
    check("ClinicalTrials.gov v2", _ctg)

    def _fda():
        a = catalysts.drug_approvals(cl, 2020, limit=200)
        if a.empty:
            raise RuntimeError("no approvals")
        return f"{len(a):,} submissions in 2020, {a.sponsor.nunique():,} sponsors"
    check("openFDA drugsfda", _fda)

    def _fred():
        b = cl.get("https://fred.stlouisfed.org/graph/fredgraph.csv"
                   "?id=DGS10&cosd=2024-01-01&coed=2024-03-01", parse="text")
        if not b or "DGS10" not in b:
            raise RuntimeError("no series")
        return f"{len(b.splitlines()) - 1} daily observations, no API key used"
    check("FRED CSV (keyless path)", _fred)

    def _tre():
        b = cl.get("https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
                   "/v2/accounting/od/avg_interest_rates?page[size]=5")
        if not b or not b.get("data"):
            raise RuntimeError("no data")
        return f"{len(b['data'])} rows, meta count {b.get('meta', {}).get('total-count')}"
    check("US Treasury fiscaldata", _tre)

    # ---- the point of all of it -----------------------------------------
    if "u" in d and Path(args.panel).exists():
        print("\n" + "=" * 96)
        print("WHAT THE UNIVERSE FILE SAYS ABOUT OUR PANEL")
        print("=" * 96)
        import pyarrow.parquet as pq
        tick = pq.read_table(args.panel, columns=["ticker"]).to_pandas().ticker.unique()
        a = universe.audit(d["u"], tick)
        print(f"  panel tickers                       {a['panel']:>8,}")
        print(f"  US-listed stocks at the midpoint    {a['listed_at_midpoint']:>8,}")
        print(f"  panel as a share of that            {a['panel_share_of_midpoint'] * 100:>7.1f}%")
        print(f"  deaths in window (>=1yr history)    {a['deaths_in_window']:>8,}")
        print(f"  of those, absent from the panel     {a['deaths_absent_from_panel']:>8,}")
        mo = pd.date_range("2015-01-31", "2025-12-31", freq="ME")
        live = universe.live_count(d["u"], mo)
        print(f"\n  listed count, measured: {live.iloc[0]:,} at {mo[0]:%Y-%m} "
              f"-> {live.iloc[-1]:,} at {mo[-1]:%Y-%m}, mean {live.mean():,.0f}")
        print("  (this replaces the 4,000-5,500 assumption in RESULT_SURVIVORSHIP.md)")

    print(f"\n{len(ok)} passed, {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
