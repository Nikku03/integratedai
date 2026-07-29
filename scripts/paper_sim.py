"""Trade the filing feed with $80, one month, minute bars. No peeking.

What this simulates
-------------------
An account with **$80**, taking at most **two positions at once** ($40 each,
compounded as the balance changes), reacting to SEC filings within one minute
of EDGAR accepting them, over the last month of real minute bars.

Every rule below is evaluated in chronological order using only information
that existed at that instant. There is no ranking over the full month, no
"best 20 filings of the period", and no exit chosen with knowledge of the path.
The event loop walks forward in time and cannot see past the current bar.

Where the honesty is load-bearing
---------------------------------
**The fill.** Minute bars carry no quotes, so the spread cannot be measured.
Entry is taken at the entry minute's **high** and exits at the exit minute's
**low** -- the worst prices that actually printed in those minutes. Real fills
sit between that and the close-to-close figure. At a $40 order size market
impact is genuinely zero, so the spread is the entire cost, and assuming the
best price in the minute would be assuming away the only cost that matters.

**The press-release column.** Newswire timestamps are not freely available.
What *is* verifiable is whether the release was filed as an exhibit to the 8-K
(EX-99.x), in which case the release and the filing are one act and there is no
gap to trade. That is reported per filing rather than guessed at.

**The traps.** Filters are prior-based, not fitted, and use only trailing data:
a price floor, a liquidity floor scaled to the order, a cap on how far the name
has already run, and a cap on how much of the move is already gone by entry.
Nothing here was tuned against the outcome.

Usage
-----
    python scripts/paper_sim.py --days 30 --capital 80 --slots 2 \\
        --user-agent "you you@example.com"
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from iai.core.config import Config
from iai.core.http import HttpClient
from iai.core.universe import Universe
from iai.sources.edgar import ITEM_WEIGHTS, SUBMISSIONS_URL, parse_items
from iai.sources.prices import BROWSER_UA, YAHOO_CHART

log = logging.getLogger("papersim")

# ---------------------------------------------------------------- trap filters
#: Sub-dollar names are where manipulation concentrates and where a penny of
#: spread is a whole percent.
MIN_PRICE = 1.00
#: The entry minute must trade at least this multiple of the order value. At
#: $40 this is a low bar by design -- it screens bars with essentially no
#: liquidity rather than pretending to model depth.
MIN_BAR_DOLLARS_X = 20.0
#: Trailing dollar volume over the prior session, below which the name is too
#: thin to exit in a hurry.
MIN_SESSION_DOLLARS = 250_000.0
#: If the name has already run this far over the prior five sessions, the
#: filing is arriving into something that is already moving -- the classic
#: pump signature, and the worst place to be the last buyer.
MAX_PRIOR_RUNUP = 0.50
#: If this much of the move is already gone by the time we can act, the
#: information was priced before we existed. Chasing it is the trap.
MAX_ALREADY_MOVED = 0.10


def snapped_now() -> pd.Timestamp:
    """Window edge on a day boundary, so repeated runs share cache keys."""
    return pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)


def recent_filings(client, uni: Universe, days: int, forms: set[str]) -> pd.DataFrame:
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
        fl = rec.get("form", [])
        for i, form in enumerate(fl):
            if form not in forms:
                continue
            raw = rec.get("acceptanceDateTime", [None] * len(fl))[i]
            if not raw:
                continue
            ts = pd.Timestamp(raw)
            ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
            if ts < cut:
                continue
            items = parse_items(rec.get("items", [""] * len(fl))[i] or "")
            rows.append({
                "ticker": t, "cik": cik, "form": form, "filed_utc": ts,
                "items": ",".join(items),
                # A fixed prior, not a fitted score: it decides which filing to
                # take when two arrive and only one slot is free. Using
                # anything fitted here would be peeking.
                "priority": max((ITEM_WEIGHTS.get(x, 0.8) for x in items), default=0.8),
                "accession": rec.get("accessionNumber", [""] * len(fl))[i],
            })
    df = pd.DataFrame(rows)
    return df.sort_values("filed_utc").reset_index(drop=True) if not df.empty else df


def pr_attached(client, cik: str, accession: str) -> bool | None:
    """Was the press release filed as an exhibit to this document?

    If EX-99 is in the submission, the release and the filing are the same act
    and there is no latency window between them -- which is the single most
    important thing to know about the whole thesis, and it is checkable.
    """
    acc = accession.replace("-", "")
    if not acc:
        return None
    j = client.get(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/index.json")
    if not j:
        return None
    names = [i.get("name", "").lower() for i in j.get("directory", {}).get("item", [])]
    return any("ex99" in n or "ex-99" in n for n in names)


def minute_bars(client, ticker: str, days: int, cache_dir: Path) -> pd.DataFrame:
    """One-minute bars with pre/post, cached to parquet so re-runs are free."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{ticker}.parquet"
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:  # noqa: BLE001 - corrupt cache, refetch
            p.unlink(missing_ok=True)

    now = snapped_now()
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
            "open": q.get("open"), "high": q.get("high"),
            "low": q.get("low"), "close": q.get("close"), "volume": q.get("volume"),
        }))
    if not frames:
        out = pd.DataFrame(columns=["t", "open", "high", "low", "close", "volume", "t_utc"])
        out.to_parquet(p)
        return out
    out = (pd.concat(frames, ignore_index=True)
             .dropna(subset=["close"])
             .drop_duplicates(subset="t").sort_values("t").reset_index(drop=True))
    out["volume"] = out["volume"].fillna(0.0)
    out["t_utc"] = out["t"].dt.tz_convert("UTC").dt.tz_localize(None)
    out.to_parquet(p)
    return out


def screen(bars: pd.DataFrame, i_ent: int, order_usd: float) -> tuple[bool, str]:
    """Trap filters, evaluated with bars strictly up to and including entry.

    ``i_ent`` is the entry bar. Nothing after it is read, which is what makes
    this a filter rather than a hindsight rule.
    """
    px = float(bars["high"].iloc[i_ent])          # what we would pay
    if not np.isfinite(px) or px < MIN_PRICE:
        return False, "sub-$1"

    vol = float(bars["volume"].iloc[i_ent])
    if vol * px < MIN_BAR_DOLLARS_X * order_usd:
        return False, "entry bar too thin"

    # Trailing liquidity: the prior 390 minutes is one session of trading.
    lo = max(0, i_ent - 390)
    prior = bars.iloc[lo:i_ent]
    if prior.empty:
        return False, "no history"
    sess_dollars = float((prior["close"] * prior["volume"]).sum())
    if sess_dollars < MIN_SESSION_DOLLARS:
        return False, "illiquid name"

    # Pump signature: already run hard before the news arrived.
    ref = max(0, i_ent - 5 * 390)
    base = float(bars["close"].iloc[ref])
    if np.isfinite(base) and base > 0 and (px / base - 1.0) > MAX_PRIOR_RUNUP:
        return False, "already ran >50%"

    return True, ""


def simulate(filings: pd.DataFrame, bars_by: dict, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Walk forward through the filings, holding at most ``slots`` positions.

    The loop is strictly chronological. A filing is considered only when it
    arrives; a slot is freed only when its exit bar is reached. Nothing is
    ranked across the month, because ranking across the month is exactly the
    peek this is meant to avoid.
    """
    cash = cfg["capital"]
    slots = cfg["slots"]
    target, stop, max_min = cfg["target"], cfg["stop"], cfg["max_hold_min"]

    open_pos: list[dict] = []
    trades, skipped = [], []
    equity_marks = []

    for f in filings.to_dict("records"):
        t = f["filed_utc"]

        # Close any position whose exit has already occurred by now.
        still = []
        for p in open_pos:
            if p["exit_t"] is not None and p["exit_t"] <= t:
                cash += p["proceeds"]
                trades.append(p["record"] | {"balance_after": cash})
                equity_marks.append({"t": p["exit_t"], "balance": cash})
            else:
                still.append(p)
        open_pos = still

        if len(open_pos) >= slots:
            skipped.append({**f, "reason": "no free slot"})
            continue

        bars = bars_by.get(f["ticker"])
        if bars is None or bars.empty:
            skipped.append({**f, "reason": "no minute data"})
            continue

        tv = bars["t_utc"].to_numpy()
        t_naive = np.datetime64(t.tz_convert("UTC").tz_localize(None))
        i_pre = int(np.searchsorted(tv, t_naive, "left")) - 1
        i_ent = int(np.searchsorted(tv, t_naive + np.timedelta64(1, "m"), "left"))
        if i_pre < 0 or i_ent >= len(bars):
            skipped.append({**f, "reason": "outside bar coverage"})
            continue
        if float(bars["volume"].iloc[i_ent]) <= 0:
            skipped.append({**f, "reason": "no trade at T+1min"})
            continue

        ok, why = screen(bars, i_ent, cash / slots)
        if not ok:
            skipped.append({**f, "reason": why})
            continue

        p_pre = float(bars["close"].iloc[i_pre])
        entry = float(bars["high"].iloc[i_ent])     # pay the offer
        already = entry / p_pre - 1.0 if p_pre > 0 else np.nan
        if np.isfinite(already) and already > MAX_ALREADY_MOVED:
            skipped.append({**f, "reason": f"already moved {already:+.1%}"})
            continue

        size = cash / slots
        if size < 1.0:
            skipped.append({**f, "reason": "insufficient capital"})
            continue
        cash -= size
        shares = size / entry
        up, dn = entry * (1 + target), entry * (1 - stop)

        # Walk forward bar by bar. Exits are decided by the bars in order; an
        # ambiguous bar (both barriers touched) resolves against us.
        exit_i, exit_px, reason = None, None, "open"
        for j in range(i_ent + 1, min(i_ent + 1 + max_min, len(bars))):
            hi, lo = float(bars["high"].iloc[j]), float(bars["low"].iloc[j])
            if not (np.isfinite(hi) and np.isfinite(lo)):
                continue
            if hi >= up and lo <= dn:
                exit_i, exit_px, reason = j, dn, "stop (ambiguous bar)"
                break
            if lo <= dn:
                exit_i, exit_px, reason = j, dn, "stop"
                break
            if hi >= up:
                exit_i, exit_px, reason = j, up, "target"
                break
        if exit_i is None:
            exit_i = min(i_ent + max_min, len(bars) - 1)
            exit_px = float(bars["low"].iloc[exit_i])   # sell into the bid
            reason = "time"

        exit_t = bars["t"].iloc[exit_i]
        proceeds = shares * exit_px
        held = (exit_t - bars["t"].iloc[i_ent]).total_seconds() / 60.0
        open_pos.append({
            "exit_t": exit_t, "proceeds": proceeds,
            "record": {
                "ticker": f["ticker"], "form": f["form"], "items": f["items"],
                "filed_utc": t, "pr_attached": f.get("pr_attached"),
                "entry_t": bars["t"].iloc[i_ent], "entry_px": entry,
                "pre_px": p_pre, "already_moved": already,
                "exit_t": exit_t, "exit_px": exit_px, "exit_reason": reason,
                "held_min": held, "size_usd": size,
                "ret": exit_px / entry - 1.0,
                "pnl": proceeds - size,
            },
        })

    for p in open_pos:                    # settle anything still open
        cash += p["proceeds"]
        trades.append(p["record"] | {"balance_after": cash})

    return pd.DataFrame(trades), pd.DataFrame(skipped)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--target", type=float, default=0.06)
    ap.add_argument("--stop", type=float, default=0.04)
    ap.add_argument("--max-hold-min", type=int, default=1950,
                    help="minutes; 1950 = five sessions. Not a 24h cap -- exits "
                         "are barrier-driven and this is only a backstop.")
    ap.add_argument("--forms", default="8-K")
    ap.add_argument("--max-names", type=int, default=400)
    ap.add_argument("--yahoo-rate", type=float, default=2.0)
    ap.add_argument("--universe", default="/root/.iai/wide2015/universe.txt")
    ap.add_argument("--bar-cache", default="/root/.iai/minutecache")
    ap.add_argument("--out", default="/root/.iai/store/paper_sim_trades.parquet")
    ap.add_argument("--user-agent", default="")
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
    uni = full.subset([x.strip().upper() for x in open(args.universe) if x.strip()])
    forms = {f.strip() for f in args.forms.split(",") if f.strip()}

    fil = recent_filings(sec, uni, args.days, forms)
    if fil.empty:
        print("no filings")
        return 1
    log.info("%d filings across %d names", len(fil), fil["ticker"].nunique())

    keep = set(fil["ticker"].value_counts().index[: args.max_names])
    fil = fil[fil["ticker"].isin(keep)].reset_index(drop=True)

    log.info("checking which filings carry the press release as an exhibit")
    fil["pr_attached"] = [pr_attached(sec, r["cik"], r["accession"])
                          for r in fil.to_dict("records")]

    cache = Path(args.bar_cache)
    bars_by = {}
    for n, tkr in enumerate(sorted(keep), 1):
        b = minute_bars(yah, tkr, args.days, cache)
        if not b.empty:
            bars_by[tkr] = b
        if n % 50 == 0:
            log.info("bars %d/%d", n, len(keep))

    trades, skipped = simulate(fil, bars_by, {
        "capital": args.capital, "slots": args.slots,
        "target": args.target, "stop": args.stop, "max_hold_min": args.max_hold_min,
    })
    if trades.empty:
        print("no trades taken")
        if not skipped.empty:
            print(skipped["reason"].value_counts().to_string())
        return 1

    trades = trades.sort_values("entry_t").reset_index(drop=True)
    trades.to_parquet(args.out)
    report(trades, skipped, fil, args)
    print(f"\nwrote {args.out}")
    return 0


def report(tr: pd.DataFrame, sk: pd.DataFrame, fil: pd.DataFrame, args) -> None:
    pd.set_option("display.width", 250)
    et = lambda s: pd.to_datetime(s).dt.tz_convert("America/New_York")  # noqa: E731

    print("=" * 130)
    print(f"PAPER SIM  ${args.capital:.0f} start, {args.slots} slots, "
          f"+{args.target:.0%}/-{args.stop:.0%}, last {args.days} days")
    print("=" * 130)

    t = tr.copy()
    t["filed_ET"] = et(t["filed_utc"]).dt.strftime("%m-%d %H:%M:%S")
    t["entry_ET"] = et(t["entry_t"]).dt.strftime("%m-%d %H:%M")
    t["exit_ET"] = et(t["exit_t"]).dt.strftime("%m-%d %H:%M")
    t["PR"] = t["pr_attached"].map({True: "attached", False: "no EX-99"}).fillna("?")
    cols = ["ticker", "items", "filed_ET", "PR", "entry_ET", "entry_px",
            "already_moved", "exit_ET", "exit_px", "exit_reason", "held_min",
            "ret", "pnl", "balance_after"]
    print("\nTRADES")
    print(t[cols].to_string(index=False, formatters={
        "entry_px": lambda v: f"{v:8.3f}", "exit_px": lambda v: f"{v:8.3f}",
        "already_moved": lambda v: f"{v:+.2%}", "ret": lambda v: f"{v:+.2%}",
        "pnl": lambda v: f"{v:+.2f}", "balance_after": lambda v: f"{v:7.2f}",
        "held_min": lambda v: f"{v:7.0f}",
    }))

    n = len(t)
    per_month = n / max(args.days, 1) * 30
    final = float(t["balance_after"].iloc[-1])
    print("\nSUMMARY")
    print(f"  trades              {n}   ({per_month:.1f}/month vs 20 targeted)")
    print(f"  win rate            {(t['ret'] > 0).mean():.1%}")
    print(f"  mean return/trade   {t['ret'].mean():+.2%}   median {t['ret'].median():+.2%}")
    print(f"  median hold         {t['held_min'].median():.0f} min "
          f"({t['held_min'].median()/60:.1f}h)")
    print(f"  start -> end        ${args.capital:.2f} -> ${final:.2f}  "
          f"({final/args.capital - 1:+.1%})")
    print("  exits               " + ", ".join(
        f"{k} {v}" for k, v in t["exit_reason"].value_counts().items()))

    print(f"\n  press release attached to the filing: "
          f"{(t['pr_attached'] == True).mean():.0%} of trades")  # noqa: E712
    print("  (where it is attached, the filing IS the announcement -- there was")
    print("   no gap between paperwork and news to trade)")

    if not sk.empty:
        print(f"\nFILINGS SKIPPED ({len(sk):,} of {len(fil):,})")
        print(sk["reason"].value_counts().to_string())

    print("\nFILL ASSUMPTION: bought at the entry minute's HIGH, sold at the exit")
    print("minute's LOW -- the worst prices that actually printed. At $40 there is")
    print("no market impact, so the spread is the whole cost, and taking the")
    print("midpoint would be assuming away the only thing that matters here.")


if __name__ == "__main__":
    raise SystemExit(main())
