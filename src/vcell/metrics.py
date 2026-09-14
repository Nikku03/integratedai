"""The five registered metrics, plus the FOV-clustered bootstrap.

The metric that matters most here is the least obvious one. Correlation between
two 3D fields is easy to inflate: both are zero outside the cell and both are
dense in the cytoplasm, so a prediction that merely respects the cell outline
already correlates. **Volume-matched Dice** removes that escape route -- the
prediction is thresholded at exactly the true structure's voxel count, so the
score is placement and nothing else, and there is no threshold left to tune.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage


def pearson_r(pred: np.ndarray, true: np.ndarray, cell_mask: np.ndarray) -> float:
    """Correlation of the two density fields over voxels inside the cell."""
    p = pred[cell_mask].astype(np.float64)
    t = true[cell_mask].astype(np.float64)
    if p.size < 2 or p.std() < 1e-12 or t.std() < 1e-12:
        return float("nan")
    return float(np.corrcoef(p, t)[0, 1])


def dice_volume_matched(
    pred: np.ndarray, true_mask: np.ndarray, cell_mask: np.ndarray
) -> float:
    """Dice with the prediction thresholded at the true structure's volume.

    With |A| = |B| = k the Dice coefficient collapses to |A n B| / k, so this is
    literally the fraction of the true structure's voxels the model put in the
    right place.
    """
    inside = np.flatnonzero(cell_mask.ravel())
    truth = true_mask.ravel()[inside]
    k = int(truth.sum())
    if k == 0 or k == inside.size:
        return float("nan")
    scores = pred.ravel()[inside]
    top = np.argpartition(-scores, k - 1)[:k]
    return float(truth[top].sum()) / float(k)


def _cell_radius_micron(cell_mask: np.ndarray, voxel_micron: np.ndarray) -> float:
    volume = float(cell_mask.sum()) * float(np.prod(voxel_micron))
    return float((3.0 * volume / (4.0 * np.pi)) ** (1.0 / 3.0))


def _center_of_mass(field: np.ndarray, cell_mask: np.ndarray) -> np.ndarray | None:
    w = np.where(cell_mask, field, 0.0).astype(np.float64)
    total = w.sum()
    if total <= 0:
        return None
    grids = np.indices(w.shape, dtype=np.float64)
    return np.array([float((g * w).sum() / total) for g in grids])


def com_displacement(
    pred: np.ndarray,
    true: np.ndarray,
    cell_mask: np.ndarray,
    voxel_micron: np.ndarray,
) -> tuple[float, float]:
    """(displacement in microns, displacement in units of the cell radius)."""
    cp = _center_of_mass(pred, cell_mask)
    ct = _center_of_mass(true, cell_mask)
    if cp is None or ct is None:
        return float("nan"), float("nan")
    micron = float(np.linalg.norm((cp - ct) * np.asarray(voxel_micron, dtype=np.float64)))
    radius = _cell_radius_micron(cell_mask, voxel_micron)
    return micron, micron / radius if radius > 0 else float("nan")


def signed_nuclear_distance(
    nuc_mask: np.ndarray, voxel_micron: np.ndarray
) -> np.ndarray:
    """Distance to the nuclear surface in microns: negative inside, positive outside."""
    sampling = tuple(float(v) for v in voxel_micron)
    if not nuc_mask.any():
        return ndimage.distance_transform_edt(np.ones_like(nuc_mask), sampling=sampling)
    outside = ndimage.distance_transform_edt(~nuc_mask, sampling=sampling)
    inside = ndimage.distance_transform_edt(nuc_mask, sampling=sampling)
    return (outside - inside).astype(np.float32)


def weighted_w1(values: np.ndarray, w_a: np.ndarray, w_b: np.ndarray) -> float:
    """Wasserstein-1 between two weighted distributions on a shared support."""
    a, b = w_a.astype(np.float64), w_b.astype(np.float64)
    if a.sum() <= 0 or b.sum() <= 0:
        return float("nan")
    order = np.argsort(values, kind="stable")
    v = values[order].astype(np.float64)
    ca = np.cumsum(a[order] / a.sum())
    cb = np.cumsum(b[order] / b.sum())
    return float(np.sum(np.abs(ca[:-1] - cb[:-1]) * np.diff(v)))


def nuclear_distance_w1(
    pred: np.ndarray,
    true: np.ndarray,
    nuc_mask: np.ndarray,
    cell_mask: np.ndarray,
    voxel_micron: np.ndarray,
    distance: np.ndarray | None = None,
) -> float:
    """Earth-mover distance, in microns, along distance-to-nuclear-surface."""
    d = signed_nuclear_distance(nuc_mask, voxel_micron) if distance is None else distance
    sel = cell_mask.ravel()
    return weighted_w1(d.ravel()[sel], pred.ravel()[sel], true.ravel()[sel])


def nuclear_fraction(field: np.ndarray, nuc_mask: np.ndarray, cell_mask: np.ndarray) -> float:
    """Share of the density that sits inside the nucleus."""
    total = float(np.where(cell_mask, field, 0.0).sum())
    if total <= 0:
        return float("nan")
    return float(np.where(nuc_mask & cell_mask, field, 0.0).sum()) / total


METRIC_NAMES = ("pearson_r", "dice", "com_radius", "w1_micron", "nuc_fraction_err")
HIGHER_IS_BETTER = {"pearson_r": True, "dice": True, "com_radius": False,
                    "w1_micron": False, "nuc_fraction_err": False}


def score_cell(
    pred: np.ndarray,
    true: np.ndarray,
    true_mask: np.ndarray,
    nuc_mask: np.ndarray,
    cell_mask: np.ndarray,
    voxel_micron: np.ndarray,
    distance: np.ndarray | None = None,
) -> dict[str, float]:
    """All five registered metrics for one cell."""
    _, com_radius = com_displacement(pred, true, cell_mask, voxel_micron)
    nf_pred = nuclear_fraction(pred, nuc_mask, cell_mask)
    nf_true = nuclear_fraction(true, nuc_mask, cell_mask)
    return {
        "pearson_r": pearson_r(pred, true, cell_mask),
        "dice": dice_volume_matched(pred, true_mask, cell_mask),
        "com_radius": com_radius,
        "w1_micron": nuclear_distance_w1(
            pred, true, nuc_mask, cell_mask, voxel_micron, distance=distance
        ),
        "nuc_fraction_err": abs(nf_pred - nf_true),
    }


def fov_clustered_bootstrap(
    values: np.ndarray,
    fov_ids: np.ndarray,
    n_resamples: int = 1000,
    seed: int = 0,
) -> tuple[float, float, float]:
    """(mean, lo, hi) with fields of view, not cells, as the resampling unit.

    Cells from one field share illumination, colony and neighbours. Treating
    them as independent understates the interval -- the same reason the equity
    work in this repository bootstraps by session rather than by name-day.
    """
    ok = np.isfinite(values)
    values, fov_ids = values[ok], fov_ids[ok]
    if values.size == 0:
        return float("nan"), float("nan"), float("nan")
    groups = [values[fov_ids == f] for f in np.unique(fov_ids)]
    rng = np.random.default_rng(seed)
    n = len(groups)
    draws = np.empty(n_resamples, dtype=np.float64)
    for i in range(n_resamples):
        pick = rng.integers(0, n, size=n)
        draws[i] = np.concatenate([groups[j] for j in pick]).mean()
    return float(values.mean()), float(np.percentile(draws, 2.5)), float(
        np.percentile(draws, 97.5)
    )
