"""Few trades a week, hunting large moves.

A different shape of strategy from the rest of this package, and the two
things that make it work are worth stating up front because both were
discovered by getting them wrong first.

**Rank on expected value, not on P(spike).**
Selecting the names most likely to jump +10% selects the names most likely to
move *at all*, which means the names most likely to drop -7% as well. Measured
on real data, ranking by P(spike) alone gives a 53.6% stop rate and **-0.44%
net per trade**; ranking by expected value, using a second model for the
downside, gives a 36.1% stop rate and **+0.56%**. Same features, same universe,
same period. The downside model is not a refinement, it is the difference
between losing and not.

**Select per period, not globally.**
Taking the global top-N across pooled walk-forward folds lets whichever fold
has the widest prediction scale dominate the selection. The first version of
this put 490 of 492 chosen trades inside a single calendar year -- a "strategy"
nobody could have traded, because it required knowing in advance which year to
show up for. Selecting the best ``k`` in each week is both the honest
construction and a literal statement of the mandate.

Why the economics work here when they did not before
----------------------------------------------------
The previous configuration chased a ~21bp edge against ~48bp of round-trip
cost. Against a 1000bp target the same cost is roughly a tenth of the gross
edge. Nothing about the alpha improved; the *denominator* changed. That is the
single most important reason this shape is worth trying on a universe where
execution is expensive.

What it is not
--------------
Not safer. Fewer, larger, lower-probability positions, an expected win rate
near or below half, and long stretches underwater by construction. See
:meth:`iai.core.config.Config.moonshot` for why the drawdown limit is
deliberately loose.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score

from .core.config import Config
from .model.ensemble import CatalystModel
from .model.splitter import PurgedWalkForward

log = logging.getLogger(__name__)

STOP_REASONS = ("stop", "both")


@dataclass
class MoonshotFit:
    """Out-of-fold predictions for both barriers, plus expected value."""

    oof: pd.DataFrame
    auc_spike: float
    auc_stop: float
    r_time: float
    calibrator_up: IsotonicRegression | None = None
    calibrator_dn: IsotonicRegression | None = None
    fold_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)


def train_moonshot(
    panel: pd.DataFrame,
    labels: pd.DataFrame,
    cfg: Config,
    *,
    permutation_repeats: int = 0,
) -> MoonshotFit:
    """Walk-forward two models: P(hit target first) and P(hit stop first).

    Both are needed. The expected value of the trade is

        EV = P(target) * target - P(stop) * stop + P(neither) * E[r | time exit]

    and only the first term is what a naive "find the spikes" model estimates.
    """
    keep = ["date", "ticker", "entry_date", "exit_date", "spike", "ret",
            "exit_reason", "holding_days"]
    df = panel.merge(
        labels[[c for c in keep if c in labels.columns]], on=["date", "ticker"], how="inner"
    ).dropna(subset=["spike"])
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    if df.empty:
        raise ValueError("no rows after joining panel to spike labels")

    feats = [c for c in panel.columns if c not in ("date", "ticker")]
    X = df[feats].astype("float64")
    y_up = df["spike"].astype(int)
    y_dn = df["exit_reason"].isin(STOP_REASONS).astype(int)

    splitter = PurgedWalkForward(
        n_splits=cfg.model.n_splits,
        purge_days=max(cfg.model.purge_days, cfg.spike.horizon),
        embargo_days=cfg.model.embargo_days,
        min_train_samples=cfg.model.min_train_samples,
    )
    folds = splitter.split(df["date"], df.get("exit_date"))

    parts, rows = [], []
    for fold in folds:
        tr, te = fold.train_idx, fold.test_idx
        cut = int(len(tr) * 0.85)
        has_eval = cut < len(tr) - 50
        fit_idx = tr[:cut] if has_eval else tr
        ev_up = (X.iloc[tr[cut:]], y_up.iloc[tr[cut:]]) if has_eval else None
        ev_dn = (X.iloc[tr[cut:]], y_dn.iloc[tr[cut:]]) if has_eval else None

        m_up = CatalystModel(cfg).fit(X.iloc[fit_idx], y_up.iloc[fit_idx], eval_set=ev_up)
        m_dn = CatalystModel(cfg).fit(X.iloc[fit_idx], y_dn.iloc[fit_idx], eval_set=ev_dn)

        part = df.iloc[te][keep].copy()
        part["p_raw"] = m_up.predict_proba(X.iloc[te])
        part["q_raw"] = m_dn.predict_proba(X.iloc[te])
        part["dispersion"] = m_up.predict_dispersion(X.iloc[te])
        part["fold"] = fold.index
        parts.append(part)
        rows.append({**fold.describe()})

    oof = pd.concat(parts, ignore_index=True)

    cal_up = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    cal_up.fit(oof["p_raw"], oof["spike"])
    oof["p"] = np.clip(cal_up.predict(oof["p_raw"]), 1e-4, 1 - 1e-4)

    cal_dn = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    y_dn_oof = oof["exit_reason"].isin(STOP_REASONS).astype(int)
    cal_dn.fit(oof["q_raw"], y_dn_oof)
    oof["q"] = np.clip(cal_dn.predict(oof["q_raw"]), 1e-4, 1 - 1e-4)

    # E[r | time exit] taken from realised time-stop outcomes. Second order
    # relative to the two barrier terms, but not zero, and using zero biases
    # the ranking toward names with a high probability of doing nothing.
    r_time = float(df.loc[df["exit_reason"] == "time", "ret"].mean())
    if not np.isfinite(r_time):
        r_time = 0.0

    oof["ev"] = expected_value(oof["p"], oof["q"], cfg.spike.target, cfg.spike.stop, r_time)

    return MoonshotFit(
        oof=oof,
        auc_spike=float(roc_auc_score(oof["spike"], oof["p_raw"])),
        auc_stop=float(roc_auc_score(y_dn_oof, oof["q_raw"])),
        r_time=r_time,
        calibrator_up=cal_up,
        calibrator_dn=cal_dn,
        fold_metrics=pd.DataFrame(rows),
    )


def expected_value(
    p_target: np.ndarray | pd.Series,
    p_stop: np.ndarray | pd.Series,
    target: float,
    stop: float,
    r_time: float = 0.0,
) -> np.ndarray:
    """EV of one absolute-barrier trade, per unit of capital committed.

    ``p_target`` and ``p_stop`` come from separate calibrated models, so they
    are not constrained to sum to <= 1. The residual is clipped at zero rather
    than renormalised: renormalising would quietly inflate whichever leg the
    models happened to over-predict, and a negative residual is a signal that
    the two models disagree, which should shrink the trade rather than be
    smoothed away.
    """
    p = np.asarray(p_target, dtype="float64")
    q = np.asarray(p_stop, dtype="float64")
    residual = np.clip(1.0 - p - q, 0.0, 1.0)
    return p * target - q * abs(stop) + residual * r_time


def select_per_week(
    scored: pd.DataFrame,
    *,
    per_week: float = 5.0,
    rank_col: str = "ev",
    min_ev: float | None = None,
    max_per_day: int | None = None,
    date_col: str = "date",
) -> pd.DataFrame:
    """Take the best ``per_week`` candidates in each calendar week.

    Selecting per period rather than globally is not cosmetic. Pooled
    walk-forward predictions do not share a scale across folds, so a global
    top-N concentrates into whichever fold ran hottest -- and a strategy that
    only trades in one year is not a strategy.

    ``max_per_day`` additionally spreads entries within the week. Five trades
    in a week is a pace; five on one morning is a single correlated bet on that
    morning's tape.
    """
    if scored.empty:
        return scored
    df = scored.copy()
    if min_ev is not None:
        df = df[df[rank_col] >= min_ev]
        if df.empty:
            return df
    df["_week"] = pd.to_datetime(df[date_col]).dt.to_period("W")
    k = max(int(round(per_week)), 1)

    if max_per_day is not None:
        df = (
            df.sort_values(rank_col, ascending=False)
            .groupby([df[date_col]], observed=True, sort=False)
            .head(max_per_day)
        )
    picked = (
        df.sort_values(rank_col, ascending=False)
        .groupby("_week", observed=True, sort=False)
        .head(k)
    )
    return picked.drop(columns=["_week"]).sort_values(date_col).reset_index(drop=True)


def clustered_se(values: pd.Series, groups: pd.Series) -> float:
    """Standard error of the mean, robust to correlation within ``groups``.

    Five trades taken in the same week are not five independent observations.
    They share a market regime, their holding periods overlap, and on a bad week
    they lose together. Dividing the per-trade standard deviation by sqrt(n)
    assumes that away and overstates the t-statistic by whatever the within-week
    correlation happens to be -- which, for a strategy that deliberately takes
    five a week, is not small.

    The cluster-robust estimator treats each week's *total* as the unit of
    observation, which is what the sampling actually is. If trades really are
    independent within a week the two estimators agree, so this is a tightening
    that costs nothing when it is not needed.

    Implementation is the standard one-way cluster sandwich for a mean:
    ``Var(x_bar) = sum_g (sum_{i in g} (x_i - x_bar))^2 / n^2``.
    """
    x = pd.Series(values).astype(float).reset_index(drop=True)
    g = pd.Series(groups).reset_index(drop=True)
    n = len(x)
    if n < 2:
        return float("nan")
    n_clusters = g.nunique()
    if n_clusters < 2:
        return float("nan")
    dev = x - x.mean()
    meat = float((dev.groupby(g, observed=True).sum() ** 2).sum())
    # Small-sample correction; without it few clusters give a badly optimistic SE.
    correction = n_clusters / max(n_clusters - 1, 1)
    return float(np.sqrt(correction * meat / n**2))


def selection_report(
    selected: pd.DataFrame,
    universe: pd.DataFrame,
    cost_col: str = "cost_rt",
    date_col: str = "date",
) -> pd.DataFrame:
    """Per-trade economics of a selection, against the universe base rate.

    Reports both the naive and the week-clustered t-statistic. The clustered
    one is the honest number; the naive one is kept beside it so the size of the
    dependence is visible rather than assumed.
    """
    if selected.empty:
        return pd.DataFrame()
    cost = selected[cost_col] if cost_col in selected.columns else 0.0
    net = selected["ret"] - cost
    se = float(net.std(ddof=1) / np.sqrt(len(net))) if len(net) > 1 else np.nan

    weeks = pd.to_datetime(selected[date_col]).dt.to_period("W")
    se_w = clustered_se(net, weeks)
    return pd.DataFrame([{
        "n": len(selected),
        "n_weeks": int(weeks.nunique()),
        "P_spike": float(selected["spike"].mean()),
        "universe_P": float(universe["spike"].mean()),
        "lift": float(selected["spike"].mean() / universe["spike"].mean())
        if universe["spike"].mean() > 0 else np.nan,
        "gross": float(selected["ret"].mean()),
        "median_gross": float(selected["ret"].median()),
        "cost": float(np.mean(cost)) if np.ndim(cost) else float(cost),
        "net": float(net.mean()),
        "net_t": float(net.mean() / se) if se and se > 0 else np.nan,
        "net_t_clustered": float(net.mean() / se_w) if se_w and se_w > 0 else np.nan,
        "pct_stop": float(selected["exit_reason"].isin(STOP_REASONS).mean()),
        "pct_target": float((selected["exit_reason"] == "target").mean()),
    }])


def volatility_control(
    selected: pd.DataFrame, universe: pd.DataFrame, vol_col: str = "vol21", n_buckets: int = 5
) -> pd.DataFrame:
    """Does the model beat the spike rate *implied by volatility alone*?

    An absolute +10% barrier is mechanically easier for a volatile name, so a
    model that only learned "pick volatile things" would show a large raw lift
    and no skill. Bucketing the universe by trailing volatility and comparing
    within bucket is the control. A lift of ~1.0 in every bucket means the
    signal is a volatility tilt, which is free.
    """
    if selected.empty or universe.empty or vol_col not in universe.columns:
        return pd.DataFrame()
    uni = universe.dropna(subset=[vol_col]).copy()
    uni["_b"] = pd.qcut(uni[vol_col].rank(method="first"), n_buckets, labels=False)
    rows = []
    for b, g in uni.groupby("_b", observed=True):
        lo, hi = g[vol_col].min(), g[vol_col].max()
        sel_b = selected[selected[vol_col].between(lo, hi)]
        if len(sel_b) < 10:
            continue
        rows.append({
            "vol_bucket": int(b),
            "median_vol": float(g[vol_col].median()),
            "universe_P": float(g["spike"].mean()),
            "n_selected": len(sel_b),
            "selected_P": float(sel_b["spike"].mean()),
            "lift": float(sel_b["spike"].mean() / g["spike"].mean()) if g["spike"].mean() > 0 else np.nan,
        })
    return pd.DataFrame(rows)
