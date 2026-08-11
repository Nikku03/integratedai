"""Fetch 8-K text and turn it into panel features.

`RESULT_WHY_LOSERS.md` measured the ceiling on the current inputs: a classifier
trained to tell winning picks from losing ones reaches 0.5302 out of sample. The
108 numeric features are exhausted — better models on them cannot help, which is
what the checklist failure and the ADRNN's loss to gradient boosting were both
saying. The only way forward is information the panel does not contain, and the
most obvious missing piece is *what the filing actually said*.

Scope, and why it is not the whole panel
----------------------------------------
There are 346,966 distinct 8-K filings across the universe. At the SEC's rate
limit that is roughly eighteen hours of fetching. Restricting to pharmaceutical,
biotech and medical SIC codes leaves 70,930 filings across 698 tickers — about
two hours — and that is where the moonshots live: clinical readouts, FDA
decisions, licensing deals and takeouts. If text carries signal anywhere it
carries it there, so this is the right subset for a first test rather than an
arbitrary sample.

Two fetch depths
----------------
The primary 8-K document is one request. For items that usually *are* a press
release (1.01, 2.01, 7.01, 8.01), the substance sits in an EX-99 exhibit and
needs the filing index plus the exhibit, so those cost three requests. Items
like 5.02 (officer change) carry their content inline and get one.

Everything is cached on disk, so the job is resumable and a rerun is nearly free.

Point-in-time
-------------
Features attach to the filing's ``available_ts``, not its event timestamp, and
are aggregated onto the first trading day at or after it. A filing accepted at
20:30 is not usable that afternoon.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from catalyst_extract import (BINDING, CATEGORY_PATTERNS, NONBINDING,  # noqa: E402
                              TOXIC, VALUE_NEAR, MULT)

#: Any dollar amount, not only ones qualified by transaction language.
#:
#: ``catalyst_extract.VALUE_NEAR`` requires a phrase like "consideration of"
#: before the figure, which is right when the goal is a defensible transaction
#: value but wrong for a feature: it misses "$250.0 million milestone payment"
#: and "up to $114.50 per share" entirely. For ranking purposes the useful
#: signal is simply the largest number the document mentions.
#:
#: Named groups matter here. VALUE_NEAR uses positional groups, so calling
#: ``m.group("num")`` on it raises IndexError on every match -- which is what
#: silently produced a zero-valued feature on the first pass.
MONEY = re.compile(
    r"\$\s?(?P<num>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<mult>thousand|million|billion|bn|mm?)?\b", re.I)
MONEY_MULT = {"thousand": 1e3, "million": 1e6, "billion": 1e9,
              "bn": 1e9, "mm": 1e6, "m": 1e6, None: 1.0, "": 1.0}
from catalyst_size import TAGS, WS  # noqa: E402
from oos_clinical import BIO_SIC, GOOD, BAD  # noqa: E402

INDEX = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/index.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
EX99 = re.compile(r"ex-?99", re.I)

#: Items whose substance is normally in an exhibit rather than the 8-K body.
EXHIBIT_ITEMS = {"1.01", "2.01", "7.01", "8.01", "2.02"}

CAT_NAMES = [c for c, _ in CATEGORY_PATTERNS]
TOX_NAMES = list(TOXIC.keys())


def largest_value(text: str) -> tuple[float, float]:
    """(biggest dollar figure anywhere, biggest qualified transaction value).

    Both are returned because they mean different things: the first is "how big
    are the numbers in this document", the second is "what is this deal worth"
    and is far rarer but much cleaner when present.
    """
    best = 0.0
    for m in MONEY.finditer(text[:40000]):
        try:
            num = float(m.group("num").replace(",", ""))
        except (ValueError, AttributeError):
            continue
        unit = (m.group("mult") or "").lower().strip()
        val = num * MONEY_MULT.get(unit, 1.0)
        if val < 1e12:                      # guard against parsed page numbers
            best = max(best, val)

    qual = 0.0
    for m in VALUE_NEAR.finditer(text[:40000]):
        try:                                 # positional groups, not named
            num = float(m.group(1).replace(",", ""))
        except (ValueError, AttributeError, IndexError):
            continue
        unit = (m.group(2) or "").lower().strip()
        qual = max(qual, num * MULT.get(unit, 1.0))
    return best, qual


def fetch_text(client, row) -> str:
    """Primary document, plus the first EX-99 when the item warrants it."""
    txt = ""
    raw = client.get_bytes(row["url"])
    if raw:
        txt = WS.sub(" ", TAGS.sub(" ", raw.decode("utf-8", errors="ignore")))
    if not (row["items"] & EXHIBIT_ITEMS):
        return txt
    cik = str(int(row["cik"]))
    acc = row["acc"].replace("-", "")
    blob = client.get(INDEX.format(cik=cik, acc=acc))
    if not blob:
        return txt
    names = [i.get("name", "")
             for i in (blob.get("directory") or {}).get("item", [])]
    for n in [x for x in names
              if EX99.search(x) and x.lower().endswith((".htm", ".html", ".txt"))][:1]:
        b = client.get_bytes(ARCHIVE.format(cik=cik, acc=acc, doc=n))
        if b:
            txt += " " + WS.sub(" ", TAGS.sub(" ", b.decode("utf-8", errors="ignore")))
    return txt


def features_from(text: str) -> dict:
    """Everything measurable from the document, as numbers."""
    t = text[:40000]
    f = {"txt_len": float(len(text)), "txt_ok": 1.0 if len(t) > 400 else 0.0}
    for name, pat in CATEGORY_PATTERNS:
        f[f"cat_{name}"] = 1.0 if pat.search(t) else 0.0
    for name, pat in TOXIC.items():
        f[f"tox_{name}"] = 1.0 if pat.search(t) else 0.0
    f["binding"] = 1.0 if BINDING.search(t) else 0.0
    f["nonbinding"] = 1.0 if NONBINDING.search(t) else 0.0
    g, b = bool(GOOD.search(t)), bool(BAD.search(t))
    f["tone_good"] = 1.0 if g else 0.0
    f["tone_bad"] = 1.0 if b else 0.0
    f["tone_net"] = float(g) - float(b)
    v, qual = largest_value(t)
    f["log_value"] = float(np.log10(v)) if v > 0 else 0.0
    f["log_deal_value"] = float(np.log10(qual)) if qual > 0 else 0.0
    f["has_deal_value"] = 1.0 if qual > 0 else 0.0
    f["tox_any"] = float(any(f[f"tox_{n}"] > 0 for n in TOX_NAMES))
    f["cat_any"] = float(any(f[f"cat_{n}"] > 0 for n in CAT_NAMES))
    return f


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    ap.add_argument("--ticker-frac", type=float, default=0.0,
                    help="sample this fraction of TICKERS and keep all of their "
                         "filings; 0 = every ticker")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--all-sic", action="store_true",
                    help="do not restrict to biotech (18h, not 2h)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    out = root / ("text_feats_all.parquet" if args.all_sic
                  else "text_feats_bio.parquet")

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0,
                     ttl_hours=24 * 365 * 5, max_retries=3)

    print("building filing list", flush=True)
    d = pd.read_parquet(root / "edgar_shard00of01.parquet",
                        columns=["kind", "ticker", "event_ts", "available_ts",
                                 "payload"])
    d = d[d.kind.str.startswith("8-K")].copy()
    pl = d.payload.map(ast.literal_eval)
    d["acc"] = pl.map(lambda x: x.get("id"))
    d["cik"] = pl.map(lambda x: x.get("cik"))
    d["sic"] = pl.map(lambda x: str(x.get("sic", "")))
    d["url"] = pl.map(lambda x: x.get("url"))
    d["item"] = d.kind.str[4:]

    # One row per filing, carrying the set of items it reported.
    g = (d.groupby("acc")
           .agg(ticker=("ticker", "first"), cik=("cik", "first"),
                sic=("sic", "first"), url=("url", "first"),
                available_ts=("available_ts", "first"),
                items=("item", lambda s: set(s))).reset_index())
    if not args.all_sic:
        g = g[g.sic.isin(BIO_SIC)]
    g = g[g.url.notna()].reset_index(drop=True)

    # Subsampling by TICKER, never by filing.
    #
    # Taking a random 10% of filings would corrupt every derived feature: the
    # trailing 5/20/60-session counts and days-since-last-filing are computed
    # from whatever filings are present, so a company that filed weekly would
    # look like one that filed rarely, and the error would be largest for
    # exactly the busiest names. Keeping every filing for a subset of tickers
    # costs universe breadth instead, which is honest and recoverable.
    if args.ticker_frac and 0 < args.ticker_frac < 1:
        names = np.sort(g.ticker.unique())
        rng = np.random.default_rng(args.seed)
        keep = rng.choice(names, max(1, int(round(len(names) * args.ticker_frac))),
                          replace=False)
        g = g[g.ticker.isin(set(keep))].reset_index(drop=True)
        print(f"  sampled {len(keep)} of {len(names)} tickers "
              f"(seed {args.seed}), keeping every filing for each", flush=True)
    if args.limit:
        g = g.head(args.limit)
    print(f"  {len(g):,} filings, {g.ticker.nunique()} tickers", flush=True)

    done = {}
    if out.exists():
        prev = pd.read_parquet(out)
        done = set(prev.acc)
        print(f"  {len(done):,} already extracted, resuming", flush=True)
        g = g[~g.acc.isin(done)]
        print(f"  {len(g):,} remaining", flush=True)
    else:
        prev = None

    rows = []

    def work(r):
        try:
            t = fetch_text(sec, r)
        except Exception:                                       # noqa: BLE001
            return None
        if not t:
            return None
        return {"acc": r["acc"], "ticker": r["ticker"],
                "available_ts": r["available_ts"], **features_from(t)}

    recs = g.to_dict("records")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, r) for r in recs]
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 2000 == 0:
                print(f"  {k:,}/{len(recs):,}  ({len(rows):,} with text)",
                      flush=True)
                if rows:
                    part = pd.DataFrame(rows)
                    if prev is not None:
                        part = pd.concat([prev, part], ignore_index=True)
                    part.to_parquet(out)
            try:
                v = fu.result()
            except Exception:                                   # noqa: BLE001
                v = None
            if v:
                rows.append(v)

    f = pd.DataFrame(rows)
    if prev is not None and len(prev):
        f = pd.concat([prev, f], ignore_index=True)
    f = f.drop_duplicates("acc")
    f.to_parquet(out)
    print(f"\n{len(f):,} filings with extracted text -> {out}")
    if len(f):
        print("\ncategory hit rates:")
        for c in [c for c in f.columns if c.startswith("cat_")]:
            print(f"  {c:28s} {f[c].mean() * 100:5.1f}%")
        print("\ntoxic-financing hit rates:")
        for c in [c for c in f.columns if c.startswith("tox_")]:
            print(f"  {c:28s} {f[c].mean() * 100:5.1f}%")
        print(f"\ntone: good {f.tone_good.mean() * 100:.1f}%  "
              f"bad {f.tone_bad.mean() * 100:.1f}%   "
              f"median doc length {f.txt_len.median():,.0f} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
