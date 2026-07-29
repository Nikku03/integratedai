"""Event studies: the first thing to run, and the thing most people skip.

Before building any model, answer the cheap question: **does this event kind
move the price at all, and when?** An event study answers it directly, in a
form no model can obscure, and it fails fast on the things that matter:

* If the abnormal return is entirely *before* the event date, the effect is
  confounded. Two causes, and they need different responses. Either your
  timestamp is late -- common with litigation, where the stock moves when the
  news breaks rather than when the docket is scraped, and with anything derived
  from a monthly-refreshed registry -- or the event is **endogenous** to the
  prior move. Companies file dilutive shelf takedowns *because* the stock ran
  up; activists file 13Ds *after* accumulating. A late timestamp is fixable; an
  endogenous event is not, and the drift measured after it is not a clean
  effect either way.
* If it is entirely *on* the event date, it is real but uncapturable: the move
  happened in the print, and by your next open it is gone.
* If it continues for days *after*, that is post-event drift, and it is the
  only part a daily-bar strategy can trade.

That decomposition is worth more than an AUC, because a model that scores well
on an uncapturable effect will still lose money, and the event study is what
tells them apart.

Returns are abnormal (in excess of the equal-weight universe) so a biotech
catalyst during a biotech rally is not credited to the catalyst.

**Every kind is tested at once, so read ``survives_fdr``, not ``drift_t``.** A
study over fifteen event kinds produces a |t| > 2 by chance most times you run
it; :func:`benjamini_hochberg` is what stops that becoming a strategy.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from scipy import stats

from .core.config import Config
from .features.events import attach_entry_session

log = logging.getLogger(__name__)


def _abnormal_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """Per-name daily return in excess of the equal-weight universe."""
    df = prices.sort_values(["ticker", "date"]).copy()
    if "adj_close" not in df.columns:
        df["adj_close"] = df["close"] * df.get("adj_factor", 1.0)
    df["ret"] = df.groupby("ticker", observed=True)["adj_close"].pct_change()
    mkt = df.groupby("date", observed=True)["ret"].transform("mean")
    df["abn"] = df["ret"] - mkt
    return df[["date", "ticker", "ret", "abn"]]


def event_study(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    cfg: Config,
    *,
    kinds: list[str] | None = None,
    pre: int = 5,
    post: int = 20,
    min_events: int = 20,
) -> pd.DataFrame:
    """Cumulative abnormal return around each event kind.

    Day 0 is ``known_date`` -- the session by whose close the event was public,
    not the session it happened. A tradable strategy enters at the open of day
    +1, so the sum of abnormal returns over days +1..+post is the part that is
    actually available to you. That column is reported separately as
    ``car_tradable`` and is the number to look at.

    Returns one row per (kind, relative day) with mean CAR, its standard error
    and a t-statistic.
    """
    if events.empty or prices.empty:
        return pd.DataFrame()

    abn = _abnormal_returns(prices)
    ev = attach_entry_session(events, cfg)
    if kinds:
        ev = ev[ev["kind"].isin(kinds)]
    if ev.empty:
        return pd.DataFrame()

    # Position of each session in the calendar, so relative offsets are in
    # trading days rather than calendar days.
    calendar = pd.DatetimeIndex(sorted(abn["date"].unique()))
    pos = pd.Series(np.arange(len(calendar)), index=calendar)
    abn = abn.merge(
        pd.DataFrame({"date": calendar, "_pos": np.arange(len(calendar))}), on="date", how="left"
    )
    wide = abn.pivot_table(index="_pos", columns="ticker", values="abn", aggfunc="last")
    wide = wide.reindex(index=np.arange(len(calendar)))
    wide_values = wide.to_numpy(dtype="float64")
    col_of = {t: i for i, t in enumerate(wide.columns)}

    # Resolve every event's (day position, ticker column) once, vectorised.
    ev = ev.assign(
        _pos=ev["known_date"].map(pos),
        _col=ev["ticker"].map(col_of),
    ).dropna(subset=["_pos", "_col"])

    offsets = np.arange(-pre, post + 1)
    rows = []
    for kind, grp in ev.groupby("kind", observed=True):
        p = grp["_pos"].to_numpy(dtype=int)
        c = grp["_col"].to_numpy(dtype=int)
        # Drop events whose window would run off either end of the calendar.
        ok = (p - pre >= 0) & (p + post < len(calendar))
        p, c = p[ok], c[ok]
        if len(p) < min_events:
            log.debug("skipping %s: only %d usable events", kind, len(p))
            continue

        # Fancy-index the whole (n_events x n_offsets) panel in one shot rather
        # than reindexing a Series per event.
        mat = wide_values[p[:, None] + offsets[None, :], c[:, None]]
        anchors = p  # kept for the n_events column below

        car = np.nancumsum(np.nan_to_num(mat), axis=1)
        # Tradable slice: enter at the open of +1, so re-base the cumulative
        # sum at day 0 and read the accumulation from +1 onward.
        base_col = int(np.where(offsets == 0)[0][0])
        car_tradable = car - car[:, [base_col]]

        for j, off in enumerate(offsets):
            vals = car[:, j]
            vals_t = car_tradable[:, j]
            n = int(np.isfinite(vals).sum())
            se = float(np.nanstd(vals, ddof=1) / np.sqrt(max(n, 1))) if n > 1 else np.nan
            se_t = float(np.nanstd(vals_t, ddof=1) / np.sqrt(max(n, 1))) if n > 1 else np.nan
            mean, mean_t = float(np.nanmean(vals)), float(np.nanmean(vals_t))
            rows.append(
                {
                    "kind": kind,
                    "day": int(off),
                    "n_events": len(anchors),
                    "car": mean,
                    "car_se": se,
                    "car_t": mean / se if se and se > 0 else np.nan,
                    "car_tradable": mean_t,
                    "car_tradable_t": mean_t / se_t if se_t and se_t > 0 else np.nan,
                }
            )
    return pd.DataFrame(rows)


def benjamini_hochberg(p_values: np.ndarray, fdr: float = 0.10) -> np.ndarray:
    """Which hypotheses survive at a given false-discovery rate.

    An event study tests every event kind at once. With fifteen kinds and a
    naive |t| > 2 cutoff you expect roughly one "discovery" from pure noise
    every time you run it, and it will be a different one each time. That is
    not a hypothetical failure mode -- it is the most common way event-study
    research produces strategies that fail to replicate.

    Benjamini-Hochberg controls the expected *proportion* of false discoveries
    among those accepted, which is the right criterion here: unlike Bonferroni
    it does not become uselessly conservative as kinds are added, and unlike an
    uncorrected threshold it does not lie to you.
    """
    p = np.asarray(p_values, dtype="float64")
    ok = np.isfinite(p)
    out = np.zeros(len(p), dtype=bool)
    if not ok.any():
        return out
    idx = np.flatnonzero(ok)
    order = idx[np.argsort(p[idx])]
    m = len(order)
    thresholds = fdr * np.arange(1, m + 1) / m
    passed = p[order] <= thresholds
    if passed.any():
        # Everything up to the largest passing rank counts as a discovery.
        cutoff = int(np.max(np.flatnonzero(passed)))
        out[order[: cutoff + 1]] = True
    return out


def event_study_summary(study: pd.DataFrame, post: int = 20, fdr: float = 0.10) -> pd.DataFrame:
    """Collapse an event study to one row per kind: pre, announcement, drift.

    ``pre_car``
        Abnormal return over days -5..-1. A large value means the price moved
        *before* our timestamp, from one of two very different causes, both
        worth knowing: our data is late, or the event is **endogenous** to the
        prior move. Companies do dilutive offerings after their stock runs up;
        activists file 13Ds after accumulating. Either way the drift measured
        afterwards is confounded and is not a clean effect.
    ``day0_car``
        The announcement move. Not available to us.
    ``drift_car`` / ``drift_t``
        Days +1..+post. **The only column that is tradable.**
    ``survives_fdr``
        Whether the effect survives Benjamini-Hochberg correction across every
        kind tested in this study. **Read this column, not ``drift_t``.** A
        study over fifteen kinds throws up a |t| > 2 by chance most of the time.
    """
    if study.empty:
        return pd.DataFrame()

    rows = []
    for kind, g in study.groupby("kind", observed=True):
        g = g.set_index("day").sort_index()
        pre_car = float(g.loc[-1, "car"]) if -1 in g.index else np.nan
        day0 = float(g.loc[0, "car"] - (g.loc[-1, "car"] if -1 in g.index else 0.0))
        last = min(post, int(g.index.max()))
        drift = float(g.loc[last, "car_tradable"])
        drift_t = float(g.loc[last, "car_tradable_t"])
        rows.append(
            {
                "kind": kind,
                "n_events": int(g["n_events"].iloc[0]),
                "pre_car": pre_car,
                "day0_car": day0,
                "drift_car": drift,
                "drift_t": drift_t,
                "p_raw": float(2 * (1 - stats.norm.cdf(abs(drift_t))))
                if np.isfinite(drift_t)
                else np.nan,
            }
        )

    out = pd.DataFrame(rows)
    out["survives_fdr"] = benjamini_hochberg(out["p_raw"].to_numpy(), fdr=fdr)
    out["verdict"] = [
        _verdict(r.pre_car, r.day0_car, r.drift_car, r.drift_t, r.survives_fdr)
        for r in out.itertuples(index=False)
    ]
    return (
        out.sort_values("drift_car", key=lambda s: s.abs(), ascending=False)
        .reset_index(drop=True)
    )


def _verdict(pre: float, day0: float, drift: float, drift_t: float, survives: bool) -> str:
    if not np.isfinite(drift_t):
        return "insufficient data"
    if not survives:
        if abs(drift_t) >= 2.0:
            # Precisely the trap this correction exists to catch.
            return "NOT SIGNIFICANT after multiple-testing correction"
        if abs(day0) > 0.01:
            return "announcement only - not tradable"
        return "no detectable effect"
    if abs(pre) > abs(drift) and abs(pre) > 0.01:
        return "CONFOUNDED: large pre-event move (late data or endogenous event)"
    return f"tradable drift {drift:+.2%}"


def conditional_event_study(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    cfg: Config,
    *,
    primary: str,
    conditions: list[str],
    window_days: int = 5,
    pre: int = 5,
    post: int = 20,
    min_events: int = 20,
    require_all: bool = False,
) -> pd.DataFrame:
    """Drift after ``primary`` fires, split by whether ``conditions`` also fired.

    Why this exists
    ---------------
    :func:`event_study` is a **marginal** test: it asks whether an event kind
    moves price *on average, unconditionally*. That averages a microcap with no
    analyst coverage together with a $9bn name where forty people read the
    filing within a minute, and the average of a heterogeneous population is
    the least informative summary of it.

    The interesting hypothesis is almost always a **conjunction** -- an insider
    cluster buy *and* a volume surge, a press release *and* a breakout. A
    marginal study cannot see that, and its silence is not evidence against it.

    This function measures the conditional drift directly and, critically,
    reports the **unconditional** arm alongside it. A conjunction that beats its
    own base case is interesting; a conjunction that merely beats zero has told
    you nothing you did not already know, because it is a strict subset chosen
    after looking.

    Parameters
    ----------
    primary:
        Event kind whose forward drift is being measured.
    conditions:
        Other kinds that must have fired on the same ticker within
        ``window_days`` *before or on* the primary's known date. Never after --
        that would be a lookahead.
    require_all:
        ``True`` demands every condition; ``False`` demands any.

    Beware the multiplicity
    ----------------------
    Every (primary, condition) pair you try is another hypothesis. The p-values
    here are raw. Count your attempts and put them through
    :func:`benjamini_hochberg`, or you are mining.
    """
    if events.empty or prices.empty:
        return pd.DataFrame()

    ev = attach_entry_session(events, cfg)
    prim = ev[ev["kind"] == primary]
    if prim.empty:
        return pd.DataFrame()

    cond = ev[ev["kind"].isin(conditions)]
    # ticker -> {kind -> sorted list of known_date}
    by_ticker: dict[str, dict[str, list]] = {}
    for row in cond.itertuples(index=False):
        by_ticker.setdefault(row.ticker, {}).setdefault(row.kind, []).append(row.known_date)
    for kinds in by_ticker.values():
        for lst in kinds.values():
            lst.sort()

    window = pd.Timedelta(days=window_days)

    def satisfied(ticker: str, when) -> bool:
        kinds = by_ticker.get(ticker, {})
        hits = []
        for k in conditions:
            dates = kinds.get(k, [])
            # Strictly at or before `when`, within the window.
            hit = any((when - window) <= d <= when for d in dates)
            hits.append(hit)
        return all(hits) if require_all else any(hits)

    flags = [satisfied(r.ticker, r.known_date) for r in prim.itertuples(index=False)]
    prim = prim.assign(_cond=flags)

    label = "+".join(c.split(".")[-1] for c in conditions)
    out = []
    for arm, sub in (
        ("with " + label, prim[prim["_cond"]]),
        ("without " + label, prim[~prim["_cond"]]),
        ("all", prim),
    ):
        if len(sub) < min_events:
            continue
        tagged = sub.assign(kind=f"{primary} [{arm}]")
        study = event_study(
            tagged.drop(columns=["_cond"]), prices, cfg,
            pre=pre, post=post, min_events=min_events,
        )
        summary = event_study_summary(study, post=post)
        if not summary.empty:
            out.append(summary.assign(arm=arm, n_primary=len(sub)))
    if not out:
        return pd.DataFrame()
    return pd.concat(out, ignore_index=True)


def label_lift(
    events: pd.DataFrame, labels: pd.DataFrame, cfg: Config, *, min_events: int = 20
) -> pd.DataFrame:
    """P(upper barrier | event) versus the unconditional base rate.

    A direct, model-free check that the event -> feature -> label chain is
    aligned. If a kind you believe in shows zero lift here, no amount of
    hyperparameter tuning will save it, and the fault is more likely in the
    timestamps than in the hypothesis.
    """
    if events.empty or labels.empty:
        return pd.DataFrame()

    base = float(labels["label"].mean())
    ev = attach_entry_session(events, cfg)[["ticker", "known_date", "kind"]].rename(
        columns={"known_date": "date"}
    )
    merged = ev.merge(labels[["ticker", "date", "label", "ret"]], on=["ticker", "date"], how="inner")
    if merged.empty:
        return pd.DataFrame()

    rows = []
    for kind, g in merged.groupby("kind", observed=True):
        n = len(g)
        if n < min_events:
            continue
        p = float(g["label"].mean())
        se = float(np.sqrt(base * (1 - base) / n))
        t = (p - base) / se if se > 0 else np.nan
        rows.append(
            {
                "kind": kind,
                "n": n,
                "p_upper": p,
                "base_rate": base,
                "lift": p - base,
                "t_stat": t,
                "mean_ret": float(g["ret"].mean()),
                "p_value": float(2 * (1 - stats.norm.cdf(abs(t)))) if np.isfinite(t) else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("t_stat", key=lambda s: s.abs(), ascending=False)


def coverage_report(events: pd.DataFrame, universe_size: int) -> pd.DataFrame:
    """How much of the universe each source actually reaches.

    A source covering 8% of names is not a feature, it is a sub-strategy, and
    training one model across both covered and uncovered names teaches it that
    "no data" means "no catalyst". Worth knowing before you wire it in.
    """
    if events.empty:
        return pd.DataFrame()
    agg = (
        events.groupby("source", observed=True)
        .agg(
            n_events=("uid", "size"),
            n_tickers=("ticker", "nunique"),
            first=("available_ts", "min"),
            last=("available_ts", "max"),
        )
        .reset_index()
    )
    agg["pct_universe"] = 100.0 * agg["n_tickers"] / max(universe_size, 1)
    agg["events_per_ticker"] = agg["n_events"] / agg["n_tickers"].replace(0, np.nan)
    lat = events.assign(
        latency_h=(events["available_ts"] - events["event_ts"]).dt.total_seconds() / 3600.0
    )
    med = lat.groupby("source", observed=True)["latency_h"].median().rename("median_latency_h")
    return agg.merge(med.reset_index(), on="source", how="left").sort_values(
        "n_events", ascending=False
    )
