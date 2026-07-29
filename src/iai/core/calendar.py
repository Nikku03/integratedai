"""US equity trading calendar and point-in-time timestamp -> session mapping.

Uses pandas holiday rules rather than an external calendar dependency. This
covers the regular NYSE holiday schedule from 1998 onward; it does not model
one-off closures (9/11, Hurricane Sandy, national days of mourning) or the
half-day early closes. For a days-to-weeks holding horizon those omissions
shift a handful of entries by one session and do not change any conclusion,
but if you move to intraday execution, swap this for ``exchange_calendars``.
"""

from __future__ import annotations

import functools

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
)

EASTERN = "America/New_York"

#: The exchange stops accepting the day's news for the purposes of "can I trade
#: on this at today's close" a few minutes before the bell. Anything available
#: after this cutoff is treated as next-session information.
LATE_CUTOFF_HOUR = 15
LATE_CUTOFF_MINUTE = 45


class NYSECalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("NewYearsDay", month=1, day=1, observance=nearest_workday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-06-20", observance=nearest_workday),
        Holiday("IndependenceDay", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


@functools.lru_cache(maxsize=8)
def sessions(start: str = "1998-01-01", end: str = "2035-12-31") -> pd.DatetimeIndex:
    """All NYSE trading sessions in ``[start, end]`` as naive dates."""
    days = pd.bdate_range(start, end)
    holidays = NYSECalendar().holidays(start=days[0], end=days[-1])
    return days.difference(pd.DatetimeIndex(holidays))


@functools.lru_cache(maxsize=8)
def _session_set(start: str = "1998-01-01", end: str = "2035-12-31") -> frozenset:
    """Membership index over :func:`sessions`.

    Cached separately and deliberately. ``is_session`` is called once per event
    -- millions of times on a full universe -- and rebuilding a 9,000-element
    set from the (already cached) DatetimeIndex on every call made event feature
    assembly take 45 seconds where it should take one.
    """
    return frozenset(sessions(start, end))


def is_session(day: pd.Timestamp) -> bool:
    day = pd.Timestamp(day).normalize()
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    return day in _session_set()


def next_session(day: pd.Timestamp, offset: int = 1) -> pd.Timestamp:
    """The session ``offset`` steps after ``day`` (``offset=0`` snaps forward)."""
    idx = sessions()
    day = pd.Timestamp(day).normalize()
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    pos = int(np.searchsorted(idx.values, day.to_datetime64(), side="left"))
    pos = min(pos + max(offset - 1, 0) if offset > 0 else pos, len(idx) - 1)
    if offset > 0 and idx[pos] == day:
        pos = min(pos + 1, len(idx) - 1)
    return idx[pos]


def entry_session(available_ts: pd.Timestamp, lag_days: int = 1) -> pd.Timestamp:
    """Map an availability timestamp to the session we could realistically enter.

    News that lands at 09:00 ET on a Tuesday is tradable at Tuesday's open only
    if you are set up to act on it pre-market; this package assumes you are not,
    and with ``lag_days=1`` enters at Wednesday's open. News that lands after
    the late cutoff, on a weekend, or on a holiday rolls forward first, then
    takes the lag. The result is conservative by roughly one session versus what
    a fast desk achieves, which is the right side to err on.
    """
    ts = pd.Timestamp(available_ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    local = ts.tz_convert(EASTERN)
    day = local.normalize().tz_localize(None)
    late = (local.hour, local.minute) >= (LATE_CUTOFF_HOUR, LATE_CUTOFF_MINUTE)
    if not is_session(day) or late:
        day = next_session(day, 1)
    if lag_days > 0:
        day = next_session(day, lag_days)
    return day


def session_offset(day: pd.Timestamp, n: int) -> pd.Timestamp:
    """Shift ``day`` by ``n`` sessions (``n`` may be negative)."""
    idx = sessions()
    day = pd.Timestamp(day).normalize()
    if day.tzinfo is not None:
        day = day.tz_localize(None)
    pos = int(np.searchsorted(idx.values, day.to_datetime64(), side="left"))
    return idx[int(np.clip(pos + n, 0, len(idx) - 1))]
