"""Position sizing: fractional Kelly, capped everywhere it can be.

The mandate is "safe high variability". Those are not in tension if you are
precise about where the variance comes from:

* **Variance comes from breadth and skew.** Twenty to thirty concurrent
  catalyst bets, each with a right-tailed payoff, produce a genuinely wide
  distribution of monthly outcomes. That is the "high variability".
* **Safety comes from every single bet being small and bounded.** No position
  can lose more than ``max_risk_per_trade`` of capital, because the stop is
  placed before the trade is sized and the size is derived *from* the stop.
  That is the "safe".

The failure mode this design rules out is the one that actually kills accounts:
a concentrated position in a name that gaps 60% against you overnight on a
catalyst that went the other way. It does not, and cannot, rule out a bad month
in which twenty small bets all lose at once -- that is the variance you asked
for, and the drawdown kill switch is what bounds it.

Kelly, and why a quarter of it
------------------------------
Full Kelly maximises long-run log growth *given the true probabilities*. Our
probabilities are estimates from a noisy model on non-stationary data, and
Kelly is brutally asymmetric to overestimation: betting 2x optimal has negative
expected log growth, while betting 0.5x optimal costs only 25% of the growth
rate. Quarter-Kelly gives up a quarter of theoretical growth to buy a large
margin against being wrong about the edge, which we assuredly are.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from ..core.config import Config

log = logging.getLogger(__name__)


#: Floor on the magnitude of the assumed loss leg, as a fraction. Kelly divides
#: by this, so an estimate near zero produces an unbounded bet size. A payoff
#: table that reports ``avg_loss = -0.001`` is not telling you the trade is
#: nearly riskless -- it is telling you the barriers are so wide that the loss
#: bucket is full of flat time-stop exits and the estimate is meaningless.
#: Floor it at 1%, which is well below any real stop this strategy would set.
MIN_LOSS_MAGNITUDE = 0.01
#: Ceiling on raw full-Kelly before the fractional multiplier. Even with the
#: floor above, a 0.95 probability against a 1% loss implies f* > 90x capital.
MAX_RAW_KELLY = 3.0


def kelly_fraction(p: np.ndarray, win: np.ndarray, loss: np.ndarray) -> np.ndarray:
    """Full-Kelly fraction for a binary bet with asymmetric payoffs.

    ``f* = p/|loss| - (1-p)/win``, expressed as a fraction of capital, for a bet
    that returns ``win`` with probability ``p`` and ``loss`` (negative) with
    probability ``1-p``. Reduces to the familiar ``(bp - q)/b`` when the loss is
    the full stake.

    Both legs are floored and the result is capped. This is not defensive
    programming for its own sake: the formula is a ratio, it is unbounded as
    the loss leg approaches zero, and the loss leg is an *estimate* from a
    finite sample of a fat-tailed distribution. The guards are what stop a bad
    payoff estimate from becoming a catastrophic position size.
    """
    p = np.clip(np.asarray(p, dtype="float64"), 0.0, 1.0)
    win = np.maximum(np.abs(np.asarray(win, dtype="float64")), MIN_LOSS_MAGNITUDE)
    loss = np.maximum(np.abs(np.asarray(loss, dtype="float64")), MIN_LOSS_MAGNITUDE)
    f = p / loss - (1.0 - p) / win
    f = np.nan_to_num(f, nan=0.0, posinf=0.0, neginf=0.0)
    # A negative Kelly means the bet is bad; it does not mean "go short". The
    # short version of a catalyst is a different trade with different borrow
    # and different tails, so it is not implied here.
    return np.clip(f, 0.0, MAX_RAW_KELLY)


def size_positions(
    signals: pd.DataFrame,
    cfg: Config,
    *,
    capital: float | None = None,
    portfolio_vol: float | None = None,
) -> pd.DataFrame:
    """Turn scored candidates into target weights.

    ``signals`` needs ``ticker``, ``p`` (calibrated), ``avg_win``, ``avg_loss``,
    ``stop_pct`` (positive fraction), and optionally ``dispersion``, ``sector``,
    ``adv_usd``, ``vol``.

    The sizing chain, in order, each step only ever shrinking:

    1. Fractional Kelly on the calibrated edge.
    2. Risk-parity cap: never risk more than ``max_risk_per_trade`` given the
       stop distance. This is what makes the downside bounded per name.
    3. Uncertainty shrinkage by seed dispersion.
    4. Hard per-name notional cap.
    5. Sector cap.
    6. Portfolio vol targeting, then the gross cap.
    """
    rc = cfg.risk
    capital = capital if capital is not None else rc.capital
    if signals.empty:
        return signals.assign(weight=pd.Series(dtype="float64"))

    df = signals.copy()
    df["edge"] = df["p"] * df["avg_win"].fillna(0.0) + (1 - df["p"]) * df["avg_loss"].fillna(0.0)

    # Gate on edge before anything else. Costs are real and a 0.2% expected
    # edge is a rounding error that pays the broker.
    df = df[df["edge"] >= rc.min_edge].copy()
    if df.empty:
        return df.assign(weight=pd.Series(dtype="float64"))

    # 1. Kelly.
    f_kelly = kelly_fraction(
        df["p"].to_numpy(),
        df["avg_win"].fillna(0.05).to_numpy(),
        df["avg_loss"].fillna(-0.05).to_numpy(),
    )
    df["f_kelly"] = np.clip(f_kelly, 0.0, None) * rc.kelly_fraction

    # 2. Risk cap. weight * stop_pct is the fraction of capital lost if the
    # stop trades, so weight <= max_risk / stop_pct.
    stop = df["stop_pct"].clip(lower=0.005).to_numpy()
    df["f_risk_cap"] = rc.max_risk_per_trade / stop
    df["weight"] = np.minimum(df["f_kelly"], df["f_risk_cap"])

    # 3. Shrink where the ensemble disagrees with itself.
    if "dispersion" in df.columns:
        disp = df["dispersion"].fillna(0.0).to_numpy()
        scale = 1.0 / (1.0 + 8.0 * disp)
        df["weight"] *= scale
        df["disp_scale"] = scale

    # 4. Per-name notional cap.
    df["weight"] = df["weight"].clip(upper=rc.max_weight_per_name)

    # Keep the best names if we are over the count limit. Rank on edge, not on
    # probability: a 90% chance of making 1% is not a better trade than a 55%
    # chance of making 20%.
    df = df.sort_values("edge", ascending=False)
    if len(df) > rc.max_positions:
        df = df.head(rc.max_positions)

    # 5. Sector cap.
    if "sector" in df.columns:
        df = _apply_sector_cap(df, rc.max_sector_weight)

    # 6. Vol target, then gross cap.
    if portfolio_vol is not None and portfolio_vol > 0:
        df["weight"] *= min(rc.target_vol / portfolio_vol, 1.5)

    gross = df["weight"].sum()
    if gross > rc.max_gross_exposure:
        df["weight"] *= rc.max_gross_exposure / gross

    # Liquidity: never target more than a few days of participation.
    if "adv_usd" in df.columns:
        max_notional = df["adv_usd"].fillna(np.inf) * cfg.costs.max_participation * 3.0
        df["weight"] = np.minimum(df["weight"], max_notional / capital)

    df["notional"] = df["weight"] * capital
    df["risk_usd"] = df["notional"] * df["stop_pct"]
    return df.reset_index(drop=True)


def _apply_sector_cap(df: pd.DataFrame, cap: float) -> pd.DataFrame:
    out = df.copy()
    for _sector, grp in out.groupby("sector", observed=True):
        total = grp["weight"].sum()
        if total > cap:
            out.loc[grp.index, "weight"] *= cap / total
    return out


def correlation_haircut(
    weights: pd.Series, corr: pd.DataFrame, target_gross: float
) -> pd.Series:
    """Shrink weights until the *diversified* gross meets the target.

    Twenty positions in twenty correlated biotechs is one position with a
    20x-sized bet on the XBI. This scales the book down until the
    correlation-adjusted risk equals what an equally-sized uncorrelated book
    would carry, which is what the gross limit was implicitly assuming.
    """
    if weights.empty or corr.empty:
        return weights

    names = [n for n in weights.index if n in corr.index]
    if len(names) < 2:
        return weights

    w = weights.loc[names].to_numpy(dtype="float64")
    # copy=True is required: pandas may hand back a read-only view, and
    # fill_diagonal writes in place.
    c = corr.loc[names, names].to_numpy(dtype="float64", copy=True)
    np.fill_diagonal(c, 1.0)

    diversified = float(np.sqrt(max(w @ c @ w, 0.0)))
    naive = float(np.sqrt((w**2).sum()))
    if diversified <= 0 or naive <= 0:
        return weights

    # Effective number of bets: naive risk over diversified risk, squared.
    concentration = diversified / naive
    scale = min(1.0, 1.0 / concentration) if concentration > 1 else 1.0
    out = weights.copy()
    out.loc[names] = weights.loc[names] * scale

    gross = out.abs().sum()
    if gross > target_gross:
        out *= target_gross / gross
    return out


def effective_bets(weights: pd.Series, corr: pd.DataFrame) -> float:
    """How many independent bets the book actually contains.

    A portfolio of 30 names with an average pairwise correlation of 0.6 has
    roughly 3 effective bets. If this number is much below the position count,
    the "diversification" is decorative and the drawdown will not be.
    """
    names = [n for n in weights.index if n in corr.index]
    if len(names) < 2:
        return float(len(names))
    w = np.abs(weights.loc[names].to_numpy(dtype="float64"))
    if w.sum() == 0:
        return 0.0
    w = w / w.sum()
    c = corr.loc[names, names].to_numpy(dtype="float64", copy=True)
    np.fill_diagonal(c, 1.0)
    var = float(w @ c @ w)
    return float(1.0 / var) if var > 0 else float(len(names))
