"""A census of common stocks that actually stopped trading, from the filings themselves.

`delisting_universe.py` counted 8,297 delisting filings and then tried to resolve
each dead CIK back to a ticker through the submissions API. That resolution is
wrong, and wrong in a way that matters: the API returns the issuer's *current*
tickers, so the resolved list is headed by APD, BMY, CAT, AIG and AMAT — all
alive. Their Form 25s delisted bonds and preferred classes, not the common.
Using that table as a death list would have counted Caterpillar as a death.

The filing itself carries the answer. A Form 25 / 25-NSE is a small XML with two
fields that settle it:

``<descriptionClassSecurity>``
    What was removed — "Common stock", "6.5% Notes due 2027", "Warrants",
    "Units", "Preferred". Only the first is a company dying.

``<ruleProvision>``
    Why. ``12d2-2(b)`` is the exchange striking the security, which is the
    involuntary case — a compliance failure, a bankruptcy, a stock that fell
    under a dollar and stayed there. ``12d2-2(a)`` and ``(c)`` are the issuer
    withdrawing voluntarily, which is overwhelmingly a completed merger. Both
    end the ticker, but only one is a loss: shareholders in a merger get paid.

That distinction is the entire point. A survivorship correction built on all
delistings would charge the strategy for takeovers, which are the *good*
outcome.

Why this is worth doing even though the prices are gone
------------------------------------------------------
Yahoo returns 404 for every delisted ticker — SIVBQ, BBBYQ, HTZGQ, ZGNX, OTIC,
ATVI, TWTR all tested, all absent — and Stooq is unreachable from here. Dead
names cannot be put back into the price panel without a paid vendor extract, and
`src/iai/sources/prices.py` already says so. What can be recovered is the
**rate**, and the rate is what the backtest correction needs: `RESULT_AGREED_
STRATEGY.md` showed the book breaks even once about 1% of trades are undisclosed
total losses, so the only question that matters is whether the real involuntary
death rate among microcaps clears 1% over a ten-session hold.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

FORM_IDX = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"
DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/primary_doc.xml"

#: Only the exchange-removal forms carry the security class. Form 15 terminates
#: a registration and is filed weeks later, so it corroborates but does not
#: identify.
FORMS = {"25", "25-NSE"}

ROW = re.compile(r"^(\S+)\s+(.+?)\s\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$")
ACC = re.compile(r"(\d{10}-\d{2}-\d{6})")


def tag(xml: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", xml, re.S | re.I)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


#: "Common stock", "Common Stock, par value $0.001", "Class A Common Stock",
#: "Ordinary Shares" for foreign issuers. Excludes anything that is plainly a
#: different instrument even when the phrase "common stock" appears inside it,
#: such as "Warrants to purchase common stock".
COMMON = re.compile(r"\b(common\s+stock|common\s+shares|ordinary\s+shares|"
                    r"class\s+[a-c]\s+common|common,?\s+no\s+par)\b", re.I)
NOT_COMMON = re.compile(r"\b(warrant|unit|right|note|debenture|bond|preferred|"
                        r"depositary|subordinated|trust\s+preferred|"
                        r"contingent\s+value)\b", re.I)

#: 12d2-2(b) is the exchange striking the security on its own motion. Everything
#: else in the rule is the issuer withdrawing, which in practice means a merger
#: closed or the listing moved.
INVOLUNTARY = re.compile(r"12d2-2\s*\(\s*b\s*\)", re.I)


def quarter_rows(client, year: int, q: int) -> list[dict]:
    raw = client.get_bytes(FORM_IDX.format(year=year, q=q))
    if raw is None:
        return []
    out = []
    for line in raw.decode("latin-1", errors="ignore").splitlines():
        if not any(line.startswith(f) for f in FORMS):
            continue
        m = ROW.match(line)
        if not m or m.group(1).strip() not in FORMS:
            continue
        a = ACC.search(m.group(5))
        if not a:
            continue
        out.append({"form": m.group(1).strip(), "company": m.group(2).strip(),
                    "cik": m.group(3), "filed": m.group(4), "acc": a.group(1)})
    return out


def read_filing(client, r: dict) -> dict | None:
    b = client.get_bytes(DOC.format(cik=int(r["cik"]), acc=r["acc"].replace("-", "")))
    if not b:
        return None
    x = b.decode("utf-8", errors="ignore")
    desc = tag(x, "descriptionClassSecurity")
    rule = tag(x, "ruleProvision")
    return {**r,
            "security": desc,
            "rule": rule,
            "exchange": tag(x, "entityName"),
            "issuer": tag(x, "issuer"),
            "is_common": bool(COMMON.search(desc) and not NOT_COMMON.search(desc)),
            "involuntary": bool(INVOLUNTARY.search(rule))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", default="integratedai research chhillarnaresh03@gmail.com")
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2025)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)
    root = Path(args.root)
    out = root / "delist_census.parquet"

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=8.0,
                     ttl_hours=24 * 365 * 5, max_retries=4)

    quarters = [(y, q) for y in range(args.start_year, args.end_year + 1)
                for q in (1, 2, 3, 4)]
    print(f"scanning {len(quarters)} quarterly indexes for {sorted(FORMS)}",
          flush=True)
    rows = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(quarter_rows, sec, y, q): (y, q) for y, q in quarters}
        for fu in as_completed(futs):
            rows.extend(fu.result() or [])
    idx = pd.DataFrame(rows).drop_duplicates("acc")
    print(f"  {len(idx):,} Form 25/25-NSE filings", flush=True)
    if args.limit:
        idx = idx.head(args.limit)

    done = pd.read_parquet(out) if out.exists() else None
    if done is not None:
        idx = idx[~idx.acc.isin(set(done.acc))]
        print(f"  {len(done):,} already read, {len(idx):,} remaining", flush=True)

    got = []
    recs = idx.to_dict("records")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(read_filing, sec, r) for r in recs]
        for k, fu in enumerate(as_completed(futs), 1):
            try:
                v = fu.result()
            except Exception:                                   # noqa: BLE001
                v = None
            if v:
                got.append(v)
            if k % 1000 == 0:
                print(f"  {k:,}/{len(recs):,} read ({len(got):,} parsed)", flush=True)
                pd.DataFrame(got + ([] if done is None else done.to_dict("records"))
                             ).to_parquet(out)
    d = pd.DataFrame(got)
    if done is not None and len(done):
        d = pd.concat([done, d], ignore_index=True)
    d = d.drop_duplicates("acc")
    d["filed"] = pd.to_datetime(d["filed"])
    d.to_parquet(out)
    print(f"\nwrote {out}  ({len(d):,} filings)\n")

    print("=" * 92)
    print("WHAT WAS ACTUALLY DELISTED")
    print("=" * 92)
    print(f"  Form 25/25-NSE filings parsed      {len(d):,}")
    print(f"  of which the security is common    {int(d.is_common.sum()):,} "
          f"({d.is_common.mean() * 100:.1f}%)")
    print(f"  of which involuntary (12d2-2(b))   "
          f"{int((d.is_common & d.involuntary).sum()):,}")
    print("\n  most common security descriptions:")
    for s, n in d.security.str.lower().str.slice(0, 54).value_counts().head(10).items():
        print(f"    {n:>6,}  {s}")
    print("\n  rule provisions:")
    for s, n in d.rule.str.slice(0, 40).value_counts().head(8).items():
        print(f"    {n:>6,}  {s}")

    print("\n" + "=" * 92)
    print("COMMON-STOCK DEATHS PER YEAR")
    print("=" * 92)
    c = d[d.is_common].copy()
    c["year"] = c.filed.dt.year
    g = c.groupby("year").agg(all_common=("acc", "size"),
                              involuntary=("involuntary", "sum"))
    g["voluntary"] = g.all_common - g.involuntary
    print(g.to_string())
    print(f"\n  totals {args.start_year}-{args.end_year}:  "
          f"{int(g.all_common.sum()):,} common-stock delistings, "
          f"{int(g.involuntary.sum()):,} involuntary, "
          f"{int(g.voluntary.sum()):,} voluntary (mergers and moves)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
