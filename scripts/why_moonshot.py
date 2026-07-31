"""Why do some filings moonshot and others crater? Fundamentals as the explanation.

Explanatory, not a strategy. The dataset is 1,540 clinical readouts over twelve
months whose outcomes span +152% to −59% — the largest clean event set this
project has, and the dispersion is what makes it worth explaining.

The hypothesis
--------------
The catalyst is the same kind of thing in every case: a company said something
about a trial. What differs is the **balance sheet the news lands on**. A company
with three months of cash must sell equity into good news, so the market front-
runs the dilution and the spike dies. A company with three years of runway can
bank the news. If that is right, financial position should separate the tails
even though the event type does not.

Outcome is measured two ways, deliberately
------------------------------------------
``max_up`` / ``max_dn`` are the highest and lowest points over the 25 sessions
after entry — the move that was *available*, independent of any exit rule.
``ret`` is what the pre-registered trailing exit actually captured. Explaining the
first is a question about the world; explaining the second confounds it with a
rule already shown not to work.

Everything is measured from the open of the session after acceptance, and every
fundamental is from filings that predate it.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

HOLD = 25


def daily(client, ticker: str, lo, hi) -> pd.DataFrame:
    from iai.sources.prices import BROWSER_UA, YAHOO_CHART
    blob = client.get(
        YAHOO_CHART.format(symbol=ticker),
        params={"period1": int(lo.timestamp()), "period2": int(hi.timestamp()),
                "interval": "1d", "includePrePost": "false"},
        headers={"User-Agent": BROWSER_UA})
    res = (blob or {}).get("chart", {}).get("result")
    if not res:
        return pd.DataFrame()
    r = res[0]
    ts = r.get("timestamp") or []
    if not ts:
        return pd.DataFrame()
    q = r["indicators"]["quote"][0]
    return (pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s", utc=True).tz_convert(
            "America/New_York").normalize().tz_localize(None),
        "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
        "close": q.get("close"), "volume": q.get("volume")})
        .dropna(subset=["close"]).sort_values("date").reset_index(drop=True))


def decile_table(d: pd.DataFrame, col: str, q: int = 5) -> pd.DataFrame | None:
    s = d[d[col].replace([np.inf, -np.inf], np.nan).notna()].copy()
    if len(s) < 100:
        return None
    try:
        s["b"] = pd.qcut(s[col], q, duplicates="drop")
    except ValueError:
        return None
    g = s.groupby("b", observed=True).agg(
        n=("max_up", "size"),
        med_up=("max_up", "median"), med_dn=("max_dn", "median"),
        up50=("max_up", lambda x: (x >= .50).mean()),
        dn30=("max_dn", lambda x: (x <= -.30).mean()),
        gap=("gap", "median"))
    for c in ("med_up", "med_dn", "gap"):
        g[c] = (g[c] * 100).round(1)
    for c in ("up50", "dn30"):
        g[c] = (g[c] * 100).round(1)
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=12.0,
                     ttl_hours=168.0)

    sig = pd.read_parquet(root / "oos_clinical_signals.parquet")
    sig["et"] = pd.to_datetime(sig["et"], utc=True).dt.tz_convert("America/New_York")
    lo = pd.Timestamp("2025-05-01", tz="UTC")
    hi = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
    names = sorted(sig.ticker.unique())
    bars = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(daily, yah, t, lo, hi): t for t in names}
        for fu in as_completed(futs):
            try:
                b = fu.result()
            except Exception:                                  # noqa: BLE001
                continue
            if len(b) > 30:
                bars[futs[fu]] = b

    rows = []
    for r in sig.itertuples():
        b = bars.get(r.ticker)
        if b is None:
            continue
        d0 = pd.Timestamp(r.et).normalize().tz_localize(None)
        nxt = b[b.date > d0]
        prev = b[b.date <= d0]
        if len(nxt) < 3 or prev.empty:
            continue
        i = nxt.index[0]
        e = float(b["open"].iloc[i])
        p_prev = float(prev["close"].iloc[-1])
        if not np.isfinite(e) or e < 1.0 or p_prev <= 0:
            continue
        pr = b.iloc[max(0, i - 20):i]
        adv = float((pr.close * pr.volume.fillna(0)).median()) if len(pr) else 0.0
        if adv < 250_000:
            continue
        j = min(i + HOLD, len(b) - 1)
        h = b["high"].to_numpy()[i:j + 1]
        l = b["low"].to_numpy()[i:j + 1]
        if len(h) < 3:
            continue
        mu, md = float(np.nanmax(h) / e - 1), float(np.nanmin(l) / e - 1)
        if abs(mu) > 5 or abs(md) > 1:
            continue                                          # split artifact
        # prior 60-session momentum, knowable at entry
        pm = b.iloc[max(0, i - 60):i]
        mom = (float(pm.close.iloc[-1]) / float(pm.close.iloc[0]) - 1
               if len(pm) > 5 else np.nan)
        rows.append({"ticker": r.ticker, "et": r.et, "verdict": r.verdict,
                     "entry": e, "gap": e / p_prev - 1.0, "adv": adv,
                     "max_up": mu, "max_dn": md, "prior_mom": mom})

    d = pd.DataFrame(rows)
    f = pd.read_parquet(root / "fundamentals_full.parquet")
    d = d.merge(f.drop(columns=["entity"], errors="ignore"), on="ticker", how="left")
    d["log_cap"] = np.log10(d["market_cap"].clip(lower=1e6))
    d["log_price"] = np.log10(d["entry"].clip(lower=1))
    d["log_adv"] = np.log10(d["adv"].clip(lower=1))
    d.to_parquet(root / "why_moonshot.parquet")

    print(f"{len(d):,} clinical readouts with prices and fundamentals, "
          f"{d.ticker.nunique()} names\n")
    print(f"outcome over {HOLD} sessions from the next open:")
    print(f"  max up  : median {d.max_up.median() * 100:+.1f}%   "
          f"p90 {d.max_up.quantile(.90) * 100:+.0f}%   max {d.max_up.max() * 100:+.0f}%")
    print(f"  max down: median {d.max_dn.median() * 100:+.1f}%   "
          f"p10 {d.max_dn.quantile(.10) * 100:+.0f}%   min {d.max_dn.min() * 100:+.0f}%")
    print(f"  reached +50%: {(d.max_up >= .50).mean() * 100:.1f}%   "
          f"reached -30%: {(d.max_dn <= -.30).mean() * 100:.1f}%")

    print("\n\nUNIVARIATE: each fundamental in quintiles, low to high")
    for col, label in (("runway_years", "CASH RUNWAY (years)"),
                       ("cash_per_cap", "CASH / MARKET CAP"),
                       ("log_cap", "MARKET CAP (log10)"),
                       ("log_price", "SHARE PRICE (log10)"),
                       ("liab_per_cash", "LIABILITIES / CASH"),
                       ("equity_per_cap", "EQUITY / MARKET CAP"),
                       ("prior_mom", "PRIOR 60d MOMENTUM"),
                       ("log_adv", "DOLLAR VOLUME (log10)")):
        g = decile_table(d, col)
        if g is None:
            continue
        print(f"\n{label}")
        print(g.to_string())

    print("\n\nBINARY SPLITS")
    for col, label in (("is_profitable", "profitable"),
                       ("pre_revenue", "pre-revenue (<$1m)")):
        if col not in d:
            continue
        s = d[d[col].notna()]
        if len(s) < 100:
            continue
        g = s.groupby(col).agg(n=("max_up", "size"), med_up=("max_up", "median"),
                               med_dn=("max_dn", "median"),
                               up50=("max_up", lambda x: (x >= .50).mean()))
        g["med_up"] = (g.med_up * 100).round(1)
        g["med_dn"] = (g.med_dn * 100).round(1)
        g["up50"] = (g.up50 * 100).round(1)
        print(f"\n{label}")
        print(g.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
