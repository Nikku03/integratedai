"""The registered protocol, end to end: six folds, eight predictors, five metrics.

The loss is a cross-entropy between unit-mass density fields, which is the same
thing as the KL divergence up to a constant the model cannot influence. That
choice follows from what is being asked: the target is a *distribution over
space*, the question is where the protein is, and the per-cell normalisation has
already thrown abundance away. A plain voxelwise MSE would instead spend most of
its gradient on getting the background right.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from vcell.baselines import (
    Atlas,
    NearestTrainingCell,
    annotation_rule,
    best_rule_on_training,
    geometric_rule,
)
from vcell.dataset import CellFrameDataset, load_frames, split_by_fov, unit_mass
from vcell.knowledge import KNOWLEDGE_DIM, POC_STRUCTURES, knowledge_vector
from vcell.metrics import (
    METRIC_NAMES,
    fov_clustered_bootstrap,
    score_cell,
    signed_nuclear_distance,
)
from vcell.model import ConditionalUNet3D, count_parameters

EPS = 1e-8

# H6, from the addendum to the pre-registration: hold out a protein while a
# different protein annotated to the same compartment stays in training, so the
# compartment input is observed and only the protein is unseen. These three
# pairs are every pair in the 25-line annotation table that shares a dominant
# compartment; microtubules and mitochondria have no partner at any scale this
# dataset supports.
COVERED_PAIRS: tuple[tuple[str, str], ...] = (
    ("SEC61B", "ATP2A2"),
    ("LMNB1", "NUP153"),
    ("ACTB", "ACTN1"),
)


def concat_frames(*parts: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Stack several frames dicts into one. Grids must already agree."""
    parts = tuple(p for p in parts if p is not None)
    grids = {tuple(p["target"].shape[1:]) for p in parts}
    if len(grids) > 1:
        raise ValueError(f"cannot concatenate frames on different grids: {grids}")
    return {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}


def _normalise_pred(pred: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    pred = pred * mask
    return pred / pred.sum(dim=(1, 2, 3), keepdim=True).clamp_min(EPS)


def cross_entropy_loss(pred: torch.Tensor, target: torch.Tensor, mask: torch.Tensor):
    """CE(target, pred) over the cell's voxels, and the KL it implies."""
    p = _normalise_pred(pred, mask)
    ce = -(target * (p + EPS).log()).sum(dim=(1, 2, 3))
    entropy = -(target * (target + EPS).log()).sum(dim=(1, 2, 3))
    return ce.mean(), (ce - entropy).mean().detach()


def train_model(
    frames: dict[str, np.ndarray],
    train_indices: np.ndarray,
    epochs: int,
    batch_size: int,
    seed: int,
    ablate_knowledge: bool = False,
    threads: int = 4,
    log_prefix: str = "",
) -> ConditionalUNet3D:
    torch.manual_seed(seed)
    torch.set_num_threads(threads)
    grid = frames["target"].shape[1:]
    model = ConditionalUNet3D(in_channels=2, cond_dim=KNOWLEDGE_DIM, base=12, depth=3)
    dataset = CellFrameDataset(
        frames, train_indices, augment=True, ablate_knowledge=ablate_knowledge, seed=seed
    )
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)
    optimiser = torch.optim.Adam(model.parameters(), lr=1e-3)
    print(
        f"{log_prefix}training on {len(dataset)} cells, grid {tuple(grid)}, "
        f"{count_parameters(model)/1e3:.0f}k parameters"
        + (", knowledge ABLATED" if ablate_knowledge else ""),
        flush=True,
    )
    model.train()
    for epoch in range(1, epochs + 1):
        t0 = time.time()
        total_kl, batches = 0.0, 0
        for reference, knowledge, target, mask in loader:
            optimiser.zero_grad(set_to_none=True)
            loss, kl = cross_entropy_loss(model(reference, knowledge), target, mask)
            loss.backward()
            optimiser.step()
            total_kl += float(kl)
            batches += 1
        if epoch == 1 or epoch % 5 == 0 or epoch == epochs:
            print(
                f"{log_prefix}  epoch {epoch:3d}/{epochs}  KL {total_kl/max(batches,1):.4f}"
                f"  {time.time()-t0:.0f}s",
                flush=True,
            )
    model.eval()
    return model


def _predict(model: ConditionalUNet3D, reference: np.ndarray, knowledge: np.ndarray,
             mask: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        out = model(
            torch.from_numpy(reference.astype(np.float32))[None],
            torch.from_numpy(knowledge.astype(np.float32))[None],
        )
        out = _normalise_pred(out, torch.from_numpy(mask.astype(np.float32))[None])
    return out[0].numpy()


def evaluate_fold(
    fold: str,
    frames: dict[str, np.ndarray],
    train_indices: np.ndarray,
    test_indices: np.ndarray,
    model: ConditionalUNet3D,
    reference_only: ConditionalUNet3D | None,
    trained_genes: set[str],
) -> list[dict]:
    """Score every predictor on every test cell. Returns flat per-cell records."""
    atlas = Atlas(
        frames["target"][train_indices],
        frames["gene"][train_indices],
        frames["cell_mask"][train_indices],
    )
    nearest = NearestTrainingCell(
        frames["reference"][train_indices].astype(np.float32),
        frames["target"][train_indices],
        frames["gene"][train_indices],
    )
    genes_in_test = sorted(set(frames["gene"][test_indices].tolist()))
    # A deterministic wrong answer for the identity control: the next gene round
    # the ring. Nothing is drawn at random, so the control is reproducible.
    ring = sorted(trained_genes | set(genes_in_test))
    wrong = {g: ring[(ring.index(g) + 1) % len(ring)] for g in ring}
    best_rules = {
        g: best_rule_on_training(frames, train_indices, g)
        for g in trained_genes
    }

    records: list[dict] = []
    for row in test_indices:
        gene = str(frames["gene"][row])
        reference = frames["reference"][row].astype(np.float32)
        cell_mask = frames["cell_mask"][row]
        nuc_mask = frames["nuc_mask"][row]
        struct_mask = frames["struct_mask"][row]
        voxel = frames["voxel_micron"][row]
        target = unit_mass(frames["target"][row].astype(np.float32), cell_mask)
        distance = signed_nuclear_distance(nuc_mask, voxel)
        maskf = cell_mask.astype(np.float32)

        predictions: dict[str, np.ndarray] = {
            "model": _predict(model, reference, knowledge_vector(gene), maskf),
            "model_shuffled_identity": _predict(
                model, reference, knowledge_vector(wrong[gene]), maskf
            ),
            "atlas_pooled": atlas.predict_pooled(),
            "nearest_train_cell": nearest.predict(
                reference, gene if gene in trained_genes else None
            ),
            "rule_annotation": geometric_rule(
                annotation_rule(gene), nuc_mask, cell_mask, voxel
            ),
        }
        if gene in trained_genes:
            predictions["atlas_own_structure"] = atlas.predict(gene)
            predictions["rule_best_on_train"] = geometric_rule(
                best_rules[gene], nuc_mask, cell_mask, voxel
            )
        if reference_only is not None:
            predictions["reference_only"] = _predict(
                reference_only, reference, np.zeros(KNOWLEDGE_DIM, np.float32), maskf
            )

        for name, field in predictions.items():
            scores = score_cell(
                unit_mass(field, cell_mask),
                target,
                struct_mask,
                nuc_mask,
                cell_mask,
                voxel,
                distance=distance,
            )
            records.append(
                {
                    "fold": fold,
                    "predictor": name,
                    "gene": gene,
                    "cell_id": str(frames["cell_id"][row]),
                    "fov_id": str(frames["fov_id"][row]),
                    "cell_stage": str(frames["cell_stage"][row]),
                    "seen_in_training": gene in trained_genes,
                    **scores,
                }
            )
    return records


def summarise(records: list[dict], seed: int = 0) -> list[dict]:
    """Mean and FOV-clustered 95% interval per (fold, gene, predictor, metric)."""
    keys = sorted({(r["fold"], r["gene"], r["predictor"]) for r in records})
    rows = []
    for fold, gene, predictor in keys:
        subset = [r for r in records if r["fold"] == fold and r["gene"] == gene
                  and r["predictor"] == predictor]
        fovs = np.array([r["fov_id"] for r in subset])
        row = {"fold": fold, "gene": gene, "predictor": predictor, "n_cells": len(subset)}
        for metric in METRIC_NAMES:
            mean, lo, hi = fov_clustered_bootstrap(
                np.array([r[metric] for r in subset], dtype=float), fovs, seed=seed
            )
            row[metric] = mean
            row[f"{metric}_lo"], row[f"{metric}_hi"] = lo, hi
        rows.append(row)
    return rows


def run_protocol(
    data_dir: Path,
    epochs: int = 25,
    batch_size: int = 4,
    folds: list[str] | None = None,
    out_dir: Path | None = None,
    seed: int = 20260914,
    threads: int = 4,
) -> int:
    out_dir = Path(out_dir or (data_dir / "results"))
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = load_frames(data_dir / "frames_interphase.npz")
    mitotic_path = data_dir / "frames_mitotic.npz"
    mitotic = load_frames(mitotic_path) if mitotic_path.exists() else None
    all_genes = sorted(set(frames["gene"].tolist()))
    print(f"{frames['target'].shape[0]} interphase cells, lines: {', '.join(all_genes)}")
    print(f"canonical voxel: {np.round(frames['voxel_micron'].mean(axis=0), 3)} micron "
          f"(mean over cells)")

    records: list[dict] = []
    wanted = set(folds) if folds else None

    # --- H1: structures in training, cells from held-out fields of view -------
    if wanted is None or "seen" in wanted:
        train_idx, test_idx = split_by_fov(frames, test_fraction=0.2, seed=seed)
        model = train_model(frames, train_idx, epochs, batch_size, seed,
                            threads=threads, log_prefix="[seen] ")
        ablated = train_model(frames, train_idx, epochs, batch_size, seed,
                              ablate_knowledge=True, threads=threads,
                              log_prefix="[seen/ablated] ")
        records += evaluate_fold("seen", frames, train_idx, test_idx, model, ablated,
                                 set(all_genes))
        torch.save(model.state_dict(), out_dir / "model_seen.pt")

        # --- H5: mitotic cells, never trained on, scored with the same model --
        if mitotic is not None:
            records += evaluate_mitotic(
                mitotic, frames, train_idx, model, ablated, set(all_genes)
            )

    # --- H2: the unseen structure, as registered -----------------------------
    for gene in POC_STRUCTURES:
        fold = f"loso_{gene}"
        if wanted is not None and fold not in wanted and gene not in wanted:
            continue
        train_idx = np.flatnonzero(frames["gene"] != gene)
        test_idx = np.flatnonzero(frames["gene"] == gene)
        trained = set(all_genes) - {gene}
        print(f"\n[{fold}] holding out {gene} entirely: "
              f"{train_idx.size} train / {test_idx.size} test cells")
        model = train_model(frames, train_idx, epochs, batch_size, seed,
                            threads=threads, log_prefix=f"[{fold}] ")
        records += evaluate_fold(fold, frames, train_idx, test_idx, model, None, trained)
        torch.save(model.state_dict(), out_dir / f"model_{fold}.pt")

    # --- H6: the unseen protein with its compartment covered -----------------
    extended_path = data_dir / "frames_extended_interphase.npz"
    if extended_path.exists():
        extended = concat_frames(frames, load_frames(extended_path))
        ext_genes = sorted(set(extended["gene"].tolist()))
        print(f"\nextended set: {extended['target'].shape[0]} cells, "
              f"lines: {', '.join(ext_genes)}")
        for held, partner in COVERED_PAIRS:
            fold = f"covered_{held}"
            if wanted is not None and fold not in wanted and held not in wanted:
                continue
            if partner not in ext_genes:
                print(f"[{fold}] skipped: partner {partner} not fetched")
                continue
            train_idx = np.flatnonzero(extended["gene"] != held)
            test_idx = np.flatnonzero(extended["gene"] == held)
            trained = set(ext_genes) - {held}
            print(f"\n[{fold}] holding out {held}, keeping {partner} "
                  f"({train_idx.size} train / {test_idx.size} test cells)")
            model = train_model(extended, train_idx, epochs, batch_size, seed,
                                threads=threads, log_prefix=f"[{fold}] ")
            records += evaluate_fold(fold, extended, train_idx, test_idx, model,
                                     None, trained)
            torch.save(model.state_dict(), out_dir / f"model_{fold}.pt")
    else:
        print(f"\nno extended set at {extended_path}; H6 folds skipped")

    (out_dir / "records.json").write_text(json.dumps(records, indent=1))
    summary = summarise(records, seed=seed)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    print(f"\nwrote {out_dir/'records.json'} ({len(records)} rows) and "
          f"{out_dir/'summary.json'} ({len(summary)} rows)")
    return 0


def evaluate_mitotic(
    mitotic: dict[str, np.ndarray],
    frames: dict[str, np.ndarray],
    train_indices: np.ndarray,
    model: ConditionalUNet3D,
    reference_only: ConditionalUNet3D | None,
    trained_genes: set[str],
) -> list[dict]:
    """Score the interphase-trained model on mitotic cells it never saw.

    The baselines still come from the interphase training set, which is the
    point: an atlas built on interphase cells is exactly what a model that
    learned "interphase geometry" has to offer a dividing cell.
    """
    merged = {
        key: np.concatenate([frames[key], mitotic[key]])
        for key in frames
        if frames[key].shape[1:] == mitotic[key].shape[1:] or frames[key].ndim == 1
    }
    offset = frames["target"].shape[0]
    test_idx = np.arange(offset, offset + mitotic["target"].shape[0])
    return evaluate_fold(
        "mitotic", merged, train_indices, test_idx, model, reference_only, trained_genes
    )
