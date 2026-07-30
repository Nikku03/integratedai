"""Start from the moves, not the filings: every 10%+ mover and what caused it.

Every study in this project so far has run the same direction -- take a set of
filings, ask what the price did. That answers "do filings pay?" but it cannot
answer the prior question: **are filings even where the big moves come from?**
Selecting on filings and then measuring returns can only ever find the moves
that had a filing, so a moonshot driven by something else is invisible by
construction.

This runs the other way. Screen the whole candidate universe for large moves in
the window, then go looking for the cause of each. The headline number it
produces is the one that matters most and that nothing else here can produce:
**what share of 10%+ moves had any 8-K at all.**

Stage 1 (this script): the census
    Daily bars for every ticker with a CIK, last ~40 days. For each name, the
    largest 1-day and largest 5-day move, with the date it happened. Filtered to
    names an $80 account could actually touch -- above $1, with real dollar
    volume -- because a 300% move on a name that trades $4,000 a day is not an
    opportunity.

Stage 2 (``--attribute``): the cause
    For each mover, every EDGAR filing in the five sessions up to and including
    the move date. A mover with a filing gets attributed to its form and items;
    a mover with none is recorded as unattributed, which is the interesting
    bucket rather than a failure.

Usage
-----
    python scripts/moonshot_census.py --user-agent "you@example.com" --days 40
    python scripts/moonshot_census.py --attribute --user-agent "you@example.com"
"""

from __future__ import annotations

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from iai.core.config import Config
from iai.core.http import HttpClient
from iai.sources.prices import BROWSER_UA, YAHOO_CHART

log = logging.getLogger("census")

#: A move must clear this to count as a moonshot. Deliberately generous: the
#: point is to enumerate the population, and the threshold can be raised later
#: in analysis without refetching.
MOONSHOT = 0.10

#: Tradability floor. Below these an $80 order is not the marginal buyer, it is
#: the entire book, and the printed move is not a price anyone could transact at.
MIN_PRICE = 1.00
MIN_MEDIAN_DOLLARS = 250_000.0


def daily_bars(client, ticker: str, days: int) -> pd.DataFrame:
    """Daily bars for the trailing window, snapped to day boundaries.

    The window edges are snapped so the HTTP cache key is stable across runs --
    deriving it from ``now`` to the second gives every invocation a fresh key
    and the cache never hits.
    """
    hi = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
    lo = hi - pd.Timedelta(days=days)
    blob = client.get(
        YAHOO_CHART.format(symbol=ticker),
        params={"period1": int(lo.timestamp()), "period2": int(hi.timestamp()),
                "interval": "1d", "includePrePost": "false"},
        headers={"User-Agent": BROWSER_UA},
    )
    res = (blob or {}).get("chart", {}).get("result")
    if not res:
        return pd.DataFrame()
    r = res[0]
    ts = r.get("timestamp") or []
    if not ts:
        return pd.DataFrame()
    q = r["indicators"]["quote"][0]
    out = pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(
            "America/New_York").normalize().tz_localize(None),
        "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
        "close": q.get("close"), "volume": q.get("volume"),
    }).dropna(subset=["close"])
    out["ticker"] = ticker
    return out


def summarise(bars: pd.DataFrame) -> dict | None:
    """Largest 1-day and 5-day move in the window, and when.

    Returns are close-to-close, which is what a screen can see. The 5-day figure
    is a rolling *forward* window measured from each close, so it captures a move
    that built over a week rather than gapping in one session -- most real
    re-ratings do the former.
    """
    if len(bars) < 6:
        return None
    b = bars.sort_values("date").reset_index(drop=True)
    c = b["close"].to_numpy(dtype=float)
    dollars = (b["close"] * b["volume"].fillna(0)).to_numpy(dtype=float)

    r1 = c[1:] / c[:-1] - 1.0
    i1 = int(np.nanargmax(r1)) if np.isfinite(r1).any() else 0

    # Forward 5-session move from each close, so a slow grind is not missed.
    r5 = np.full(len(c), np.nan)
    for i in range(len(c)):
        j = min(i + 5, len(c) - 1)
        if j > i:
            r5[i] = c[j] / c[i] - 1.0
    i5 = int(np.nanargmax(r5)) if np.isfinite(r5).any() else 0

    return {
        "ticker": b["ticker"].iloc[0],
        "n_days": len(b),
        "last_close": float(c[-1]),
        "min_close": float(np.nanmin(c)),
        "median_dollars": float(np.nanmedian(dollars)),
        "max_1d": float(r1[i1]) if np.isfinite(r1).any() else np.nan,
        "max_1d_date": b["date"].iloc[i1 + 1],
        "max_5d": float(r5[i5]) if np.isfinite(r5[i5]) else np.nan,
        "max_5d_start": b["date"].iloc[i5],
        "window_ret": float(c[-1] / c[0] - 1.0),
    }


def census(argv_root: Path, tickers: list[str], client, days: int,
           workers: int) -> pd.DataFrame:
    rows, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(daily_bars, client, t, days): t for t in tickers}
        for fut in as_completed(futs):
            done += 1
            if done % 500 == 0:
                log.info("%d/%d fetched, %d usable", done, len(tickers), len(rows))
            try:
                b = fut.result()
            except Exception:                       # noqa: BLE001
                continue
            if b.empty:
                continue
            s = summarise(b)
            if s:
                rows.append(s)
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True,
                    help="real contact string; Yahoo and SEC both want one")
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--yahoo-rate", type=float, default=12.0)
    ap.add_argument("--attribute", action="store_true",
                    help="stage 2: find the cause of each mover")
    ap.add_argument("--threshold", type=float, default=MOONSHOT)
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")
    root = Path(args.root)

    if args.attribute:
        a = attribute(root, args.threshold)
        a.to_parquet(root / "census_attributed.parquet")
        print(f"\n{len(a)} movers >= {args.threshold:.0%} "
              f"(1-day or 5-day), tradable universe\n")
        g = (a.groupby("cause")
              .agg(n=("move_size", "size"), median_move=("move_size", "median"),
                   max_move=("move_size", "max"))
              .sort_values("n", ascending=False))
        g["share %"] = (g["n"] / len(a) * 100).round(1)
        g["median_move"] = (g["median_move"] * 100).round(1)
        g["max_move"] = (g["max_move"] * 100).round(1)
        print(g.to_string())
        covered = a[a.cause != "not covered"]
        if len(covered):
            no_fil = (covered.cause == "no filing").mean()
            print(f"\nof {len(covered)} movers with filing coverage, "
                  f"**{no_fil * 100:.0f}% had no filing at all** in the seven "
                  "days up to the move")
        return 0

    cfg = Config.load()
    yah = HttpClient(cfg.data.cache_dir, args.user_agent,
                     rate_per_sec=args.yahoo_rate, ttl_hours=6.0, max_retries=4)

    pool_df = pd.read_parquet(root / "candidate_pool.parquet")
    tickers = sorted(pool_df["ticker"].dropna().unique().tolist())
    log.info("screening %d tickers over the last %d days", len(tickers), args.days)

    d = census(root, tickers, yah, args.days, args.workers)
    d.to_parquet(root / "census_moves.parquet")
    log.info("%d tickers returned usable bars", len(d))

    tradable = d[(d.min_close >= MIN_PRICE) &
                 (d.median_dollars >= MIN_MEDIAN_DOLLARS)]
    print(f"\nuniverse screened: {len(d)} names with bars, "
          f"{len(tradable)} above ${MIN_PRICE:.0f} and "
          f"${MIN_MEDIAN_DOLLARS:,.0f} median daily dollars\n")

    for label, col in (("1-day", "max_1d"), ("5-day", "max_5d")):
        c = tradable[col].dropna()
        print(f"largest {label} move per name, distribution across "
              f"{len(c)} tradable names:")
        print(f"  median {c.median() * 100:+.1f}%   p90 {c.quantile(.90) * 100:+.1f}%"
              f"   >=10%: {(c >= .10).sum():4d} ({(c >= .10).mean() * 100:.0f}%)"
              f"   >=20%: {(c >= .20).sum():4d}"
              f"   >=50%: {(c >= .50).sum():4d}   max {c.max() * 100:+.0f}%")
    return 0



#: How a filing form maps to a cause. Ordered: the first match wins, so a mover
#: with both an offering and an 8-K is attributed to the offering, which is the
#: economically dominant event.
FORM_CAUSE = [
    ("offering/dilution", ("424B", "S-1", "S-3", "S-1/A", "S-3/A", "F-1", "F-3")),
    ("merger/tender",     ("425", "SC TO-T", "SC 14D9", "SC TO-I", "DEFM14A")),
    ("activist/stake",    ("SCHEDULE 13D", "SCHEDULE 13D/A", "SC 13D", "SC 13D/A")),
    ("8-K",               ("8-K", "8-K/A")),
    ("passive stake",     ("SCHEDULE 13G", "SCHEDULE 13G/A")),
    ("periodic report",   ("10-Q", "10-K", "20-F", "6-K", "10-Q/A", "10-K/A")),
    ("insider",           ("4", "3", "144")),
    ("proxy/other",       ("DEF 14A", "DEFA14A", "PRE 14A", "8-A12B", "S-8")),
]

#: 8-K item codes grouped by what they say. Only used to label an 8-K cause more
#: precisely; the grouping mirrors the trap taxonomy used elsewhere.
ITEM_CAUSE = {
    "1.01": "material agreement", "1.02": "agreement terminated",
    "1.03": "bankruptcy", "2.01": "acquisition completed",
    "2.02": "earnings", "2.03": "debt incurred", "2.04": "debt accelerated",
    "2.05": "restructuring", "2.06": "impairment",
    "3.01": "delisting notice", "3.02": "equity issued (dilution)",
    "3.03": "security terms changed", "4.01": "auditor change",
    "4.02": "non-reliance/restatement", "5.01": "control change",
    "5.02": "officer/director change", "5.03": "charter amended",
    "5.07": "vote results", "7.01": "reg-FD disclosure",
    "8.01": "other event", "9.01": "exhibits",
}


def cause_of(forms: list[str], items: list[str]) -> tuple[str, str]:
    """Map a mover's filings in the window to a cause label and detail."""
    upper = {str(f).upper().strip() for f in forms}
    for label, prefixes in FORM_CAUSE:
        for f in upper:
            if any(f == p or f.startswith(p) for p in prefixes):
                if label == "8-K":
                    codes = sorted({c.strip() for i in items
                                    for c in str(i).split(",") if c.strip()})
                    named = [ITEM_CAUSE.get(c, c) for c in codes
                             if c not in ("9.01",)]
                    return label, ", ".join(named) or "exhibits only"
                return label, ",".join(sorted(upper & {f}))
    return "no filing", ""


def attribute(root: Path, threshold: float) -> pd.DataFrame:
    """Join every mover to the filings in the five sessions up to its move.

    A mover with no filing is kept and labelled ``no filing`` rather than
    dropped. That bucket is the whole point: it measures how much of the tail
    the paperwork never explains.
    """
    d = pd.read_parquet(root / "census_moves.parquet")
    fil = pd.read_parquet(root / "recent_filings.parquet")
    fil["accepted"] = pd.to_datetime(fil["accepted"], utc=True, format="mixed")
    fil["d"] = fil["accepted"].dt.tz_convert("America/New_York").dt.normalize() \
                              .dt.tz_localize(None)

    trad = d[(d.min_close >= MIN_PRICE) &
             (d.median_dollars >= MIN_MEDIAN_DOLLARS)].copy()
    mv = trad[(trad.max_1d >= threshold) | (trad.max_5d >= threshold)].copy()
    # Anchor on whichever definition caught it, preferring the 1-day date when
    # both fire -- a gap is a sharper timestamp than the start of a grind.
    mv["move_date"] = np.where(mv.max_1d >= threshold,
                               mv.max_1d_date, mv.max_5d_start)
    mv["move_date"] = pd.to_datetime(mv["move_date"])
    mv["move_size"] = mv[["max_1d", "max_5d"]].max(axis=1)

    covered = set(fil["ticker"].unique())
    rows = []
    for r in mv.to_dict("records"):
        if r["ticker"] not in covered:
            rows.append({**r, "cause": "not covered", "detail": "",
                         "n_filings": 0, "forms": ""})
            continue
        lo = r["move_date"] - pd.Timedelta(days=7)
        hi = r["move_date"] + pd.Timedelta(days=1)
        w = fil[(fil.ticker == r["ticker"]) & (fil.d >= lo) & (fil.d <= hi)]
        cause, detail = cause_of(w["form"].tolist(), w["items"].tolist())
        rows.append({**r, "cause": cause, "detail": detail,
                     "n_filings": len(w),
                     "forms": ",".join(sorted(set(w["form"].astype(str))))})
    return pd.DataFrame(rows)


def fill_coverage(root: Path, movers: list[str], client, workers: int = 8) -> pd.DataFrame:
    """Fetch EDGAR submissions for movers the existing filing set does not cover.

    ``recent_filings.parquet`` was built for a different question and covers
    2,853 names. Any mover outside that set would come back ``not covered``,
    which would silently understate the filing-attributed share -- the exact
    number this census exists to measure. So the gap gets filled rather than
    reported as a category.
    """
    from iai.sources.edgar import SUBMISSIONS_URL, parse_items

    pool = pd.read_parquet(root / "candidate_pool.parquet")
    cik_of = {r.ticker: str(r.cik).zfill(10)
              for r in pool.itertuples() if pd.notna(r.cik)}
    todo = [(t, cik_of[t]) for t in movers if t in cik_of]
    log.info("filling filing coverage for %d movers", len(todo))

    cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60)
    rows = []

    def one(pair):
        t, cik = pair
        blob = client.get(SUBMISSIONS_URL.format(cik=cik))
        rec = (blob or {}).get("filings", {}).get("recent", {})
        forms = rec.get("form", [])
        out = []
        for i, form in enumerate(forms):
            raw = rec.get("acceptanceDateTime", [None] * len(forms))[i]
            if not raw:
                continue
            ts = pd.Timestamp(raw)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            if ts < cut:
                continue
            out.append({"ticker": t, "form": form, "accepted": ts,
                        "items": ",".join(parse_items(
                            rec.get("items", [""] * len(forms))[i] or "")),
                        "accession": rec.get("accessionNumber",
                                             [""] * len(forms))[i]})
        return out

    with ThreadPoolExecutor(max_workers=workers) as pool_ex:
        futs = [pool_ex.submit(one, p) for p in todo]
        for k, fut in enumerate(as_completed(futs), 1):
            if k % 100 == 0:
                log.info("  %d/%d", k, len(todo))
            try:
                rows.extend(fut.result())
            except Exception:                       # noqa: BLE001
                continue
    return pd.DataFrame(rows)

if __name__ == "__main__":
    sys.exit(main())
