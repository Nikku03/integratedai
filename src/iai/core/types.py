"""Core data types.

The single most important idea in this package is the distinction between
``event_ts`` and ``available_ts`` on :class:`Event`:

``event_ts``
    When the thing actually happened in the world. A complaint was filed, a
    jet touched down, a vessel discharged cargo, a board signed an agreement.

``available_ts``
    The first moment *we* could have acted on it. EDGAR filings are timestamped
    on acceptance but only hit the full-text index minutes later. Court dockets
    are scraped on a poll interval. Comtrade publishes with a two-month lag.
    ADS-B is near-real-time but the *interpretation* ("the CEO flew to Basel")
    requires knowing the tail number's owner, which is itself a lagged dataset.

Every feature in this package is computed against ``available_ts``. Sorting or
joining on ``event_ts`` is the classic way to build a backtest that prints
Sharpe 4 and loses money live, so :func:`validate_events` refuses to let an
event through with ``available_ts < event_ts``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import pandas as pd

UTC = "UTC"


def to_utc(ts: Any) -> pd.Timestamp:
    """Coerce anything timestamp-like to a tz-aware UTC ``pd.Timestamp``."""
    out = pd.Timestamp(ts)
    if out.tzinfo is None:
        out = out.tz_localize(UTC)
    return out.tz_convert(UTC)


@dataclass(frozen=True, slots=True)
class Event:
    """A single point-in-time observation about one issuer.

    Parameters
    ----------
    source:
        Registered source name, e.g. ``"edgar"``, ``"litigation"``.
    kind:
        Source-specific subtype. Convention is dotted and increasingly
        specific: ``"8-K.1.01"``, ``"docket.complaint"``, ``"flight.arrival"``.
    ticker:
        Resolved exchange ticker. Sources that natively key on CIK, LEI, tail
        number or IMO must resolve to a ticker before emitting.
    event_ts / available_ts:
        See module docstring. Both tz-aware UTC.
    payload:
        Free-form source detail. Feature builders read from here; nothing in
        the modelling layer depends on its schema.
    weight:
        Prior importance in ``[0, inf)``. Used as a multiplier when events are
        aggregated into decay-weighted intensities. A routine Item 7.01 press
        release is ~0.3; an Item 1.03 bankruptcy is ~3.0.
    """

    source: str
    kind: str
    ticker: str
    event_ts: pd.Timestamp
    available_ts: pd.Timestamp
    payload: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_ts", to_utc(self.event_ts))
        object.__setattr__(self, "available_ts", to_utc(self.available_ts))
        object.__setattr__(self, "ticker", self.ticker.upper().strip())

    @property
    def uid(self) -> str:
        """Stable content hash, used to dedupe across overlapping fetches."""
        raw = f"{self.source}|{self.kind}|{self.ticker}|{self.event_ts.isoformat()}|{self.payload.get('id', '')}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @property
    def latency(self) -> timedelta:
        """How long after the fact the event became actionable."""
        return (self.available_ts - self.event_ts).to_pytimedelta()


EVENT_COLUMNS = [
    "uid",
    "source",
    "kind",
    "ticker",
    "event_ts",
    "available_ts",
    "weight",
    "payload",
]


def events_to_frame(events: list[Event]) -> pd.DataFrame:
    """Convert events to a deduplicated frame sorted by ``available_ts``."""
    if not events:
        return pd.DataFrame(
            {
                "uid": pd.Series(dtype="object"),
                "source": pd.Series(dtype="object"),
                "kind": pd.Series(dtype="object"),
                "ticker": pd.Series(dtype="object"),
                "event_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "available_ts": pd.Series(dtype="datetime64[ns, UTC]"),
                "weight": pd.Series(dtype="float64"),
                "payload": pd.Series(dtype="object"),
            }
        )
    rows = [
        {
            "uid": e.uid,
            "source": e.source,
            "kind": e.kind,
            "ticker": e.ticker,
            "event_ts": e.event_ts,
            "available_ts": e.available_ts,
            "weight": float(e.weight),
            "payload": e.payload,
        }
        for e in events
    ]
    df = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    df = df.drop_duplicates(subset="uid", keep="first")
    return df.sort_values("available_ts").reset_index(drop=True)


class LookaheadError(AssertionError):
    """Raised when an event or feature frame could not have been known in time."""


def validate_events(df: pd.DataFrame) -> pd.DataFrame:
    """Assert point-in-time sanity. Returns the frame unchanged on success.

    This is deliberately a hard failure rather than a warning. A silent
    lookahead bug is worth more negative alpha than any feature in this
    repository is worth positive.
    """
    if df.empty:
        return df
    missing = [c for c in EVENT_COLUMNS if c not in df.columns]
    if missing:
        raise LookaheadError(f"event frame missing columns: {missing}")
    bad = df["available_ts"] < df["event_ts"]
    if bool(bad.any()):
        sample = df.loc[bad, ["source", "kind", "ticker", "event_ts", "available_ts"]].head(5)
        raise LookaheadError(
            f"{int(bad.sum())} events have available_ts < event_ts (time travel):\n{sample}"
        )
    for col in ("event_ts", "available_ts"):
        if getattr(df[col].dtype, "tz", None) is None:
            raise LookaheadError(f"column {col} must be tz-aware UTC")
    return df
