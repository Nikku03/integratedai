"""The four things that have to be beaten before anything has been learned.

Ordered by how badly each one can embarrass the model.

1. **Geometric rules.** A shell just inside the nuclear surface, the nuclear
   interior, the cytoplasm, a shell inside the cell surface, a perinuclear
   gradient, or the cell filled uniformly. No fitted parameters at all -- these
   are computed from the input masks by arithmetic. For the nuclear envelope in
   particular this is close to a correct answer, which is exactly why it is
   here: if the network cannot beat a shell rule on LMNB1, then LMNB1 was never
   inferred, it was handed over in the DNA channel.
2. **Atlas.** The voxelwise mean of a structure over training cells, in the
   canonical frame. One prediction for every cell. Beating it is the minimum
   evidence that anything cell-specific was learned. In a leave-one-out fold the
   only atlas available is the mean over *trained* structures, since the held-out
   structure has no training images by construction.
3. **Nearest training cell.** Copy the structure image of whichever training
   cell has the most similar reference channels. This is the memorisation
   baseline: it is what "the model just retrieves a similar picture" looks like
   when done deliberately and well.
4. **Shuffled identity.** The model itself, fed a different protein's annotation
   vector. Not a competitor -- a control. If it scores the same, the model is
   ignoring the protein.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from vcell.knowledge import COMPARTMENTS, PROTEINS

RULE_NAMES = (
    "nuclear_shell",
    "nuclear_interior",
    "cytoplasm",
    "cell_shell",
    "perinuclear",
    "uniform",
)

# Which geometric rule the annotation alone implies. Deterministic, and settled
# before any image was scored -- this is the rule a leave-one-out fold is
# allowed to use, because picking the best rule on the held-out structure's own
# images would be picking on the test set.
COMPARTMENT_RULE: dict[str, str] = {
    "nucleoplasm": "nuclear_interior",
    "chromatin": "nuclear_interior",
    "nucleolus": "nuclear_interior",
    "nuclear_envelope": "nuclear_shell",
    "nuclear_pore": "nuclear_shell",
    "nuclear_speckle": "nuclear_interior",
    "cytosol": "cytoplasm",
    "actin_cytoskeleton": "cell_shell",
    "microtubule": "cytoplasm",
    "centrosome": "perinuclear",
    "endoplasmic_reticulum": "perinuclear",
    "golgi": "perinuclear",
    "mitochondrion": "cytoplasm",
    "endolysosome": "cytoplasm",
    "peroxisome": "cytoplasm",
    "plasma_membrane": "cell_shell",
    "cell_junction": "cell_shell",
}


def geometric_rule(
    rule: str,
    nuc_mask: np.ndarray,
    cell_mask: np.ndarray,
    voxel_micron: np.ndarray,
) -> np.ndarray:
    """One parameter-free prediction built from the input masks."""
    sampling = tuple(float(v) for v in voxel_micron)
    cyto = cell_mask & ~nuc_mask
    if rule == "uniform":
        field = cell_mask.astype(np.float32)
    elif rule == "nuclear_interior":
        field = (nuc_mask & cell_mask).astype(np.float32)
    elif rule == "cytoplasm":
        field = cyto.astype(np.float32)
    elif rule == "nuclear_shell":
        # A ~0.5 micron shell straddling the nuclear surface. Note the `where`:
        # each distance transform is zero on the far side of the boundary, so
        # combining them with a minimum would select every voxel in the cell.
        if nuc_mask.any():
            d_out = ndimage.distance_transform_edt(~nuc_mask, sampling=sampling)
            d_in = ndimage.distance_transform_edt(nuc_mask, sampling=sampling)
            to_surface = np.where(nuc_mask, d_in, d_out)
            field = ((to_surface <= 0.5) & cell_mask).astype(np.float32)
        else:
            field = cyto.astype(np.float32)
    elif rule == "cell_shell":
        d_in = ndimage.distance_transform_edt(cell_mask, sampling=sampling)
        field = ((d_in <= 0.75) & cell_mask).astype(np.float32)
    elif rule == "perinuclear":
        if nuc_mask.any():
            d = ndimage.distance_transform_edt(~nuc_mask, sampling=sampling)
            field = (np.exp(-d / 2.0) * cyto).astype(np.float32)
        else:
            field = cyto.astype(np.float32)
    else:  # pragma: no cover - guarded by RULE_NAMES
        raise ValueError(f"unknown rule {rule!r}")
    if field.sum() <= 0:
        field = cell_mask.astype(np.float32)
    return field


def annotation_rule(gene: str) -> str:
    """The rule implied by the protein's dominant annotated compartment."""
    record = PROTEINS[gene]
    weights = record.compartment_vector()
    dominant = COMPARTMENTS[int(np.argmax(weights))]
    return COMPARTMENT_RULE[dominant]


class Atlas:
    """Voxelwise mean target per gene, plus the pooled mean over all genes."""

    def __init__(self, targets: np.ndarray, genes: np.ndarray, cell_masks: np.ndarray):
        self.per_gene: dict[str, np.ndarray] = {}
        # Normalise each cell to unit mass inside its own mask before averaging,
        # so a bright cell does not dominate the atlas.
        unit = np.empty_like(targets, dtype=np.float32)
        for i in range(targets.shape[0]):
            field = np.where(cell_masks[i], targets[i].astype(np.float32), 0.0)
            total = field.sum()
            unit[i] = field / total if total > 0 else field
        for gene in np.unique(genes):
            self.per_gene[str(gene)] = unit[genes == gene].mean(axis=0)
        self.pooled = np.stack(list(self.per_gene.values())).mean(axis=0)

    def predict(self, gene: str) -> np.ndarray:
        """The structure's own atlas if it was trained on, else the pooled one."""
        return self.per_gene.get(gene, self.pooled)

    def predict_pooled(self, gene: str = "") -> np.ndarray:
        return self.pooled


class NearestTrainingCell:
    """Copy the structure image of the most similar training cell."""

    def __init__(self, references: np.ndarray, targets: np.ndarray, genes: np.ndarray):
        n = references.shape[0]
        self.flat = references.reshape(n, -1).astype(np.float32)
        self.norms = (self.flat**2).sum(axis=1)
        self.targets = targets
        self.genes = np.asarray(genes)

    def predict(self, reference: np.ndarray, gene: str | None = None) -> np.ndarray:
        """Nearest by reference-channel L2. `gene` restricts to that line's cells."""
        query = reference.reshape(-1).astype(np.float32)
        pool = (
            np.flatnonzero(self.genes == gene)
            if gene is not None and (self.genes == gene).any()
            else np.arange(self.flat.shape[0])
        )
        distances = self.norms[pool] - 2.0 * (self.flat[pool] @ query)
        return self.targets[pool[int(np.argmin(distances))]].astype(np.float32)


def best_rule_on_training(
    frames: dict[str, np.ndarray], indices: np.ndarray, gene: str
) -> str:
    """Pick the rule with the highest mean volume-matched Dice on training cells.

    Used only for structures that *are* in training. The choice is made on
    training images, and among six named rules with no free parameters inside
    them, so it cannot fit noise the way a tuned threshold would.
    """
    from vcell.metrics import dice_volume_matched

    rows = indices[frames["gene"][indices] == gene]
    if rows.size == 0:
        return annotation_rule(gene)
    scores = {}
    for rule in RULE_NAMES:
        values = [
            dice_volume_matched(
                geometric_rule(
                    rule,
                    frames["nuc_mask"][i],
                    frames["cell_mask"][i],
                    frames["voxel_micron"][i],
                ),
                frames["struct_mask"][i],
                frames["cell_mask"][i],
            )
            for i in rows[: min(rows.size, 24)]
        ]
        values = [v for v in values if np.isfinite(v)]
        scores[rule] = float(np.mean(values)) if values else -1.0
    return max(scores, key=scores.get)
