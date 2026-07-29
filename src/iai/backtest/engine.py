"""Daily portfolio simulation.

Mechanics, stated explicitly because the details are where backtests lie:

* Signals dated ``t`` are acted on at the **open of ``t+1``**. Never the close
  of ``t``, which is the most common way to accidentally trade on information
  released after the close.
* Fills are at the open plus one-way costs. No mid, no VWAP fantasy.
* Orders are capped at a fraction of ADV and the truncation is *recorded*, so
  a strategy whose paper returns depend on impossible fills is visible rather
  than silently profitable.
* Exits use the same triple-barrier rule the model was trained on, checked
  against intraday highs and lows.
* When both barriers fall inside one bar, the stop is assumed to have traded
  first. Daily data cannot resolve the order, and the optimistic assumption
  flatters exactly the most volatile names.
* Positions are marked at the close each day; equity is cash plus marks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..core.config import Config
from ..risk.limits import RiskState, check_limits, stop_levels
from ..risk.sizing import size_positions
from .costs import apply_participation_cap, total_cost_bps

log = logging.getLogger(__name__)


@dataclass
class Position:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    shares: float
    stop_pct: float
    target_pct: float
    sector: str = "unknown"

    @property
    def notional(self) -> float:
        return self.shares * self.entry_price


@dataclass
class BacktestResult:
    equity: pd.DataFrame
    trades: pd.DataFrame
    fills: pd.DataFrame
    breaches: pd.DataFrame
    exposure: pd.DataFrame = field(default_factory=pd.DataFrame)

    def summary(self) -> pd.DataFrame:
        from .metrics import performance_summary

        return performance_summary(self.equity, self.trades)


class Backtester:
    """Event-driven daily backtest over a signal frame."""

    def __init__(self, cfg: Config, prices: pd.DataFrame, sectors: dict[str, str] | None = None):
        self.cfg = cfg
        self.sectors = sectors or {}
        px = prices.sort_values(["date", "ticker"]).copy()
        if "adj_close" not in px.columns:
            px["adj_close"] = px["close"] * px.get("adj_factor", 1.0)
        if "adv_usd" not in px.columns:
            px["adv_usd"] = (
                px.groupby("ticker", observed=True)
                .apply(lambda g: (g["close"] * g["volume"]).rolling(21, min_periods=5).mean(),
                       include_groups=False)
                .reset_index(level=0, drop=True)
            )
        if "sigma_d" not in px.columns:
            ret = px.groupby("ticker", observed=True)["adj_close"].pct_change()
            px["sigma_d"] = ret.groupby(px["ticker"]).transform(
                lambda s: s.rolling(cfg.labels.vol_window, min_periods=10).std()
            )
        self.prices = px
        # (date, ticker) -> row, for O(1) lookup inside the day loop.
        self.by_key = {
            (d, t): i for i, (d, t) in enumerate(zip(px["date"], px["ticker"], strict=False))
        }
        self.arr = {c: px[c].to_numpy() for c in ("open", "high", "low", "close", "adj_close", "adv_usd", "sigma_d")}
        self.dates = pd.DatetimeIndex(sorted(px["date"].unique()))

    def _bar(self, date: pd.Timestamp, ticker: str) -> dict | None:
        i = self.by_key.get((date, ticker))
        if i is None:
            return None
        return {k: v[i] for k, v in self.arr.items()}

    def run(self, signals: pd.DataFrame) -> BacktestResult:
        """``signals`` needs date, ticker, p, avg_win, avg_loss[, dispersion]."""
        cfg = self.cfg
        state = RiskState(capital=cfg.risk.capital, peak_equity=cfg.risk.capital, equity=cfg.risk.capital)
        cash = cfg.risk.capital
        open_positions: dict[str, Position] = {}

        sig_by_date = {d: g for d, g in signals.groupby("date", observed=True)} if not signals.empty else {}

        equity_rows, trade_rows, fill_rows, breach_rows, exposure_rows = [], [], [], [], []

        for di, date in enumerate(self.dates):
            # ---- 1. Exits, checked against today's bar before any new entries.
            for ticker in list(open_positions):
                pos = open_positions[ticker]
                bar = self._bar(date, ticker)
                if bar is None or date <= pos.entry_date:
                    continue
                days_held = int(np.busday_count(pos.entry_date.date(), date.date()))
                stop_px = pos.entry_price * (1 - pos.stop_pct)
                target_px = pos.entry_price * (1 + pos.target_pct)

                exit_px, reason = None, ""
                if bar["low"] <= stop_px and bar["high"] >= target_px:
                    # Ambiguous bar: assume the stop. See module docstring.
                    exit_px, reason = stop_px, "stop_ambiguous"
                elif bar["low"] <= stop_px:
                    exit_px, reason = stop_px, "stop"
                elif bar["high"] >= target_px:
                    exit_px, reason = target_px, "target"
                elif days_held >= cfg.risk.max_holding_days:
                    exit_px, reason = bar["close"], "time"

                if exit_px is None:
                    continue

                notional = pos.shares * exit_px
                cost_bps = total_cost_bps(notional, bar["adv_usd"], cfg, news_day=False)
                cost = abs(notional) * float(cost_bps) / 1e4
                cash += notional - cost
                pnl = (exit_px - pos.entry_price) * pos.shares - cost
                trade_rows.append(
                    {
                        "ticker": ticker,
                        "entry_date": pos.entry_date,
                        "exit_date": date,
                        "entry_price": pos.entry_price,
                        "exit_price": exit_px,
                        "shares": pos.shares,
                        "notional": pos.notional,
                        "pnl": pnl,
                        "ret": exit_px / pos.entry_price - 1.0,
                        "days_held": days_held,
                        "reason": reason,
                        "sector": pos.sector,
                    }
                )
                fill_rows.append(
                    {"date": date, "ticker": ticker, "side": "sell", "notional": notional,
                     "cost_usd": cost, "participation": abs(notional) / bar["adv_usd"] if bar["adv_usd"] else np.nan,
                     "capped": 0}
                )
                del open_positions[ticker]

            # ---- 2. Mark to market and update risk state.
            mark = 0.0
            for ticker, pos in open_positions.items():
                bar = self._bar(date, ticker)
                mark += pos.shares * (bar["close"] if bar else pos.entry_price)
            equity = cash + mark
            state.equity = equity
            state.peak_equity = max(state.peak_equity, equity)
            state.positions = {
                t: (p.shares * (self._bar(date, t) or {"close": p.entry_price})["close"]) / equity
                for t, p in open_positions.items()
            } if equity > 0 else {}
            state.sectors = {t: p.sector for t, p in open_positions.items()}

            equity_rows.append(
                {"date": date, "equity": equity, "cash": cash, "mark": mark,
                 "n_positions": len(open_positions), "gross": state.gross, "drawdown": state.drawdown}
            )
            exposure_rows.append({"date": date, **{f"sec_{k}": v for k, v in state.sector_weights().items()}})

            # ---- 3. Entries from yesterday's signals, filled at today's open.
            if di == 0:
                continue
            prev = self.dates[di - 1]
            todays = sig_by_date.get(prev)
            if todays is None or todays.empty:
                continue

            candidates = todays.copy()
            candidates = candidates[~candidates["ticker"].isin(open_positions)]
            if candidates.empty:
                continue

            # Stops are derived from volatility known at the signal date.
            stops, targets, advs = [], [], []
            for row in candidates.itertuples(index=False):
                sbar = self._bar(prev, row.ticker)
                if sbar is None or not np.isfinite(sbar["sigma_d"]):
                    stops.append(np.nan)
                    targets.append(np.nan)
                    advs.append(np.nan)
                    continue
                _, stop_pct = stop_levels(sbar["close"], sbar["sigma_d"], cfg)
                stops.append(stop_pct)
                targets.append(
                    float(cfg.labels.upper_mult * sbar["sigma_d"] * np.sqrt(cfg.labels.max_holding_days))
                )
                advs.append(sbar["adv_usd"])
            candidates["stop_pct"] = stops
            candidates["target_pct"] = targets
            candidates["adv_usd"] = advs
            candidates["sector"] = candidates["ticker"].map(lambda t: self.sectors.get(t, "unknown"))
            candidates = candidates.dropna(subset=["stop_pct", "target_pct"])
            if candidates.empty:
                continue

            sized = size_positions(candidates, cfg, capital=equity)
            if sized.empty:
                continue
            allowed, breaches = check_limits(state, sized, cfg)
            for b in breaches:
                breach_rows.append({"date": date, "limit": b.limit, "detail": b.detail, "severity": b.severity})
            if allowed.empty:
                continue

            for row in allowed.itertuples(index=False):
                bar = self._bar(date, row.ticker)
                if bar is None or not np.isfinite(bar["open"]) or bar["open"] <= 0:
                    continue
                want = float(row.weight) * equity
                filled = float(apply_participation_cap(want, bar["adv_usd"], cfg))
                if filled <= 0:
                    continue
                capped = int(abs(filled) < abs(want) - 1e-6)
                cost_bps = float(total_cost_bps(filled, bar["adv_usd"], cfg, news_day=True))
                cost = abs(filled) * cost_bps / 1e4
                if cash < filled + cost:
                    filled = max(cash - cost, 0.0)
                    if filled <= 0:
                        continue
                shares = filled / bar["open"]
                cash -= filled + cost
                open_positions[row.ticker] = Position(
                    ticker=row.ticker,
                    entry_date=date,
                    entry_price=bar["open"],
                    shares=shares,
                    stop_pct=float(row.stop_pct),
                    target_pct=float(row.target_pct),
                    sector=getattr(row, "sector", "unknown"),
                )
                fill_rows.append(
                    {"date": date, "ticker": row.ticker, "side": "buy", "notional": filled,
                     "cost_usd": cost,
                     "participation": abs(filled) / bar["adv_usd"] if bar["adv_usd"] else np.nan,
                     "capped": capped}
                )

        return BacktestResult(
            equity=pd.DataFrame(equity_rows),
            trades=pd.DataFrame(trade_rows),
            fills=pd.DataFrame(fill_rows),
            breaches=pd.DataFrame(breach_rows),
            exposure=pd.DataFrame(exposure_rows).fillna(0.0),
        )
