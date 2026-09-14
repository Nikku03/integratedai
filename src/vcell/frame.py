"""The canonical cell frame: one coordinate system every cell is mapped into.

Two independent reasons this has to exist. The first is that the model needs a
fixed-size input. The second matters more: the primary baseline of this study is
the *atlas* -- the voxelwise mean of a structure across many cells -- and an
atlas is only as strong as the frame it is averaged in. Average mitochondria
over cells in arbitrary orientations and you get a blur that anything would
beat. So the frame rotates each cell onto its own principal axis before
averaging, which makes the baseline as strong as it reasonably can be, which is
the only way beating it means anything.

The frame is defined in `docs/PREREG_VIRTUAL_CELL.md` and fixed there. This
module implements it and nothing else.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import ndimage

# Channel layout of the Allen per-cell crops, from the dataset's `name_dict`.
RAW_CHANNELS = ("dna", "membrane", "structure")
SEG_CHANNELS = (
    "dna_segmentation",
    "membrane_segmentation",
    "membrane_segmentation_roof",
    "struct_segmentation",
    "struct_segmentation_roof",
)

CANONICAL_GRID = (24, 48, 48)  # (Z, Y, X) -- registered


@dataclass
class CellFrame:
    """One cell resampled into the canonical frame."""

    reference: np.ndarray  # (2, Z, Y, X) float32 in [0, 1]: dna, membrane
    target: np.ndarray  # (Z, Y, X) float32 in [0, 1]: the tagged structure
    struct_mask: np.ndarray  # (Z, Y, X) bool -- Allen's own structure segmentation
    nuc_mask: np.ndarray  # (Z, Y, X) bool
    cell_mask: np.ndarray  # (Z, Y, X) bool
    voxel_micron: np.ndarray  # (3,) float32 -- canonical voxel size, per axis
    cell_id: str = ""
    fov_id: str = ""
    gene: str = ""
    cell_stage: str = ""


def _principal_angle_deg(mask_2d: np.ndarray) -> float:
    """Angle of the mask's major axis, in degrees, in (row, col) coordinates."""
    rows, cols = np.nonzero(mask_2d)
    if rows.size < 8:
        return 0.0
    coords = np.stack([cols - cols.mean(), rows - rows.mean()]).astype(np.float64)
    cov = np.cov(coords)
    if not np.all(np.isfinite(cov)):
        return 0.0
    _, vecs = np.linalg.eigh(cov)
    dx, dy = vecs[:, -1]
    return math.degrees(math.atan2(dy, dx))


def _bbox_slices(mask: np.ndarray, pad: int = 0) -> tuple[slice, ...]:
    out = []
    for axis in range(mask.ndim):
        proj = mask.any(axis=tuple(a for a in range(mask.ndim) if a != axis))
        idx = np.nonzero(proj)[0]
        lo, hi = (0, mask.shape[axis]) if idx.size == 0 else (idx[0], idx[-1] + 1)
        out.append(slice(max(0, lo - pad), min(mask.shape[axis], hi + pad)))
    return tuple(out)


def _resample(volume: np.ndarray, grid: tuple[int, int, int], order: int) -> np.ndarray:
    factors = [g / s for g, s in zip(grid, volume.shape, strict=True)]
    out = ndimage.zoom(volume.astype(np.float32), factors, order=order, mode="nearest")
    # zoom's output size can be off by one from rounding; trim or pad to exact.
    slices = tuple(slice(0, g) for g in grid)
    out = out[slices]
    if out.shape != tuple(grid):
        pad = [(0, g - s) for g, s in zip(grid, out.shape, strict=True)]
        out = np.pad(out, pad, mode="edge")
    return out


def _normalise(volume: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Per-cell percentile normalisation to [0, 1], computed inside the mask only.

    Nothing here looks at any other cell, which is what keeps the leave-one-out
    folds clean: a held-out line's intensity scale never reaches training.
    """
    inside = volume[mask]
    if inside.size == 0:
        return np.zeros_like(volume, dtype=np.float32)
    lo, hi = np.percentile(inside, [1.0, 99.9])
    if hi <= lo:
        hi = lo + 1.0
    out = np.clip((volume - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)
    return out * mask


def build_frame(
    raw: np.ndarray,
    seg: np.ndarray,
    scale_micron: float,
    grid: tuple[int, int, int] = CANONICAL_GRID,
    cell_id: str = "",
    fov_id: str = "",
    gene: str = "",
    cell_stage: str = "",
) -> CellFrame:
    """Map one Allen crop pair into the canonical frame.

    `raw` is (Z, C, Y, X) uint16 with channels RAW_CHANNELS; `seg` is
    (Z, C, Y, X) uint8 with channels SEG_CHANNELS. Both come straight out of
    `tifffile.imread` on the dataset's `crop_raw` / `crop_seg` files.
    """
    if raw.ndim != 4 or seg.ndim != 4:
        raise ValueError(f"expected (Z, C, Y, X); got raw {raw.shape}, seg {seg.shape}")

    dna = raw[:, RAW_CHANNELS.index("dna")].astype(np.float32)
    mem = raw[:, RAW_CHANNELS.index("membrane")].astype(np.float32)
    structure = raw[:, RAW_CHANNELS.index("structure")].astype(np.float32)
    nuc_mask = seg[:, SEG_CHANNELS.index("dna_segmentation")] > 0
    cell_mask = seg[:, SEG_CHANNELS.index("membrane_segmentation")] > 0
    struct_mask = seg[:, SEG_CHANNELS.index("struct_segmentation")] > 0

    if not cell_mask.any():
        raise ValueError(f"cell {cell_id}: empty membrane segmentation")

    # Structure segmentation in this dataset is computed per FOV, so it can carry
    # a neighbour's organelles inside this crop. Restrict everything to this cell.
    struct_mask = struct_mask & cell_mask
    nuc_mask = nuc_mask & cell_mask

    # 1. crop to the cell's bounding box, with room for the rotation
    box = _bbox_slices(cell_mask, pad=2)
    dna, mem, structure = dna[box], mem[box], structure[box]
    nuc_mask, cell_mask, struct_mask = nuc_mask[box], cell_mask[box], struct_mask[box]

    # 2. rotate in-plane onto the cell's principal axis
    angle = _principal_angle_deg(cell_mask.any(axis=0))
    if abs(angle) > 0.5:
        kw = dict(axes=(1, 2), reshape=True, mode="constant", cval=0.0)
        dna = ndimage.rotate(dna, angle, order=1, **kw)
        mem = ndimage.rotate(mem, angle, order=1, **kw)
        structure = ndimage.rotate(structure, angle, order=1, **kw)
        nuc_mask = ndimage.rotate(nuc_mask.astype(np.uint8), angle, order=0, **kw) > 0
        cell_mask = ndimage.rotate(cell_mask.astype(np.uint8), angle, order=0, **kw) > 0
        struct_mask = ndimage.rotate(struct_mask.astype(np.uint8), angle, order=0, **kw) > 0
        if not cell_mask.any():  # pragma: no cover - rotation cannot empty a mask
            raise ValueError(f"cell {cell_id}: mask lost in rotation")
        box = _bbox_slices(cell_mask)
        dna, mem, structure = dna[box], mem[box], structure[box]
        nuc_mask, cell_mask, struct_mask = nuc_mask[box], cell_mask[box], struct_mask[box]

    extent_micron = np.array(cell_mask.shape, dtype=np.float32) * float(scale_micron)

    # 3. resample onto the canonical grid
    cell_r = _resample(cell_mask.astype(np.float32), grid, order=0) > 0.5
    if not cell_r.any():  # a cell thinner than one canonical voxel; drop it upstream
        raise ValueError(f"cell {cell_id}: vanished on resampling to {grid}")
    nuc_r = (_resample(nuc_mask.astype(np.float32), grid, order=0) > 0.5) & cell_r
    struct_r = (_resample(struct_mask.astype(np.float32), grid, order=0) > 0.5) & cell_r
    dna_r = _normalise(_resample(dna, grid, order=1), cell_r)
    mem_r = _normalise(_resample(mem, grid, order=1), cell_r)
    str_r = _normalise(_resample(structure, grid, order=1), cell_r)

    # 4. resolve the two 180-degree ambiguities with the nuclear offset
    if nuc_r.any():
        nuc_c = np.array(ndimage.center_of_mass(nuc_r))
        cell_c = np.array(ndimage.center_of_mass(cell_r))
        offset = nuc_c - cell_c
        flips = []
        if offset[2] < 0:
            flips.append(2)
        if offset[1] < 0:
            flips.append(1)
        if flips:
            dna_r, mem_r, str_r = (np.flip(a, flips).copy() for a in (dna_r, mem_r, str_r))
            cell_r, nuc_r, struct_r = (np.flip(a, flips).copy() for a in (cell_r, nuc_r, struct_r))

    return CellFrame(
        reference=np.stack([dna_r, mem_r]).astype(np.float32),
        target=str_r.astype(np.float32),
        struct_mask=struct_r,
        nuc_mask=nuc_r,
        cell_mask=cell_r,
        voxel_micron=(extent_micron / np.array(grid, dtype=np.float32)).astype(np.float32),
        cell_id=cell_id,
        fov_id=fov_id,
        gene=gene,
        cell_stage=cell_stage,
    )
