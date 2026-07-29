"""Event-stream features: decayed intensity, novelty, breadth, recency.

The join
--------
Everything here reduces to one operation: for each (ticker, session) cell,
summarise the events that were already public at that session's close. The
mapping from ``available_ts`` to a session goes through
:func:`iai.core.calendar.entry_session`, which handles after-hours, weekends
and holidays. See :func:`attach_entry_session` for the exact timing convention
and why it applies no lag of its own.

The reason this is a separate module from the market features is that it is the
place lookahead creeps in. Two rules, enforced by construction rather than by
care:

1. A feature row dated ``t`` is built only from events with
   ``known_date <= t``. No centred windows, no ``rolling(...).mean()`` reaching
   forward, no full-sample normalisation.
2. Baselines for novelty and z-scores use *expanding* statistics, so the
   normaliser at ``t`` knows only about the past.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..core.calendar import entry_session, sessions
from ..core.config import Config

log = logging.getLogger(__name__)

#: Feature families. Each becomes a column prefix. Grouping by family lets the
#: model report importance per data source, which is how you find out that the
#: expensive vendor feed is contributing nothing.
FAMILIES = {
    "edgar": ("edgar", "edgar_fts"),
    "legal": ("litigation",),
    "partner": ("partners",),
    "flight": ("flights",),
    "trade": ("trade", "shipping", "shipping_ais"),
    "insider": ("insiders",),
    "instl": ("institutional", "stakes"),
    "flow": ("flow",),
    "news": ("news", "news_live"),
}


def attach_entry_session(events: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Add ``known_date``: the session by whose close the event was public.

    This is the *first* half of the timing convention; the second half lives in
    :mod:`iai.labels`, which enters at the open of ``known_date + 1``. Written
    out in full, the convention is:

        panel row dated t  ->  contains only what was public at the close of t
        trade for row t    ->  entered at the open of t+1

    So this function applies **no lag of its own**. An event available at 10:00
    ET on Tuesday is public by Tuesday's close, lands on row Tuesday, and is
    traded at Wednesday's open. An event available at 16:15 ET on Tuesday is
    after the cutoff, rolls to row Wednesday, and is traded at Thursday's open
    -- one session more conservative than a desk that trades Wednesday's open
    on overnight news, which is the direction to err in.

    Applying ``entry_lag_days`` here as well would lag event features twice,
    once here and once at entry, quietly discarding the first session or two of
    every catalyst's move -- which is most of it.
    """
    if events.empty:
        out = events.copy()
        out["known_date"] = pd.Series(dtype="datetime64[ns]")
        return out
    df = events.copy()
    # entry_session is pure and the input has heavy duplication (many events
    # share a timestamp), so memoise on the minute.
    keys = df["available_ts"].dt.floor("min")
    unique = {k: entry_session(k, lag_days=0) for k in keys.unique()}
    df["known_date"] = keys.map(unique)
    return df


def _family_of(source: str) -> str:
    for fam, members in FAMILIES.items():
        if source in members:
            return fam
    return "other"


def build_event_features(
    events: pd.DataFrame,
    cfg: Config,
    calendar: pd.DatetimeIndex | None = None,
) -> pd.DataFrame:
    """Panel of (date, ticker) -> event features.

    Produces, per family and per configured half-life:

    ``{fam}_int_h{H}``
        Exponentially decayed weighted event count. The half-life sets what
        "recent" means; several are included because a merger rumour decays
        over days and a litigation overhang over quarters.
    ``{fam}_cnt_5``
        Raw count in the trailing 5 sessions - an unsmoothed burst detector.
    ``{fam}_novel``
        Decayed intensity divided by its own expanding mean. Answers "is this
        a lot *for this name*", which is the only version of the question that
        transfers across a 60-name universe.
    ``{fam}_days_since``
        Sessions since the last event of the family, capped. Recency is
        non-linear and trees split on it happily.
    ``{fam}_maxw_5``
        Largest single event weight in the trailing week - separates one 4.02
        from five 9.01s.
    """
    if events.empty:
        return pd.DataFrame(columns=["date", "ticker"])

    df = attach_entry_session(events, cfg)
    df["family"] = df["source"].map(_family_of)

    if calendar is None:
        calendar = sessions(
            str(df["known_date"].min().date()),
            str((df["known_date"].max() + pd.Timedelta(days=5)).date()),
        )
    calendar = pd.DatetimeIndex(calendar).sort_values()

    tickers = sorted(df["ticker"].unique())
    index = pd.MultiIndex.from_product([calendar, tickers], names=["date", "ticker"])
    panel = pd.DataFrame(index=index)

    for family in sorted(df["family"].unique()):
        sub = df[df["family"] == family]
        if sub.empty:
            continue
        panel = panel.join(_family_block(sub, family, calendar, tickers, cfg))

    # Cross-family aggregates. Breadth -- how many distinct sources fired --
    # is a genuinely different signal from intensity in any one of them.
    int_cols = [c for c in panel.columns if c.endswith(f"_int_h{cfg.features.halflives[1]}")]
    if int_cols:
        panel["all_int"] = panel[int_cols].sum(axis=1)
        panel["all_breadth"] = (panel[int_cols] > 0.05).sum(axis=1).astype("float64")

    return panel.reset_index()


def _family_block(
    sub: pd.DataFrame,
    family: str,
    calendar: pd.DatetimeIndex,
    tickers: list[str],
    cfg: Config,
) -> pd.DataFrame:
    """Dense (date, ticker) block of features for one family."""
    daily = (
        sub.groupby(["known_date", "ticker"], observed=True)
        .agg(w_sum=("weight", "sum"), n=("weight", "size"), w_max=("weight", "max"))
        .reset_index()
        .rename(columns={"known_date": "date"})
    )

    index = pd.MultiIndex.from_product([calendar, tickers], names=["date", "ticker"])
    dense = (
        daily.set_index(["date", "ticker"])
        .reindex(index)
        .fillna({"w_sum": 0.0, "n": 0.0, "w_max": 0.0})
    )

    # Work in wide (date x ticker) form: ewm and rolling then operate down the
    # time axis for every name at once, which is both fast and impossible to
    # accidentally leak across.
    w_sum = dense["w_sum"].unstack("ticker").reindex(calendar).fillna(0.0)
    n = dense["n"].unstack("ticker").reindex(calendar).fillna(0.0)
    w_max = dense["w_max"].unstack("ticker").reindex(calendar).fillna(0.0)

    out: dict[str, pd.DataFrame] = {}
    for hl in cfg.features.halflives:
        out[f"{family}_int_h{hl}"] = w_sum.ewm(halflife=hl, adjust=False).mean()

    out[f"{family}_cnt_5"] = n.rolling(5, min_periods=1).sum()
    out[f"{family}_maxw_5"] = w_max.rolling(5, min_periods=1).max()

    ref = out[f"{family}_int_h{cfg.features.halflives[1]}"]
    # Expanding mean, shifted, so today's value is normalised by a baseline
    # that does not contain today.
    baseline = ref.expanding(min_periods=21).mean().shift(1)
    out[f"{family}_novel"] = (ref / baseline.replace(0.0, np.nan)).clip(upper=25.0)

    had_event = n > 0
    # Sessions since the last event: cumulative count of days since the most
    # recent True, computed without any forward reference.
    idx = pd.Series(np.arange(len(calendar)), index=calendar)
    last_idx = had_event.mul(idx, axis=0).where(had_event).ffill()
    days_since = (-last_idx).add(idx, axis=0)
    out[f"{family}_days_since"] = days_since.fillna(cfg.features.novelty_window).clip(
        upper=cfg.features.novelty_window
    )

    return _wide_to_long(out, calendar, tickers)


def _wide_to_long(
    frames: dict[str, pd.DataFrame], calendar: pd.DatetimeIndex, tickers: list[str]
) -> pd.DataFrame:
    """Flatten aligned (date x ticker) frames into one (date, ticker) block.

    Every frame shares the same index and columns, so this is a plain ravel
    rather than a per-column ``stack`` and ``concat``. That is roughly 30x
    faster on a realistic panel, but the reason to avoid ``stack`` is
    correctness: it drops all-NaN rows, and the ``novel`` column is NaN during
    its warm-up window. Stacking frames with different NaN patterns and
    concatenating them relies on index alignment to undo the damage, which
    works until one column is entirely NaN for a date and the row silently
    disappears from that column only.
    """
    index = pd.MultiIndex.from_product([calendar, tickers], names=["date", "ticker"])
    data = {}
    for name, frame in frames.items():
        aligned = frame.reindex(index=calendar, columns=tickers)
        # C-order ravel is date-major, ticker-minor, matching from_product.
        data[name] = aligned.to_numpy(dtype="float64").ravel(order="C")
    return pd.DataFrame(data, index=index)


def kind_features(events: pd.DataFrame, cfg: Config, top_k: int = 25) -> pd.DataFrame:
    """One decayed-intensity column per individual event kind.

    The family aggregates above lose the distinction between an 8-K 4.02 and an
    8-K 9.01. This restores it for the ``top_k`` most frequent kinds, which is
    where a tree model finds most of its edge. Kinds are selected by frequency
    over the *training* window only -- pass a pre-sliced frame, or you have
    chosen your feature set using the test set.
    """
    if events.empty:
        return pd.DataFrame(columns=["date", "ticker"])

    df = attach_entry_session(events, cfg)
    keep = df["kind"].value_counts().head(top_k).index.tolist()
    df = df[df["kind"].isin(keep)]
    if df.empty:
        return pd.DataFrame(columns=["date", "ticker"])

    calendar = sessions(
        str(df["known_date"].min().date()),
        str((df["known_date"].max() + pd.Timedelta(days=5)).date()),
    )
    tickers = sorted(df["ticker"].unique())
    hl = cfg.features.halflives[1]

    # One groupby over all kinds at once, then reshape per kind. The previous
    # version filtered and pivoted inside the loop, which re-scanned the event
    # frame `top_k` times.
    daily = (
        df.groupby(["kind", "known_date", "ticker"], observed=True)["weight"]
        .sum()
        .rename("w")
        .reset_index()
    )
    frames: dict[str, pd.DataFrame] = {}
    for kind in keep:
        sub = daily[daily["kind"] == kind]
        wide = (
            sub.pivot(index="known_date", columns="ticker", values="w")
            .reindex(index=calendar, columns=tickers)
            .fillna(0.0)
        )
        col = f"kind_{kind.replace('.', '_').replace('-', '_')}"
        frames[col] = wide.ewm(halflife=hl, adjust=False).mean()

    return _wide_to_long(frames, calendar, tickers).reset_index()
