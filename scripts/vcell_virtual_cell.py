#!/usr/bin/env python3
"""Experiment 1 of docs/PREREG_SCALE.md: the virtual cell at 25 structures.

The five-structure version reported an arrangement correlation of 0.990 over 10
pairs, 4 of which involved the single nuclear structure. All 25 Allen lines give
**300 pairs** spanning nucleolus, chromatin, nuclear envelope, pores, speckles,
centrosome, ER, Golgi, mitochondria, endolysosome, peroxisome, plasma membrane,
junctions and the cytoskeleton, where a correlation near 0.99 is no longer
available for free.

    python scripts/vcell_virtual_cell.py --data-dir .vcell
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.baselines import annotation_rule, geometric_rule  # noqa: E402
from vcell.dataset import load_frames, split_by_fov  # noqa: E402
from vcell.joint import joint_consistency  # noqa: E402
from vcell.knowledge import COMPARTMENTS as KNOWN_COMPARTMENTS  # noqa: E402
from vcell.knowledge import PROTEINS, knowledge_vector  # noqa: E402
from vcell.metrics import dice_volume_matched  # noqa: E402
from vcell.retrieval import protein_clustered_bootstrap  # noqa: E402
from vcell.train import _predict, concat_frames, train_model  # noqa: E402

# Which of the 25 structures sit inside the nucleus. Taken from the dominant
# annotated compartment in vcell.knowledge, not from any image.
NUCLEAR = {"nucleoplasm", "chromatin", "nucleolus", "nuclear_envelope",
           "nuclear_pore", "nuclear_speckle"}


def dominant_compartment(gene: str) -> str:
    v = PROTEINS[gene].compartment_vector()
    return KNOWN_COMPARTMENTS[int(np.argmax(v))] if v.any() else "unknown"


def subset_correlation(genes, real, pred, keep) -> dict:
    idx = [i for i, g in enumerate(genes) if g in keep]
    if len(idx) < 3:
        return {"n_pairs": 0, "pearson": float("nan"), "spearman": float("nan")}
    R = real[np.ix_(idx, idx)]
    P = pred[np.ix_(idx, idx)]
    u = np.triu_indices(len(idx), 1)
    a, b = R[u], P[u]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return {"n_pairs": int(a.size), "pearson": float("nan"),
                "spearman": float("nan")}
    from scipy.stats import spearmanr
    return {
        "n_pairs": int(a.size),
        "pearson": float(np.corrcoef(a, b)[0, 1]),
        "spearman": float(spearmanr(a, b).statistic),
        "mae_micron": float(np.abs(a - b).mean()),
        "measured_range": [float(a.min()), float(a.max())],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--epochs", type=int, default=25)
    ap.add_argument("--batch-size", type=int, default=4)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--reuse-model", default=None)
    args = ap.parse_args()

    D = Path(args.data_dir)
    parts = []
    for name in ("frames_interphase.npz", "frames_extended_interphase.npz",
                 "frames_more_interphase.npz"):
        if (D / name).exists():
            parts.append(load_frames(D / name))
            print(f"loaded {name}: {parts[-1]['target'].shape[0]} cells")
    frames = concat_frames(*parts)
    genes = sorted(set(frames["gene"].tolist()))
    print(f"\n{frames['target'].shape[0]} cells over {len(genes)} structures: "
          f"{', '.join(genes)}")

    train_idx, test_idx = split_by_fov(frames, test_fraction=0.2, seed=args.seed)
    out_dir = D / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt = Path(args.reuse_model) if args.reuse_model else out_dir / "model_all25.pt"

    from vcell.knowledge import KNOWLEDGE_DIM
    from vcell.model import ConditionalUNet3D
    if ckpt.exists():
        print(f"reusing {ckpt}")
        model = ConditionalUNet3D(in_channels=2, cond_dim=KNOWLEDGE_DIM,
                                  base=12, depth=3)
        model.load_state_dict(torch.load(ckpt, map_location="cpu"))
        model.eval()
    else:
        model = train_model(frames, train_idx, args.epochs, args.batch_size,
                            args.seed, threads=args.threads, log_prefix="[all25] ")
        torch.save(model.state_dict(), ckpt)

    # H3: per-structure accuracy on held-out cells, against the geometric rule.
    print("\n=== H3: per-structure accuracy at 25 conditions ===")
    print(f"{'structure':12s} {'n':>4s} {'model Dice':>11s} {'rule Dice':>10s} "
          f"{'chance':>7s} {'lift':>6s}")
    per_structure, dice_all, dice_genes = {}, [], []
    for gene in genes:
        rows = test_idx[frames["gene"][test_idx] == gene]
        if rows.size == 0:
            continue
        md, rd, ch = [], [], []
        for row in rows:
            cell = frames["cell_mask"][row]
            nuc = frames["nuc_mask"][row]
            truth = frames["struct_mask"][row]
            vox = frames["voxel_micron"][row]
            pred = _predict(model, frames["reference"][row].astype(np.float32),
                            knowledge_vector(gene), cell.astype(np.float32))
            md.append(dice_volume_matched(pred, truth, cell))
            rd.append(dice_volume_matched(
                geometric_rule(annotation_rule(gene), nuc, cell, vox), truth, cell))
            ch.append(float(truth.sum()) / max(float(cell.sum()), 1.0))
        md = np.array(md, float)
        per_structure[gene] = {
            "n": int(rows.size), "dice": float(np.nanmean(md)),
            "rule_dice": float(np.nanmean(rd)), "chance": float(np.mean(ch)),
            "lift": float(np.nanmean(md) / max(np.mean(ch), 1e-9)),
            "compartment": dominant_compartment(gene),
        }
        dice_all += [x for x in md if np.isfinite(x)]
        dice_genes += [gene] * int(np.isfinite(md).sum())
        s = per_structure[gene]
        print(f"{gene:12s} {s['n']:4d} {s['dice']:11.3f} {s['rule_dice']:10.3f} "
              f"{s['chance']:7.3f} {s['lift']:6.2f}x")
    m, lo, hi = protein_clustered_bootstrap(np.array(dice_all),
                                            np.array(dice_genes), seed=args.seed)
    print(f"\nmean Dice over {len(per_structure)} structures: "
          f"{m:.3f} [{lo:.3f}, {hi:.3f}]")

    # H1 and H2: the arrangement, over all 300 pairs.
    print("\n=== H1/H2: the joint virtual cell ===")
    joint = joint_consistency(
        lambda ref, know, mask: _predict(model, ref, know, mask),
        frames, train_idx, test_idx, genes)
    names = joint["genes"]
    real = np.array(joint["real_pairwise_w1"])
    pred = np.array(joint["predicted_pairwise_w1"])
    nuclear = {g for g in names if dominant_compartment(g) in NUCLEAR}
    cyto = set(names) - nuclear
    result = {
        "n_structures": len(names),
        "structures": names,
        "nuclear": sorted(nuclear),
        "cytoplasmic": sorted(cyto),
        "all_pairs": subset_correlation(names, real, pred, set(names)),
        "cytoplasmic_only": subset_correlation(names, real, pred, cyto),
        "nuclear_only": subset_correlation(names, real, pred, nuclear),
        "n_virtual_cells": joint["n_virtual_cells"],
        "profile_w1_micron": joint["profile_w1_micron"],
        "per_structure": per_structure,
        "mean_dice": m, "mean_dice_lo": lo, "mean_dice_hi": hi,
        "real_pairwise_w1": real.tolist(),
        "predicted_pairwise_w1": pred.tolist(),
    }
    for key in ("all_pairs", "cytoplasmic_only", "nuclear_only"):
        s = result[key]
        print(f"  {key:18s} {s['n_pairs']:4d} pairs  pearson {s['pearson']:.3f}  "
              f"spearman {s['spearman']:.3f}"
              + (f"  measured range {s['measured_range'][0]:.2f}-"
                 f"{s['measured_range'][1]:.2f} um" if s["n_pairs"] else ""))
    (out_dir / "virtual_cell_25.json").write_text(json.dumps(result, indent=1,
                                                             default=float))
    print(f"\nwrote {out_dir/'virtual_cell_25.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
