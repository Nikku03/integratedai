"""Trade the frozen clinical-readout rule over twelve months of daily bars.

Consumes `oos_clinical_signals.parquet` from `oos_clinical.py` and applies the
rule exactly as pre-registered in `docs/PREREGISTRATION_CLINICAL.md`: enter at the
next session's open, arm at +8%, initial stop -15%, 8% trail off the high-water
mark, exit on 8 sessions without a new high, hard cap at 25 sessions.

Nothing here is fitted. Every parameter arrives from the pre-registration.
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oos_clinical import walk_daily  # noqa: E402

ARM, TRAIL, INIT_STOP, STALL, CAP = 0.08, 0.08, 0.15, 8, 25


def daily(client, ticker: str, lo: pd.Timestamp, hi: pd.Timestamp) -> pd.DataFrame:
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
        "open": q.get("open"), "high": q.get("high"),
        "low": q.get("low"), "close": q.get("close"),
        "volume": q.get("volume")}).dropna(subset=["close"])
        .sort_values("date").reset_index(drop=True))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--user-agent", required=True)
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    args = ap.parse_args(argv)
    root = Path(args.root)

    from iai.core.config import Config
    from iai.core.http import HttpClient
    cfg = Config.load()
    yah = HttpClient(cfg.data.cache_dir, args.user_agent, rate_per_sec=12.0,
                     ttl_hours=168.0, max_retries=4)

    sig = pd.read_parquet(root / "oos_clinical_signals.parquet")
    sig["et"] = pd.to_datetime(sig["et"], utc=True).dt.tz_convert("America/New_York")
    print(f"{len(sig)} clinical readouts, {sig.ticker.nunique()} names, "
          f"{sig.et.min():%Y-%m-%d} to {sig.et.max():%Y-%m-%d}")
    print(sig.verdict.value_counts().to_string())

    lo = pd.Timestamp("2025-05-01", tz="UTC")
    hi = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta(days=1)
    names = sorted(sig.ticker.unique())
    bars: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(daily, yah, t, lo, hi): t for t in names}
        for k, fu in enumerate(as_completed(futs), 1):
            if k % 200 == 0:
                print(f"  bars {k}/{len(names)}", flush=True)
            try:
                b = fu.result()
            except Exception:                                  # noqa: BLE001
                continue
            if len(b) > 30:
                bars[futs[fu]] = b

    rows = []
    for r in sig.sort_values("et").itertuples():
        b = bars.get(r.ticker)
        if b is None:
            continue
        d0 = pd.Timestamp(r.et).normalize().tz_localize(None)
        nxt = b[b.date > d0]
        if len(nxt) < 3:
            continue
        i = nxt.index[0]
        e = float(b["open"].iloc[i])
        if not np.isfinite(e) or e < 1.0:
            continue
        prior = b.iloc[max(0, i - 20):i]
        if prior.empty or float((prior.close * prior.volume.fillna(0)).median()) < 250_000:
            continue
        j = min(i + CAP, len(b) - 1)
        h = b["high"].to_numpy()[i:j + 1]
        l = b["low"].to_numpy()[i:j + 1]
        if len(h) < 2:
            continue
        ret, why, k = walk_daily(h, l, e, arm=ARM, trail=TRAIL,
                                 init_stop=INIT_STOP, stall=STALL)
        rows.append({"ticker": r.ticker, "et": r.et, "verdict": r.verdict,
                     "entry_date": b["date"].iloc[i], "entry": e,
                     "exit_date": b["date"].iloc[min(i + k, len(b) - 1)],
                     "ret": ret, "why": why})
    t = pd.DataFrame(rows)
    t.to_parquet(root / "oos_clinical_trades.parquet")
    print(f"\n{len(t)} tradable signals\n")

    print(f"{'verdict':10s}{'n':>6s}{'mean':>9s}{'median':>9s}{'win':>6s}"
          f"{'best':>8s}{'worst':>8s}")
    for v, g in t.groupby("verdict"):
        print(f"{v:10s}{len(g):>6d}{g.ret.mean() * 100:>8.2f}%"
              f"{g.ret.median() * 100:>8.2f}%{(g.ret > 0).mean() * 100:>5.0f}%"
              f"{g.ret.max() * 100:>7.0f}%{g.ret.min() * 100:>7.0f}%")

    p = t[t.verdict == "POSITIVE"]
    if len(p) < 5:
        print("\ntoo few POSITIVE signals to test")
        return 0
    n = len(p)
    se = p.ret.std(ddof=1) / np.sqrt(n)
    boot = np.array([np.random.default_rng(s).choice(p.ret.to_numpy(), n,
                                                     replace=True).mean()
                     for s in range(20000)])
    print(f"\nPRIMARY CRITERION -- POSITIVE cohort, n={n}")
    print(f"  mean {p.ret.mean() * 100:+.2f}%   median {p.ret.median() * 100:+.2f}%"
          f"   win {(p.ret > 0).mean() * 100:.0f}%   t={p.ret.mean() / se:+.2f}")
    print(f"  bootstrap 95% CI [{np.percentile(boot, 2.5) * 100:+.2f}%, "
          f"{np.percentile(boot, 97.5) * 100:+.2f}%]   "
          f"P(mean<=0)={(boot <= 0).mean():.4f}")
    verdict = "PASS" if np.percentile(boot, 2.5) > 0 else "FAIL"
    print(f"  -> {verdict}")

    p = p.copy()
    p["q"] = p.et.dt.to_period("Q")
    print("\nby quarter:")
    print(p.groupby("q").agg(n=("ret", "size"), mean=("ret", "mean"),
                             win=("ret", lambda s: (s > 0).mean())).round(4).to_string())
    big = p.nlargest(2, "ret")
    rest = p.drop(big.index)
    print(f"\ndropping the 2 largest winners ({', '.join(big.ticker)}): "
          f"n={len(rest)} mean {rest.ret.mean() * 100:+.2f}%")
    print("exits:", p.why.value_counts().to_dict())

    # portfolio
    cash, open_pos = args.capital, []
    for r in t[t.verdict == "POSITIVE"].sort_values("entry_date").itertuples():
        still = []
        for xd, cost, pro in open_pos:
            if xd <= r.entry_date:
                cash += pro
            else:
                still.append((xd, cost, pro))
        open_pos = still
        if len(open_pos) >= args.slots:
            continue
        eq = cash + sum(c for _, c, _ in open_pos)
        size = eq / args.slots
        if size < 0.5:
            continue
        cash -= size
        open_pos.append((r.exit_date, size, size * (1 + r.ret)))
    for _, _, pro in open_pos:
        cash += pro
    print(f"\n${args.capital:.2f}, {args.slots} slots -> ${cash:.2f} "
          f"({cash / args.capital - 1:+.1%}) over 12 months")
    return 0


if __name__ == "__main__":
    sys.exit(main())
