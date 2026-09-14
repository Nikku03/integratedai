"""H4: the joint virtual cell -- five proteins measured apart, placed together.

This is the original motivating idea, and it is the one hypothesis here with no
paired ground truth of any kind. No cell in the collection contains two tagged
structures, so "are these five fields mutually correct in this cell" cannot be
answered directly. What *can* be answered is the population version:

    Do the five predicted fields, conditioned on one shared cell geometry,
    reproduce the spatial relationships that hold between the real structures
    when each is measured in different cells?

The comparison runs on the **signed distance to the nuclear surface**, which is
intrinsic to a cell rather than to the frame, so profiles from different cells
are on the same axis by construction. For each pair of structures we take the
Wasserstein-1 distance between their distance profiles -- a single number saying
how far apart the two structures sit radially. That gives a 5x5 matrix from real
images and a 5x5 matrix from one virtual cell, and the question becomes whether
the two matrices agree.

Evidential status, stated plainly: this is a consistency check, not a test with
ground truth. Reproducing population-level arrangement is necessary for a
virtual cell to be worth anything and nowhere near sufficient.
"""

from __future__ import annotations

import numpy as np

from vcell.dataset import unit_mass
from vcell.knowledge import knowledge_vector
from vcell.metrics import signed_nuclear_distance, weighted_w1

N_BINS = 24
DISTANCE_RANGE = (-4.0, 12.0)  # microns, from inside the nucleus out to the cortex


def distance_profile(
    field: np.ndarray,
    distance: np.ndarray,
    cell_mask: np.ndarray,
    bins: np.ndarray | None = None,
) -> np.ndarray:
    """Density-weighted histogram over signed distance to the nuclear surface."""
    edges = np.linspace(*DISTANCE_RANGE, N_BINS + 1) if bins is None else bins
    weights = np.where(cell_mask, field, 0.0).ravel()
    histogram, _ = np.histogram(distance.ravel(), bins=edges, weights=weights)
    total = histogram.sum()
    return histogram / total if total > 0 else histogram


def profile_distance_matrix(profiles: dict[str, np.ndarray]) -> tuple[list[str], np.ndarray]:
    """Pairwise W1 between structures' radial profiles, in microns."""
    genes = sorted(profiles)
    centres = np.linspace(*DISTANCE_RANGE, N_BINS + 1)
    centres = 0.5 * (centres[:-1] + centres[1:])
    matrix = np.zeros((len(genes), len(genes)), dtype=np.float64)
    for i, a in enumerate(genes):
        for j, b in enumerate(genes):
            if i < j:
                value = weighted_w1(centres, profiles[a], profiles[b])
                matrix[i, j] = matrix[j, i] = value
    return genes, matrix


def real_profiles(
    frames: dict[str, np.ndarray], indices: np.ndarray, genes: list[str]
) -> dict[str, np.ndarray]:
    """Mean measured profile per structure, each from its own cells."""
    out: dict[str, np.ndarray] = {}
    for gene in genes:
        rows = indices[frames["gene"][indices] == gene]
        stacked = []
        for row in rows:
            cell_mask = frames["cell_mask"][row]
            distance = signed_nuclear_distance(
                frames["nuc_mask"][row], frames["voxel_micron"][row]
            )
            stacked.append(
                distance_profile(
                    unit_mass(frames["target"][row].astype(np.float32), cell_mask),
                    distance,
                    cell_mask,
                )
            )
        if stacked:
            out[gene] = np.mean(stacked, axis=0)
    return out


def virtual_cell(
    predict,
    frames: dict[str, np.ndarray],
    row: int,
    genes: list[str],
) -> dict[str, np.ndarray]:
    """Every structure's predicted field on one cell's geometry."""
    reference = frames["reference"][row].astype(np.float32)
    cell_mask = frames["cell_mask"][row]
    maskf = cell_mask.astype(np.float32)
    return {
        gene: unit_mass(predict(reference, knowledge_vector(gene), maskf), cell_mask)
        for gene in genes
    }


def joint_consistency(
    predict,
    frames: dict[str, np.ndarray],
    train_indices: np.ndarray,
    test_indices: np.ndarray,
    genes: list[str],
) -> dict:
    """Compare the virtual cell's 5x5 arrangement against the measured one."""
    measured = real_profiles(frames, train_indices, genes)
    genes = [g for g in genes if g in measured]
    names, real_matrix = profile_distance_matrix(measured)

    predicted_profiles: dict[str, list[np.ndarray]] = {g: [] for g in genes}
    per_cell_matrices = []
    for row in test_indices:
        fields = virtual_cell(predict, frames, int(row), genes)
        cell_mask = frames["cell_mask"][row]
        distance = signed_nuclear_distance(
            frames["nuc_mask"][row], frames["voxel_micron"][row]
        )
        profiles = {
            g: distance_profile(f, distance, cell_mask) for g, f in fields.items()
        }
        for g, p in profiles.items():
            predicted_profiles[g].append(p)
        per_cell_matrices.append(profile_distance_matrix(profiles)[1])

    predicted_mean = {g: np.mean(v, axis=0) for g, v in predicted_profiles.items() if v}
    _, predicted_matrix = profile_distance_matrix(predicted_mean)
    upper = np.triu_indices(len(names), k=1)
    real_pairs, pred_pairs = real_matrix[upper], predicted_matrix[upper]

    # How far each predicted structure's mean profile sits from the measured one.
    profile_w1 = {}
    centres = np.linspace(*DISTANCE_RANGE, N_BINS + 1)
    centres = 0.5 * (centres[:-1] + centres[1:])
    for gene in names:
        profile_w1[gene] = weighted_w1(centres, predicted_mean[gene], measured[gene])

    correlation = (
        float(np.corrcoef(real_pairs, pred_pairs)[0, 1])
        if real_pairs.size > 1 and real_pairs.std() > 0 and pred_pairs.std() > 0
        else float("nan")
    )
    return {
        "genes": names,
        "real_pairwise_w1": real_matrix.tolist(),
        "predicted_pairwise_w1": predicted_matrix.tolist(),
        "pairwise_correlation": correlation,
        "pairwise_mean_abs_error_micron": float(np.abs(real_pairs - pred_pairs).mean()),
        "profile_w1_micron": profile_w1,
        "n_virtual_cells": int(len(per_cell_matrices)),
    }
