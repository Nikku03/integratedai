"""Which 20% moves went up, which went down, why -- and can you tell in advance?

The move census only ever recorded the *largest up move* per name, so the 222
"movers" were all winners by construction and the losers were invisible. This
recomputes both tails, attributes a cause to each, and then asks the question that
matters: standing before the move, with only what was knowable then, can the two
be told apart?

Design of the honest test
-------------------------
Any rule fitted on a month and scored on the same month will look good. So the
month is cut in half by calendar date: **the rule is built on 1-14 July and
scored on 15-29 July**, with nothing from the second half touching the first.
That is a real out-of-sample test, small but genuine, and it is the only kind
available inside a single month of data.

Features are restricted to what exists before the move: the filing's form and item
codes, the stock's own pre-move volatility, liquidity, price and cap band. No text
classification, because only 83 filings were ever read and using them would leak
the second half.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from moonshot_census import MIN_MEDIAN_DOLLARS, MIN_PRICE, daily_bars  # noqa: E402

WINDOW = (pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-29"))
SPLIT_DATE = pd.Timestamp("2026-07-15")
THRESHOLD = 0.20

#: 8-K item codes, grouped by what they say about direction. These groupings come
#: from what the codes *mean*, not from this month's returns.
BEARISH_ITEMS = {"3.01", "3.02", "4.02", "1.03", "2.06", "2.05", "2.04"}
BULLISH_ITEMS = {"2.01", "1.01", "8.01"}
SCHEDULED_ITEMS = {"2.02", "7.01"}


def both_tails(b: pd.DataFrame) -> dict | None:
    """Largest up move and largest down move, with dates, over the window."""
    if len(b) < 6:
        return None
    b = b.sort_values("date").reset_index(drop=True)
    c = b["close"].to_numpy(dtype=float)
    dollars = (b["close"] * b["volume"].fillna(0)).to_numpy(dtype=float)

    r1 = c[1:] / c[:-1] - 1.0
    if not np.isfinite(r1).any():
        return None
    iu, idn = int(np.nanargmax(r1)), int(np.nanargmin(r1))

    # Forward 5-session move from each close, both directions.
    f5 = np.full(len(c), np.nan)
    for i in range(len(c)):
        j = min(i + 5, len(c) - 1)
        if j > i:
            f5[i] = c[j] / c[i] - 1.0
    ju = int(np.nanargmax(f5)) if np.isfinite(f5).any() else 0
    jd = int(np.nanargmin(f5)) if np.isfinite(f5).any() else 0

    return {"ticker": b["ticker"].iloc[0], "last_close": float(c[-1]),
            "min_close": float(np.nanmin(c)),
            "median_dollars": float(np.nanmedian(dollars)),
            "up_1d": float(r1[iu]), "up_1d_date": b["date"].iloc[iu + 1],
            "dn_1d": float(r1[idn]), "dn_1d_date": b["date"].iloc[idn + 1],
            "up_5d": float(f5[ju]), "up_5d_date": b["date"].iloc[ju],
            "dn_5d": float(f5[jd]), "dn_5d_date": b["date"].iloc[jd]}


def build_events(root: Path, client, days: int) -> pd.DataFrame:
    """One row per (name, direction) that cleared the threshold in the window."""
    pool = pd.read_parquet(root / "candidate_pool.parquet")
    tickers = sorted(pool["ticker"].dropna().unique().tolist())

    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(daily_bars, client, t, days): t for t in tickers}
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 1000 == 0:
                print(f"  {k}/{len(tickers)}", flush=True)
            try:
                b = fu.result()
            except Exception:                      # noqa: BLE001
                continue
            if b.empty:
                continue
            s = both_tails(b)
            if s:
                rows.append(s)
    d = pd.DataFrame(rows)
    d = d[(d.min_close >= MIN_PRICE) & (d.median_dollars >= MIN_MEDIAN_DOLLARS)]

    out = []
    for r in d.to_dict("records"):
        for sign, one, five, dt1, dt5 in (
                ("up", r["up_1d"], r["up_5d"], r["up_1d_date"], r["up_5d_date"]),
                ("down", r["dn_1d"], r["dn_5d"], r["dn_1d_date"], r["dn_5d_date"])):
            hit1 = (one >= THRESHOLD) if sign == "up" else (one <= -THRESHOLD)
            hit5 = (five >= THRESHOLD) if sign == "up" else (five <= -THRESHOLD)
            if not (hit1 or hit5):
                continue
            date = pd.Timestamp(dt1 if hit1 else dt5)
            if not (WINDOW[0] <= date <= WINDOW[1]):
                continue
            out.append({"ticker": r["ticker"], "direction": sign,
                        "move": one if hit1 else five, "move_date": date,
                        "last_close": r["last_close"],
                        "median_dollars": r["median_dollars"]})
    return pd.DataFrame(out)


def attach_cause(ev: pd.DataFrame, root: Path) -> pd.DataFrame:
    """The filings in the seven days up to each move, and what they were."""
    fil = pd.read_parquet(root / "recent_filings.parquet")
    fil["accepted"] = pd.to_datetime(fil["accepted"], utc=True, format="mixed")
    fil["d"] = (fil["accepted"].dt.tz_convert("America/New_York")
                .dt.normalize().dt.tz_localize(None))
    covered = set(fil["ticker"].unique())

    rows = []
    for r in ev.to_dict("records"):
        lo, hi = r["move_date"] - pd.Timedelta(days=7), r["move_date"]
        if r["ticker"] not in covered:
            rows.append({**r, "n_filings": -1, "forms": "", "codes": set()})
            continue
        w = fil[(fil.ticker == r["ticker"]) & (fil.d >= lo) & (fil.d <= hi)]
        codes = {c.strip() for s in w.get("items", pd.Series(dtype=str)).fillna("")
                 for c in str(s).split(",") if c.strip()}
        rows.append({**r, "n_filings": len(w),
                     "forms": ",".join(sorted(set(w["form"].astype(str)))),
                     "codes": codes})
    d = pd.DataFrame(rows)
    d["has_8k"] = d["forms"].str.contains("8-K", na=False)
    d["has_offering"] = d["forms"].str.contains("424B|S-1|S-3|F-1|F-3", na=False,
                                                regex=True)
    d["has_merger"] = d["forms"].str.contains("425|SC TO|DEFM14A", na=False,
                                              regex=True)
    d["has_13d"] = d["forms"].str.contains("SCHEDULE 13D|SC 13D", na=False,
                                           regex=True)
    d["has_insider"] = d["forms"].apply(
        lambda s: any(f.strip() in ("4", "144", "3") for f in str(s).split(",")))
    d["bearish_item"] = d["codes"].apply(lambda c: bool(c & BEARISH_ITEMS))
    d["bullish_item"] = d["codes"].apply(lambda c: bool(c & BULLISH_ITEMS))
    d["scheduled_item"] = d["codes"].apply(lambda c: bool(c & SCHEDULED_ITEMS))
    d["no_filing"] = d["n_filings"] == 0
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--days", type=int, default=40)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)

    cached = root / "direction_events.parquet"
    if args.rebuild or not cached.exists():
        from iai.core.config import Config
        from iai.core.http import HttpClient
        cfg = Config.load()
        yah = HttpClient(cfg.data.cache_dir, args.user_agent,
                         rate_per_sec=12.0, ttl_hours=12.0)
        ev = build_events(root, yah, args.days)
        ev = attach_cause(ev, root)
        ev.drop(columns=["codes"]).to_parquet(cached)
    else:
        ev = pd.read_parquet(cached)

    print(f"\n{len(ev)} moves of >= {THRESHOLD:.0%} in 1-29 July, tradable universe")
    print(ev.direction.value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
