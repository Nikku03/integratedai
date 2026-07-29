"""Backtest mechanics. Mostly tests that it cannot cheat."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from iai.backtest.engine import Backtester
from iai.backtest.metrics import deflated_sharpe, max_drawdown, performance_summary, sharpe
from iai.core.config import Config
from iai.labels import build_labels


@pytest.fixture
def bt_cfg():
    c = Config()
    c.risk.capital = 100_000.0
    return c


def _signals(prices: pd.DataFrame, p: float = 0.7) -> pd.DataFrame:
    dates = sorted(prices["date"].unique())[30:]
    rows = []
    for d in dates:
        for t in sorted(prices[prices["date"] == d]["ticker"].unique())[:5]:
            rows.append({"date": d, "ticker": t, "p": p, "dispersion": 0.01,
                         "avg_win": 0.15, "avg_loss": -0.06})
    return pd.DataFrame(rows)


def test_entries_fill_at_the_next_open_never_the_signal_close(world, bt_cfg):
    """A trade for a signal dated t must be entered at the open of t+1."""
    prices = world["prices"]
    bt = Backtester(bt_cfg, prices, sectors=world["sectors"])
    res = bt.run(_signals(prices))
    assert not res.trades.empty

    px = prices.set_index(["ticker", "date"])
    for row in res.trades.head(50).itertuples(index=False):
        bar = px.loc[(row.ticker, row.entry_date)]
        assert row.entry_price == pytest.approx(float(bar["open"]), rel=1e-9), (
            "entry did not fill at the open of the entry session"
        )


def test_no_position_exits_before_it_is_entered(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    assert (res.trades["exit_date"] > res.trades["entry_date"]).all()


def test_holding_period_is_bounded(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    assert res.trades["days_held"].max() <= bt_cfg.risk.max_holding_days + 3


def test_equity_is_cash_plus_marks(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    eq = res.equity
    assert np.allclose(eq["equity"], eq["cash"] + eq["mark"], rtol=1e-9)
    assert (eq["cash"] >= -1e-6).all(), "backtest spent money it did not have"


def test_position_count_never_exceeds_the_limit(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    assert res.equity["n_positions"].max() <= bt_cfg.risk.max_positions


def test_costs_are_always_charged(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    assert not res.fills.empty
    assert (res.fills["cost_usd"] > 0).all(), "a fill was executed for free"


def test_higher_costs_reduce_returns(world, bt_cfg):
    cheap = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    expensive_cfg = Config()
    expensive_cfg.costs.half_spread_bps = 50.0
    expensive_cfg.costs.impact_coef_bps = 200.0
    dear = Backtester(expensive_cfg, world["prices"], sectors=world["sectors"]).run(
        _signals(world["prices"])
    )
    assert dear.equity["equity"].iloc[-1] < cheap.equity["equity"].iloc[-1]


def test_ambiguous_bar_resolves_pessimistically(world, bt_cfg):
    """When both barriers sit inside one bar, the stop is assumed to trade."""
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    ambiguous = res.trades[res.trades["reason"] == "stop_ambiguous"]
    if not ambiguous.empty:
        assert (ambiguous["ret"] < 0).all(), "an ambiguous bar was resolved in our favour"


def test_no_trades_when_no_signal_clears_the_edge_threshold(world, bt_cfg):
    weak = _signals(world["prices"], p=0.30)
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(weak)
    assert res.trades.empty


# ------------------------------------------------------------------ metrics


def test_sharpe_of_constant_returns_is_undefined():
    assert np.isnan(sharpe(pd.Series([0.001] * 100)))


def test_max_drawdown_on_a_known_path():
    eq = pd.Series([100, 120, 90, 95, 130], dtype="float64")
    dd, underwater = max_drawdown(eq)
    assert dd == pytest.approx(90 / 120 - 1.0)
    assert underwater == 2


def test_deflated_sharpe_punishes_multiple_testing():
    """The same track record is less convincing after 500 attempts."""
    rng = np.random.default_rng(0)
    rets = pd.Series(rng.normal(0.0008, 0.01, 800))
    honest = deflated_sharpe(rets, n_trials=1)
    after_search = deflated_sharpe(rets, n_trials=500)
    assert after_search < honest


def test_performance_summary_reports_concentration(world, bt_cfg):
    res = Backtester(bt_cfg, world["prices"], sectors=world["sectors"]).run(_signals(world["prices"]))
    summary = performance_summary(res.equity, res.trades)
    assert "top_trade_pnl_share" in summary.columns
    assert "days_underwater" in summary.columns
    assert 0 <= float(summary["hit_rate"].iloc[0]) <= 1


def test_backtest_on_labels_agrees_with_label_construction(world, bt_cfg):
    """The engine's exit rule and the label's barriers must describe one trade.

    If they drift apart, the model is trained to predict an outcome the
    backtest never realises, and every probability it emits is describing a
    trade nobody makes.
    """
    labels = build_labels(world["prices"], bt_cfg)
    assert bt_cfg.risk.max_holding_days == bt_cfg.labels.max_holding_days
    assert labels["holding_days"].max() <= bt_cfg.risk.max_holding_days + 1
