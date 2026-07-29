"""Walk-forward training loop: the only place a model ever sees a label.

The loop is deliberately boring. For each fold: fit on purged history, predict
the test window, record. After all folds, fit the calibrator on the pooled
out-of-fold predictions, which is the only calibration that is not itself
in-sample.

The final "production" model is refit on everything, but its calibrator comes
from the walk-forward pass. Refitting the calibrator in-sample would produce a
perfectly calibrated model on data it has memorised, which is worse than no
calibration at all because it looks correct.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from ..core.config import Config
from ..features.assembler import ID_COLS, feature_columns
from ..labels import sample_weights
from .ensemble import (
    CatalystModel,
    FitResult,
    assign_payoffs,
    estimate_payoffs,
    permutation_importance,
)
from .splitter import PurgedWalkForward

log = logging.getLogger(__name__)


def make_dataset(
    panel: pd.DataFrame, labels: pd.DataFrame, cfg: Config
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Join features to labels and return ``(X, y, meta)``.

    ``meta`` carries the columns the splitter and the risk layer need but the
    model must never see: dates, tickers, exit dates, realised returns.
    """
    keep = ["date", "ticker", "entry_date", "exit_date", "label", "ret", "holding_days",
            "barrier_up", "barrier_dn"]
    lab = labels[[c for c in keep if c in labels.columns]]
    df = panel.merge(lab, on=ID_COLS, how="inner").dropna(subset=["label"])
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)

    feats = [c for c in feature_columns(df) if c not in lab.columns]
    X = df[feats].astype("float64")
    y = df["label"].astype(int)
    meta = df[[c for c in keep if c in df.columns]].copy()
    meta["sample_weight"] = sample_weights(meta, cfg).to_numpy()
    return X, y, meta


def walk_forward(
    X: pd.DataFrame,
    y: pd.Series,
    meta: pd.DataFrame,
    cfg: Config,
    *,
    expanding: bool = True,
    permutation_repeats: int = 2,
) -> FitResult:
    """Run purged walk-forward and return pooled out-of-fold predictions."""
    splitter = PurgedWalkForward(
        n_splits=cfg.model.n_splits,
        purge_days=cfg.model.purge_days,
        embargo_days=cfg.model.embargo_days,
        expanding=expanding,
        min_train_samples=cfg.model.min_train_samples,
    )
    if cfg.model.purge_days < cfg.labels.max_holding_days:
        log.warning(
            "purge_days=%d is shorter than max_holding_days=%d; labels will leak across folds",
            cfg.model.purge_days, cfg.labels.max_holding_days,
        )

    folds = splitter.split(meta["date"], meta.get("exit_date"))
    log.info("walk-forward: %d folds\n%s", len(folds), splitter.describe(folds).to_string(index=False))

    oof_parts: list[pd.DataFrame] = []
    fold_rows: list[dict] = []
    importances: list[pd.DataFrame] = []
    perms: list[pd.DataFrame] = []

    for fold in folds:
        tr, te = fold.train_idx, fold.test_idx
        X_tr, y_tr = X.iloc[tr], y.iloc[tr]
        X_te, y_te = X.iloc[te], y.iloc[te]
        w_tr = meta["sample_weight"].iloc[tr]

        # Carve a validation tail out of the *training* window for early
        # stopping. Using the test fold here would be the same leak the whole
        # splitter exists to prevent.
        cut = int(len(tr) * 0.85)
        eval_set = (X_tr.iloc[cut:], y_tr.iloc[cut:]) if cut < len(tr) - 50 else None
        fit_X, fit_y, fit_w = (
            (X_tr.iloc[:cut], y_tr.iloc[:cut], w_tr.iloc[:cut]) if eval_set else (X_tr, y_tr, w_tr)
        )

        model = CatalystModel(cfg).fit(fit_X, fit_y, sample_weight=fit_w, eval_set=eval_set)
        p_raw = model.predict_proba(X_te)
        disp = model.predict_dispersion(X_te)

        part = meta.iloc[te][["date", "ticker", "entry_date", "exit_date", "ret", "label"]].copy()
        part["y"] = y_te.to_numpy()
        part["p_raw"] = p_raw
        part["dispersion"] = disp
        part["fold"] = fold.index
        oof_parts.append(part)

        auc = float(roc_auc_score(y_te, p_raw)) if y_te.nunique() > 1 else np.nan
        fold_rows.append(
            {
                **fold.describe(),
                "auc": auc,
                "brier": float(brier_score_loss(y_te, p_raw)) if len(y_te) else np.nan,
                "base_rate": float(y_te.mean()),
                "mean_pred": float(np.mean(p_raw)),
            }
        )
        importances.append(model.importance().assign(fold=fold.index))
        if permutation_repeats > 0:
            perms.append(
                permutation_importance(
                    model, X_te, y_te, n_repeats=permutation_repeats, seed=fold.index
                ).assign(fold=fold.index)
            )
        log.info("fold %d: auc=%.4f n_train=%d n_test=%d", fold.index, auc, len(tr), len(te))

    oof = pd.concat(oof_parts, ignore_index=True)

    # Calibrate on pooled out-of-fold predictions only.
    calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calibrator.fit(oof["p_raw"], oof["y"])
    oof["p"] = np.clip(calibrator.predict(oof["p_raw"]), 1e-4, 1 - 1e-4)

    imp = (
        pd.concat(importances, ignore_index=True)
        .groupby("feature", as_index=False, observed=True)["gain"]
        .mean()
        .sort_values("gain", ascending=False)
        .reset_index(drop=True)
    )
    imp["gain_pct"] = 100 * imp["gain"] / imp["gain"].sum() if imp["gain"].sum() else 0.0

    perm = pd.DataFrame(columns=["feature", "auc_drop", "auc_drop_std"])
    if perms:
        perm = (
            pd.concat(perms, ignore_index=True)
            .groupby("feature", as_index=False, observed=True)
            .agg(auc_drop=("auc_drop", "mean"), auc_drop_std=("auc_drop", "std"))
            .sort_values("auc_drop", ascending=False)
            .reset_index(drop=True)
        )

    payoffs = estimate_payoffs(meta)

    return FitResult(
        oof=oof,
        importance=imp,
        fold_metrics=pd.DataFrame(fold_rows),
        calibrator=calibrator,
        payoff_table=payoffs,
        perm_importance=perm,
    )


def fit_production(
    X: pd.DataFrame, y: pd.Series, meta: pd.DataFrame, cfg: Config, result: FitResult
) -> CatalystModel:
    """Refit on all data, keeping the out-of-fold calibrator and payoff table."""
    model = CatalystModel(cfg).fit(X, y, sample_weight=meta["sample_weight"])
    model.calibrator = result.calibrator
    model.payoff_table = result.payoff_table
    return model


def family_importance(importance: pd.DataFrame, value_col: str = "gain") -> pd.DataFrame:
    """Roll feature importance up to data source.

    This is the number that decides whether a vendor contract gets renewed. If
    ``flight`` contributes 2% of the total, the jet data is not paying for
    itself.

    Pass ``value_col="auc_drop"`` with :attr:`FitResult.perm_importance` when
    the decision matters -- split gain over-credits high-frequency features.
    """
    if importance.empty or value_col not in importance.columns:
        return pd.DataFrame(columns=["family", value_col, "n_features", "pct"])

    def _fam(name: str) -> str:
        if name.startswith("kind_"):
            body = name[5:]
            for prefix, fam in (
                ("8_K", "edgar"), ("form", "edgar"), ("catalyst", "edgar_fts"),
                ("legal", "edgar_fts"), ("regulatory", "edgar_fts"),
                ("docket", "legal"), ("spillover", "partner"),
                ("flight", "flight"), ("trade", "trade"),
                ("shipping", "trade"), ("portcall", "trade"),
            ):
                if body.startswith(prefix):
                    return fam
            return "other"
        for fam in ("edgar", "legal", "partner", "flight", "trade"):
            if name.startswith(fam + "_"):
                return fam
        if name.startswith("all_"):
            return "cross_source"
        return "market"

    out = importance.copy()
    out["family"] = out["feature"].map(_fam)
    agg = (
        out.groupby("family", as_index=False, observed=True)
        .agg(**{value_col: (value_col, "sum"), "n_features": ("feature", "size")})
        .sort_values(value_col, ascending=False)
    )
    total = agg[value_col].sum()
    # Permutation drops can be negative (destroying a useless feature can help
    # by chance), so normalise on the positive mass to keep the shares readable.
    positive = agg[value_col].clip(lower=0).sum()
    agg["pct"] = 100 * agg[value_col].clip(lower=0) / positive if positive else 0.0
    _ = total
    return agg.reset_index(drop=True)


def attach_edge(oof: pd.DataFrame, meta: pd.DataFrame, payoffs: pd.DataFrame) -> pd.DataFrame:
    """Add per-row payoff estimates and expected edge to the OOF frame."""
    joined = oof.merge(
        meta[["date", "ticker", "barrier_up", "barrier_dn"]], on=["date", "ticker"], how="left"
    )
    joined = assign_payoffs(joined, payoffs)
    joined["edge"] = joined["p"] * joined["avg_win"].fillna(0.0) + (1 - joined["p"]) * joined[
        "avg_loss"
    ].fillna(0.0)
    return joined
