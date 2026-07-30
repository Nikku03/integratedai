"""The whole thing, run as if live: pick filings, trade them, 20 trades in a month.

Every decision uses only what existed at the moment the filing hit EDGAR. There is
no ranking across the month, no threshold chosen from the month's outcomes, and no
filing skipped because of what it later did.

The three causal commitments
----------------------------
**Selection is an expanding window.** Each arriving filing is ranked against the
pre-event volatility of the filings *already seen this month*, never against the
month's full distribution. The first ``--warmup`` filings build the distribution
and are not traded. Ranking against the finished month would need the month to be
over.

**Entry is a resting order.** The order is sent one minute after acceptance and
fills at the first print at or after that instant -- immediately if the tape is
running, hours later if it is not, at whatever that print costs. Filings with no
counterparty are not dropped; dropping them is what made earlier versions of this
look tradable.

**Exit reads bars in order.** Barriers are checked bar by bar starting after the
entry bar, an ambiguous bar resolves against the trade, a stop fills at
``min(level, bar_low)`` to price gaps, and a zero-volume bar can neither trigger
an exit nor supply an exit price.

What is and is not pre-registered
---------------------------------
The **trap screen** (drop Item 3.01 delisting and 3.02 dilution) and the
**tradability floors** are mechanical: they follow from what the item codes mean
and from an $80 order needing a counterparty, not from this month's returns.

The **volatility selector** is not innocent. `moonshot_select.py` found pre-event
volatility to be the best ex-ante predictor of a large move, measured on July
data -- the same month traded here. It is reported alongside a random-selection
control drawn from the identical eligible pool, which is the only way to see
whether the selector is doing anything a coin could not.

The **percentile threshold** is tuned to land near twenty trades. That fits the
trade *count*, which the mandate specifies, not the return.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

#: Item codes dropped on sight. 3.02 is unregistered equity issued (dilution) and
#: measured -11.61% at ten days over 62 filings; 3.01 is a delisting notice.
TRAP_ITEMS = {"3.01", "3.02"}

#: Tradability floors, all evaluated on bars strictly before the fill.
MIN_PRICE = 1.00
MIN_PRIOR_DOLLARS = 250_000.0

#: Sessions of history for the pre-event volatility estimate.
VOL_LOOKBACK_BARS = 5 * 390


def load_filings(root: Path) -> pd.DataFrame:
    f = pd.read_parquet(root / "recent_filings.parquet")
    f["accepted"] = pd.to_datetime(f["accepted"], utc=True, format="mixed")
    e8 = f[f.form.isin(["8-K", "8-K/A"])].copy()
    e8["et"] = e8.accepted.dt.tz_convert("America/New_York")
    e8 = e8[(e8.et >= pd.Timestamp("2026-07-01", tz="America/New_York")) &
            (e8.et <= pd.Timestamp("2026-07-29", tz="America/New_York"))]
    e8["codes"] = e8["items"].fillna("").apply(
        lambda s: {c.strip() for c in str(s).split(",") if c.strip()})
    return e8.sort_values("accepted").reset_index(drop=True)


def pre_features(b: pd.DataFrame, i_fill: int) -> dict | None:
    """Volatility and depth from traded bars strictly before the fill bar."""
    lo = max(0, i_fill - VOL_LOOKBACK_BARS)
    prior = b.iloc[lo:i_fill]
    if len(prior) < 30:
        return None
    r = prior["close"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(r) < 10:
        return None
    return {"pre_vol": float(r.std() * np.sqrt(390)),
            "prior_dollars": float((prior["close"] * prior["volume"]).sum())}


def walk_exit(b: pd.DataFrame, i_ent: int, entry: float, target: float,
              stop: float, max_bars: int) -> tuple[int, float, str]:
    up, dn = entry * (1 + target), entry * (1 - stop)
    last = min(i_ent + max_bars, len(b) - 1)
    for j in range(i_ent + 1, last + 1):
        if not (float(b["volume"].iloc[j]) > 0):
            continue
        hi, lo = float(b["high"].iloc[j]), float(b["low"].iloc[j])
        if not (np.isfinite(hi) and np.isfinite(lo)):
            continue
        hit_dn, hit_up = lo <= dn, hi >= up
        if hit_dn:                       # ambiguity resolves against the trade
            return j, min(dn, lo), "stop"
        if hit_up:
            return j, up, "target"
    j = last
    while j > i_ent and not (float(b["volume"].iloc[j]) > 0):
        j -= 1
    return j, float(b["low"].iloc[j]), "time"


#: Minute bars are read once and shared across passes. The random-selection
#: control re-runs the whole month hundreds of times, and re-reading 1,600
#: parquet files per draw dominates everything else by two orders of magnitude.
_BARS: dict[str, pd.DataFrame] = {}


def run(root: Path, cache: Path, args, selector: str = "vol",
        seed: int = 0) -> pd.DataFrame:
    """One pass over the month. ``selector`` is 'vol', 'random' or 'all'."""
    fil = load_filings(root)
    bars_cache = _BARS
    rng = np.random.default_rng(seed)

    cash, open_pos, trades, seen = args.capital, [], [], []
    n_screened = n_noslot = n_nofill = 0

    for r in fil.to_dict("records"):
        t0 = np.datetime64(r["accepted"].tz_convert("UTC").tz_localize(None))

        still = []
        for p in open_pos:
            if p["exit_t"] <= r["accepted"]:
                cash += p["proceeds"]
                trades.append(p["rec"])
            else:
                still.append(p)
        open_pos = still

        if r["codes"] & TRAP_ITEMS:
            n_screened += 1
            continue

        tkr = r["ticker"]
        if tkr not in bars_cache:
            p = cache / f"{tkr}.parquet"
            if not p.exists():
                bars_cache[tkr] = pd.DataFrame()
            else:
                b = pd.read_parquet(p)
                bars_cache[tkr] = (b.sort_values("t_utc").reset_index(drop=True)
                                   if len(b) and "t_utc" in b.columns
                                   else pd.DataFrame())
        b = bars_cache[tkr]
        if b.empty:
            continue

        tv = b["t_utc"].to_numpy()
        traded = b["volume"].fillna(0).to_numpy() > 0
        # The resting order: first bar that actually trades at or after T+1min.
        i0 = int(np.searchsorted(tv, t0 + np.timedelta64(1, "m"), "left"))
        cand = np.nonzero(traded[i0:])[0]
        if not len(cand):
            n_nofill += 1
            continue
        i_fill = i0 + int(cand[0])
        lag = float((tv[i_fill] - t0) / np.timedelta64(1, "m"))
        # Strict mode: a genuine one-minute trade only exists if the tape is
        # running. Beyond the cutoff the order would rest into the next session,
        # which is a different strategy wearing the same name -- so it is
        # declined rather than silently relabelled.
        if args.max_fill_lag and lag > args.max_fill_lag:
            n_nofill += 1
            continue
        entry = float(b["high"].iloc[i_fill])
        if not np.isfinite(entry) or entry < MIN_PRICE:
            n_screened += 1
            continue

        feats = pre_features(b, i_fill)
        if feats is None or feats["prior_dollars"] < MIN_PRIOR_DOLLARS:
            n_screened += 1
            continue

        v = feats["pre_vol"]
        eligible = np.isfinite(v)
        # Rank against filings ALREADY SEEN, never the finished month.
        if selector == "vol":
            take = (eligible and len(seen) >= args.warmup
                    and v >= np.quantile(seen, args.pctile))
        elif selector == "random":
            take = eligible and len(seen) >= args.warmup and rng.random() < args.rate
        else:
            take = eligible and len(seen) >= args.warmup
        if eligible:
            seen.append(v)                       # append AFTER the decision

        if not take:
            continue
        if len(open_pos) >= args.slots:
            n_noslot += 1
            continue

        equity = cash + sum(p["cost"] for p in open_pos)
        size = equity / args.slots
        if size < 0.50:
            continue
        cash -= size

        j, px, why = walk_exit(b, i_fill, entry, args.target, args.stop,
                               args.max_bars)
        exit_t = b["t"].iloc[j]
        open_pos.append({
            "exit_t": exit_t, "cost": size, "proceeds": size * (px / entry),
            "rec": {
                "ticker": tkr, "items": r["items"],
                "public_et": r["et"],
                "fill_et": pd.Timestamp(b["t"].iloc[i_fill]).tz_convert(
                    "America/New_York"),
                "lag_min": float((tv[i_fill] - t0) / np.timedelta64(1, "m")),
                "entry": entry, "exit_et": pd.Timestamp(exit_t).tz_convert(
                    "America/New_York"),
                "exit_px": px, "why": why, "pre_vol": v,
                "ret": px / entry - 1.0, "size": size,
                "pnl": size * (px / entry - 1.0)},
        })

    for p in sorted(open_pos, key=lambda q: q["exit_t"]):
        cash += p["proceeds"]
        trades.append(p["rec"])

    out = pd.DataFrame(trades)
    if not out.empty:
        out = out.sort_values("exit_et").reset_index(drop=True)
        bal, eq = [], args.capital
        for pnl in out["pnl"]:
            eq += pnl
            bal.append(eq)
        out["balance"] = bal
    out.attrs.update(screened=n_screened, noslot=n_noslot, nofill=n_nofill,
                     universe=len(fil))
    return out


def summarise(tr: pd.DataFrame, cap: float) -> dict:
    if tr.empty:
        return {}
    r = tr["ret"]
    n = len(r)
    se = r.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    curve = np.concatenate([[cap], tr["balance"].to_numpy()])
    dd = float((curve / np.maximum.accumulate(curve) - 1).min())
    return {"trades": n, "end": float(tr["balance"].iloc[-1]),
            "roi": float(tr["balance"].iloc[-1]) / cap - 1,
            "mean": r.mean(), "median": r.median(), "win": (r > 0).mean(),
            "t": r.mean() / se if se and se == se else np.nan, "dd": dd}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--cache", default="/root/.iai/minutecache")
    ap.add_argument("--capital", type=float, default=80.0)
    ap.add_argument("--slots", type=int, default=2)
    ap.add_argument("--target", type=float, default=0.06)
    ap.add_argument("--stop", type=float, default=0.10)
    ap.add_argument("--max-bars", type=int, default=390)
    ap.add_argument("--pctile", type=float, default=0.80)
    ap.add_argument("--rate", type=float, default=0.05)
    ap.add_argument("--warmup", type=int, default=30)
    ap.add_argument("--max-fill-lag", type=float, default=0.0,
                    help="decline the filing if no print within this many "
                         "minutes; 0 = let the order rest indefinitely")
    ap.add_argument("--draws", type=int, default=200)
    args = ap.parse_args(argv)

    root, cache = Path(args.root), Path(args.cache)
    tr = run(root, cache, args, "vol")
    a = tr.attrs
    print(f"8-K filings in July: {a['universe']:,}   screened out "
          f"{a['screened']:,}   never printed {a['nofill']:,}   "
          f"no free slot {a['noslot']:,}\n")

    if tr.empty:
        print("no trades")
        return 1

    cols = ["ticker", "items", "public_et", "fill_et", "lag_min", "entry",
            "exit_et", "exit_px", "why", "ret", "pnl", "balance"]
    d = tr[cols].copy()
    for c in ("public_et", "fill_et", "exit_et"):
        d[c] = pd.to_datetime(d[c]).dt.strftime("%m-%d %H:%M")
    d["ret"] = (d["ret"] * 100).round(2)
    for c in ("entry", "exit_px", "pnl", "balance"):
        d[c] = d[c].round(2)
    d["lag_min"] = d["lag_min"].round(1)
    print(d.to_string(index=False))

    s = summarise(tr, args.capital)
    print(f"\n{s['trades']} trades   ${args.capital:.2f} -> ${s['end']:.2f}   "
          f"ROI {s['roi']:+.2%}   max DD {s['dd']:.1%}")
    print(f"mean {s['mean']:+.2%}   median {s['median']:+.2%}   "
          f"win {s['win']:.0%}   t {s['t']:+.2f}")
    print("exits:", tr["why"].value_counts().to_dict())
    print(f"fill lag: median {tr.lag_min.median():.0f} min, "
          f"{(tr.lag_min <= 2).mean():.0%} within 2 min")

    print(f"\nCONTROL: random selection from the same eligible pool, "
          f"{args.draws} draws")
    rows = []
    for k in range(args.draws):
        rt = run(root, cache, args, "random", seed=k)
        if not rt.empty:
            rows.append(summarise(rt, args.capital))
    c = pd.DataFrame(rows)
    if len(c):
        print(f"  random  trades {c.trades.mean():.1f}   "
              f"end ${c['end'].mean():.2f}   ROI {c.roi.mean():+.2%}   "
              f"mean/trade {c['mean'].mean():+.3%}")
        print(f"  model   trades {s['trades']}   end ${s['end']:.2f}   "
              f"ROI {s['roi']:+.2%}   mean/trade {s['mean']:+.3%}")
        print(f"  p(random ROI >= model) = {(c.roi >= s['roi']).mean():.3f}   "
              f"p(random mean >= model) = {(c['mean'] >= s['mean']).mean():.3f}")
    tr.to_parquet(root / "live_sim_trades.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
