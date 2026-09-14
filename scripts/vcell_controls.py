#!/usr/bin/env python3
"""Two corrections to the registered evaluation, computed from saved checkpoints.

**Chance.** Volume-matched Dice is thresholded at the true structure's voxel
count, so a prediction placed at random scores the structure's *base rate* --
the fraction of the cell its structure occupies. Those base rates run from 3.0%
(NUP153) to 18.3% (the AAVS1 control), so raw Dice is not comparable across
structures, and registered gate 4 -- "beat the AAVS1 floor" -- was comparing
numbers on different scales. Reported here as **lift**, Dice divided by that
structure's own measured chance level.

**A wrong identity that is actually wrong.** The registered identity control
feeds the next cell line alphabetically. In the two H6 folds where a
same-compartment partner was added on purpose, the alphabetical neighbour *is*
that partner -- ACTN1 for ACTB, NUP153 for LMNB1 -- so the control was asking
the model for an actin protein instead of actin, and a nuclear-envelope protein
instead of the nuclear envelope. It could not fail. Recomputed here over every
other trained line, split into swaps that keep the compartment and swaps that
change it. The second group is the real control; the first measures something
else worth knowing, which is whether the model has learned the compartment or
the individual protein.

No model is retrained: this reloads each fold's checkpoint and re-runs
inference.

    python scripts/vcell_controls.py --data-dir .vcell --out controls.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.dataset import load_frames, split_by_fov, unit_mass  # noqa: E402
from vcell.knowledge import KNOWLEDGE_DIM, POC_STRUCTURES, PROTEINS, knowledge_vector  # noqa: E402
from vcell.metrics import dice_volume_matched, fov_clustered_bootstrap, pearson_r  # noqa: E402
from vcell.model import ConditionalUNet3D  # noqa: E402
from vcell.train import COVERED_PAIRS, _predict, concat_frames  # noqa: E402


def shares_compartment(a: str, b: str) -> bool:
    """True if the two lines are annotated to any compartment in common."""
    va = PROTEINS[a].compartment_vector() > 0
    vb = PROTEINS[b].compartment_vector() > 0
    return bool((va & vb).any())


def load_model(path: Path) -> ConditionalUNet3D:
    model = ConditionalUNet3D(in_channels=2, cond_dim=KNOWLEDGE_DIM, base=12, depth=3)
    model.load_state_dict(torch.load(path, map_location="cpu"))
    model.eval()
    return model


def fold_specs(data_dir: Path, seed: int):
    """(fold, frames, test indices, trained genes, checkpoint) for every fold."""
    base = load_frames(data_dir / "frames_interphase.npz")
    extended = concat_frames(base, load_frames(data_dir / "frames_extended_interphase.npz"))
    mitotic = concat_frames(
        load_frames(data_dir / "frames_mitotic.npz"),
        load_frames(data_dir / "frames_extended_mitotic.npz"),
    )
    base_genes = sorted(set(base["gene"].tolist()))
    ext_genes = sorted(set(extended["gene"].tolist()))

    train_idx, test_idx = split_by_fov(base, test_fraction=0.2, seed=seed)
    yield "seen", base, test_idx, set(base_genes), "model_seen.pt"

    # H5 reuses the `seen` model on mitotic cells of the six registered lines.
    mito_six = np.flatnonzero(np.isin(mitotic["gene"], list(base_genes)))
    yield "mitotic", mitotic, mito_six, set(base_genes), "model_seen.pt"

    for gene in POC_STRUCTURES:
        yield (
            f"loso_{gene}",
            base,
            np.flatnonzero(base["gene"] == gene),
            set(base_genes) - {gene},
            f"model_loso_{gene}.pt",
        )
    for held, _partner in COVERED_PAIRS:
        yield (
            f"covered_{held}",
            extended,
            np.flatnonzero(extended["gene"] == held),
            set(ext_genes) - {held},
            f"model_covered_{held}.pt",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".vcell")
    parser.add_argument("--results", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    torch.set_num_threads(args.threads)
    data_dir = Path(args.data_dir)
    results = Path(args.results or (data_dir / "results"))
    out_path = Path(args.out or (results / "controls.json"))

    rows = []
    for fold, frames, test_idx, trained, checkpoint in fold_specs(data_dir, args.seed):
        path = results / checkpoint
        if not path.exists():
            print(f"[{fold}] no checkpoint at {path}; skipped")
            continue
        model = load_model(path)
        for gene in sorted(set(frames["gene"][test_idx].tolist())):
            rows_for_gene = test_idx[frames["gene"][test_idx] == gene]
            others = sorted(trained - {gene})
            same = [g for g in others if shares_compartment(gene, g)]
            diff = [g for g in others if not shares_compartment(gene, g)]

            chance, true_dice, true_r = [], [], []
            swap_same: dict[str, list[float]] = {g: [] for g in same}
            swap_diff: dict[str, list[float]] = {g: [] for g in diff}
            for row in rows_for_gene:
                cell_mask = frames["cell_mask"][row]
                struct_mask = frames["struct_mask"][row]
                maskf = cell_mask.astype(np.float32)
                reference = frames["reference"][row].astype(np.float32)
                target = unit_mass(frames["target"][row].astype(np.float32), cell_mask)
                chance.append(float(struct_mask.sum()) / max(float(cell_mask.sum()), 1.0))
                own = _predict(model, reference, knowledge_vector(gene), maskf)
                true_dice.append(dice_volume_matched(own, struct_mask, cell_mask))
                true_r.append(pearson_r(own, target, cell_mask))
                for other in others:
                    pred = _predict(model, reference, knowledge_vector(other), maskf)
                    score = dice_volume_matched(pred, struct_mask, cell_mask)
                    (swap_same if other in swap_same else swap_diff)[other].append(score)

            fovs = frames["fov_id"][rows_for_gene]
            dice_mean, dice_lo, dice_hi = fov_clustered_bootstrap(
                np.array(true_dice), fovs, seed=args.seed
            )
            chance_mean = float(np.mean(chance))

            def pooled(bucket: dict[str, list[float]]) -> float:
                values = [v for vs in bucket.values() for v in vs if np.isfinite(v)]
                return float(np.mean(values)) if values else float("nan")

            rows.append({
                "fold": fold,
                "gene": gene,
                "n_cells": int(rows_for_gene.size),
                "chance_dice": chance_mean,
                "dice": dice_mean,
                "dice_lo": dice_lo,
                "dice_hi": dice_hi,
                "lift": dice_mean / chance_mean if chance_mean > 0 else float("nan"),
                "pearson_r": float(np.nanmean(true_r)),
                "swap_same_compartment": pooled(swap_same),
                "swap_same_compartment_lines": same,
                "swap_diff_compartment": pooled(swap_diff),
                "swap_diff_compartment_lines": diff,
            })
            print(
                f"[{fold}/{gene}] n={rows_for_gene.size} chance={chance_mean:.3f} "
                f"dice={dice_mean:.3f} lift={rows[-1]['lift']:.2f}x  "
                f"swap-same={rows[-1]['swap_same_compartment']:.3f} "
                f"({len(same)} lines)  swap-diff={rows[-1]['swap_diff_compartment']:.3f} "
                f"({len(diff)} lines)",
                flush=True,
            )

    out_path.write_text(json.dumps(rows, indent=1))
    print(f"\nwrote {out_path} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
