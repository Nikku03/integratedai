"""A fixed image descriptor, for the gate that runs before any model.

Gate 1 of `docs/PREREG_OPENCELL.md` asks something no model can answer: **is a
protein identifiable from its own pixels at all?** If every ER protein produces
the same reticular pattern at 0.2 micron, then failing to tell two of them apart
says nothing about conditioning, and the experiment is vacuous rather than
negative. So the gate is a nearest-neighbour retrieval on a descriptor with no
fitted parameters and no annotation -- the bar the model then has to clear.

The four blocks are chosen to span the ways two proteins in one compartment can
actually differ:

* **where**, relative to the nuclei -- the only positional reference available
  without a membrane channel;
* **how coarse** -- granulometry, i.e. how much intensity a morphological
  opening removes at each radius. Fine punctae and thick tubules differ here
  even when their intensity histograms match;
* **how contrasted** -- the shape of the intensity distribution, which separates
  a few bright puncta from a uniform haze;
* **at what spatial frequency** -- the radial power spectrum, which picks up
  periodic or filamentous texture the other three miss.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

DISTANCE_BINS = 12
DISTANCE_RANGE_PX = (-12.0, 48.0)  # pixels at 0.2 micron: -2.4 to +9.6 micron
OPENING_RADII = (1, 2, 4, 8, 16)
INTENSITY_RATIO_EDGES = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.5, 5.0, np.inf)
SPECTRUM_BINS = 8

DESCRIPTOR_DIM = (
    DISTANCE_BINS + len(OPENING_RADII) + (len(INTENSITY_RATIO_EDGES) - 1) + 3 + SPECTRUM_BINS
)


def nucleus_mask(reference: np.ndarray) -> np.ndarray:
    """Threshold the nucleus channel at its own midpoint between the modes.

    No fitted parameter: the threshold is the mean of the 40th and 99th
    percentile of this tile's nucleus channel, which sits between the dark
    background and the bright nuclei for any exposure.
    """
    lo, hi = np.percentile(reference, [40.0, 99.0])
    mask = reference > 0.5 * (lo + hi)
    return ndimage.binary_opening(mask, iterations=2)


def signed_nucleus_distance(reference: np.ndarray) -> np.ndarray:
    mask = nucleus_mask(reference)
    if not mask.any() or mask.all():
        return np.zeros_like(reference, dtype=np.float32)
    outside = ndimage.distance_transform_edt(~mask)
    inside = ndimage.distance_transform_edt(mask)
    return (outside - inside).astype(np.float32)


def _distance_profile(target: np.ndarray, distance: np.ndarray) -> np.ndarray:
    edges = np.linspace(*DISTANCE_RANGE_PX, DISTANCE_BINS + 1)
    h, _ = np.histogram(distance.ravel(), bins=edges, weights=target.ravel())
    total = h.sum()
    return (h / total if total > 0 else h).astype(np.float32)


def _granulometry(target: np.ndarray) -> np.ndarray:
    """Fraction of total intensity surviving a grey opening at each radius."""
    total = float(target.sum())
    if total <= 0:
        return np.zeros(len(OPENING_RADII), dtype=np.float32)
    out = []
    for r in OPENING_RADII:
        size = 2 * r + 1
        opened = ndimage.grey_opening(target, size=(size, size))
        out.append(float(opened.sum()) / total)
    return np.array(out, dtype=np.float32)


def _intensity_shape(target: np.ndarray) -> np.ndarray:
    mean = float(target.mean())
    if mean <= 0:
        return np.zeros(len(INTENSITY_RATIO_EDGES) - 1 + 3, dtype=np.float32)
    ratio = target / mean
    hist, _ = np.histogram(ratio.ravel(), bins=np.array(INTENSITY_RATIO_EDGES))
    hist = hist.astype(np.float32) / ratio.size
    centred = (ratio - 1.0).ravel()
    sd = float(centred.std())
    skew = float((centred**3).mean() / sd**3) if sd > 1e-8 else 0.0
    kurt = float((centred**4).mean() / sd**4) if sd > 1e-8 else 0.0
    return np.concatenate([hist, np.array([sd, np.clip(skew, -20, 20) / 10.0,
                                           np.clip(kurt, 0, 200) / 100.0], np.float32)])


def _radial_spectrum(target: np.ndarray) -> np.ndarray:
    centred = target - target.mean()
    power = np.abs(np.fft.rfft2(centred)) ** 2
    ny, nx = power.shape
    fy = np.fft.fftfreq(target.shape[0])[:, None]
    fx = np.fft.rfftfreq(target.shape[1])[None, :]
    radius = np.sqrt(fy**2 + fx**2)[:ny, :nx]
    edges = np.geomspace(1.0 / target.shape[0], 0.5, SPECTRUM_BINS + 1)
    out = []
    for i in range(SPECTRUM_BINS):
        sel = (radius >= edges[i]) & (radius < edges[i + 1])
        out.append(float(power[sel].mean()) if sel.any() else 0.0)
    out = np.array(out, dtype=np.float32)
    total = out.sum()
    return out / total if total > 0 else out


def describe(reference: np.ndarray, target: np.ndarray) -> np.ndarray:
    """The fixed descriptor of one tile. `reference` is (1, H, W) or (H, W)."""
    ref = reference[0] if reference.ndim == 3 else reference
    ref = ref.astype(np.float32)
    tgt = np.clip(target.astype(np.float32), 0.0, None)
    distance = signed_nucleus_distance(ref)
    return np.concatenate([
        _distance_profile(tgt, distance),
        _granulometry(tgt),
        _intensity_shape(tgt),
        _radial_spectrum(tgt),
    ])


def describe_all(references: np.ndarray, targets: np.ndarray) -> np.ndarray:
    return np.stack([
        describe(references[i], targets[i]) for i in range(targets.shape[0])
    ])


def standardise(descriptors: np.ndarray, reference_rows: np.ndarray | None = None):
    """Z-score each column so no block dominates the distance by its scale.

    Statistics come from `reference_rows` when given -- the training tiles -- so
    the gate never standardises using the test set it is about to score.
    """
    basis = descriptors if reference_rows is None else descriptors[reference_rows]
    mean = basis.mean(axis=0)
    sd = basis.std(axis=0)
    sd[sd < 1e-8] = 1.0
    return (descriptors - mean) / sd
