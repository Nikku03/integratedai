"""The model: a seed-averaged, calibrated gradient-boosted classifier.

Choices, and why
----------------
**Gradient-boosted trees, not a neural net.** The feature set is a few hundred
mostly-sparse tabular columns with heavy missingness, non-linear thresholds
(``days_since < 3``) and strong interactions. That is exactly the regime where
GBDTs dominate and where a net needs ten times the data to draw. LightGBM also
handles NaN natively, which matters because "no event has ever happened here"
and "we have no data" are genuinely different states and imputing them to the
same number destroys information.

**Seed averaging, not a single fit.** Boosted trees on noisy financial data
have high variance across seeds -- run-to-run AUC swings of 0.01-0.02 are
normal. A five-seed average is the cheapest available variance reduction and
it also gives a free dispersion estimate: when the seeds disagree about a name,
that is a signal the model is extrapolating, and the risk layer sizes it down.

**Calibration is mandatory.** Kelly sizing consumes a *probability*, and raw
GBDT scores are not probabilities -- they are systematically overconfident at
the extremes, which is precisely where the sizing formula is most sensitive.
Isotonic regression on out-of-fold predictions fixes this. Skipping it is the
difference between betting 2% and betting 9% on the same view.

**Predict the barrier, size with the payoff.** The classifier estimates
P(upper barrier first). Expected return needs that probability *and* the
realised payoffs, which are estimated separately per volatility bucket. A 55%
win rate is a great bet at 2:1 and a terrible one at 1:2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from ..core.config import Config

log = logging.getLogger(__name__)

try:
    import lightgbm as lgb

    HAS_LGB = True
except ImportError:  # pragma: no cover - exercised only in minimal installs

    HAS_LGB = False
    log.warning("lightgbm not installed; falling back to sklearn HistGradientBoosting")


@dataclass
class FitResult:
    """Out-of-fold predictions and diagnostics from one walk-forward pass."""

    oof: pd.DataFrame
    importance: pd.DataFrame
    fold_metrics: pd.DataFrame
    calibrator: IsotonicRegression | None = None
    payoff_table: pd.DataFrame = field(default_factory=pd.DataFrame)
    #: Out-of-sample permutation importance. Prefer this over ``importance``
    #: (split gain) for any decision that costs money -- see
    #: :func:`permutation_importance`.
    perm_importance: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def auc(self) -> float:
        d = self.oof.dropna(subset=["y", "p_raw"])
        return float(roc_auc_score(d["y"], d["p_raw"])) if d["y"].nunique() > 1 else np.nan

    @property
    def brier(self) -> float:
        d = self.oof.dropna(subset=["y", "p"])
        return float(brier_score_loss(d["y"], d["p"])) if len(d) else np.nan


class CatalystModel:
    """Seed-averaged classifier over the catalyst feature panel."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.models: list = []
        self.features: list[str] = []
        self.calibrator: IsotonicRegression | None = None
        self.payoff_table: pd.DataFrame = pd.DataFrame()

    # ---------------------------------------------------------------- fitting

    def _make(self, seed: int):
        mc = self.cfg.model
        if HAS_LGB:
            return lgb.LGBMClassifier(
                objective="binary",
                learning_rate=mc.learning_rate,
                num_leaves=mc.num_leaves,
                min_child_samples=mc.min_child_samples,
                feature_fraction=mc.feature_fraction,
                bagging_fraction=mc.bagging_fraction,
                bagging_freq=mc.bagging_freq,
                lambda_l2=mc.lambda_l2,
                n_estimators=mc.n_estimators,
                random_state=seed,
                n_jobs=-1,
                verbose=-1,
            )
        from sklearn.ensemble import HistGradientBoostingClassifier

        return HistGradientBoostingClassifier(
            learning_rate=mc.learning_rate,
            max_leaf_nodes=mc.num_leaves,
            min_samples_leaf=mc.min_child_samples,
            l2_regularization=mc.lambda_l2,
            max_iter=mc.n_estimators,
            random_state=seed,
        )

    def fit(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        sample_weight: pd.Series | None = None,
        eval_set: tuple[pd.DataFrame, pd.Series] | None = None,
    ) -> CatalystModel:
        self.features = list(X.columns)
        self.models = []
        for s in range(self.cfg.model.n_seeds):
            m = self._make(seed=1000 + s)
            if HAS_LGB and eval_set is not None:
                m.fit(
                    X,
                    y,
                    sample_weight=sample_weight,
                    eval_X=eval_set[0],
                    eval_y=eval_set[1],
                    eval_metric="auc",
                    callbacks=[
                        lgb.early_stopping(self.cfg.model.early_stopping_rounds, verbose=False),
                        lgb.log_evaluation(0),
                    ],
                )
            else:
                m.fit(X, y, sample_weight=sample_weight)
            self.models.append(m)
        return self

    # ------------------------------------------------------------- predicting

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Mean predicted probability across seeds."""
        X = X.reindex(columns=self.features)
        preds = np.column_stack([m.predict_proba(X)[:, 1] for m in self.models])
        return preds.mean(axis=1)

    def predict_dispersion(self, X: pd.DataFrame) -> np.ndarray:
        """Standard deviation across seeds -- an epistemic-uncertainty proxy.

        High dispersion means the seeds are extrapolating into a region the
        training data did not cover. The risk layer shrinks those positions.
        """
        X = X.reindex(columns=self.features)
        preds = np.column_stack([m.predict_proba(X)[:, 1] for m in self.models])
        return preds.std(axis=1)

    def calibrated_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.predict_proba(X)
        if self.calibrator is None:
            return raw
        return np.clip(self.calibrator.predict(raw), 1e-4, 1 - 1e-4)

    def importance(self) -> pd.DataFrame:
        if not self.models:
            return pd.DataFrame(columns=["feature", "gain"])
        if HAS_LGB:
            gains = np.mean(
                [m.booster_.feature_importance(importance_type="gain") for m in self.models], axis=0
            )
        else:
            gains = np.zeros(len(self.features))
        return (
            pd.DataFrame({"feature": self.features, "gain": gains})
            .sort_values("gain", ascending=False)
            .reset_index(drop=True)
        )


def permutation_importance(
    model: CatalystModel,
    X: pd.DataFrame,
    y: pd.Series,
    *,
    n_repeats: int = 3,
    seed: int = 0,
    features: list[str] | None = None,
) -> pd.DataFrame:
    """Drop in out-of-sample AUC when a feature is shuffled.

    Use this, not split gain, whenever the answer matters.

    LightGBM's ``importance_type="gain"`` is systematically biased toward
    features with many distinct values, because such a feature offers more
    candidate split points and therefore accumulates gain across many shallow,
    individually-worthless splits. A pure-noise column that happens to fire
    often will out-rank a genuinely predictive column that fires rarely -- which
    is exactly backwards for a catalyst strategy, where the valuable events are
    the rare ones.

    Permuting a feature in the *held-out* fold and measuring the AUC drop has
    no such bias: a noise feature costs nothing when destroyed, regardless of
    how often it fires. This is the number to use when deciding whether a data
    vendor is worth its invoice.
    """
    rng = np.random.default_rng(seed)
    cols = features or list(X.columns)
    if y.nunique() < 2:
        return pd.DataFrame(columns=["feature", "auc_drop", "auc_drop_std"])

    base = float(roc_auc_score(y, model.predict_proba(X)))
    rows = []
    for col in cols:
        drops = []
        original = X[col].to_numpy(copy=True)
        for _ in range(n_repeats):
            shuffled = X.copy()
            shuffled[col] = rng.permutation(original)
            drops.append(base - float(roc_auc_score(y, model.predict_proba(shuffled))))
        rows.append(
            {
                "feature": col,
                "auc_drop": float(np.mean(drops)),
                "auc_drop_std": float(np.std(drops, ddof=1)) if n_repeats > 1 else 0.0,
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values("auc_drop", ascending=False)
        .reset_index(drop=True)
        .assign(base_auc=base)
    )


def estimate_payoffs(labels: pd.DataFrame, n_buckets: int = 5) -> pd.DataFrame:
    """Average win and loss size per volatility bucket.

    Kelly needs the payoff ratio, and it varies enormously across the universe.
    Bucketing by the barrier width (a direct function of trailing vol) rather
    than fitting a regression keeps this robust to the fat tails that make a
    mean-based estimate unstable.
    """
    if labels.empty:
        return pd.DataFrame(columns=["bucket", "avg_win", "avg_loss", "n"])

    df = labels.dropna(subset=["ret", "label"]).copy()
    width = (df["barrier_up"] - df["barrier_dn"]) / df["barrier_dn"].replace(0, np.nan)
    df["bucket"] = pd.qcut(width.rank(method="first"), n_buckets, labels=False)

    rows = []
    for b, grp in df.groupby("bucket", observed=True):
        wins = grp.loc[grp["label"] == 1, "ret"]
        losses = grp.loc[grp["label"] == 0, "ret"]
        rows.append(
            {
                "bucket": int(b),
                "avg_win": float(wins.mean()) if len(wins) else np.nan,
                "avg_loss": float(losses.mean()) if len(losses) else np.nan,
                "width_lo": float(width[grp.index].min()),
                "width_hi": float(width[grp.index].max()),
                "n": len(grp),
            }
        )
    return pd.DataFrame(rows).sort_values("bucket").reset_index(drop=True)


def assign_payoffs(labels: pd.DataFrame, table: pd.DataFrame) -> pd.DataFrame:
    """Attach the bucket payoffs to each row by barrier width."""
    if labels.empty or table.empty:
        out = labels.copy()
        out["avg_win"] = np.nan
        out["avg_loss"] = np.nan
        return out
    df = labels.copy()
    width = (df["barrier_up"] - df["barrier_dn"]) / df["barrier_dn"].replace(0, np.nan)
    edges = table["width_hi"].to_numpy()
    idx = np.clip(np.searchsorted(edges, width.to_numpy(), side="left"), 0, len(table) - 1)
    df["avg_win"] = table["avg_win"].to_numpy()[idx]
    df["avg_loss"] = table["avg_loss"].to_numpy()[idx]
    return df


def expected_edge(p: np.ndarray, avg_win: np.ndarray, avg_loss: np.ndarray) -> np.ndarray:
    """E[return] = p * win + (1 - p) * loss, with ``loss`` already negative."""
    return p * np.nan_to_num(avg_win) + (1.0 - p) * np.nan_to_num(avg_loss)
