"""Seaborne trade and import/export flows.

Three tiers, in descending order of usefulness and ascending order of cost.

1. ``BillOfLading`` -- **name-level, the only tier with real single-stock alpha.**
   US Customs vessel manifests name the consignee, the shipper, the commodity
   and the container count for every ocean import. When a consignee resolves
   to a listed issuer you get that issuer's physical import volume, weeks
   before it shows up in a 10-Q. There is no free API: the data is released in
   bulk by CBP and resold by ImportGenius, Panjiva/S&P, Descartes Datamyne and
   Tradlinx. This class reads a CSV extract, which is what every one of those
   vendors will sell you. Air freight is *not* in the manifest data, which
   biases coverage against high-value/low-weight industries -- semiconductors
   and pharmaceuticals move by air, so their import signal is systematically
   understated.

2. ``AISPortCalls`` -- vessel-level. Which ships called at which terminals and
   how long they stayed. Free-ish options are AISHub (requires you to
   contribute a receiver feed) and NOAA Marine Cadastre (free, US waters,
   ~1 year lag -- useless for live trading, useful for backtest construction).
   Paid: Kpler, Windward, Spire, MarineTraffic. Attribution from a berth to an
   issuer requires a terminal-ownership map, which you build once by hand.

3. ``ComtradeFlows`` -- **country x commodity, free, no key needed.** UN
   Comtrade monthly bilateral trade. This is macro, not single-stock: it tells
   you Chinese lithium carbonate exports to Korea fell 30% month-over-month,
   which is a sector tilt and a cost-input signal, not a reason to buy one
   ticker. Published with a one-to-three month lag, which the availability
   logic below models explicitly.

The honest summary: tier 3 is free and weak, tier 1 is expensive and genuinely
differentiated, tier 2 is in between and operationally annoying. This module
gives all three the same interface so you can start on tier 3 and upgrade
without touching the model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..core.types import Event, to_utc
from .base import EventSource

log = logging.getLogger(__name__)

COMTRADE_URL = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"

#: Comtrade publishes a reference month roughly this long after it ends, and
#: revises for months afterward. Using the reference month as the availability
#: date is the single most common lookahead bug in trade-data backtests.
COMTRADE_PUBLICATION_LAG = pd.Timedelta(days=75)

#: US Customs manifest data reaches resellers a few days after vessel arrival.
BOL_LAG = pd.Timedelta(days=4)

#: AIS positions are near-real-time; berth-level interpretation is not.
AIS_LAG = pd.Timedelta(hours=6)


@dataclass
class TradeExposure:
    """Which issuers care about which trade lanes.

    ``by_ticker[ticker]`` is a list of (hs_code_prefix, partner_country_code,
    direction, sensitivity). Direction is ``"M"`` (the issuer imports this, so
    rising volume means rising input cost or rising demand depending on sign)
    or ``"X"``. Sensitivity is signed: +1 means higher flow is good for the
    issuer, -1 means it is bad.

    Build this by hand from 10-K risk factors and segment disclosures. It is a
    few hours of work for a hundred names and it is the difference between
    trade data being a signal and being noise.
    """

    by_ticker: dict[str, list[tuple[str, str, str, float]]] = field(default_factory=dict)

    def add(self, ticker: str, hs: str, partner: str, direction: str = "M", sensitivity: float = 1.0) -> None:
        self.by_ticker.setdefault(ticker.upper(), []).append((hs, partner, direction, sensitivity))

    def lanes(self) -> set[tuple[str, str, str]]:
        return {(hs, partner, d) for v in self.by_ticker.values() for hs, partner, d, _ in v}

    def tickers_for(self, hs: str, partner: str, direction: str) -> list[tuple[str, float]]:
        out = []
        for tkr, rows in self.by_ticker.items():
            for r_hs, r_partner, r_dir, sens in rows:
                if r_dir == direction and hs.startswith(r_hs) and r_partner in (partner, "ALL"):
                    out.append((tkr, sens))
        return out

    @classmethod
    def from_csv(cls, path: str | Path) -> TradeExposure:
        exp = cls()
        df = pd.read_csv(path)
        for row in df.to_dict("records"):
            exp.add(
                str(row["ticker"]),
                str(row["hs"]),
                str(row.get("partner", "ALL")),
                str(row.get("direction", "M")),
                float(row.get("sensitivity", 1.0)),
            )
        return exp


class ComtradeFlows(EventSource):
    """Monthly bilateral trade flows, mapped to issuers via :class:`TradeExposure`.

    Emits an event when a lane's month-over-month change exceeds a threshold,
    z-scored against that lane's own history so a seasonal commodity does not
    fire every December.
    """

    name = "trade"
    default_latency = COMTRADE_PUBLICATION_LAG

    def __init__(
        self,
        *args,
        exposure: TradeExposure | None = None,
        reporter: str = "842",  # USA
        z_threshold: float = 1.5,
        history_months: int = 36,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.exposure = exposure or TradeExposure()
        self.reporter = reporter
        self.z_threshold = z_threshold
        self.history_months = history_months
        self.enabled = bool(self.exposure.by_ticker)

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": "" if self.enabled else "TradeExposure map is empty; nothing to attribute",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        # Work back from availability to the reference months that would have
        # been published inside our window.
        ref_start = (start - COMTRADE_PUBLICATION_LAG).normalize()
        ref_end = (end - COMTRADE_PUBLICATION_LAG).normalize()
        hist_start = ref_start - pd.DateOffset(months=self.history_months)

        events: list[Event] = []
        for hs, partner, direction in sorted(self.exposure.lanes()):
            series = self._series(hs, partner, direction, hist_start, ref_end)
            if series is None or len(series) < 12:
                continue
            events.extend(
                self._to_events(series, hs, partner, direction, ref_start, ref_end, start, end)
            )
        return events

    def _series(
        self, hs: str, partner: str, direction: str, start: pd.Timestamp, end: pd.Timestamp
    ) -> pd.Series | None:
        periods = pd.date_range(start, end, freq="MS").strftime("%Y%m").tolist()
        if not periods:
            return None
        values: dict[pd.Timestamp, float] = {}
        # Comtrade accepts comma-joined periods; chunk to keep URLs sane.
        for i in range(0, len(periods), 12):
            chunk = ",".join(periods[i : i + 12])
            params = {
                "reporterCode": self.reporter,
                "period": chunk,
                "cmdCode": hs,
                "flowCode": direction,
                "partnerCode": "0" if partner == "ALL" else partner,
            }
            if self.cfg.data.comtrade_key:
                params["subscription-key"] = self.cfg.data.comtrade_key
            blob = self.client.get(COMTRADE_URL, params=params)
            for rec in (blob or {}).get("data", []):
                period = str(rec.get("period", ""))
                val = rec.get("primaryValue")
                if len(period) == 6 and val is not None:
                    values[pd.Timestamp(f"{period[:4]}-{period[4:]}-01")] = float(val)
        if not values:
            return None
        return pd.Series(values).sort_index()

    def _to_events(
        self,
        series: pd.Series,
        hs: str,
        partner: str,
        direction: str,
        ref_start: pd.Timestamp,
        ref_end: pd.Timestamp,
        start: pd.Timestamp,
        end: pd.Timestamp,
    ) -> list[Event]:
        # Year-over-year log change strips the seasonality that wrecks
        # month-over-month comparisons on commodity lanes. The z-score baseline
        # is expanding rather than full-sample so it only ever uses the past.
        ratio = series / series.shift(12)
        logy = np.log(ratio.where(ratio > 0))
        z = (logy - logy.expanding(min_periods=12).mean()) / logy.expanding(min_periods=12).std()

        out: list[Event] = []
        for ref_month, score in z.items():
            if pd.isna(score) or abs(score) < self.z_threshold:
                continue
            if not (ref_start <= to_utc(ref_month).tz_localize(None) <= ref_end):
                continue
            available = to_utc(ref_month + pd.offsets.MonthEnd(1)) + COMTRADE_PUBLICATION_LAG
            if not (start <= available < end):
                continue
            for ticker, sensitivity in self.exposure.tickers_for(hs, partner, direction):
                direction_word = "surge" if score > 0 else "collapse"
                out.append(
                    Event(
                        source=self.name,
                        kind=f"trade.{direction_word}",
                        ticker=ticker,
                        event_ts=to_utc(ref_month + pd.offsets.MonthEnd(1)),
                        available_ts=available,
                        payload={
                            "id": f"{hs}:{partner}:{direction}:{ref_month:%Y%m}:{ticker}",
                            "hs": hs,
                            "partner": partner,
                            "flow": direction,
                            "z": float(score),
                            "signed_z": float(score) * sensitivity,
                            "ref_month": f"{ref_month:%Y-%m}",
                        },
                        weight=min(abs(float(score)), 4.0) / 2.0,
                    )
                )
        return out


class BillOfLading(EventSource):
    """Name-level US import manifests from a vendor CSV extract.

    Expected columns: ``arrival_date, consignee, shipper, hs_code, teu,
    weight_kg, port, country_of_origin``. Consignee strings are filthy --
    "SAMSUNG ELECTRONICS AMERICA INC C/O EXPEDITORS" -- so resolution goes
    through :meth:`Universe.resolve_name` and misses are logged rather than
    silently dropped.

    The emitted event is not "a shipment arrived" but "this issuer's trailing
    import volume deviated from its own baseline", because a single container
    is noise and the level is what matters.
    """

    name = "shipping"
    default_latency = BOL_LAG

    def __init__(
        self,
        *args,
        path: str | Path | None = None,
        baseline_weeks: int = 26,
        z_threshold: float = 1.5,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path = Path(path) if path else None
        self.baseline_weeks = baseline_weeks
        self.z_threshold = z_threshold
        self.enabled = bool(self.path and self.path.exists())

    def health(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "reason": ""
            if self.enabled
            else "no manifest extract; buy from ImportGenius/Panjiva/Descartes and point --bol at the CSV",
        }

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        df = pd.read_csv(self.path)
        df["arrival_date"] = pd.to_datetime(df["arrival_date"])
        df["ticker"] = df["consignee"].map(lambda n: self.universe.resolve_name(str(n), record_misses=True))
        matched = df.dropna(subset=["ticker"])
        if matched.empty:
            log.warning("bill of lading: no consignees resolved to the universe")
            return []
        log.info(
            "bill of lading: resolved %d/%d rows (%.1f%%)",
            len(matched), len(df), 100 * len(matched) / len(df),
        )

        metric = "teu" if "teu" in matched.columns else "weight_kg"
        weekly = (
            matched.set_index("arrival_date")
            .groupby("ticker", observed=True)[metric]
            .resample("W")
            .sum()
            .reset_index()
        )

        out: list[Event] = []
        for ticker, grp in weekly.groupby("ticker", observed=True):
            s = grp.set_index("arrival_date")[metric].astype("float64")
            mean = s.rolling(self.baseline_weeks, min_periods=8).mean().shift(1)
            std = s.rolling(self.baseline_weeks, min_periods=8).std().shift(1)
            z = (s - mean) / std
            for week_end, score in z.items():
                if pd.isna(score) or abs(score) < self.z_threshold:
                    continue
                event_ts = to_utc(week_end)
                available = event_ts + BOL_LAG
                if not (start <= available < end):
                    continue
                out.append(
                    Event(
                        source=self.name,
                        kind="shipping.surge" if score > 0 else "shipping.slump",
                        ticker=str(ticker),
                        event_ts=event_ts,
                        available_ts=available,
                        payload={
                            "id": f"bol:{ticker}:{week_end:%Y%m%d}",
                            "z": float(score),
                            "metric": metric,
                            "value": float(s.loc[week_end]),
                        },
                        weight=min(abs(float(score)), 4.0) / 2.0,
                    )
                )
        return out


class AISPortCalls(EventSource):
    """Vessel port calls from an AIS extract.

    Expected columns: ``imo, vessel_name, port, berth, arrival_utc,
    departure_utc, draught_arrival, draught_departure``. The draught delta is
    the useful part: a vessel riding higher on departure discharged cargo, and
    how much higher tells you roughly how much. Attribution to an issuer needs
    ``berth_owner_map``, a dict of berth or terminal identifier -> ticker,
    which you build once from terminal ownership records.
    """

    name = "shipping_ais"
    default_latency = AIS_LAG

    def __init__(
        self,
        *args,
        path: str | Path | None = None,
        berth_owner_map: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.path = Path(path) if path else None
        self.berth_owner_map = {k.upper(): v.upper() for k, v in (berth_owner_map or {}).items()}
        self.enabled = bool(self.path and self.path.exists() and self.berth_owner_map)

    def health(self) -> dict:
        if not (self.path and self.path.exists()):
            reason = "no AIS extract (try NOAA Marine Cadastre for backtest, Kpler/Spire for live)"
        elif not self.berth_owner_map:
            reason = "berth_owner_map is empty; port calls cannot be attributed to issuers"
        else:
            reason = ""
        return {"name": self.name, "enabled": self.enabled, "reason": reason}

    def fetch(self, start: pd.Timestamp, end: pd.Timestamp) -> list[Event]:
        if not self.enabled:
            return []
        start, end = to_utc(start), to_utc(end)
        df = pd.read_csv(self.path)
        out: list[Event] = []
        for row in df.to_dict("records"):
            berth = str(row.get("berth") or row.get("port") or "").upper()
            ticker = self.berth_owner_map.get(berth)
            if not ticker:
                continue
            departure = row.get("departure_utc")
            if pd.isna(departure) or not departure:
                continue
            event_ts = to_utc(departure)
            available = event_ts + AIS_LAG
            if not (start <= available < end):
                continue
            d_in = row.get("draught_arrival")
            d_out = row.get("draught_departure")
            delta = (float(d_in) - float(d_out)) if pd.notna(d_in) and pd.notna(d_out) else None
            dwell_h = (to_utc(departure) - to_utc(row["arrival_utc"])).total_seconds() / 3600.0
            out.append(
                Event(
                    source=self.name,
                    kind="portcall.discharge" if (delta or 0) > 0 else "portcall.load",
                    ticker=ticker,
                    event_ts=event_ts,
                    available_ts=available,
                    payload={
                        "id": f"ais:{row.get('imo')}:{event_ts.isoformat()}",
                        "imo": row.get("imo"),
                        "vessel": row.get("vessel_name", ""),
                        "berth": berth,
                        "draught_delta": delta,
                        "dwell_hours": dwell_h,
                    },
                    weight=min(abs(delta or 0.5), 4.0) / 2.0,
                )
            )
        return out
