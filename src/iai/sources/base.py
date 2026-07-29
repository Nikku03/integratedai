"""Source protocol and registry.

Every source answers the same question -- "what became knowable about these
issuers between ``start`` and ``end``?" -- and returns :class:`Event` objects.
Sources are deliberately allowed to fail: :meth:`SourceRegistry.collect`
catches, logs and continues, because a dead vendor API should cost you a
feature block, not the whole day's signal.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import pandas as pd

from ..core.config import Config
from ..core.http import HttpClient
from ..core.types import Event, events_to_frame, validate_events
from ..core.universe import Universe

log = logging.getLogger(__name__)


class EventSource(ABC):
    """Base class for all data sources."""

    #: Registry key, also the ``Event.source`` value.
    name: str = "base"
    #: Typical wall-clock delay between an event happening and us being able to
    #: act on it. Used as the default when a source cannot determine per-record
    #: latency. Documented per subclass because this number is the difference
    #: between a real backtest and a fantasy.
    default_latency: pd.Timedelta = pd.Timedelta(minutes=15)
    #: Set False when the source needs credentials that are not configured.
    enabled: bool = True

    def __init__(self, cfg: Config, client: HttpClient, universe: Universe) -> None:
        self.cfg = cfg
        self.client = client
        self.universe = universe

    @abstractmethod
    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        """Return events that became available in ``[start, end)``."""

    def health(self) -> dict:
        """Report readiness so ``iai doctor`` can tell you what is actually on."""
        return {"name": self.name, "enabled": self.enabled, "reason": ""}


class SourceRegistry:
    """Fan-out over configured sources with per-source error isolation."""

    def __init__(self, sources: list[EventSource]) -> None:
        self.sources = sources

    def collect(self, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        for src in self.sources:
            if not src.enabled:
                log.info("source %s disabled, skipping", src.name)
                continue
            try:
                events = src.fetch(start, end)
                log.info("source %s: %d events", src.name, len(events))
                frames.append(events_to_frame(events))
            except Exception:  # noqa: BLE001 - isolation is the point
                log.exception("source %s failed; continuing without it", src.name)
        if not frames:
            return events_to_frame([])
        out = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        if out.empty:
            return events_to_frame([])
        out = out.drop_duplicates(subset="uid").sort_values("available_ts").reset_index(drop=True)
        return validate_events(out)

    def health(self) -> pd.DataFrame:
        return pd.DataFrame([s.health() for s in self.sources])
