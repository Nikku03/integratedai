"""Transaction costs.

A catalyst strategy trades small caps on news days. That is the single worst
combination for execution: spreads widen on news, depth evaporates, and the
names are illiquid to begin with. A backtest that assumes 5bp round-trip on
this universe is not optimistic, it is fictional.

The model here has three components, all charged on both entry and exit:

``spread``
    Half the quoted spread. Scaled by a news-day multiplier, because the
    spread you sampled on a quiet Tuesday is not the spread you will pay in the
    first hour after an 8-K.
``impact``
    Square-root law: ``impact = coef * sqrt(order / ADV)``. The square root is
    the standard empirical form; the coefficient is the part you must calibrate
    against your own fills, and the default here is a plausible mid-range value
    for US small caps, not a measurement of your broker.
``commission``
    Linear, small, and the least of your problems.

Shorts additionally accrue borrow. Hard-to-borrow small caps in the middle of a
catalyst can run 20-100% annualised, which is frequently larger than the entire
expected edge -- which is why the default configuration of this package is long
only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core.config import Config


def spread_cost_bps(cfg: Config, news_day: bool = False) -> float:
    """Half-spread in basis points, widened on news days."""
    return cfg.costs.half_spread_bps * (2.0 if news_day else 1.0)


def impact_bps(order_usd: np.ndarray | float, adv_usd: np.ndarray | float, cfg: Config) -> np.ndarray:
    """Square-root market impact in basis points.

    Order size and ADV are broadcast against each other explicitly. Passing a
    scalar order with a vector of ADVs -- "what would a fixed $25k clip cost
    across every name?" -- is the natural way to ask the cost question, and the
    previous version allocated its ``out`` buffer from the *order* alone, so
    that call raised a broadcasting error instead of answering.
    """
    order, adv = np.broadcast_arrays(
        np.asarray(order_usd, dtype="float64"),
        np.asarray(adv_usd, dtype="float64"),
    )
    participation = np.divide(
        np.abs(order), adv, out=np.zeros(order.shape, dtype="float64"), where=adv > 0
    )
    return cfg.costs.impact_coef_bps * np.sqrt(np.clip(participation, 0.0, 1.0))


def total_cost_bps(
    order_usd: np.ndarray | float,
    adv_usd: np.ndarray | float,
    cfg: Config,
    news_day: bool = False,
) -> np.ndarray:
    """One-way cost in basis points."""
    return (
        cfg.costs.commission_bps
        + spread_cost_bps(cfg, news_day)
        + impact_bps(order_usd, adv_usd, cfg)
    )


def apply_participation_cap(
    order_usd: np.ndarray | float, adv_usd: np.ndarray | float, cfg: Config
) -> np.ndarray:
    """Truncate orders that would take too much of the day's volume.

    Without this, the backtest quietly assumes it can buy $5m of a name that
    trades $800k a day. Capping is more honest than paying a huge modelled
    impact, because in reality you would not get the fill at all.
    """
    order = np.asarray(order_usd, dtype="float64")
    adv = np.asarray(adv_usd, dtype="float64")
    cap = adv * cfg.costs.max_participation
    return np.sign(order) * np.minimum(np.abs(order), np.where(adv > 0, cap, np.abs(order)))


def borrow_cost(notional: float, days: int, cfg: Config) -> float:
    """Borrow accrual for a short, in dollars."""
    return abs(notional) * (cfg.costs.borrow_bps_annual / 10_000.0) * (days / 252.0)


def cost_summary(fills: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Break down where the money went. Read this before believing a Sharpe."""
    if fills.empty:
        return pd.DataFrame()
    total = fills["cost_usd"].sum()
    gross = fills["notional"].abs().sum()
    return pd.DataFrame(
        [
            {
                "n_fills": len(fills),
                "gross_traded_usd": float(gross),
                "total_cost_usd": float(total),
                "avg_cost_bps": float(1e4 * total / gross) if gross else np.nan,
                "median_participation": float(fills.get("participation", pd.Series([np.nan])).median()),
                "capped_orders": int(fills.get("capped", pd.Series([0])).sum()),
            }
        ]
    )
