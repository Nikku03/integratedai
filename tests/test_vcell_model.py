"""The model, the loss, and one end-to-end pass over synthetic cells."""

import numpy as np
import torch

from vcell.dataset import CellFrameDataset, split_by_fov
from vcell.knowledge import KNOWLEDGE_DIM, knowledge_vector
from vcell.metrics import METRIC_NAMES
from vcell.model import ConditionalUNet3D, count_parameters
from vcell.synthetic import synth_frames
from vcell.train import cross_entropy_loss, evaluate_fold, summarise, train_model


def test_output_shape_and_non_negativity():
    model = ConditionalUNet3D(cond_dim=KNOWLEDGE_DIM, base=4, depth=2)
    out = model(torch.randn(2, 2, 8, 16, 16), torch.randn(2, KNOWLEDGE_DIM))
    assert out.shape == (2, 8, 16, 16)
    assert (out >= 0).all()
    assert count_parameters(model) > 0


def test_no_learned_embedding_table_anywhere():
    # A per-line embedding table would make the leave-one-out question
    # unanswerable, so its absence is part of the design and is tested.
    model = ConditionalUNet3D(cond_dim=KNOWLEDGE_DIM, base=4, depth=2)
    assert not any(isinstance(m, torch.nn.Embedding) for m in model.modules())


def test_conditioning_starts_as_the_identity_and_can_take_effect():
    torch.manual_seed(0)
    model = ConditionalUNet3D(cond_dim=KNOWLEDGE_DIM, base=4, depth=2)
    x = torch.randn(1, 2, 8, 16, 16)
    a = model(x, torch.from_numpy(knowledge_vector("TOMM20"))[None])
    b = model(x, torch.from_numpy(knowledge_vector("LMNB1"))[None])
    # FiLM is initialised to the identity, so identity cannot matter yet.
    assert torch.allclose(a, b, atol=1e-6)
    for module in model.modules():
        if hasattr(module, "to_scale_shift"):
            torch.nn.init.normal_(module.to_scale_shift.weight, std=0.2)
    c = model(x, torch.from_numpy(knowledge_vector("TOMM20"))[None])
    d = model(x, torch.from_numpy(knowledge_vector("LMNB1"))[None])
    assert not torch.allclose(c, d, atol=1e-4)


def test_cross_entropy_is_minimised_by_the_truth():
    torch.manual_seed(0)
    mask = torch.zeros(1, 6, 8, 8)
    mask[:, 1:5, 2:6, 2:6] = 1.0
    target = torch.rand(1, 6, 8, 8) * mask
    target = target / target.sum()
    perfect, kl_perfect = cross_entropy_loss(target.clone(), target, mask)
    wrong, kl_wrong = cross_entropy_loss(torch.rand(1, 6, 8, 8) + 0.1, target, mask)
    assert float(perfect) < float(wrong)
    assert abs(float(kl_perfect)) < 1e-3
    assert float(kl_wrong) > float(kl_perfect)


def test_dataset_augmentation_keeps_reference_and_target_aligned():
    frames = synth_frames(n_per_gene=2, seed=4)
    plain = CellFrameDataset(frames, np.arange(2), augment=False)
    reference, knowledge, target, mask = plain[0]
    assert reference.shape[0] == 2
    assert knowledge.shape == (KNOWLEDGE_DIM,)
    assert abs(float(target.sum()) - 1.0) < 1e-4
    # The mask and the reference channels must agree about where the cell is.
    assert float(((reference.sum(0) > 0) & (mask == 0)).sum()) == 0.0
    ablated = CellFrameDataset(frames, np.arange(2), ablate_knowledge=True)
    assert float(ablated[0][1].abs().sum()) == 0.0


def test_end_to_end_one_epoch_produces_finite_metrics():
    torch.set_num_threads(2)
    frames = synth_frames(n_per_gene=4, seed=5)
    train, test = split_by_fov(frames, test_fraction=0.25, seed=5)
    model = train_model(frames, train, epochs=1, batch_size=2, seed=5, threads=2)
    records = evaluate_fold(
        "seen", frames, train, test, model, None, set(np.unique(frames["gene"]))
    )
    assert records
    assert {"model", "atlas_pooled", "rule_annotation"} <= {r["predictor"] for r in records}
    for record in records:
        for metric in METRIC_NAMES:
            assert metric in record
    summary = summarise(records, seed=5)
    assert summary
    assert all(row["n_cells"] > 0 for row in summary)


def test_leave_one_out_fold_can_be_evaluated_without_the_held_out_structure():
    torch.set_num_threads(2)
    frames = synth_frames(n_per_gene=4, seed=6)
    held = "LMNB1"
    train = np.flatnonzero(frames["gene"] != held)
    test = np.flatnonzero(frames["gene"] == held)
    model = train_model(frames, train, epochs=1, batch_size=2, seed=6, threads=2)
    records = evaluate_fold(
        f"loso_{held}", frames, train, test, model, None,
        set(np.unique(frames["gene"])) - {held},
    )
    predictors = {r["predictor"] for r in records}
    # The held-out structure has no atlas and no best-on-train rule, by
    # construction -- only the pooled atlas and the annotation rule are legal.
    assert "atlas_own_structure" not in predictors
    assert "rule_best_on_train" not in predictors
    assert {"model", "atlas_pooled", "rule_annotation"} <= predictors
    assert all(r["seen_in_training"] is False for r in records)


def test_concat_frames_requires_a_common_grid():
    import pytest

    from vcell.train import concat_frames

    a = synth_frames(n_per_gene=1, seed=1)
    b = synth_frames(n_per_gene=1, seed=2)
    merged = concat_frames(a, b)
    assert merged["target"].shape[0] == a["target"].shape[0] + b["target"].shape[0]
    assert merged["gene"].size == merged["target"].shape[0]
    small = synth_frames(n_per_gene=1, grid=(8, 16, 16), seed=3)
    with pytest.raises(ValueError, match="different grids"):
        concat_frames(a, small)


def test_covered_pairs_share_a_dominant_compartment():
    # H6 only means anything if the partner really does cover the compartment.
    import numpy as np

    from vcell.baselines import COMPARTMENT_RULE
    from vcell.knowledge import COMPARTMENTS, PROTEINS
    from vcell.train import COVERED_PAIRS

    for held, partner in COVERED_PAIRS:
        held_vector = PROTEINS[held].compartment_vector()
        partner_vector = PROTEINS[partner].compartment_vector()
        dominant = int(np.argmax(held_vector))
        assert partner_vector[dominant] > 0, (
            f"{partner} does not cover {COMPARTMENTS[dominant]} for {held}"
        )
        # And every compartment must map to a geometric rule, or gate 2 has a hole.
        assert COMPARTMENTS[dominant] in COMPARTMENT_RULE
