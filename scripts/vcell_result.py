#!/usr/bin/env python3
"""Render the result tables for docs/RESULT_VIRTUAL_CELL.md from the run's JSON.

Every number in the result document comes out of here, so none of them is
transcribed by hand and all of them can be regenerated from `records.json`.

    python scripts/vcell_result.py --results .vcell/results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.metrics import METRIC_NAMES  # noqa: E402
from vcell.report import LABELS, gene_table, headline_table  # noqa: E402


def _value(summary, fold, gene, predictor, metric="dice"):
    for row in summary:
        if (row["fold"], row["gene"], row["predictor"]) == (fold, gene, predictor):
            return float(row[metric])
    return float("nan")


def gate_report(summary, folds, metric="dice") -> str:
    """The four registered gates, per fold and structure, pass or fail."""
    lines = [
        "| fold | structure | vs atlas | vs geometric rule | identity used | vs AAVS1 floor |",
        "|---|---|---|---|---|---|",
    ]
    for fold in folds:
        for gene in sorted({r["gene"] for r in summary if r["fold"] == fold}):
            model = _value(summary, fold, gene, "model", metric)
            if not np.isfinite(model):
                continue
            own = _value(summary, fold, gene, "atlas_own_structure", metric)
            pooled = _value(summary, fold, gene, "atlas_pooled", metric)
            atlas = np.nanmax([own, pooled])
            rule = np.nanmax([
                _value(summary, fold, gene, "rule_annotation", metric),
                _value(summary, fold, gene, "rule_best_on_train", metric),
            ])
            shuffled = _value(summary, fold, gene, "model_shuffled_identity", metric)
            floor = _value(summary, fold, "AAVS1", "model", metric)

            def verdict(ours, theirs, label):
                if not np.isfinite(theirs):
                    return "n/a"
                mark = "pass" if ours > theirs else "**FAIL**"
                return f"{mark} ({ours:.3f} vs {theirs:.3f})"

            identity = (
                "n/a" if not np.isfinite(shuffled)
                else ("pass" if model > shuffled else "**FAIL**")
                + f" ({model:.3f} vs {shuffled:.3f})"
            )
            above_floor = (
                "n/a" if not np.isfinite(floor) or gene == "AAVS1"
                else ("pass" if model > floor else "**FAIL**") + f" ({floor:.3f})"
            )
            lines.append(
                f"| {fold} | {gene} | {verdict(model, atlas, 'atlas')} | "
                f"{verdict(model, rule, 'rule')} | {identity} | {above_floor} |"
            )
    return "\n".join(lines) + "\n"


def loso_vs_covered(summary, metric="dice") -> str:
    """H2 against H6 for the three structures that have both."""
    lines = [
        "| structure | seen (H1) | held out, compartment uncovered (H2) | "
        "held out, compartment covered (H6) | partner |",
        "|---|---|---|---|---|",
    ]
    partners = {"SEC61B": "ATP2A2", "LMNB1": "NUP153", "ACTB": "ACTN1"}
    for gene in ("ACTB", "TUBA1B", "SEC61B", "TOMM20", "LMNB1"):
        seen = _value(summary, "seen", gene, "model", metric)
        loso = _value(summary, f"loso_{gene}", gene, "model", metric)
        covered = _value(summary, f"covered_{gene}", gene, "model", metric)
        fmt = lambda v: "n/a" if not np.isfinite(v) else f"{v:.3f}"  # noqa: E731
        lines.append(
            f"| {gene} | {fmt(seen)} | {fmt(loso)} | {fmt(covered)} | "
            f"{partners.get(gene, 'none in any of the 25 lines')} |"
        )
    return "\n".join(lines) + "\n"


def joint_table(joint: dict) -> str:
    genes = joint["genes"]
    real = np.array(joint["real_pairwise_w1"])
    pred = np.array(joint["predicted_pairwise_w1"])
    lines = ["| pair | measured W1 (um) | virtual cell W1 (um) | error |", "|---|---|---|---|"]
    for i, a in enumerate(genes):
        for j, b in enumerate(genes):
            if i < j:
                lines.append(
                    f"| {a} - {b} | {real[i, j]:.2f} | {pred[i, j]:.2f} | "
                    f"{pred[i, j] - real[i, j]:+.2f} |"
                )
    lines.append("")
    lines.append(
        f"Arrangement correlation across the {len(genes) * (len(genes) - 1) // 2} pairs: "
        f"**{joint['pairwise_correlation']:.3f}**; mean absolute error "
        f"**{joint['pairwise_mean_abs_error_micron']:.2f} um** over "
        f"{joint['n_virtual_cells']} virtual cells."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default=".vcell/results")
    parser.add_argument("--metric", default="dice", choices=list(METRIC_NAMES))
    args = parser.parse_args()

    root = Path(args.results)
    summary = json.loads((root / "summary.json").read_text())
    folds = sorted({r["fold"] for r in summary})

    print("## Headline\n")
    print(headline_table(summary, folds, metric=args.metric))
    print("\n## Gates\n")
    print(gate_report(summary, folds, metric=args.metric))
    print("\n## H2 against H6\n")
    print(loso_vs_covered(summary, metric=args.metric))
    joint_path = root / "joint.json"
    if joint_path.exists():
        print("\n## H4, the joint virtual cell\n")
        print(joint_table(json.loads(joint_path.read_text())))
    print("\n## Every fold, every structure, every predictor\n")
    for fold in folds:
        for gene in sorted({r["gene"] for r in summary if r["fold"] == fold}):
            print(f"\n### {fold} / {gene}\n")
            print(gene_table(summary, fold, gene))
    print(f"\n_Predictor labels: {', '.join(sorted(LABELS.values()))}._")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
