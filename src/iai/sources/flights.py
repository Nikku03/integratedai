"""Corporate aircraft movement from ADS-B (OpenSky).

Legality and framing
--------------------
ADS-B is an unencrypted position broadcast that every aircraft is required to
transmit, and the FAA aircraft registry is a public record. Observing and
aggregating both is lawful, and it is not material non-public information --
it is material *public* information that happens to be inconvenient to
collect. That distinction is the entire thesis. It also means the moment you
pair it with an actual tip from someone inside the deal, you are trading on
MNPI and the provenance of your other features will not save you.

What the signal actually is
---------------------------
Not "the CEO flew to Basel therefore buy". The tradable patterns are:

``convergence``
    Aircraft linked to two or more *different* issuers on the ground at the
    same airport within a short window. Advisers and principals meet in
    person for things that get announced.
``novel_destination``
    A tail visiting an airport it has not visited in the trailing year.
``activity_burst``
    Flight count for an issuer's fleet, z-scored against its own baseline.
    Controls for the fact that some companies simply fly constantly.
``offhours``
    Weekend and late-night legs. Deals get signed on Sundays.
``hub_visit``
    Legs into airports serving a known counterparty or regulator.

Coverage bias you must not ignore
---------------------------------
Companies can suppress their tail numbers from public feeds via the FAA's LADD
and PIA programmes, and the sophisticated ones do. Coverage is therefore
biased toward issuers that are not hiding, which is correlated with *not*
being in play. This is a real selection effect on the feature, and it is why
flight features enter the model as one input among many rather than as a
standalone trigger.

Point-in-time handling
----------------------
Positions are near-real-time, but two things lag: OpenSky's flight-level
aggregation (a leg appears once complete, not on takeoff), and the ownership
attribution, which comes from a registry snapshot refreshed monthly. The
registry must be read *as of* the trade date, not today -- an aircraft sold in
2023 was not the issuer's aircraft in 2021.
"""

from __future__ import annotations

import csv
import logging
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource

log = logging.getLogger(__name__)

OPENSKY_FLIGHTS_URL = "https://opensky-network.org/api/flights/aircraft"
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"

#: Delay before a completed leg is queryable and attributable.
FLIGHT_LAG = pd.Timedelta(hours=2)

#: Airports that show up disproportionately in deal and regulatory travel.
#: Not exhaustive -- extend via the CSV override.
NOTABLE_AIRPORTS: dict[str, str] = {
    "KTEB": "teterboro_nyc_finance",
    "KHPN": "westchester_nyc_finance",
    "KDCA": "washington_regulatory",
    "KIAD": "washington_regulatory",
    "KBWI": "baltimore_fda_corridor",
    "KSMO": "santa_monica_la",
    "KVNY": "van_nuys_la",
    "KPAO": "palo_alto_vc",
    "KSQL": "san_carlos_vc",
    "KBED": "bedford_boston_biotech",
    "KOWD": "norwood_boston_biotech",
    "LSZH": "zurich_pharma",
    "LFSB": "basel_pharma",
    "EGGW": "luton_london_finance",
    "EGLF": "farnborough_london_finance",
}


@dataclass
class TailRegistry:
    """icao24 -> issuer, with validity intervals so ownership is point-in-time.

    Build from the FAA releasable aircraft database (free, monthly:
    ``registry.faa.gov/database/ReleasableAircraft.zip``) joined on registrant
    name, or hand-maintain a CSV. The join is the hard part: aircraft are held
    in single-purpose LLCs whose names share nothing with the operating
    company, so expect to curate the high-value tails manually and accept
    partial coverage on the rest.

    CSV schema: ``icao24,ticker,owner,valid_from,valid_to`` with ISO dates and
    an empty ``valid_to`` meaning "still owned".
    """

    #: icao24 -> sorted list of (valid_from, valid_to_or_none, ticker, owner)
    records: dict[str, list[tuple[pd.Timestamp, pd.Timestamp | None, str, str]]] = field(
        default_factory=lambda: defaultdict(list)
    )

    def add(
        self,
        icao24: str,
        ticker: str,
        owner: str = "",
        valid_from: str | pd.Timestamp = "1990-01-01",
        valid_to: str | pd.Timestamp | None = None,
    ) -> None:
        key = icao24.lower().strip()
        self.records[key].append(
            (
                to_utc(valid_from),
                to_utc(valid_to) if valid_to not in (None, "", "NaT") else None,
                ticker.upper().strip(),
                owner,
            )
        )
        self.records[key].sort(key=lambda r: r[0])

    def owner_at(self, icao24: str, ts: pd.Timestamp) -> tuple[str, str] | None:
        """Who owned this airframe at ``ts``? ``None`` if unknown or unowned then."""
        ts = to_utc(ts)
        for valid_from, valid_to, ticker, owner in self.records.get(icao24.lower(), []):
            if valid_from <= ts and (valid_to is None or ts < valid_to):
                return ticker, owner
        return None

    @property
    def icao24s(self) -> list[str]:
        return sorted(self.records)

    def tickers_at(self, ts: pd.Timestamp) -> set[str]:
        out = set()
        for icao in self.records:
            hit = self.owner_at(icao, ts)
            if hit:
                out.add(hit[0])
        return out

    @classmethod
    def from_csv(cls, path: str | Path) -> TailRegistry:
        reg = cls()
        with open(path, newline="") as fh:
            for row in csv.DictReader(fh):
                reg.add(
                    icao24=row["icao24"],
                    ticker=row["ticker"],
                    owner=row.get("owner", ""),
                    valid_from=row.get("valid_from") or "1990-01-01",
                    valid_to=row.get("valid_to") or None,
                )
        log.info("tail registry: %d airframes", len(reg.records))
        return reg

    def to_csv(self, path: str | Path) -> None:
        with open(path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["icao24", "ticker", "owner", "valid_from", "valid_to"])
            for icao, recs in sorted(self.records.items()):
                for vf, vt, tkr, owner in recs:
                    w.writerow([icao, tkr, owner, vf.date(), vt.date() if vt else ""])


class OpenSkyFlights(EventSource):
    """Completed flight legs for registered corporate airframes.

    OpenSky's historical ``/flights/aircraft`` endpoint requires an
    authenticated account (anonymous callers get "You cannot access historical
    flights"). Without credentials this source disables itself rather than
    silently returning nothing, so ``iai doctor`` reports the gap.
    """

    name = "flights"
    default_latency = FLIGHT_LAG

    def __init__(self, *args, registry: TailRegistry | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.registry = registry or TailRegistry()
        has_creds = bool(self.cfg.data.opensky_user and self.cfg.data.opensky_pass)
        self.enabled = has_creds and bool(self.registry.records)
        self._auth = (
            (self.cfg.data.opensky_user, self.cfg.data.opensky_pass) if has_creds else None
        )

    def health(self) -> dict:
        if not self.cfg.data.opensky_user:
            reason = "set OPENSKY_USER/OPENSKY_PASS for historical flights"
        elif not self.registry.records:
            reason = "tail registry is empty; load one with TailRegistry.from_csv"
        else:
            reason = ""
        return {"name": self.name, "enabled": self.enabled, "reason": reason}

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        events: list[Event] = []
        # OpenSky caps a single query at 30 days per airframe.
        windows = list(pd.date_range(start, end, freq="30D"))
        if windows[-1] < end:
            windows.append(end)

        for icao in self.registry.icao24s:
            for w_start, w_end in zip(windows[:-1], windows[1:], strict=False):
                legs = self._legs(icao, w_start, w_end)
                for leg in legs:
                    ev = self._to_event(icao, leg, start, end)
                    if ev:
                        events.append(ev)
        return events

    def _legs(self, icao: str, start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
        blob = self.client.get(
            OPENSKY_FLIGHTS_URL,
            params={
                "icao24": icao,
                "begin": int(start.timestamp()),
                "end": int(end.timestamp()),
            },
            headers={"Authorization": self._basic()} if self._auth else None,
        )
        return blob if isinstance(blob, list) else []

    def _basic(self) -> str:
        import base64

        user, pwd = self._auth  # type: ignore[misc]
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        return f"Basic {token}"

    def _to_event(
        self, icao: str, leg: dict, start: pd.Timestamp, end: pd.Timestamp
    ) -> Event | None:
        arrival = leg.get("lastSeen")
        if not arrival:
            return None
        event_ts = to_utc(pd.Timestamp(int(arrival), unit="s", tz="UTC"))
        available = event_ts + FLIGHT_LAG
        if not (start <= available < end):
            return None
        owner = self.registry.owner_at(icao, event_ts)
        if not owner:
            return None
        ticker, owner_name = owner
        dest = leg.get("estArrivalAirport") or ""
        origin = leg.get("estDepartureAirport") or ""
        local_hour = event_ts.tz_convert("America/New_York")
        return Event(
            source=self.name,
            kind="flight.arrival",
            ticker=ticker,
            event_ts=event_ts,
            available_ts=available,
            payload={
                "id": f"{icao}:{arrival}",
                "icao24": icao,
                "owner": owner_name,
                "origin": origin,
                "destination": dest,
                "destination_tag": NOTABLE_AIRPORTS.get(dest, ""),
                "offhours": bool(local_hour.weekday() >= 5 or local_hour.hour >= 21 or local_hour.hour < 6),
                "duration_min": (leg.get("lastSeen", 0) - leg.get("firstSeen", 0)) / 60.0,
            },
            weight=1.0,
        )


class CsvFlights(EventSource):
    """Flight legs from a local CSV, for vendors other than OpenSky.

    Schema: ``icao24,arrival_utc,origin,destination`` (extra columns pass
    through into the payload). Use with ADS-B Exchange enterprise extracts,
    JetNet, or your own receiver logs.
    """

    name = "flights"
    default_latency = FLIGHT_LAG

    def __init__(self, *args, path: str | Path, registry: TailRegistry, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.path = Path(path)
        self.registry = registry
        self.enabled = self.path.exists()

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.enabled else f"{self.path} not found",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        df = pd.read_csv(self.path)
        out: list[Event] = []
        for row in df.to_dict("records"):
            event_ts = to_utc(row["arrival_utc"])
            available = event_ts + FLIGHT_LAG
            if not (start <= available < end):
                continue
            owner = self.registry.owner_at(str(row["icao24"]), event_ts)
            if not owner:
                continue
            ticker, owner_name = owner
            local = event_ts.tz_convert("America/New_York")
            dest = str(row.get("destination", ""))
            out.append(
                Event(
                    source=self.name,
                    kind="flight.arrival",
                    ticker=ticker,
                    event_ts=event_ts,
                    available_ts=available,
                    payload={
                        "id": f"{row['icao24']}:{event_ts.isoformat()}",
                        "icao24": str(row["icao24"]),
                        "owner": owner_name,
                        "origin": str(row.get("origin", "")),
                        "destination": dest,
                        "destination_tag": NOTABLE_AIRPORTS.get(dest, ""),
                        "offhours": bool(local.weekday() >= 5 or local.hour >= 21 or local.hour < 6),
                    },
                )
            )
        return out


def detect_convergence(
    events: pd.DataFrame, window_hours: float = 12.0, min_issuers: int = 2
) -> list[dict]:
    """Find airports where aircraft of >=``min_issuers`` issuers coincided.

    Returns one record per (airport, cluster) with the participating tickers
    and the timestamp at which the *last* of them landed -- which is the
    earliest moment the pattern was observable.
    """
    if events.empty:
        return []
    fl = events[events["source"] == "flights"].copy()
    if fl.empty:
        return []
    fl["destination"] = fl["payload"].map(lambda p: (p or {}).get("destination", ""))
    fl = fl[fl["destination"].astype(bool)].sort_values("event_ts")

    out: list[dict] = []
    for airport, grp in fl.groupby("destination", observed=True):
        times = grp["event_ts"].tolist()
        tickers = grp["ticker"].tolist()
        avail = grp["available_ts"].tolist()
        secs = [t.timestamp() for t in times]
        span = window_hours * 3600.0
        for i in range(len(secs)):
            j = bisect_right(secs, secs[i] + span)
            members = set(tickers[i:j])
            if len(members) >= min_issuers:
                out.append(
                    {
                        "airport": airport,
                        "tickers": sorted(members),
                        "n_issuers": len(members),
                        "event_ts": times[j - 1],
                        "available_ts": max(avail[i:j]),
                    }
                )
    return out


def convergence_events(events: pd.DataFrame, **kwargs) -> list[Event]:
    """Emit a ``flight.convergence`` event on every ticker in each cluster."""
    out: list[Event] = []
    for cluster in detect_convergence(events, **kwargs):
        for tkr in cluster["tickers"]:
            others = [t for t in cluster["tickers"] if t != tkr]
            out.append(
                Event(
                    source="flights",
                    kind="flight.convergence",
                    ticker=tkr,
                    event_ts=cluster["event_ts"],
                    available_ts=cluster["available_ts"],
                    payload={
                        "id": f"conv:{cluster['airport']}:{cluster['event_ts'].isoformat()}:{tkr}",
                        "airport": cluster["airport"],
                        "counterparties": others,
                        "n_issuers": cluster["n_issuers"],
                    },
                    # Scale with cluster size: three issuers in one place is a
                    # much stronger tell than two.
                    weight=1.0 + 0.75 * (cluster["n_issuers"] - 1),
                )
            )
    return out
