"""Build the point-in-time panel the ADRNN trains on.

Implements the dataset half of ``docs/PREREGISTRATION_ADRNN.md``. Nothing here
is chosen after seeing a result; the feature list and the label were frozen
before this file was written.

The whole job is to make sure that a row dated *t* contains only what was
knowable at the close of *t*. Two things make that non-trivial:

**Events carry two timestamps.** ``event_ts`` is when the thing happened and
``available_ts`` is when it could be read. A filing accepted at 20:30 ET is not
usable on the day it is stamped. Every event feature is therefore aggregated on
``available_ts``, and an event lands on the first trading day whose close is at
or after it.

**Fundamentals are reported late.** A balance sheet dated 31 March is not public
until the 10-Q that discloses it, so values are forward-filled from the filing
date, never from the period end.

The output is one row per (ticker, date) with a flat feature vector; the
sequence model assembles its own 60-step windows at load time, which keeps this
file's output about 60x smaller than materialising the windows here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HORIZON = 10
SEQ_LEN = 60
MIN_HISTORY = 250
MIN_ADV = 1_000_000.0
BIG_MOVE = 0.20
SPLIT_ARTIFACT = 0.60

#: 8-K item codes and forms tracked as separate counters.
ITEMS = ["1.01", "2.01", "2.02", "2.03", "3.01", "3.02",
         "5.02", "5.03", "5.07", "7.01", "8.01", "9.01"]
FORMS = ["10-Q", "10-K", "S-3", "424B5", "SC 13D", "SC 13G"]
INSIDER = ["insider.buy", "insider.sell", "insider.cluster_buy"]
WINDOWS = [5, 20, 60]

#: Registration forms and the weight used to rebuild the dilution-armed score
#: historically. Same ordering as ``dilution_armed.ARMED``: a priced takedown
#: outranks an effective shelf, which outranks a filed one.
REG_WEIGHT = {"424B5": 4, "S-3": 2}
REG_LOOKBACK = 120


def price_features(p: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker price and volume features, all backward-looking."""
    g = p.groupby("ticker", sort=False)
    c, h, l = p["close"], p["high"], p["low"]

    out = pd.DataFrame(index=p.index)
    logc = np.log(c.clip(lower=1e-6))
    for w in (1, 5, 20, 60):
        out[f"ret_{w}d"] = g["close"].transform(
            lambda s, w=w: np.log(s.clip(lower=1e-6)).diff(w))
    r1 = out["ret_1d"]
    for w in (5, 20, 60):
        out[f"vol_{w}d"] = r1.groupby(p.ticker, sort=False).transform(
            lambda s, w=w: s.rolling(w, min_periods=max(3, w // 2)).std())

    out["log_price"] = logc
    dv = p["dollar_vol"].clip(lower=1.0)
    out["log_dollar_vol"] = np.log(dv)
    med20 = dv.groupby(p.ticker, sort=False).transform(
        lambda s: s.rolling(20, min_periods=5).median())
    out["rvol"] = np.log((dv / med20.clip(lower=1.0)).clip(lower=1e-3))

    hi60 = g["high"].transform(lambda s: s.rolling(60, min_periods=20).max())
    lo60 = g["low"].transform(lambda s: s.rolling(60, min_periods=20).min())
    rng = (hi60 - lo60).replace(0, np.nan)
    out["pos_in_range"] = ((c - lo60) / rng).clip(0, 1)
    out["dist_hi60"] = np.log((c / hi60.replace(0, np.nan)).clip(lower=1e-3))

    # The direct autocorrelation term: how big was the last 20 days' excursion.
    prev_c = g["close"].shift(1)
    up = (h / prev_c - 1).abs()
    dn = (l / prev_c - 1).abs()
    exc = pd.concat([up, dn], axis=1).max(axis=1)
    out["max_exc_20d"] = exc.groupby(p.ticker, sort=False).transform(
        lambda s: s.rolling(20, min_periods=5).max())
    out["mean_exc_20d"] = exc.groupby(p.ticker, sort=False).transform(
        lambda s: s.rolling(20, min_periods=5).mean())
    return out


def event_features(ev: pd.DataFrame, keys: pd.DataFrame) -> pd.DataFrame:
    """Trailing counts and recency for every tracked event kind.

    Aggregated on ``available_ts``, snapped forward to the first trading day at
    or after it, so an after-hours filing is credited to the next session.
    """
    trading = keys[["ticker", "date"]].copy()
    trading["_row"] = np.arange(len(trading))

    ev = ev.copy()
    ev["avail"] = pd.to_datetime(ev["available_ts"], utc=True, errors="coerce")
    ev = ev.dropna(subset=["avail"])
    ev["date"] = ev["avail"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)

    def tag(row) -> str | None:
        k = str(row)
        if k.startswith("8-K."):
            item = k[4:]
            return f"i{item}" if item in ITEMS else None
        if k.startswith("form."):
            f = k[5:]
            return f"f{f}" if f in FORMS else None
        if k in INSIDER:
            return "n" + k.split(".")[1]
        return None

    ev["tag"] = ev["kind"].map(tag)
    ev = ev.dropna(subset=["tag"])
    if ev.empty:
        return pd.DataFrame(index=keys.index)

    # Daily count per (ticker, date, tag) -> wide, then rolled forward.
    cnt = (ev.groupby(["ticker", "date", "tag"], observed=True)
             .size().rename("n").reset_index())
    wide = cnt.pivot_table(index=["ticker", "date"], columns="tag",
                           values="n", fill_value=0, aggfunc="sum")
    wide.columns = [str(c) for c in wide.columns]

    # Align onto the trading calendar. Reindexing per ticker keeps the rolling
    # windows in trading days rather than calendar days, which matters because
    # a 60-calendar-day window spans a variable number of sessions.
    merged = (trading.set_index(["ticker", "date"])
                     .join(wide, how="left").fillna(0.0))
    tags = [c for c in merged.columns if c != "_row"]
    gb = merged.groupby(level=0, sort=False)

    out = pd.DataFrame(index=merged.index)
    for w in WINDOWS:
        r = gb[tags].transform(lambda s, w=w: s.rolling(w, min_periods=1).sum())
        r.columns = [f"{c}_{w}d" for c in tags]
        out = pd.concat([out, r], axis=1)

    # Days since the last occurrence, capped so "never" is a finite number.
    for c in tags:
        seen = merged[c] > 0
        idx = np.where(seen, np.arange(len(seen)), np.nan)
        last = pd.Series(idx, index=merged.index).groupby(level=0, sort=False).ffill()
        since = pd.Series(np.arange(len(seen)), index=merged.index) - last
        out[f"{c}_since"] = since.fillna(999).clip(upper=999)

    out["_row"] = merged["_row"].to_numpy()
    out = out.sort_values("_row").drop(columns="_row")
    out.index = keys.index
    return out


def dilution_score(ev: pd.DataFrame, keys: pd.DataFrame) -> pd.Series:
    """Historical reconstruction of the dilution-armed score.

    The live screen reads the EDGAR filing index; here the same forms come out
    of the events table, so the feature the model sees in 2018 is the feature
    the screen would have produced in 2018.
    """
    e = ev[ev["kind"].isin([f"form.{f}" for f in REG_WEIGHT])].copy()
    if e.empty:
        return pd.Series(0.0, index=keys.index)
    e["avail"] = pd.to_datetime(e["available_ts"], utc=True, errors="coerce")
    e = e.dropna(subset=["avail"])
    e["date"] = e["avail"].dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
    e["w"] = e["kind"].str[5:].map(REG_WEIGHT).astype(float)

    daily = (e.groupby(["ticker", "date"], observed=True)["w"].max()
               .rename("w").reset_index())
    t = keys[["ticker", "date"]].copy()
    t["_row"] = np.arange(len(t))
    m = t.merge(daily, on=["ticker", "date"], how="left")
    m["w"] = m["w"].fillna(0.0)
    s = (m.groupby("ticker", sort=False)["w"]
           .transform(lambda x: x.rolling(REG_LOOKBACK, min_periods=1).max()))
    return pd.Series(s.to_numpy(), index=keys.index)


def labels(p: pd.DataFrame) -> pd.DataFrame:
    """Forward-looking label from the t+1 open over HORIZON sessions."""
    g = p.groupby("ticker", sort=False)
    entry = g["open"].shift(-1)

    # Rolling forward max/min over [t+1, t+H] using a reversed rolling window.
    def fwd(col: str, how: str) -> pd.Series:
        s = g[col].shift(-1)
        r = s[::-1].groupby(p.ticker[::-1], sort=False).transform(
            lambda x: x.rolling(HORIZON, min_periods=HORIZON).max()
            if how == "max" else
            x.rolling(HORIZON, min_periods=HORIZON).min())
        return r[::-1]

    hi = fwd("high", "max")
    lo = fwd("low", "min")
    out = pd.DataFrame(index=p.index)
    out["entry"] = entry
    out["max_up"] = hi / entry - 1.0
    out["max_dn"] = lo / entry - 1.0
    mag = pd.concat([out["max_up"], -out["max_dn"]], axis=1).max(axis=1)
    out["mag"] = mag
    out["y_mag"] = (mag >= BIG_MOVE).astype("float32")
    out["y_dir"] = (out["max_up"] >= -out["max_dn"]).astype("float32")
    bad = (out[["max_up", "max_dn"]].abs() > 5.0).any(axis=1)
    out.loc[bad, ["y_mag", "y_dir", "mag"]] = np.nan
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default="/root/.iai/wide2015")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    root = Path(args.root)
    out_path = Path(args.out) if args.out else root / "adrnn_panel.parquet"

    print("loading prices", flush=True)
    p = pd.read_parquet(root / "w2015_prices.parquet",
                        columns=["date", "ticker", "open", "high", "low",
                                 "close", "volume", "dollar_vol", "adv_usd",
                                 "tradable"])
    p["date"] = pd.to_datetime(p["date"])
    p = p.sort_values(["ticker", "date"]).reset_index(drop=True)
    print(f"  {len(p):,} rows, {p.ticker.nunique()} tickers, "
          f"{p.date.min():%Y-%m-%d}..{p.date.max():%Y-%m-%d}", flush=True)

    # Split artifacts: a huge move with no volume cannot be traded and is
    # almost always a reverse split in unadjusted data.
    g = p.groupby("ticker", sort=False)
    jump = (p["close"] / g["close"].shift(1) - 1).abs()
    art = (jump > SPLIT_ARTIFACT) & (p["volume"].fillna(0) <= 0)
    print(f"  {int(art.sum()):,} split-artifact bars flagged", flush=True)

    print("price features", flush=True)
    feat = price_features(p)

    print("labels", flush=True)
    lab = labels(p)

    keys = p[["ticker", "date"]].reset_index(drop=True)

    print("loading events", flush=True)
    ev = pd.read_parquet(root / "w2015_events.parquet",
                         columns=["source", "kind", "ticker", "available_ts"])
    ev = ev[ev.ticker.isin(set(p.ticker.unique()))]
    print(f"  {len(ev):,} events", flush=True)

    print("event features", flush=True)
    ef = event_features(ev, keys)
    print(f"  {ef.shape[1]} event columns", flush=True)

    print("dilution score", flush=True)
    dil = dilution_score(ev, keys)

    d = pd.concat([keys, feat.reset_index(drop=True),
                   ef.reset_index(drop=True),
                   lab.reset_index(drop=True)], axis=1)
    d["dilution_armed"] = dil.to_numpy()
    d["adv_usd"] = p["adv_usd"].to_numpy()
    d["tradable"] = p["tradable"].to_numpy()
    d["_artifact"] = art.to_numpy()

    print("fundamentals", flush=True)
    try:
        f = pd.read_parquet(root / "fundamentals_full.parquet")
        cols = [c for c in ["ticker", "market_cap", "cash_per_cap",
                            "runway_years", "liab_per_cash", "equity_per_cap",
                            "share_growth", "is_profitable", "pre_revenue"]
                if c in f.columns]
        f = f[cols].drop_duplicates("ticker")
        d = d.merge(f, on="ticker", how="left")
        d["log_cap"] = np.log10(d["market_cap"].clip(lower=1e6)) if "market_cap" in d else np.nan
        d = d.drop(columns=["market_cap"], errors="ignore")
        for c in ("is_profitable", "pre_revenue"):
            if c in d:
                d[c] = d[c].astype("float32")
        print(f"  merged {len(cols) - 1} fundamental columns "
              f"(static, so they are a weak point -- see the pre-registration)",
              flush=True)
    except FileNotFoundError:
        print("  fundamentals_full.parquet missing, skipping", flush=True)

    print("gov events", flush=True)
    try:
        gv = pd.read_parquet(root / "gov_events.parquet")
        gv["date"] = pd.to_datetime(gv["date"], errors="coerce").dt.tz_localize(None)
        gv = gv.dropna(subset=["date", "ticker"])
        gc = (gv.groupby(["ticker", "date"]).size().rename("gov_n").reset_index())
        d = d.merge(gc, on=["ticker", "date"], how="left")
        d["gov_n"] = d["gov_n"].fillna(0.0)
        d["gov_60d"] = (d.groupby("ticker", sort=False)["gov_n"]
                         .transform(lambda s: s.rolling(60, min_periods=1).sum()))
        print(f"  {len(gc):,} gov event-days", flush=True)
    except FileNotFoundError:
        d["gov_60d"] = 0.0

    # Eligibility. Kept as a column rather than filtered away, because the
    # sequence model still needs the ineligible rows to build its history.
    hist = d.groupby("ticker", sort=False).cumcount()
    d["eligible"] = ((hist >= MIN_HISTORY)
                     & (d["adv_usd"].fillna(0) >= MIN_ADV)
                     & (d["tradable"].fillna(False).astype(bool))
                     & (~d["_artifact"])
                     & d["y_mag"].notna()).astype("bool")
    d = d.drop(columns=["_artifact"])

    e = d[d.eligible]
    print(f"\n{len(d):,} panel rows, {int(d.eligible.sum()):,} eligible "
          f"({d.eligible.mean() * 100:.1f}%)")
    print(f"base rate P(|move| >= {BIG_MOVE:.0%} in {HORIZON}d) = "
          f"{e.y_mag.mean() * 100:.2f}%")
    print(f"of those, P(up)                                     = "
          f"{e.loc[e.y_mag == 1, 'y_dir'].mean() * 100:.2f}%")
    print("\nbase rate by year:")
    yr = e.assign(y=e.date.dt.year).groupby("y").agg(
        n=("y_mag", "size"), p_big=("y_mag", "mean"),
        p_up=("y_dir", lambda s: s[e.loc[s.index, "y_mag"] == 1].mean()))
    yr["p_big"] = (yr.p_big * 100).round(2)
    yr["p_up"] = (yr.p_up * 100).round(2)
    print(yr.to_string())

    d.to_parquet(out_path)
    nfeat = len([c for c in d.columns if c not in
                 {"ticker", "date", "entry", "max_up", "max_dn", "mag",
                  "y_mag", "y_dir", "eligible", "adv_usd", "tradable"}])
    print(f"\nwrote {out_path}  ({nfeat} feature columns)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
