"""Performance statistics, including the ones that make a strategy look worse.

A summary that reports only CAGR and Sharpe is marketing. The additions here
are the numbers that decide whether a strategy is real:

``deflated_sharpe``
    Sharpe adjusted for the number of strategy variants you tried. If you
    backtested 200 configurations and kept the best, its Sharpe of 1.8 is
    roughly what you would expect from 200 coin flips. Bailey and López de
    Prado's deflated Sharpe makes that explicit.
``sharpe_se``
    Standard error of the Sharpe estimate, adjusted for skew and kurtosis. On
    three years of daily data the SE is about 0.6, which means a measured
    Sharpe of 1.0 is not distinguishable from 0.
``turnover`` / ``cost_drag``
    Gross return minus net return. If cost drag exceeds half of gross alpha,
    the strategy belongs to your broker.
``worst_month`` / ``ulcer_index``
    Drawdown depth is what you feel; time underwater is what makes you quit.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

TRADING_DAYS = 252


def equity_returns(equity: pd.DataFrame) -> pd.Series:
    if equity.empty:
        return pd.Series(dtype="float64")
    s = equity.set_index("date")["equity"].astype("float64")
    return s.pct_change().dropna()


#: A daily return series whose standard deviation is below this is treated as
#: constant. Testing ``std() == 0`` is not enough: a genuinely flat equity
#: curve accumulates floating-point noise of order 1e-19, which sails past an
#: exact-zero check and produces a Sharpe of 7e16. That is not a hypothetical --
#: any strategy that stops trading for a stretch will do it.
FLAT_RETURN_TOL = 1e-12


def sharpe(returns: pd.Series, rf: float = 0.0) -> float:
    if returns.empty:
        return np.nan
    excess = returns - rf / TRADING_DAYS
    sd = float(excess.std(ddof=1))
    if not np.isfinite(sd) or sd < FLAT_RETURN_TOL:
        return np.nan
    return float(np.sqrt(TRADING_DAYS) * excess.mean() / sd)


def sharpe_standard_error(returns: pd.Series) -> float:
    """SE of the annualised Sharpe, corrected for non-normality.

    Lo (2002). The correction matters here because catalyst returns are
    strongly right-skewed and fat-tailed, which inflates the naive SE.
    """
    n = len(returns)
    if n < 30:
        return np.nan
    sr = sharpe(returns) / np.sqrt(TRADING_DAYS)  # per-period
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))
    var = (1 + 0.5 * sr**2 - skew * sr + (kurt - 3) / 4 * sr**2) / (n - 1)
    return float(np.sqrt(max(var, 0.0)) * np.sqrt(TRADING_DAYS))


def deflated_sharpe(returns: pd.Series, n_trials: int = 1) -> float:
    """Probability the true Sharpe exceeds zero, given ``n_trials`` searched.

    Returns a probability, not a Sharpe. Below ~0.95 the strategy has not
    cleared the multiple-testing bar and you should assume it is noise.
    """
    n = len(returns)
    if n < 30:
        return np.nan
    sr = sharpe(returns) / np.sqrt(TRADING_DAYS)
    skew = float(stats.skew(returns))
    kurt = float(stats.kurtosis(returns, fisher=False))

    # Expected maximum Sharpe from n_trials independent noise strategies.
    if n_trials > 1:
        e = np.euler_gamma
        sr_std = returns.std(ddof=1) and 1.0 / np.sqrt(n)
        z1 = stats.norm.ppf(1 - 1.0 / n_trials)
        z2 = stats.norm.ppf(1 - 1.0 / (n_trials * np.e))
        sr0 = sr_std * ((1 - e) * z1 + e * z2)
    else:
        sr0 = 0.0

    denom = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-12))
    stat = (sr - sr0) * np.sqrt(n - 1) / denom
    return float(stats.norm.cdf(stat))


def max_drawdown(equity: pd.Series) -> tuple[float, int]:
    """(depth, longest underwater run in days)."""
    if equity.empty:
        return np.nan, 0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    underwater = (dd < 0).astype(int)
    runs, current = [], 0
    for v in underwater:
        current = current + 1 if v else 0
        runs.append(current)
    return float(dd.min()), int(max(runs) if runs else 0)


def ulcer_index(equity: pd.Series) -> float:
    """RMS drawdown. Penalises long shallow pain, which Sharpe ignores."""
    if equity.empty:
        return np.nan
    dd = equity / equity.cummax() - 1.0
    return float(np.sqrt((dd**2).mean()))


def performance_summary(
    equity: pd.DataFrame, trades: pd.DataFrame, n_trials: int = 1
) -> pd.DataFrame:
    if equity.empty:
        return pd.DataFrame()
    eq = equity.set_index("date")["equity"].astype("float64")
    rets = equity_returns(equity)
    years = max(len(eq) / TRADING_DAYS, 1e-9)
    dd, uw = max_drawdown(eq)

    monthly = eq.resample("ME").last().pct_change().dropna() if len(eq) > 40 else pd.Series(dtype="float64")

    row = {
        "start": eq.index.min(),
        "end": eq.index.max(),
        "years": round(years, 2),
        "total_return": float(eq.iloc[-1] / eq.iloc[0] - 1.0),
        "cagr": float((eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1.0),
        "vol_annual": float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS)) if len(rets) > 1 else np.nan,
        "sharpe": sharpe(rets),
        "sharpe_se": sharpe_standard_error(rets),
        "deflated_sharpe_prob": deflated_sharpe(rets, n_trials),
        "sortino": _sortino(rets),
        "max_drawdown": dd,
        "days_underwater": uw,
        "ulcer_index": ulcer_index(eq),
        "worst_month": float(monthly.min()) if len(monthly) else np.nan,
        "best_month": float(monthly.max()) if len(monthly) else np.nan,
        "skew": float(stats.skew(rets)) if len(rets) > 8 else np.nan,
        "kurtosis": float(stats.kurtosis(rets, fisher=False)) if len(rets) > 8 else np.nan,
        "avg_positions": float(equity["n_positions"].mean()),
        "avg_gross": float(equity["gross"].mean()) if "gross" in equity.columns else np.nan,
    }

    if not trades.empty:
        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]
        row.update(
            {
                "n_trades": len(trades),
                "hit_rate": float((trades["pnl"] > 0).mean()),
                "avg_win_pct": float(wins["ret"].mean()) if len(wins) else np.nan,
                "avg_loss_pct": float(losses["ret"].mean()) if len(losses) else np.nan,
                "profit_factor": float(wins["pnl"].sum() / abs(losses["pnl"].sum()))
                if len(losses) and losses["pnl"].sum() != 0
                else np.nan,
                "avg_days_held": float(trades["days_held"].mean()),
                "pct_stopped": float((trades["reason"].str.startswith("stop")).mean()),
                "pct_target": float((trades["reason"] == "target").mean()),
                "pct_time": float((trades["reason"] == "time").mean()),
                # The largest single trade's share of total profit. If one
                # trade made the strategy, you do not have a strategy.
                "top_trade_pnl_share": float(trades["pnl"].max() / trades["pnl"].sum())
                if trades["pnl"].sum() > 0
                else np.nan,
            }
        )
    return pd.DataFrame([row])


def _sortino(returns: pd.Series) -> float:
    if returns.empty:
        return np.nan
    downside = returns[returns < 0]
    if downside.empty or downside.std() == 0:
        return np.nan
    return float(np.sqrt(TRADING_DAYS) * returns.mean() / downside.std(ddof=1))


def monthly_table(equity: pd.DataFrame) -> pd.DataFrame:
    """Year x month return grid. The fastest way to spot a single lucky quarter."""
    if equity.empty:
        return pd.DataFrame()
    eq = equity.set_index("date")["equity"].astype("float64")
    m = eq.resample("ME").last().pct_change().dropna()
    if m.empty:
        return pd.DataFrame()
    frame = pd.DataFrame({"year": m.index.year, "month": m.index.month, "ret": m.to_numpy()})
    return frame.pivot(index="year", columns="month", values="ret")


def trade_attribution(trades: pd.DataFrame, by: str = "sector") -> pd.DataFrame:
    """Where the P&L came from. Concentration here is a warning, not a feature."""
    if trades.empty or by not in trades.columns:
        return pd.DataFrame()
    agg = (
        trades.groupby(by, observed=True)
        .agg(n=("pnl", "size"), pnl=("pnl", "sum"), hit_rate=("pnl", lambda s: float((s > 0).mean())),
             avg_ret=("ret", "mean"))
        .sort_values("pnl", ascending=False)
    )
    agg["pnl_share"] = agg["pnl"] / agg["pnl"].sum() if agg["pnl"].sum() else np.nan
    return agg.reset_index()
