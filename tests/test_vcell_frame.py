"""The canonical frame and the knowledge vector."""

import numpy as np
import pytest

from vcell.frame import CANONICAL_GRID, build_frame
from vcell.knowledge import KNOWLEDGE_DIM, POC_STRUCTURES, PROTEINS, knowledge_vector
from vcell.synthetic import synth_cell


def test_knowledge_covers_every_line_in_the_dataset():
    # The 25 lines of the hiPSC single-cell image dataset.
    assert len(PROTEINS) == 25
    for gene in PROTEINS:
        vector = knowledge_vector(gene)
        assert vector.shape == (KNOWLEDGE_DIM,)
        assert np.isfinite(vector).all()


def test_knowledge_is_available_for_an_untrained_structure():
    # The whole leave-one-out design depends on this: a held-out line's
    # conditioning vector exists without any of its images.
    for gene in POC_STRUCTURES:
        assert np.isfinite(knowledge_vector(gene)).all()


def test_knowledge_distinguishes_compartments():
    er = knowledge_vector("SEC61B")
    mito = knowledge_vector("TOMM20")
    assert not np.allclose(er, mito)


def test_unknown_gene_raises():
    with pytest.raises(KeyError):
        knowledge_vector("NOT_A_GENE")


def test_frame_shape_and_range():
    rng = np.random.default_rng(0)
    raw, seg = synth_cell("TOMM20", rng)
    frame = build_frame(raw, seg, scale_micron=0.15, gene="TOMM20")
    assert frame.reference.shape == (2, *CANONICAL_GRID)
    assert frame.target.shape == CANONICAL_GRID
    assert frame.reference.min() >= 0.0 and frame.reference.max() <= 1.0
    assert frame.cell_mask.any() and frame.nuc_mask.any() and frame.struct_mask.any()
    assert (frame.voxel_micron > 0).all()


def test_frame_puts_the_major_axis_on_x():
    rng = np.random.default_rng(3)
    # An elongated cell, so the principal axis is well determined.
    raw, seg = synth_cell("TOMM20", rng, shape=(40, 80, 200))
    frame = build_frame(raw, seg, scale_micron=0.15)
    footprint = frame.cell_mask.any(axis=0)
    rows, cols = np.nonzero(footprint)
    cov = np.cov(np.stack([cols - cols.mean(), rows - rows.mean()]).astype(float))
    _, vectors = np.linalg.eigh(cov)
    dx, dy = vectors[:, -1]
    assert abs(dx) > abs(dy), f"major axis not on X: ({dx:.2f}, {dy:.2f})"


def test_frame_fixes_the_nuclear_offset_sign():
    rng = np.random.default_rng(7)
    for _ in range(3):
        raw, seg = synth_cell("FBL", rng)
        frame = build_frame(raw, seg, scale_micron=0.15)
        nuc = np.array(np.nonzero(frame.nuc_mask), dtype=float).mean(axis=1)
        cell = np.array(np.nonzero(frame.cell_mask), dtype=float).mean(axis=1)
        # Y and X flips are chosen so the nucleus sits at non-negative offset.
        assert nuc[1] - cell[1] >= -1e-6
        assert nuc[2] - cell[2] >= -1e-6


def test_frame_rejects_a_cell_with_no_membrane_segmentation():
    rng = np.random.default_rng(0)
    raw, seg = synth_cell("TOMM20", rng)
    seg[:, 1] = 0
    with pytest.raises(ValueError, match="membrane segmentation"):
        build_frame(raw, seg, scale_micron=0.15)


def test_frame_normalisation_uses_only_this_cell():
    # Doubling one cell's intensities must not change its normalised frame --
    # this is what keeps a held-out line's intensity scale out of training.
    rng = np.random.default_rng(11)
    raw, seg = synth_cell("TOMM20", rng)
    a = build_frame(raw, seg, scale_micron=0.15)
    b = build_frame((raw.astype(np.uint32) * 2).astype(np.uint16), seg, scale_micron=0.15)
    assert np.allclose(a.target, b.target, atol=2e-2)
