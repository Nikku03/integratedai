"""Reconstruct the delisted names, so the panel stops lying about survival.

Every absolute number in this repository is computed on a panel where zero of
3,662 tickers stopped trading in eleven years. That is not a small bias. The
names that vanish from a price vendor are overwhelmingly the ones that went to
zero, so their disappearance deletes the left tail of the return distribution
and inflates every mean, every win rate, and above all ``P(up | big move)``.

There is a survivorship-free record of who died, and it is public. When a
security stops trading on an exchange somebody has to file for it:

| form | what it means |
|---|---|
| 25-NSE | the **exchange** removed the security -- the cleanest delisting mark |
| 25 | the issuer notified removal from listing |
| 15-12B | registration under section 12(b) terminated |
| 15-12G | registration under 12(g) terminated |
| 15F-12B / 15F-12G | the same, for foreign private issuers |

These appear in EDGAR's quarterly ``form.idx``, which lists every filing of
every type by every filer in the quarter -- including filers that no longer
exist, which is exactly the property the price vendor lacks.

This script does two separable things, and the first matters more than the
second:

1. **Measure the missing mass.** Count delistings per year and check how many
   of them are present in the price panel. This alone converts "the panel is
   survivorship-biased" from an apology into a number.
2. **Attempt price recovery.** Try to resolve delisted CIKs back to tickers and
   pull whatever history still exists. Recovery will be partial -- vendors drop
   dead tickers, and that is the whole problem -- so the measurement is designed
   not to depend on it.
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

FORM_IDX = "https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{q}/form.idx"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"

#: Forms that mark a security leaving an exchange or a registration ending.
#: 25-NSE is exchange-initiated and is the single most reliable marker; Form 15
#: usually follows weeks later, so counting both without deduplicating by CIK
#: would double-count one death.
DELIST_FORMS = {"25-NSE", "25", "15-12B", "15-12G", "15F-12B", "15F-12G"}

#: form.idx is fixed-width-ish but the company name can contain runs of spaces,
#: so anchor on the CIK and date rather than splitting on whitespace.
ROW = re.compile(r"^(\S+)\s+(.+?)\s\s+(\d+)\s+(\d{4}-\d{2}-\d{2})\s+(\S+)\s*$")


def quarter_rows(client, year: int, q: int) -> list[dict]:
    """Delisting-form rows from one quarterly index."""
    raw = client.get_bytes(FORM_IDX.format(year=year, q=q))
    if raw is None:
        return []
    out = []
    for line in raw.decode("latin-1", errors="ignore").splitlines():
        if not line[:8].strip().split(" ")[0] in DELIST_FORMS:
            # cheap prefix reject before the regex; the index is ~50MB a quarter
            if not any(line.startswith(f) for f in DELIST_FORMS):
                continue
        m = ROW.match(line)
        if not m:
            continue
        form = m.group(1).strip()
        if form not in DELIST_FORMS:
            continue
        out.append({"form": form, "company": m.group(2).strip(),
                    "cik": m.group(3).zfill(10), "filed": m.group(4)})
    return out


def former_ticker(client, cik: str) -> dict | None:
    """Resolve a dead CIK back to whatever ticker it used to trade under."""
    blob = client.get(SUBMISSIONS.format(cik=cik))
    if not blob:
        return None
    tick = blob.get("tickers") or []
    ex = blob.get("exchanges") or []
    former = blob.get("formerNames") or []
    return {"cik": cik, "entity": blob.get("name", ""),
            "sic": str(blob.get("sic", "")).strip(),
            "ticker": tick[0] if tick else None,
            "n_tickers": len(tick),
            "exchange": ex[0] if ex else None,
            "n_former_names": len(former)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--start-year", type=int, default=2015)
    ap.add_argument("--end-year", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resolve", action="store_true",
                    help="also resolve dead CIKs to former tickers (slow)")
    args = ap.parse_args(argv)
    root = Path(args.root)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=6.0,
                     ttl_hours=24 * 30, max_retries=4)

    quarters = [(y, q) for y in range(args.start_year, args.end_year + 1)
                for q in (1, 2, 3, 4)]
    print(f"scanning {len(quarters)} quarterly form indexes for "
          f"{sorted(DELIST_FORMS)}", flush=True)

    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(quarter_rows, sec, y, q): (y, q) for y, q in quarters}
        for k, fu in enumerate(as_completed(futs), 1):
            y, q = futs[fu]
            try:
                r = fu.result()
            except Exception as e:                              # noqa: BLE001
                print(f"  {y}Q{q}: {e}")
                continue
            rows.extend(r)
            print(f"  [{k:>2d}/{len(quarters)}] {y}Q{q}: {len(r):>4d} rows, "
                  f"{len(rows):>6d} total", flush=True)

    d = pd.DataFrame(rows)
    if d.empty:
        print("no delisting filings found -- check index access")
        return 1
    d["filed"] = pd.to_datetime(d["filed"])
    d.to_parquet(root / "delist_filings.parquet")
    print(f"\n{len(d):,} delisting-form filings, {d.cik.nunique():,} distinct CIKs")
    print(d.form.value_counts().to_string())

    # One death per CIK: the earliest exchange-removal form, falling back to
    # the earliest deregistration if the company never filed a Form 25.
    d["is25"] = d.form.isin({"25-NSE", "25"})
    first = (d.sort_values(["cik", "is25", "filed"], ascending=[True, False, True])
               .drop_duplicates("cik", keep="first"))
    first.to_parquet(root / "delist_events.parquet")
    print(f"\n{len(first):,} distinct delisting events "
          f"({first.is25.mean() * 100:.1f}% marked by a Form 25)")

    print("\ndelistings per year:")
    yr = first.assign(y=first.filed.dt.year).groupby("y").size().rename("n")
    print(yr.to_string())

    # ------------------------------------------------------------------
    print("\n" + "=" * 72)
    print("HOW MUCH OF THIS IS MISSING FROM THE PRICE PANEL?")
    print("=" * 72)
    pool = pd.read_parquet(root / "candidate_pool.parquet")
    pool["cik"] = pool["cik"].astype(str).str.zfill(10)
    px = pd.read_parquet(root / "w2015_prices.parquet", columns=["ticker"])
    live = set(px.ticker.unique())
    pool_live = pool[pool.ticker.isin(live)]
    print(f"  price panel                 {len(live):,} tickers")
    print(f"  candidate pool              {len(pool):,} tickers")
    print(f"  pool names with prices      {len(pool_live):,}")

    dead_ciks = set(first.cik)
    pool_dead = pool[pool.cik.isin(dead_ciks)]
    panel_dead = pool_live[pool_live.cik.isin(dead_ciks)]
    print(f"\n  CIKs with a delisting event {len(dead_ciks):,}")
    print(f"  of those, in candidate pool {len(pool_dead):,}")
    print(f"  of those, in price panel    {len(panel_dead):,}")

    denom = len(pool_live) + len(pool_dead[~pool_dead.ticker.isin(live)])
    if denom:
        miss = len(pool_dead[~pool_dead.ticker.isin(live)])
        print(f"\n  a universe of pool names that were alive at some point since "
              f"{args.start_year}\n  would contain about {denom:,} tickers, of which "
              f"{miss:,} ({miss / denom * 100:.1f}%) delisted and\n  are absent "
              f"from the price panel entirely.")

    if args.resolve:
        print("\nresolving dead CIKs to former tickers", flush=True)
        todo = sorted(dead_ciks)
        res = []
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(former_ticker, sec, c) for c in todo]
            for k, fu in enumerate(as_completed(futs), 1):
                if k % 500 == 0:
                    print(f"  {k}/{len(todo)}", flush=True)
                try:
                    v = fu.result()
                except Exception:                               # noqa: BLE001
                    v = None
                if v:
                    res.append(v)
        r = pd.DataFrame(res)
        r = r.merge(first[["cik", "filed", "form", "company"]], on="cik", how="left")
        r.to_parquet(root / "delist_resolved.parquet")
        got = r[r.ticker.notna()]
        print(f"\n  {len(r):,} CIKs resolved, {len(got):,} still expose a ticker "
              f"({len(got) / max(len(r), 1) * 100:.1f}%)")
        print(f"  of those, {got.ticker.isin(live).sum():,} are already in the panel")
        print("  The rest are the recoverable candidates; a vendor that has "
              "dropped\n  them will simply return nothing, which is the bias "
              "restating itself.")

    print("\nWhat this changes: nothing about the model's *ranking*, which is")
    print("computed within-day across names that all exist. It changes every")
    print("absolute rate, and it changes P(up | big move) most of all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
