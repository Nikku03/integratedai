"""Loading framed cells, splitting them by field of view, and augmenting.

The split is the part worth reading. Cells from one field of view share
illumination, colony and neighbours, so a random cell split puts near-copies on
both sides and manufactures a result. Every split here is over `fov_id`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from vcell.knowledge import knowledge_vector

ARRAY_KEYS = (
    "reference",
    "target",
    "struct_mask",
    "nuc_mask",
    "cell_mask",
    "voxel_micron",
    "cell_id",
    "fov_id",
    "gene",
    "cell_stage",
)


def load_frames(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        frames = {key: data[key] for key in ARRAY_KEYS}
    frames["gene"] = frames["gene"].astype(str)
    frames["fov_id"] = frames["fov_id"].astype(str)
    frames["cell_id"] = frames["cell_id"].astype(str)
    frames["cell_stage"] = frames["cell_stage"].astype(str)
    return frames


def split_by_fov(
    frames: dict[str, np.ndarray], test_fraction: float, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Hold out whole fields of view, stratified within each gene."""
    rng = np.random.default_rng(seed)
    train, test = [], []
    for gene in np.unique(frames["gene"]):
        rows = np.flatnonzero(frames["gene"] == gene)
        fovs = np.unique(frames["fov_id"][rows])
        rng.shuffle(fovs)
        n_test = max(1, int(round(len(fovs) * test_fraction)))
        held = set(fovs[:n_test].tolist())
        for row in rows:
            (test if frames["fov_id"][row] in held else train).append(row)
    return np.array(sorted(train)), np.array(sorted(test))


def unit_mass(field: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Scale a field to unit total mass inside the mask. Where, not how much."""
    out = np.where(mask, field.astype(np.float32), 0.0)
    total = out.sum()
    return out / total if total > 0 else out


class CellFrameDataset(Dataset):
    """Reference channels + knowledge vector -> unit-mass target density."""

    def __init__(
        self,
        frames: dict[str, np.ndarray],
        indices: np.ndarray,
        augment: bool = False,
        ablate_knowledge: bool = False,
        seed: int = 0,
    ):
        self.frames = frames
        self.indices = np.asarray(indices)
        self.augment = augment
        self.ablate_knowledge = ablate_knowledge
        self.rng = np.random.default_rng(seed)
        self._knowledge = {
            gene: knowledge_vector(gene) for gene in np.unique(frames["gene"][self.indices])
        }

    def __len__(self) -> int:
        return int(self.indices.size)

    def __getitem__(self, item: int):
        row = int(self.indices[item])
        reference = self.frames["reference"][row].astype(np.float32)
        cell_mask = self.frames["cell_mask"][row]
        target = unit_mass(self.frames["target"][row].astype(np.float32), cell_mask)
        mask = cell_mask.astype(np.float32)

        if self.augment:
            # X and Y only. Z is the optical axis: point-spread function, depth
            # attenuation and the coverslip all break the symmetry, so a Z flip
            # would be an untrue statement about the microscope.
            flips = [axis for axis in (1, 2) if self.rng.random() < 0.5]
            if flips:
                reference = np.flip(reference, [a + 1 for a in flips]).copy()
                target = np.flip(target, flips).copy()
                mask = np.flip(mask, flips).copy()

        gene = str(self.frames["gene"][row])
        knowledge = (
            np.zeros_like(self._knowledge[gene])
            if self.ablate_knowledge
            else self._knowledge[gene]
        )
        return (
            torch.from_numpy(reference),
            torch.from_numpy(knowledge.astype(np.float32)),
            torch.from_numpy(target),
            torch.from_numpy(mask),
        )
