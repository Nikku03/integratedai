"""Propagation analysis: what moves first, by how much, and what is left.

The thesis this module tests
----------------------------
    "We are not fighting institutions' million-dollar analyst tools. We are
    fighting mass-trader sentiment."

That is a specific, testable claim about **who prices what, and when**. An SEC
filing hits EDGAR at 16:05. Machines read it in milliseconds; the stock reprices
in the after-hours session. Then, hours or a day later, retail reads a headline
about the same filing and a second wave arrives.

If that is right, the money is not in the first leg -- you cannot win that race
and should not try -- but in the **second leg**, which is slow, human, and
driven by attention rather than analysis.

If it is wrong, the whole move happens in leg one and there is nothing to trade.

Daily bars cannot tell these apart. They report the same +6% whether you could
have captured six points or zero. This module splits the move into legs.

The four legs
-------------
For an event with a known acceptance timestamp:

``leg0_immediate``
    The bar containing the event, plus the next bar. Machine repricing. **Assume
    you get none of this** -- by the time you have parsed the filing, sized the
    trade and routed an order, this leg is done.
``leg1_rest_of_session``
    From two bars after the event through that session's close. Partly
    capturable if you are set up to act same-session.
``leg2_next_session``
    The following full session. **This is the retail wave**, and it is the one
    a daily-bar strategy can actually trade at the next open.
``leg3_days_2_5``
    The continuation. Slow money, index inclusion, follow-on coverage.

The natural experiment
----------------------
Filings arrive at all hours, and *when* they arrive is close to random with
respect to their content. Filings accepted **after the close** cannot move the
price until the next session, so their entire cascade is observable from t=0.
Filings accepted **mid-session** reprice instantly. Comparing the two arms
separates "the market is fast" from "our data is late" without needing a model.

What "capturable" means here
----------------------------
``capturable_share`` is legs 2 and 3 as a fraction of the total move. It is the
only fraction that matters, and it is the number this module exists to produce.
A catalyst with a 20% total move and a 2% capturable share is a worse trade than
one with a 4% move and a 90% capturable share.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from .core.types import to_utc

log = logging.getLogger(__name__)

#: Bars, at 1-hour resolution including pre/post, that each leg spans.
#: Leg boundaries are in *bars* rather than clock time because an event at
#: 16:05 on a Friday is one bar -- not 64 hours -- from the next print.
LEG_DEFINITIONS: dict[str, tuple[int, int]] = {
    "leg0_immediate": (0, 1),        # event bar + next bar: machine repricing
    "leg1_rest_of_session": (2, 6),  # rest of the day
    "leg2_next_session": (7, 22),    # the next full session: the retail wave
    "leg3_days_2_5": (23, 80),       # continuation
}


@dataclass
class CascadeResult:
    per_event: pd.DataFrame
    by_kind: pd.DataFrame
    lead_lag: pd.DataFrame

    def report(self) -> str:
        lines = ["=" * 96, "PROPAGATION / CASCADE ANALYSIS", "=" * 96, ""]
        lines.append("How a catalyst's move is distributed across time, in abnormal-return terms.")
        lines.append("leg0 = machine repricing (assume you get NONE of it)")
        lines.append("leg2 = the next full session -- the retail wave, and what you can trade")
        lines.append("capturable = (leg2 + leg3) / total move")
        lines.append("")
        if self.by_kind.empty:
            lines.append("  no events with enough coverage")
        else:
            lines.append(self.by_kind.to_string(index=False))
        lines.append("")
        if not self.lead_lag.empty:
            lines += ["", "LEAD-LAG: which event kind fires first when two land together", "-" * 96]
            lines.append(self.lead_lag.to_string(index=False))
        return "\n".join(lines)


def _abnormal_intraday(intraday: pd.DataFrame) -> pd.DataFrame:
    """Bar-level returns in excess of the cross-sectional mean for that bar.

    The market adjustment matters more intraday than daily: a 09:30 bar during a
    market-wide gap would otherwise credit every catalyst in the sample with the
    index move.
    """
    df = intraday.sort_values(["ticker", "ts"]).copy()
    df["ret"] = df.groupby("ticker", observed=True)["close"].pct_change()
    # Trim before averaging: one halted microcap reopening +300% would otherwise
    # define "the market" for that bar.
    mkt = df.groupby("ts", observed=True)["ret"].transform(
        lambda s: s.clip(s.quantile(0.05), s.quantile(0.95)).mean()
    )
    df["abn"] = df["ret"] - mkt
    df["bar_i"] = df.groupby("ticker", observed=True).cumcount()
    return df


def analyse_cascade(
    events: pd.DataFrame,
    intraday: pd.DataFrame,
    *,
    kinds: list[str] | None = None,
    min_events: int = 30,
    legs: dict[str, tuple[int, int]] | None = None,
) -> CascadeResult:
    """Split each event's forward move into propagation legs.

    ``events`` must carry ``available_ts`` with real intraday precision -- the
    whole analysis is meaningless if timestamps have been rounded to a date.
    """
    legs = legs or LEG_DEFINITIONS
    if events.empty or intraday.empty:
        return CascadeResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    bars = _abnormal_intraday(intraday)
    # (ticker -> sorted array of bar timestamps) for locating the event bar.
    by_ticker: dict[str, pd.DataFrame] = {t: g for t, g in bars.groupby("ticker", observed=True)}

    ev = events.copy()
    if kinds:
        ev = ev[ev["kind"].isin(kinds)]
    if ev.empty:
        return CascadeResult(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())

    max_bar = max(hi for _, hi in legs.values())
    rows = []
    for row in ev.itertuples(index=False):
        g = by_ticker.get(row.ticker)
        if g is None or g.empty:
            continue
        ts = to_utc(row.available_ts)
        arr = g["ts"].to_numpy()
        # First bar at or after the event: the bar in which the news could
        # first have affected a print.
        pos = int(np.searchsorted(arr, ts.to_datetime64(), side="left"))
        if pos >= len(arr) - max_bar:
            continue

        abn = g["abn"].to_numpy()
        vol = g["volume"].to_numpy()
        # Baseline volume from the 40 bars before the event, shifted so the
        # event bar cannot inflate its own baseline.
        lo = max(pos - 40, 0)
        base_vol = float(np.nanmean(vol[lo:pos])) if pos > lo else np.nan

        rec = {
            "ticker": row.ticker,
            "kind": row.kind,
            "available_ts": ts,
            "et_hour": ts.tz_convert("America/New_York").hour,
            "arrival": _arrival_bucket(ts),
        }
        total = 0.0
        for name, (a, b) in legs.items():
            seg = abn[pos + a : pos + b + 1]
            val = float(np.nansum(seg))
            rec[name] = val
            total += val
        rec["total"] = total
        # Volume in the retail-wave window relative to the pre-event baseline.
        a, b = legs["leg2_next_session"]
        wave_vol = float(np.nanmean(vol[pos + a : pos + b + 1])) if base_vol else np.nan
        rec["leg2_volume_ratio"] = (wave_vol / base_vol) if base_vol and base_vol > 0 else np.nan
        rows.append(rec)

    per_event = pd.DataFrame(rows)
    if per_event.empty:
        return CascadeResult(per_event, pd.DataFrame(), pd.DataFrame())

    by_kind = _summarise(per_event, legs, min_events)
    return CascadeResult(per_event, by_kind, pd.DataFrame())


def _arrival_bucket(ts: pd.Timestamp) -> str:
    """When did the news land, relative to the cash session?"""
    et = ts.tz_convert("America/New_York")
    hm = (et.hour, et.minute)
    if et.weekday() >= 5:
        return "weekend"
    if hm < (9, 30):
        return "premarket"
    if hm < (16, 0):
        return "intraday"
    return "afterhours"


def _summarise(per_event: pd.DataFrame, legs: dict, min_events: int) -> pd.DataFrame:
    leg_names = list(legs)
    out = []
    for kind, g in per_event.groupby("kind", observed=True):
        if len(g) < min_events:
            continue
        rec = {"kind": kind, "n": len(g)}
        for name in leg_names:
            rec[name] = float(g[name].mean())
        rec["total"] = float(g["total"].mean())

        capturable = float(g["leg2_next_session"].mean() + g["leg3_days_2_5"].mean())
        denom = abs(rec["total"])
        rec["capturable"] = capturable
        rec["capturable_share"] = (capturable / denom) if denom > 1e-9 else np.nan

        # t-stat on the capturable part only. The total's significance is
        # irrelevant if none of it is reachable.
        cap_series = g["leg2_next_session"] + g["leg3_days_2_5"]
        se = float(cap_series.std(ddof=1) / np.sqrt(len(g))) if len(g) > 1 else np.nan
        rec["capturable_t"] = (capturable / se) if se and se > 0 else np.nan
        rec["capturable_p"] = (
            float(2 * (1 - stats.norm.cdf(abs(rec["capturable_t"]))))
            if np.isfinite(rec["capturable_t"]) else np.nan
        )
        rec["leg2_vol_ratio"] = float(g["leg2_volume_ratio"].mean(skipna=True))
        out.append(rec)
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("capturable", key=lambda s: s.abs(), ascending=False)


def arrival_split(per_event: pd.DataFrame, kind: str | None = None) -> pd.DataFrame:
    """The natural experiment: cascade shape by when the news landed.

    After-hours filings cannot move the price until the next session, so their
    whole cascade is visible. Intraday filings reprice immediately. If the
    capturable share is similar across both arms, the second leg is a real
    behavioural wave. If after-hours events show a large capturable share and
    intraday ones show none, the "wave" was just the market being closed.
    """
    if per_event.empty:
        return pd.DataFrame()
    df = per_event if kind is None else per_event[per_event["kind"] == kind]
    if df.empty:
        return pd.DataFrame()
    agg = df.groupby("arrival", observed=True).agg(
        n=("total", "size"),
        leg0=("leg0_immediate", "mean"),
        leg1=("leg1_rest_of_session", "mean"),
        leg2=("leg2_next_session", "mean"),
        leg3=("leg3_days_2_5", "mean"),
        total=("total", "mean"),
    )
    agg["capturable"] = agg["leg2"] + agg["leg3"]
    agg["capturable_share"] = agg["capturable"] / agg["total"].abs().replace(0, np.nan)
    return agg.reset_index()


def daily_cascade(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    kinds: list[str] | None = None,
    min_events: int = 30,
    tail_days: int = 5,
) -> pd.DataFrame:
    """Split the move using only daily OHLC, via the overnight/intraday break.

    Intraday bars are limited to ~2 years and are rate-limited to fetch. Daily
    OHLC is not, and it still supports the decomposition that matters, because
    the **open** is a clean boundary between two different populations of
    traders.

    For an event that lands **after the close** of session ``D`` -- which is
    when most 8-Ks are filed -- the next session ``D+1`` splits into:

    ``gap``
        ``open(D+1) / close(D) - 1``. Set overnight, before the bell, by
        whoever read the filing. **You cannot trade this.** By the time the
        opening auction prints, it has happened.
    ``day1_intraday``
        ``close(D+1) / open(D+1) - 1``. The regular session *after* the news is
        already public and already reflected in the open. Anyone buying here is
        reacting to the news having been priced, not to the news. **This is the
        retail wave, and you can trade it** -- you buy at the open.
    ``days_2_to_N``
        ``close(D+1+N) / close(D+1) - 1``. The continuation.

    So the user's question -- "the filing moves it 5%, then the articles move it
    another 15%" -- is exactly ``gap`` versus ``day1_intraday + days_2_to_N``.
    If the gap dominates, the machines have it and there is nothing left. If the
    intraday leg dominates, the slow money is the opportunity.

    Only after-hours and pre-market arrivals are used. Events landing mid-session
    have no clean boundary in daily data -- their move is already partly inside
    the day's OHLC -- and including them would smear the very distinction this
    function exists to draw.
    """
    if events.empty or prices.empty:
        return pd.DataFrame()

    px = prices.sort_values(["ticker", "date"]).copy()
    if "adj_close" not in px.columns:
        px["adj_close"] = px["close"] * px.get("adj_factor", 1.0)
    px["bar_i"] = px.groupby("ticker", observed=True).cumcount()
    # Market benchmark per session, for abnormal returns.
    px["o2c"] = px["close"] / px["open"] - 1.0
    px["c2o"] = px["open"] / px.groupby("ticker", observed=True)["close"].shift(1) - 1.0
    mkt_o2c = px.groupby("date", observed=True)["o2c"].transform(
        lambda s: s.clip(s.quantile(0.05), s.quantile(0.95)).mean()
    )
    mkt_c2o = px.groupby("date", observed=True)["c2o"].transform(
        lambda s: s.clip(s.quantile(0.05), s.quantile(0.95)).mean()
    )
    px["abn_gap"] = px["c2o"] - mkt_c2o
    px["abn_intraday"] = px["o2c"] - mkt_o2c
    # Close-to-close abnormal return, for the tail leg. Must be market-adjusted
    # like the other two, or the tail silently carries the index's drift and a
    # rising market makes every catalyst look like it kept working.
    px["c2c"] = px["adj_close"] / px.groupby("ticker", observed=True)["adj_close"].shift(1) - 1.0
    mkt_c2c = px.groupby("date", observed=True)["c2c"].transform(
        lambda s: s.clip(s.quantile(0.05), s.quantile(0.95)).mean()
    )
    px["abn_c2c"] = px["c2c"] - mkt_c2c

    by_ticker = {t: g.reset_index(drop=True) for t, g in px.groupby("ticker", observed=True)}

    ev = events.copy()
    ev["available_ts"] = pd.to_datetime(ev["available_ts"], utc=True)
    if kinds:
        ev = ev[ev["kind"].isin(kinds)]
    ev["arrival"] = [_arrival_bucket(t) for t in ev["available_ts"]]
    # Only clean overnight arrivals.
    ev = ev[ev["arrival"].isin(["afterhours", "premarket", "weekend"])]
    if ev.empty:
        return pd.DataFrame()

    rows = []
    for row in ev.itertuples(index=False):
        g = by_ticker.get(row.ticker)
        if g is None or g.empty:
            continue
        et_date = row.available_ts.tz_convert("America/New_York").normalize().tz_localize(None)
        dates = g["date"].to_numpy()
        # The next session strictly after the arrival date for after-hours
        # events; for pre-market arrivals the same date still qualifies.
        side = "right" if row.arrival == "afterhours" else "left"
        pos = int(np.searchsorted(dates, np.datetime64(et_date), side=side))
        if pos < 1 or pos + tail_days >= len(g):
            continue

        gap = float(g["abn_gap"].iloc[pos])
        intra = float(g["abn_intraday"].iloc[pos])
        # Sum of abnormal close-to-close returns over the tail window.
        after = float(np.nansum(g["abn_c2c"].to_numpy()[pos + 1 : pos + 1 + tail_days]))
        if not np.isfinite(gap) or not np.isfinite(intra):
            continue
        rows.append(
            {
                "ticker": row.ticker,
                "kind": row.kind,
                "available_ts": row.available_ts,
                "arrival": row.arrival,
                "gap": gap,
                "day1_intraday": intra,
                "days_2_to_N": after,
            }
        )

    per_event = pd.DataFrame(rows)
    if per_event.empty:
        return pd.DataFrame()

    out = []
    for kind, g in per_event.groupby("kind", observed=True):
        if len(g) < min_events:
            continue
        gap = float(g["gap"].mean())
        intra = float(g["day1_intraday"].mean())
        after = float(g["days_2_to_N"].mean())
        total = gap + intra + after
        capt = intra + after
        cap_series = g["day1_intraday"] + g["days_2_to_N"]
        se = float(cap_series.std(ddof=1) / np.sqrt(len(g)))
        t = capt / se if se > 0 else np.nan
        out.append(
            {
                "kind": kind,
                "n": len(g),
                "gap": gap,
                "day1_intraday": intra,
                "days_2_to_N": after,
                "total": total,
                "capturable": capt,
                "capturable_share": capt / abs(total) if abs(total) > 1e-9 else np.nan,
                "capturable_t": t,
                "capturable_p": float(2 * (1 - stats.norm.cdf(abs(t)))) if np.isfinite(t) else np.nan,
            }
        )
    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values("total", key=lambda s: s.abs(), ascending=False)


def lead_lag(
    events: pd.DataFrame,
    *,
    pairs: list[tuple[str, str]],
    window_hours: float = 72.0,
) -> pd.DataFrame:
    """For co-occurring event kinds, which one arrives first and by how long?

    This is the ordering question directly: when a filing and a volume surge
    both land on the same name inside a few days, which one is the leader? A
    kind that is reliably *second* is not a signal -- it is a confirmation, and
    by the time you see it the first mover has already been priced.
    """
    if events.empty:
        return pd.DataFrame()
    ev = events[["ticker", "kind", "available_ts"]].copy()
    ev["available_ts"] = pd.to_datetime(ev["available_ts"], utc=True)
    window = pd.Timedelta(hours=window_hours)

    rows = []
    for a, b in pairs:
        left = ev[ev["kind"] == a].sort_values("available_ts")
        right = ev[ev["kind"] == b].sort_values("available_ts")
        if left.empty or right.empty:
            continue
        gaps = []
        # Stay in tz-aware pandas Timestamps throughout. Two traps otherwise:
        # `.to_numpy()` on a tz-aware column yields tz-naive datetime64, so
        # comparing it against an aware Timestamp raises; and converting to
        # int64 is *resolution dependent* -- pandas 3 stores datetimes at
        # microsecond precision while `Timestamp.value` reports nanoseconds, so
        # mixing the two silently scales every gap by 1000.
        right_by_ticker = {
            t: g["available_ts"].reset_index(drop=True)
            for t, g in right.groupby("ticker", observed=True)
        }
        for row in left.itertuples(index=False):
            arr = right_by_ticker.get(row.ticker)
            if arr is None or len(arr) == 0:
                continue
            anchor = pd.Timestamp(row.available_ts)
            # Nearest counterpart in either direction, within the window.
            i = int(arr.searchsorted(anchor))
            cands = [arr.iloc[j] for j in (i - 1, i) if 0 <= j < len(arr)]
            if not cands:
                continue
            deltas = [c - anchor for c in cands]
            nearest = min(deltas, key=abs)
            if abs(nearest) <= window:
                gaps.append(nearest.total_seconds() / 3600.0)
        if len(gaps) < 10:
            continue
        gaps_arr = np.array(gaps)
        rows.append(
            {
                "first": a,
                "second": b,
                "n_pairs": len(gaps_arr),
                # Positive median gap => b arrives AFTER a, i.e. a leads.
                "median_gap_h": float(np.median(gaps_arr)),
                "pct_b_after_a": float((gaps_arr > 0).mean()),
                "leader": a if np.median(gaps_arr) > 0 else b,
            }
        )
    return pd.DataFrame(rows).sort_values("pct_b_after_a", ascending=False) if rows else pd.DataFrame()
