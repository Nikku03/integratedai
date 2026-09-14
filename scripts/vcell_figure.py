#!/usr/bin/env python3
"""Render predicted against measured density fields, as maximum projections.

Correlations and Dice scores say how well a prediction places a structure. They
do not show *how* it is wrong, and the failure modes here are visual: a field
smeared over the whole cytoplasm scores respectably while looking nothing like
mitochondria, and a nuclear-envelope prediction that is really just the edge of
the DNA channel is obvious at a glance and invisible in a table.

    python scripts/vcell_figure.py --data-dir .vcell --fold seen --out fig.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.baselines import annotation_rule, geometric_rule  # noqa: E402
from vcell.dataset import load_frames, split_by_fov, unit_mass  # noqa: E402
from vcell.knowledge import KNOWLEDGE_DIM, POC_STRUCTURES, knowledge_vector  # noqa: E402
from vcell.metrics import dice_volume_matched  # noqa: E402
from vcell.model import ConditionalUNet3D  # noqa: E402
from vcell.train import _predict  # noqa: E402


def _projection(field: np.ndarray) -> np.ndarray:
    """Maximum intensity along Z, the optical axis."""
    out = field.max(axis=0)
    top = np.percentile(out, 99.5)
    return out / top if top > 0 else out


def main() -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".vcell")
    parser.add_argument("--results", default=None)
    parser.add_argument("--fold", default="seen")
    parser.add_argument("--out", default="vcell_fields.png")
    parser.add_argument("--seed", type=int, default=20260914)
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    results = Path(args.results or (data_dir / "results"))
    frames = load_frames(data_dir / "frames_interphase.npz")
    if args.fold.startswith("covered_"):
        from vcell.train import concat_frames

        frames = concat_frames(frames, load_frames(data_dir / "frames_extended_interphase.npz"))

    model = ConditionalUNet3D(in_channels=2, cond_dim=KNOWLEDGE_DIM, base=12, depth=3)
    model.load_state_dict(torch.load(results / f"model_{args.fold}.pt", map_location="cpu"))
    model.eval()

    if args.fold == "seen":
        _, test_idx = split_by_fov(frames, test_fraction=0.2, seed=args.seed)
        genes = list(POC_STRUCTURES)
    else:
        held = args.fold.split("_", 1)[1]
        test_idx = np.flatnonzero(frames["gene"] == held)
        genes = [held]

    rows = []
    for gene in genes:
        candidates = [i for i in test_idx if str(frames["gene"][i]) == gene]
        if candidates:
            rows.append((gene, candidates[0]))
    if not rows:
        print("no test cells to draw")
        return 1

    columns = ["DNA", "membrane", "measured", "model", "geometric rule"]
    fig, axes = plt.subplots(
        len(rows), len(columns), figsize=(2.1 * len(columns), 2.25 * len(rows)), squeeze=False
    )
    for r, (gene, row) in enumerate(rows):
        reference = frames["reference"][row].astype(np.float32)
        cell_mask = frames["cell_mask"][row]
        nuc_mask = frames["nuc_mask"][row]
        voxel = frames["voxel_micron"][row]
        truth = unit_mass(frames["target"][row].astype(np.float32), cell_mask)
        prediction = _predict(model, reference, knowledge_vector(gene),
                              cell_mask.astype(np.float32))
        rule = unit_mass(
            geometric_rule(annotation_rule(gene), nuc_mask, cell_mask, voxel), cell_mask
        )
        dice_model = dice_volume_matched(prediction, frames["struct_mask"][row], cell_mask)
        dice_rule = dice_volume_matched(rule, frames["struct_mask"][row], cell_mask)
        panels = [reference[0], reference[1], truth, prediction, rule]
        titles = [
            "DNA", "membrane", f"{gene} measured",
            f"model  Dice {dice_model:.2f}", f"rule  Dice {dice_rule:.2f}",
        ]
        for c, (panel, title) in enumerate(zip(panels, titles, strict=True)):
            ax = axes[r][c]
            ax.imshow(_projection(panel), cmap="magma", vmin=0, vmax=1)
            ax.set_title(title, fontsize=8)
            ax.set_xticks([])
            ax.set_yticks([])
        axes[r][0].set_ylabel(gene, fontsize=9)

    fig.suptitle(
        f"{args.fold}: maximum-intensity projections through the canonical frame",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(args.out, dpi=130)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
