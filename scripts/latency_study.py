"""Does the price move at the filing, or after it?

The thesis under test
---------------------
Official paperwork is public the instant EDGAR accepts it, but most people find
out later, via a press release or a news feed. If the crowd is asleep and the
paperwork is already filed, a scraper watching EDGAR could position ahead of
them -- not to beat institutions to the microsecond, but to get filled into
normal liquidity instead of chasing a gap.

That is an *execution* claim, and it is testable without any model. It reduces
to a single measurement:

    at filing time T, and one minute later, where is the price?

If the move is already complete at T+1min, there is nothing to harvest -- the
information was priced before a retail scraper could act, and buying then means
paying for a move that already happened. If the price is flat at T+1min and
drifts over the following hour, the window is real and worth money.

This script measures that, per filing, on real minute bars.

What it does not model, and why that matters
--------------------------------------------
**Minute bars have no spread.** Filling at the close of the T+1 bar is
optimistic, and knowingly so. Real entry pays the offer, and on a small cap
outside regular hours that is routinely 100-300 bps rather than the ~15 bps
half-spread the daily cost model charges. Every return here is therefore an
*upper bound* on what an actual account would have earned. Where the answer is
"no edge even before spread", the spread does not need estimating.

**Volume is reported, never assumed.** A bar with zero volume is not a fill; it
is a print that did not happen. Filings whose next minute has no trade are
counted separately rather than silently given the last price.

Usage
-----
    python scripts/latency_study.py --days 28 --forms 8-K --max-names 400
"""

from __future__ import annotations

import argparse
import logging
import sys

import numpy as np
import pandas as pd

from iai.core.config import Config
from iai.core.http import HttpClient
from iai.core.universe import Universe
from iai.sources.edgar import SUBMISSIONS_URL, parse_items
from iai.sources.prices import BROWSER_UA, YAHOO_CHART

log = logging.getLogger("latency")

#: Minutes after the filing at which the position is marked. The first entry is
#: the assumed entry point: one minute is roughly the fastest a polling scraper
#: plus a manual or API order can realistically achieve, and it is deliberately
#: slower than the 50-200ms a colocated firm manages -- the whole point is to
#: ask what is left after they have acted.
HORIZONS = [1, 5, 15, 30, 60, 120]

#: Session boundaries in ET minutes-from-midnight.
PRE_OPEN, RTH_OPEN, RTH_CLOSE, POST_CLOSE = 240, 570, 960, 1200


def session_of(ts_et: pd.Timestamp) -> str:
    m = ts_et.hour * 60 + ts_et.minute
    if RTH_OPEN <= m < RTH_CLOSE:
        return "rth"
    if PRE_OPEN <= m < RTH_OPEN:
        return "premarket"
    if RTH_CLOSE <= m < POST_CLOSE:
        return "afterhours"
    return "closed"


def recent_filings(client, uni: Universe, days: int, forms: set[str]) -> pd.DataFrame:
    """Filings accepted in the last ``days``, with exact acceptance timestamps.

    ``acceptanceDateTime`` is the field that makes this study possible: it is
    when EDGAR took the document, to the second, which is the instant the
    information became publicly retrievable.
    """
    cut = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    rows = []
    for t in uni.tickers:
        cik = uni.cik(t)
        if not cik:
            continue
        blob = client.get(SUBMISSIONS_URL.format(cik=cik))
        if not blob:
            continue
        rec = blob.get("filings", {}).get("recent", {})
        f_list = rec.get("form", [])
        for i, form in enumerate(f_list):
            if form not in forms:
                continue
            raw = rec.get("acceptanceDateTime", [None] * len(f_list))[i]
            if not raw:
                continue
            ts = pd.Timestamp(raw)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            if ts < cut:
                continue
            rows.append({
                "ticker": t, "form": form, "accepted": ts, "cik": cik,
                "items": ",".join(parse_items(rec.get("items", [""] * len(f_list))[i] or "")),
                "accession": rec.get("accessionNumber", [""] * len(f_list))[i],
                "primary_doc": rec.get("primaryDocument", [""] * len(f_list))[i],
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    et = df["accepted"].dt.tz_convert("America/New_York")
    df["session"] = [session_of(x) for x in et]
    return df.sort_values("accepted").reset_index(drop=True)


def keep_form4_buys(client, filings: pd.DataFrame, workers: int = 8) -> pd.DataFrame:
    """Reduce Form 4 filings to those containing an open-market purchase.

    Form 4 is the strongest case for the latency thesis, because the filer is
    the *insider*, not the company: nobody issues a press release announcing
    that an officer bought stock, so there is no simultaneous announcement to
    collapse the window the way an 8-K's Exhibit 99.1 does.

    But most Form 4s are not purchases. Awards, tax-withholding sales and
    option exercises are compensation mechanics, and treating them as signal
    would bury the ~15% that are real conviction buys. The submissions API does
    not expose transaction codes, so the documents have to be read -- which is
    affordable here only because the window is short.
    """
    from iai.sources.insiders import parse_form4

    urls, meta = [], []
    for r in filings.to_dict("records"):
        doc = (r.get("primary_doc") or "").split("/")[-1]
        if not doc or not r.get("cik"):
            continue
        urls.append(
            f"https://www.sec.gov/Archives/edgar/data/{int(r['cik'])}/"
            f"{r['accession'].replace('-', '')}/{doc}"
        )
        meta.append(r)

    log.info("classifying %d Form 4 documents", len(urls))
    bodies = client.get_many(urls, parse="text", workers=workers, progress_every=250)

    kept = []
    for url, r in zip(urls, meta, strict=True):
        body = bodies.get(url)
        if not body:
            continue
        try:
            trades = parse_form4(body, r["accepted"], r["accession"])
        except Exception:  # noqa: BLE001 - one malformed filing must not stop the study
            continue
        buys = [t for t in trades if t.code == "P"]
        if not buys:
            continue
        kept.append({**r, "buy_value_usd": float(sum(t.value_usd or 0 for t in buys)),
                     "role": buys[0].role})
    out = pd.DataFrame(kept)
    log.info("%d of %d Form 4s contain an open-market purchase", len(out), len(urls))
    return out


def minute_bars(client, ticker: str, days: int) -> pd.DataFrame:
    """One-minute bars including pre- and post-market.

    Yahoo caps a single 1-minute request at roughly seven days, so the window is
    paged backwards a week at a time. Beyond about 30 days it returns nothing at
    any offset, which is the hard ceiling on how far back this study can look.
    """
    now = pd.Timestamp.now(tz="UTC")
    frames = []
    for wk in range(int(np.ceil(days / 7))):
        hi = now - pd.Timedelta(days=7 * wk)
        lo = hi - pd.Timedelta(days=7)
        blob = client.get(
            YAHOO_CHART.format(symbol=ticker),
            params={"period1": int(lo.timestamp()), "period2": int(hi.timestamp()),
                    "interval": "1m", "includePrePost": "true"},
            headers={"User-Agent": BROWSER_UA},
        )
        res = (blob or {}).get("chart", {}).get("result")
        if not res:
            continue
        r = res[0]
        ts = r.get("timestamp") or []
        if not ts:
            continue
        q = r["indicators"]["quote"][0]
        frames.append(pd.DataFrame({
            "t": pd.to_datetime(ts, unit="s", utc=True),
            "close": q.get("close"), "high": q.get("high"),
            "low": q.get("low"), "volume": q.get("volume"),
        }))
    if not frames:
        return pd.DataFrame(columns=["t", "close", "high", "low", "volume"])
    out = (pd.concat(frames, ignore_index=True)
             .dropna(subset=["close"])
             .drop_duplicates(subset="t")
             .sort_values("t")
             .reset_index(drop=True))
    out["volume"] = out["volume"].fillna(0.0)
    # A tz-aware Series returns an *object* array from .to_numpy(), which will
    # not compare against datetime64 and makes every searchsorted below raise.
    # Carry a naive-UTC twin for the searches; everything is UTC already, so no
    # information is lost and no conversion can go wrong later.
    out["t_utc"] = out["t"].dt.tz_convert("UTC").dt.tz_localize(None)
    return out


def measure(filing: dict, bars: pd.DataFrame) -> dict | None:
    """Price path around one filing, in event time.

    The decomposition is the point:

    ``missed``    entry price over the last pre-filing print -- the part of the
                  move that was already gone by the time a one-minute scraper
                  could act. Money someone else made.
    ``captured``  the horizon price over the entry price -- what is actually
                  left to trade.
    """
    if bars.empty:
        return None
    t = filing["accepted"]
    t_naive = np.datetime64(t.tz_convert("UTC").tz_localize(None))
    tv = bars["t_utc"].to_numpy()

    # Last print strictly before the filing: the pre-news reference.
    i_pre = int(np.searchsorted(tv, t_naive, "left")) - 1
    if i_pre < 0:
        return None
    p_pre = float(bars["close"].iloc[i_pre])
    if not np.isfinite(p_pre) or p_pre <= 0:
        return None

    # Entry: the first bar that closes at least one minute after acceptance.
    entry_at = t_naive + np.timedelta64(1, "m")
    i_ent = int(np.searchsorted(tv, entry_at, "left"))
    if i_ent >= len(bars):
        return None
    p_ent = float(bars["close"].iloc[i_ent])
    v_ent = float(bars["volume"].iloc[i_ent])
    if not np.isfinite(p_ent) or p_ent <= 0:
        return None

    gap_min = (bars["t_utc"].iloc[i_ent] - pd.Timestamp(t_naive)).total_seconds() / 60.0

    out = {
        **{k: filing[k] for k in ("ticker", "form", "items", "session", "accepted")},
        "p_pre": p_pre, "p_entry": p_ent,
        "entry_volume": v_ent,
        "entry_lag_min": gap_min,
        "fillable": v_ent > 0,
        # The move that happened before a one-minute reaction could act.
        "missed": p_ent / p_pre - 1.0,
    }
    for h in HORIZONS:
        at = t_naive + np.timedelta64(h, "m")
        j = int(np.searchsorted(tv, at, "left"))
        j = min(j, len(bars) - 1)
        pj = float(bars["close"].iloc[j])
        out[f"captured_{h}m"] = pj / p_ent - 1.0 if np.isfinite(pj) and pj > 0 else np.nan
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=28,
                    help="lookback; 1-minute data is unavailable past ~30 days")
    ap.add_argument("--forms", default="8-K")
    ap.add_argument("--max-names", type=int, default=400,
                    help="cap on distinct tickers, most-filings-first")
    ap.add_argument("--yahoo-rate", type=float, default=2.0)
    ap.add_argument("--universe", default="/root/.iai/wide2015/universe.txt")
    ap.add_argument("--out", default="/root/.iai/store/latency_study.parquet")
    ap.add_argument("--user-agent", default="")
    ap.add_argument("--buys-only", action="store_true",
                    help="Form 4 only: read each document and keep open-market "
                         "purchases (code P). Awards and tax-withholding sales "
                         "are compensation mechanics, not signal.")
    ap.add_argument("--rth-only", action="store_true",
                    help="keep only filings accepted during regular hours -- the "
                         "subset where a fill at T+1min is actually possible")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stderr)
    if "@" not in args.user_agent:
        print("ERROR: --user-agent must be a real contact", file=sys.stderr)
        return 2

    cfg = Config.moonshot()
    cfg.data.user_agent = args.user_agent
    cfg.ensure_dirs()
    sec = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=9.0, ttl_hours=720.0)
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=args.yahoo_rate, ttl_hours=6.0)

    full = Universe.from_sec(sec)
    tickers = [x.strip().upper() for x in open(args.universe) if x.strip()]
    uni = full.subset(tickers)

    forms = {f.strip() for f in args.forms.split(",") if f.strip()}
    fil = recent_filings(sec, uni, args.days, forms)
    if fil.empty:
        print("no filings in window")
        return 1
    log.info("%d filings across %d names", len(fil), fil["ticker"].nunique())

    if args.rth_only:
        fil = fil[fil["session"] == "rth"].reset_index(drop=True)
        log.info("regular hours only: %d filings", len(fil))
    if args.buys_only:
        fil = keep_form4_buys(sec, fil)
        if fil.empty:
            print("no open-market purchases in window")
            return 1

    # Minute data is the expensive half (4 requests per ticker), so spend it on
    # the names with the most filings rather than an arbitrary slice.
    order = fil["ticker"].value_counts().index.tolist()[: args.max_names]
    fil = fil[fil["ticker"].isin(set(order))].reset_index(drop=True)
    log.info("studying %d filings across %d names", len(fil), len(order))

    rows = []
    for n, tkr in enumerate(order, 1):
        bars = minute_bars(yah, tkr, args.days)
        if bars.empty:
            continue
        for f in fil[fil["ticker"] == tkr].to_dict("records"):
            m = measure(f, bars)
            if m:
                rows.append(m)
        if n % 25 == 0:
            log.info("%d/%d names, %d measured", n, len(order), len(rows))

    df = pd.DataFrame(rows)
    if df.empty:
        print("nothing measurable")
        return 1
    df.to_parquet(args.out)
    report(df)
    print(f"\nwrote {args.out}")
    return 0


def report(df: pd.DataFrame) -> None:
    pd.set_option("display.width", 200)
    print("=" * 96)
    print(f"LATENCY STUDY  {len(df):,} filings, {df['ticker'].nunique():,} names")
    print("=" * 96)

    # Can you trade it at all? This is prior to any question of whether it is
    # profitable, and it is where most of the thesis is decided: a filing whose
    # next minute has no print is not an opportunity, it is a spectator sport.
    print("\nCAN YOU EVEN FILL AT T+1min?")
    print("-" * 96)
    g = df.groupby("session")
    fill = pd.DataFrame({
        "filings": g.size().astype(int),
        "share": (g.size() / len(df)),
        "fillable": g["fillable"].mean(),
    }).sort_values("filings", ascending=False)
    print(fill.to_string(formatters={
        "filings": lambda v: f"{v:,}",
        "share": lambda v: f"{v:6.1%}",
        "fillable": lambda v: f"{v:8.1%}",
    }))
    print(f"\noverall fillable: {df['fillable'].mean():.1%} of {len(df):,} filings")

    ok = df[df["fillable"]]
    if ok.empty:
        print("\nno fillable filings -- nothing to trade")
        return

    print(f"\nHOW MUCH MOVED BEFORE YOU COULD ACT  (fillable only, n={len(ok):,})")
    print("-" * 96)
    print(f"  median {ok['missed'].median():+.4f}   mean {ok['missed'].mean():+.4f}   "
          f"|move|>=2%: {(ok['missed'].abs() >= 0.02).mean():.1%}")

    def _table(sub: pd.DataFrame, label: str, min_n: int = 10) -> None:
        print(f"\nRETURN AFTER ENTERING AT T+1min -- {label} (n={len(sub):,})")
        print(f"{'horizon':>8} {'n':>6} {'median':>10} {'mean':>10} {'win%':>7} {'t':>7}")
        for h in HORIZONS[1:]:
            r = sub[f"captured_{h}m"].dropna()
            if len(r) < min_n:
                print(f"{h:>7}m {len(r):>6,}   too few to report")
                continue
            sd = r.std(ddof=1)
            t = r.mean() / (sd / np.sqrt(len(r))) if sd > 0 else np.nan
            print(f"{h:>7}m {len(r):>6,} {r.median():>+10.4f} {r.mean():>+10.4f} "
                  f"{(r > 0).mean():>6.1%} {t:>+7.2f}")

    _table(ok, "all fillable")
    rth = ok[ok["session"] == "rth"]
    if len(rth) >= 10:
        _table(rth, "regular hours only -- the genuinely tradable subset")

    big = ok[ok["missed"].abs() >= 0.02]
    if len(big) >= 10:
        _table(big, "already moved >=2% before entry -- was anything left?")

    print("\nNOTE: minute bars carry no spread, so every figure above is an upper")
    print("bound. Real entry pays the offer, which outside regular hours on a")
    print("small cap is routinely 100-300 bps rather than the ~15 bps modelled")
    print("for liquid RTH trading.")


if __name__ == "__main__":
    raise SystemExit(main())
