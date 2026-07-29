"""Pre-trade limit checks and the drawdown kill switch.

Every limit here is a hard stop evaluated before an order is sent, not a
soft preference expressed in an objective function. The distinction matters:
an optimiser will happily trade a limit breach for expected return if the
return is large enough, and the whole point of a limit is that it is not for
sale.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..core.config import Config

log = logging.getLogger(__name__)


@dataclass
class LimitBreach:
    limit: str
    detail: str
    severity: str = "block"  # "block" rejects the order; "warn" logs and allows


@dataclass
class RiskState:
    """Mutable book state the limit checks read."""

    capital: float
    peak_equity: float
    equity: float
    positions: dict[str, float] = field(default_factory=dict)  # ticker -> weight
    sectors: dict[str, str] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str = ""

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return self.equity / self.peak_equity - 1.0

    @property
    def gross(self) -> float:
        return float(sum(abs(w) for w in self.positions.values()))

    @property
    def net(self) -> float:
        return float(sum(self.positions.values()))

    def sector_weights(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for tkr, w in self.positions.items():
            sec = self.sectors.get(tkr, "unknown")
            out[sec] = out.get(sec, 0.0) + abs(w)
        return out


def check_limits(
    state: RiskState, proposed: pd.DataFrame, cfg: Config
) -> tuple[pd.DataFrame, list[LimitBreach]]:
    """Filter ``proposed`` down to what the limits allow.

    Returns the allowed subset and the list of breaches. Orders are dropped
    individually where possible rather than rejecting the whole basket, except
    for the kill switch, which rejects everything.
    """
    rc = cfg.risk
    breaches: list[LimitBreach] = []

    if state.halted:
        breaches.append(LimitBreach("halted", f"trading halted: {state.halt_reason}"))
        return proposed.iloc[0:0], breaches

    if state.drawdown <= -rc.max_drawdown:
        state.halted = True
        state.halt_reason = f"drawdown {state.drawdown:.1%} breached limit {-rc.max_drawdown:.1%}"
        breaches.append(LimitBreach("max_drawdown", state.halt_reason))
        return proposed.iloc[0:0], breaches

    if proposed.empty:
        return proposed, breaches

    df = proposed.copy()
    keep = np.ones(len(df), dtype=bool)

    # Per-name cap, counting what we already hold.
    for i, row in enumerate(df.itertuples(index=False)):
        existing = state.positions.get(row.ticker, 0.0)
        if abs(existing + row.weight) > rc.max_weight_per_name + 1e-9:
            keep[i] = False
            breaches.append(
                LimitBreach(
                    "max_weight_per_name",
                    f"{row.ticker}: {existing + row.weight:.3f} > {rc.max_weight_per_name:.3f}",
                )
            )

    df = df[keep].copy()
    if df.empty:
        return df, breaches

    # Position count.
    room = rc.max_positions - len(state.positions)
    if room <= 0:
        breaches.append(LimitBreach("max_positions", f"already holding {len(state.positions)}"))
        return df.iloc[0:0], breaches
    if len(df) > room:
        df = df.sort_values("edge", ascending=False).head(room)
        breaches.append(LimitBreach("max_positions", f"truncated to {room} new positions", "warn"))

    # Sector caps, evaluated cumulatively so the basket cannot collectively
    # breach a limit that no single order breaches.
    if "sector" in df.columns:
        # Best-edge-first, so when a sector fills up the orders that survive are
        # the ones worth keeping.
        df = df.sort_values("edge", ascending=False)
        running = state.sector_weights()
        mask = []
        for row in df.itertuples(index=False):
            sec = getattr(row, "sector", "unknown")
            new_total = running.get(sec, 0.0) + abs(row.weight)
            ok = new_total <= rc.max_sector_weight + 1e-9
            if ok:
                running[sec] = new_total
            else:
                breaches.append(
                    LimitBreach(
                        "max_sector_weight",
                        f"{row.ticker} would take {sec} to {new_total:.3f} > {rc.max_sector_weight:.3f}",
                    )
                )
            mask.append(ok)
        df = df[pd.Series(mask, index=df.index)]
        if df.empty:
            return df, breaches

    # Gross and net, scaled down proportionally rather than dropped.
    proposed_gross = state.gross + df["weight"].abs().sum()
    if proposed_gross > rc.max_gross_exposure:
        room_gross = max(rc.max_gross_exposure - state.gross, 0.0)
        current = df["weight"].abs().sum()
        if current > 0 and room_gross > 0:
            df["weight"] *= room_gross / current
            breaches.append(
                LimitBreach("max_gross_exposure", f"scaled basket to fit {room_gross:.2f} gross", "warn")
            )
        else:
            breaches.append(LimitBreach("max_gross_exposure", "no gross room"))
            return df.iloc[0:0], breaches

    proposed_net = state.net + df["weight"].sum()
    if abs(proposed_net) > rc.max_net_exposure:
        breaches.append(
            LimitBreach("max_net_exposure", f"net {proposed_net:.2f} > {rc.max_net_exposure:.2f}", "warn")
        )

    return df.reset_index(drop=True), breaches


def stop_levels(entry_price: float, sigma_daily: float, cfg: Config) -> tuple[float, float]:
    """(stop_price, stop_pct) for a long, from trailing volatility.

    The stop is set from the name's own volatility, not a fixed percentage: a
    3% stop on a 90%-vol biotech is noise and will be hit by lunchtime.
    """
    horizon_sigma = sigma_daily * np.sqrt(cfg.risk.max_holding_days)
    stop_pct = float(np.clip(cfg.risk.stop_loss_sigma * horizon_sigma, 0.02, 0.35))
    return entry_price * (1 - stop_pct), stop_pct


def should_exit(
    entry_price: float,
    current_price: float,
    days_held: int,
    stop_pct: float,
    target_pct: float,
    cfg: Config,
) -> tuple[bool, str]:
    """Exit rule matching the triple barrier the model was trained on.

    Keeping these identical is not a detail. If the model is trained on 15-day
    triple-barrier outcomes and the live book holds for 40 days, the model's
    probabilities describe a trade nobody is making.
    """
    ret = current_price / entry_price - 1.0
    if ret <= -stop_pct:
        return True, "stop"
    if ret >= target_pct:
        return True, "target"
    if days_held >= cfg.risk.max_holding_days:
        return True, "time"
    return False, ""
