"""Turn the per-cell records into the tables that go in the result document."""

from __future__ import annotations

import numpy as np

from vcell.metrics import HIGHER_IS_BETTER, METRIC_NAMES

PREDICTOR_ORDER = (
    "model",
    "model_shuffled_identity",
    "reference_only",
    "atlas_own_structure",
    "atlas_pooled",
    "nearest_train_cell",
    "rule_best_on_train",
    "rule_annotation",
)

LABELS = {
    "model": "model",
    "model_shuffled_identity": "model, shuffled identity",
    "reference_only": "reference-only (ablated)",
    "atlas_own_structure": "atlas, own structure",
    "atlas_pooled": "atlas, pooled",
    "nearest_train_cell": "nearest training cell",
    "rule_best_on_train": "geometric rule, best on train",
    "rule_annotation": "geometric rule, from annotation",
}

METRIC_HEADERS = {
    "pearson_r": "r",
    "dice": "Dice",
    "com_radius": "COM (r_cell)",
    "w1_micron": "W1 (um)",
    "nuc_fraction_err": "nuc-frac err",
}


def _rows(summary: list[dict], fold: str, gene: str) -> dict[str, dict]:
    return {
        r["predictor"]: r
        for r in summary
        if r["fold"] == fold and r["gene"] == gene
    }


def gene_table(summary: list[dict], fold: str, gene: str, ci_metric: str = "dice") -> str:
    """One markdown table: predictors down the side, the five metrics across."""
    rows = _rows(summary, fold, gene)
    if not rows:
        return f"_no rows for {fold}/{gene}_\n"
    header = "| predictor | " + " | ".join(METRIC_HEADERS[m] for m in METRIC_NAMES) + " |"
    rule = "|---" * (len(METRIC_NAMES) + 1) + "|"
    lines = [header, rule]
    best = {
        m: max(
            (r[m] for r in rows.values() if np.isfinite(r[m])),
            default=float("nan"),
            key=(lambda v: v) if HIGHER_IS_BETTER[m] else (lambda v: -v),
        )
        for m in METRIC_NAMES
    }
    for predictor in PREDICTOR_ORDER:
        if predictor not in rows:
            continue
        row = rows[predictor]
        cells = []
        for metric in METRIC_NAMES:
            value = row[metric]
            text = "n/a" if not np.isfinite(value) else f"{value:.3f}"
            if np.isfinite(value) and np.isclose(value, best[metric]):
                text = f"**{text}**"
            if metric == ci_metric and np.isfinite(row.get(f"{metric}_lo", float("nan"))):
                text += f" [{row[f'{metric}_lo']:.3f}, {row[f'{metric}_hi']:.3f}]"
            cells.append(text)
        lines.append(f"| {LABELS.get(predictor, predictor)} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def headline_table(summary: list[dict], folds: list[str], metric: str = "dice") -> str:
    """Model against the baselines it has to beat, one row per fold."""
    contenders = (
        "model",
        "model_shuffled_identity",
        "atlas_pooled",
        "atlas_own_structure",
        "nearest_train_cell",
        "rule_annotation",
        "rule_best_on_train",
    )
    present = [
        c for c in contenders
        if any(r["predictor"] == c and r["fold"] in folds for r in summary)
    ]
    lines = [
        "| fold | structure | n | " + " | ".join(LABELS[c] for c in present) + " | verdict |",
        "|---" * (len(present) + 4) + "|",
    ]
    for fold in folds:
        genes = sorted({r["gene"] for r in summary if r["fold"] == fold})
        for gene in genes:
            rows = _rows(summary, fold, gene)
            if "model" not in rows:
                continue
            model_value = rows["model"][metric]
            if not np.isfinite(model_value):
                lines.append(
                    f"| {fold} | {gene} | {rows['model']['n_cells']} | "
                    + " | ".join("n/a" for _ in present)
                    + " | metric undefined |"
                )
                continue
            beaten = [
                c for c in present
                if c not in ("model", "model_shuffled_identity")
                and c in rows
                and np.isfinite(rows[c][metric])
                and rows[c][metric] >= model_value
            ]
            cells = [
                f"{rows[c][metric]:.3f}" if c in rows and np.isfinite(rows[c][metric]) else "n/a"
                for c in present
            ]
            verdict = "model wins" if not beaten else "lost to " + ", ".join(
                LABELS[b] for b in beaten
            )
            lines.append(
                f"| {fold} | {gene} | {rows['model']['n_cells']} | "
                + " | ".join(cells)
                + f" | {verdict} |"
            )
    return "\n".join(lines) + "\n"
