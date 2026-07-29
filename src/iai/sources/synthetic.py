"""A deterministic synthetic market, for testing the machinery.

Why this exists
---------------
Every component downstream of the sources -- point-in-time joins, triple
barrier labelling, purged walk-forward, Kelly sizing, the cost model -- can be
wrong in ways that are invisible when you are also fighting flaky APIs and
missing credentials. This module generates a world where the ground truth is
known by construction, so a test can assert that the pipeline *recovers* the
planted effect and, just as importantly, does not find effects that were never
planted.

Read this before believing any number the demo prints
-----------------------------------------------------
The synthetic world contains real, planted predictability. A backtest on it
will look good. **That says nothing whatsoever about whether this strategy
works on real markets.** It says the plumbing is connected. Two of the six
event kinds here are deliberately pure noise precisely so you can check that
the model assigns them no importance -- if it does assign them importance,
something is overfitting and the number you are looking at is a lie.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..core.calendar import sessions
from ..core.types import Event, to_utc
from ..core.universe import Universe

#: (source, kind, annual rate per name, forward drift over 10 sessions, weight).
#:
#: ``source`` must match the names the real adapters emit -- ``edgar``,
#: ``edgar_fts``, ``litigation``, ``flights``, ``shipping`` -- so the synthetic
#: world exercises the same family-aggregation path in
#: :mod:`iai.features.events` that live data does. Using cosmetic names here
#: silently routes every synthetic event into the ``other`` family and the
#: demo stops testing the code that actually runs in production.
#:
#: Drift of 0.0 marks a deliberate control. ``docket.securities`` is planted
#: negative, so recovery requires finding the sign as well as the magnitude.
#: The magnitudes are chosen to be *realistic* -- a 2% post-event drift is
#: about what a real 8-K Item 1.01 delivers -- which is why the resulting model
#: AUC is ~0.54 rather than something impressive. That is the honest number for
#: this problem; a synthetic world tuned to produce AUC 0.75 would validate
#: nothing except the tuning.
PLANTED_EFFECTS: list[tuple[str, str, float, float, float]] = [
    ("edgar", "8-K.1.01", 6.0, 0.020, 2.0),            # real positive: material agreements
    ("edgar_fts", "catalyst.merger", 0.4, 0.070, 3.0),  # real, large, rare
    ("litigation", "docket.securities", 1.2, -0.035, 3.0),  # real negative
    ("flights", "flight.convergence", 2.0, 0.030, 2.0),  # real positive
    ("edgar", "8-K.7.01", 14.0, 0.0, 0.6),             # CONTROL: noise, high frequency
    ("shipping", "shipping.surge", 4.0, 0.0, 1.0),     # CONTROL: pure noise
]


@dataclass
class SyntheticWorld:
    n_tickers: int = 60
    start: str = "2019-01-02"
    end: str = "2024-12-31"
    seed: int = 7
    #: Annualised idiosyncratic vol range. Wide, to exercise the
    #: volatility-scaled barrier logic on both a utility and a microcap.
    vol_range: tuple[float, float] = (0.25, 0.95)
    market_vol: float = 0.16

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(self.seed)
        self.dates = sessions(self.start, self.end)
        self.tickers = [f"SYN{i:03d}" for i in range(self.n_tickers)]
        self.betas = self.rng.uniform(0.4, 1.6, self.n_tickers)
        self.vols = self.rng.uniform(*self.vol_range, self.n_tickers)
        self.sector_names = ["biotech", "tech", "industrial", "energy", "consumer", "financial"]
        self.sector_of = {
            t: self.sector_names[i % len(self.sector_names)] for i, t in enumerate(self.tickers)
        }

    def sectors(self) -> dict[str, str]:
        """Sector map, so the demo exercises the sector concentration limit."""
        return dict(self.sector_of)

    def universe(self) -> Universe:
        uni = Universe()
        for i, t in enumerate(self.tickers):
            uni.add(ticker=t, cik=str(1000000 + i), name=f"Synthetic Holdings {i} Inc")
        return uni

    def generate(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return ``(prices, events)``.

        Events are generated first so their price impact can be injected into
        the return series, which is what makes the world learnable.
        """
        events = self._events()
        prices = self._prices(events)
        return prices, events

    def _events(self) -> pd.DataFrame:
        n_days = len(self.dates)
        years = n_days / 252.0
        rows = []
        for source, kind, rate, _drift, weight in PLANTED_EFFECTS:
            for t_idx, ticker in enumerate(self.tickers):
                n = self.rng.poisson(rate * years)
                if n == 0:
                    continue
                day_idx = self.rng.choice(n_days, size=min(n, n_days), replace=False)
                for di in day_idx:
                    day = self.dates[di]
                    # Land the event at a random hour, so the entry-session
                    # logic gets exercised on both sides of the close.
                    hour = int(self.rng.integers(7, 22))
                    event_ts = to_utc(
                        pd.Timestamp(day).tz_localize("America/New_York") + pd.Timedelta(hours=hour)
                    )
                    rows.append(
                        {
                            "source": source,
                            "kind": kind,
                            "ticker": ticker,
                            "event_ts": event_ts,
                            "available_ts": event_ts + pd.Timedelta(minutes=15),
                            "weight": weight,
                            "payload": {"id": f"{ticker}:{kind}:{di}", "synthetic": True},
                            "_day_idx": int(di),
                            "_ticker_idx": t_idx,
                        }
                    )
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["uid"] = [f"syn{i:07d}" for i in range(len(df))]
        return df.sort_values("available_ts").reset_index(drop=True)

    def _prices(self, events: pd.DataFrame) -> pd.DataFrame:
        n_days, n_names = len(self.dates), len(self.tickers)
        daily_mkt_vol = self.market_vol / np.sqrt(252)
        market = self.rng.normal(0.0002, daily_mkt_vol, n_days)

        idio = self.rng.normal(0.0, 1.0, (n_days, n_names)) * (self.vols / np.sqrt(252))
        rets = market[:, None] * self.betas[None, :] + idio

        # Inject planted drift: spread the effect over the 10 sessions after the
        # event so it is a drift to be captured, not a one-bar jump that no
        # realistic execution could catch.
        drift_by_kind = {k: d for _, k, _, d, _ in PLANTED_EFFECTS}
        horizon = 10
        if not events.empty:
            # itertuples mangles leading-underscore column names, so read the
            # generator's bookkeeping columns as arrays instead.
            kinds = events["kind"].to_numpy()
            day_idx = events["_day_idx"].to_numpy()
            tkr_idx = events["_ticker_idx"].to_numpy()
            for k in range(len(kinds)):
                drift = drift_by_kind.get(kinds[k], 0.0)
                if drift == 0.0:
                    continue
                # Entry is the next session, so the drift starts one bar after
                # the event: an effect beginning on the event bar itself would
                # be uncapturable and would flatter the backtest.
                lo = min(int(day_idx[k]) + 1, n_days - 1)
                hi = min(lo + horizon, n_days)
                per_bar = drift / max(hi - lo, 1)
                j = int(tkr_idx[k])
                # Scale by the name's own vol so the planted effect is a
                # constant information ratio, not a constant return.
                rets[lo:hi, j] += per_bar * (self.vols[j] / 0.5)

        close = 20.0 * np.exp(np.cumsum(rets, axis=0)) * self.rng.uniform(0.5, 5.0, n_names)
        intraday = np.abs(self.rng.normal(0, 0.006, (n_days, n_names)))
        open_ = close * (1 + self.rng.normal(0, 0.004, (n_days, n_names)))
        high = np.maximum(open_, close) * (1 + intraday)
        low = np.minimum(open_, close) * (1 - intraday)
        base_vol = self.rng.uniform(2e5, 4e6, n_names)
        volume = base_vol[None, :] * np.exp(self.rng.normal(0, 0.4, (n_days, n_names)))

        frames = []
        for j, ticker in enumerate(self.tickers):
            frames.append(
                pd.DataFrame(
                    {
                        "date": self.dates,
                        "ticker": ticker,
                        "open": open_[:, j],
                        "high": high[:, j],
                        "low": low[:, j],
                        "close": close[:, j],
                        "volume": volume[:, j],
                        "adj_factor": 1.0,
                    }
                )
            )
        return pd.concat(frames, ignore_index=True)


def synthetic_events_to_frame(events: pd.DataFrame) -> pd.DataFrame:
    """Drop the generator's private columns so the frame matches the event schema."""
    from ..core.types import EVENT_COLUMNS

    if events.empty:
        from ..core.types import events_to_frame

        return events_to_frame([])
    return events[EVENT_COLUMNS].reset_index(drop=True)


def make_events(world: SyntheticWorld) -> list[Event]:
    """Materialise as :class:`Event` objects, for source-level tests."""
    df = world._events()
    return [
        Event(
            source=r.source,
            kind=r.kind,
            ticker=r.ticker,
            event_ts=r.event_ts,
            available_ts=r.available_ts,
            payload=r.payload,
            weight=r.weight,
        )
        for r in df.itertuples(index=False)
    ]
