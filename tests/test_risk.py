"""Risk sizing and limits. The 'safe' half of the mandate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from iai.backtest.costs import apply_participation_cap, impact_bps, total_cost_bps
from iai.core.config import Config
from iai.risk.limits import RiskState, check_limits, stop_levels
from iai.risk.sizing import (
    MAX_RAW_KELLY,
    effective_bets,
    kelly_fraction,
    size_positions,
)


@pytest.fixture
def risk_cfg():
    return Config()


# -------------------------------------------------------------------- kelly


def test_kelly_matches_closed_form():
    """Even-money bet at p=0.6: f* = 2p - 1 = 0.2."""
    f = kelly_fraction(np.array([0.6]), np.array([1.0]), np.array([-1.0]))
    assert f[0] == pytest.approx(0.2, abs=1e-9)


def test_kelly_is_zero_for_a_losing_bet():
    f = kelly_fraction(np.array([0.3]), np.array([1.0]), np.array([-1.0]))
    assert f[0] == 0.0


def test_kelly_survives_a_degenerate_loss_estimate():
    """A payoff table reporting avg_loss ~ 0 must not produce an infinite bet.

    This is the guard that matters: the Kelly denominator is an *estimate* from
    a finite sample, and without a floor a bad estimate becomes a catastrophic
    position size rather than a merely wrong one.
    """
    f = kelly_fraction(np.array([0.7]), np.array([0.15]), np.array([-1e-9]))
    assert np.isfinite(f).all()
    assert f[0] <= MAX_RAW_KELLY


def test_kelly_handles_nan_and_zero_payoffs():
    f = kelly_fraction(
        np.array([0.6, 0.6, 0.6]),
        np.array([np.nan, 0.0, 0.1]),
        np.array([-0.05, -0.05, np.nan]),
    )
    assert np.isfinite(f).all()
    assert (f >= 0).all()


# ------------------------------------------------------------------- sizing


def _candidates(n=10, p=0.65, stop=0.10):
    return pd.DataFrame(
        {
            "ticker": [f"T{i:02d}" for i in range(n)],
            "p": p,
            "avg_win": 0.15,
            "avg_loss": -0.06,
            "stop_pct": stop,
            "dispersion": 0.01,
            "adv_usd": 5e7,
            "sector": ["tech", "biotech"] * (n // 2),
        }
    )


def test_risk_per_trade_is_hard_capped(risk_cfg):
    sized = size_positions(_candidates(), risk_cfg)
    assert not sized.empty
    risk_fraction = sized["weight"] * sized["stop_pct"]
    assert (risk_fraction <= risk_cfg.risk.max_risk_per_trade + 1e-9).all()


def test_weight_per_name_is_hard_capped(risk_cfg):
    sized = size_positions(_candidates(p=0.95, stop=0.02), risk_cfg)
    assert (sized["weight"] <= risk_cfg.risk.max_weight_per_name + 1e-9).all()


def test_gross_exposure_is_capped(risk_cfg):
    sized = size_positions(_candidates(n=40, p=0.9, stop=0.02), risk_cfg)
    assert sized["weight"].sum() <= risk_cfg.risk.max_gross_exposure + 1e-9


def test_position_count_is_capped(risk_cfg):
    sized = size_positions(_candidates(n=100), risk_cfg)
    assert len(sized) <= risk_cfg.risk.max_positions


def test_low_edge_candidates_are_rejected(risk_cfg):
    """A bet that does not clear costs plus margin must not be taken.

    Note the threshold is on *expected edge*, not on probability. At p=0.42
    with a 2.5:1 payoff the expected return is +2.8% and the bet is good; the
    gate only rejects it once the probability drops far enough that the payoff
    no longer compensates.
    """
    assert size_positions(_candidates(p=0.25), risk_cfg).empty
    # And the boundary is where the arithmetic says it is, not where intuition
    # about win rates says it is.
    assert not size_positions(_candidates(p=0.42), risk_cfg).empty


def test_wider_stop_gets_smaller_size(risk_cfg):
    """Risk-based sizing: size must fall as the stop widens."""
    tight = size_positions(_candidates(stop=0.05), risk_cfg)["weight"].iloc[0]
    wide = size_positions(_candidates(stop=0.25), risk_cfg)["weight"].iloc[0]
    assert wide < tight


def test_ensemble_disagreement_shrinks_size(risk_cfg):
    confident = _candidates()
    confident["dispersion"] = 0.001
    unsure = _candidates()
    unsure["dispersion"] = 0.15
    assert size_positions(unsure, risk_cfg)["weight"].iloc[0] < size_positions(confident, risk_cfg)["weight"].iloc[0]


def test_sector_cap_binds(risk_cfg):
    cand = _candidates(n=30)
    cand["sector"] = "biotech"
    sized = size_positions(cand, risk_cfg)
    assert sized["weight"].sum() <= risk_cfg.risk.max_sector_weight + 1e-9


# ------------------------------------------------------------------- limits


def test_drawdown_kill_switch_halts_trading(risk_cfg):
    state = RiskState(capital=100_000, peak_equity=100_000, equity=78_000)  # -22%
    allowed, breaches = check_limits(state, _candidates(), risk_cfg)
    assert allowed.empty
    assert state.halted
    assert any(b.limit == "max_drawdown" for b in breaches)


def test_halt_persists_across_calls(risk_cfg):
    state = RiskState(capital=100_000, peak_equity=100_000, equity=70_000)
    check_limits(state, _candidates(), risk_cfg)
    state.equity = 99_000  # recovered, but the halt should stick
    allowed, breaches = check_limits(state, _candidates(), risk_cfg)
    assert allowed.empty
    assert any(b.limit == "halted" for b in breaches)


def test_existing_position_counts_against_the_name_cap(risk_cfg):
    state = RiskState(capital=100_000, peak_equity=100_000, equity=100_000)
    state.positions = {"T00": risk_cfg.risk.max_weight_per_name}
    cand = _candidates(n=2)
    cand["weight"] = 0.05
    cand["edge"] = 0.05
    allowed, breaches = check_limits(state, cand, risk_cfg)
    assert "T00" not in set(allowed["ticker"])
    assert any(b.limit == "max_weight_per_name" for b in breaches)


def test_stop_scales_with_volatility(risk_cfg):
    _, quiet = stop_levels(100.0, sigma_daily=0.01, cfg=risk_cfg)
    _, wild = stop_levels(100.0, sigma_daily=0.06, cfg=risk_cfg)
    assert wild > quiet
    assert 0.02 <= quiet <= 0.35 and 0.02 <= wild <= 0.35


# -------------------------------------------------------------------- costs


def test_impact_grows_with_participation(risk_cfg):
    small = impact_bps(1e4, 1e8, risk_cfg)
    large = impact_bps(1e7, 1e8, risk_cfg)
    assert large > small


def test_impact_is_sublinear(risk_cfg):
    """Square-root law: 100x the order is 10x the impact, not 100x."""
    a = float(impact_bps(1e5, 1e9, risk_cfg))
    b = float(impact_bps(1e7, 1e9, risk_cfg))
    assert b / a == pytest.approx(10.0, rel=0.01)


def test_participation_cap_truncates_oversized_orders(risk_cfg):
    adv = 1_000_000.0
    filled = float(apply_participation_cap(500_000.0, adv, risk_cfg))
    assert filled == pytest.approx(adv * risk_cfg.costs.max_participation)


def test_news_day_costs_more(risk_cfg):
    quiet = float(total_cost_bps(1e5, 1e8, risk_cfg, news_day=False))
    news = float(total_cost_bps(1e5, 1e8, risk_cfg, news_day=True))
    assert news > quiet


# ------------------------------------------------------------ concentration


def test_effective_bets_detects_hidden_concentration():
    """Twenty correlated names are not twenty bets."""
    names = [f"T{i}" for i in range(20)]
    w = pd.Series(0.05, index=names)
    independent = pd.DataFrame(np.eye(20), index=names, columns=names)
    # Build the array before wrapping it: pandas 3.0 exposes .values read-only.
    corr_arr = np.full((20, 20), 0.9)
    np.fill_diagonal(corr_arr, 1.0)
    correlated = pd.DataFrame(corr_arr, index=names, columns=names)

    assert effective_bets(w, independent) == pytest.approx(20.0, rel=0.01)
    assert effective_bets(w, correlated) < 2.0
