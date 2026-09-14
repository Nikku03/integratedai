"""The five registered metrics, the baselines, and the split."""

import numpy as np

from vcell.baselines import RULE_NAMES, Atlas, NearestTrainingCell, geometric_rule
from vcell.dataset import split_by_fov, unit_mass
from vcell.metrics import (
    com_displacement,
    dice_volume_matched,
    fov_clustered_bootstrap,
    nuclear_distance_w1,
    nuclear_fraction,
    pearson_r,
    signed_nuclear_distance,
    weighted_w1,
)
from vcell.synthetic import synth_frames


def _toy():
    cell = np.zeros((8, 12, 12), dtype=bool)
    cell[1:7, 2:10, 2:10] = True
    nuc = np.zeros_like(cell)
    nuc[3:5, 5:8, 5:8] = True
    truth = np.zeros_like(cell)
    truth[2:4, 3:6, 3:6] = True
    voxel = np.array([0.4, 0.3, 0.3], dtype=np.float32)
    return cell, nuc, truth, voxel


def test_dice_is_one_for_a_perfect_prediction():
    cell, _, truth, _ = _toy()
    assert dice_volume_matched(truth.astype(np.float32), truth, cell) == 1.0


def test_dice_is_near_chance_for_a_flat_prediction():
    cell, _, truth, _ = _toy()
    flat = np.full(cell.shape, 0.5, dtype=np.float32)
    chance = truth[cell].mean()
    score = dice_volume_matched(flat, truth, cell)
    # A flat field breaks ties arbitrarily, so the score has to sit near the
    # base rate. If volume matching were wrong this would drift far from it.
    assert abs(score - chance) < 0.25


def test_dice_undefined_when_the_structure_fills_or_misses_the_cell():
    cell, _, _, _ = _toy()
    assert np.isnan(dice_volume_matched(np.zeros_like(cell, float), np.zeros_like(cell), cell))
    assert np.isnan(dice_volume_matched(np.zeros_like(cell, float), cell.copy(), cell))


def test_pearson_and_com_on_identical_fields():
    cell, _, truth, voxel = _toy()
    field = truth.astype(np.float32)
    assert pearson_r(field, field, cell) > 0.999
    micron, radius = com_displacement(field, field, cell, voxel)
    assert micron < 1e-6 and radius < 1e-6


def test_w1_is_zero_for_identical_and_grows_with_a_shift():
    values = np.linspace(0.0, 10.0, 101)
    a = np.exp(-((values - 3.0) ** 2))
    b = np.exp(-((values - 3.0) ** 2))
    c = np.exp(-((values - 6.0) ** 2))
    assert weighted_w1(values, a, b) < 1e-9
    assert 2.5 < weighted_w1(values, a, c) < 3.5


def test_signed_nuclear_distance_changes_sign_at_the_surface():
    _, nuc, _, voxel = _toy()
    d = signed_nuclear_distance(nuc, voxel)
    assert (d[nuc] < 0).all()
    assert (d[~nuc] > 0).all()


def test_nuclear_distance_w1_zero_for_identical_fields():
    cell, nuc, truth, voxel = _toy()
    field = truth.astype(np.float32)
    assert nuclear_distance_w1(field, field, nuc, cell, voxel) < 1e-9


def test_nuclear_fraction_endpoints():
    cell, nuc, _, _ = _toy()
    assert nuclear_fraction(nuc.astype(np.float32), nuc, cell) == 1.0
    outside = (cell & ~nuc).astype(np.float32)
    assert nuclear_fraction(outside, nuc, cell) == 0.0


def test_nuclear_shell_rule_is_a_shell_not_the_whole_cell():
    # Regression test. Combining the two distance transforms with a minimum
    # selects every voxel in the cell, because each transform is zero on the
    # far side of the boundary. That bug made the strongest baseline vacuous.
    cell, nuc, _, voxel = _toy()
    shell = geometric_rule("nuclear_shell", nuc, cell, voxel) > 0
    assert shell.sum() < 0.5 * cell.sum()
    assert shell.sum() > 0
    # The shell must straddle the nuclear surface.
    d = np.abs(signed_nuclear_distance(nuc, voxel))
    assert d[shell].max() <= 0.5 + 1e-6


def test_every_rule_produces_something_inside_the_cell():
    cell, nuc, _, voxel = _toy()
    for rule in RULE_NAMES:
        field = geometric_rule(rule, nuc, cell, voxel)
        assert field.sum() > 0
        assert field[~cell].sum() == 0


def test_fov_clustered_bootstrap_is_wider_than_ignoring_clusters():
    rng = np.random.default_rng(0)
    # Ten fields, five cells each, with the field explaining most of the spread.
    fov_effect = rng.normal(0, 1.0, 10)
    values = np.concatenate([f + rng.normal(0, 0.05, 5) for f in fov_effect])
    fovs = np.repeat([f"fov{i}" for i in range(10)], 5)
    _, lo_c, hi_c = fov_clustered_bootstrap(values, fovs, n_resamples=400, seed=1)
    _, lo_i, hi_i = fov_clustered_bootstrap(
        values, np.array([f"cell{i}" for i in range(values.size)]), n_resamples=400, seed=1
    )
    assert (hi_c - lo_c) > 1.5 * (hi_i - lo_i)


def test_split_by_fov_shares_no_field():
    frames = synth_frames(n_per_gene=4, seed=1)
    # Two cells per field, so the split has something to keep together.
    frames["fov_id"] = np.array([f"fov{i // 2}" for i in range(frames["gene"].size)])
    train, test = split_by_fov(frames, test_fraction=0.5, seed=1)
    assert train.size and test.size
    assert not (set(frames["fov_id"][train]) & set(frames["fov_id"][test]))


def test_unit_mass_normalises_inside_the_mask_only():
    cell, _, truth, _ = _toy()
    field = np.random.default_rng(0).random(cell.shape).astype(np.float32)
    out = unit_mass(field, cell)
    assert abs(out.sum() - 1.0) < 1e-5
    assert out[~cell].sum() == 0.0


def test_atlas_and_nearest_cell_shapes():
    frames = synth_frames(n_per_gene=3, seed=2)
    idx = np.arange(frames["gene"].size)
    atlas = Atlas(frames["target"][idx], frames["gene"][idx], frames["cell_mask"][idx])
    assert atlas.predict("LMNB1").shape == frames["target"].shape[1:]
    # An unknown structure falls back to the pooled atlas, which is the only
    # atlas a leave-one-out fold is allowed to use.
    assert np.allclose(atlas.predict("NOT_A_GENE"), atlas.pooled)
    nearest = NearestTrainingCell(
        frames["reference"][idx].astype(np.float32), frames["target"][idx], frames["gene"][idx]
    )
    out = nearest.predict(frames["reference"][0].astype(np.float32), "LMNB1")
    assert out.shape == frames["target"].shape[1:]


def test_joint_profile_and_matrix():
    from vcell.joint import (
        DISTANCE_RANGE,
        N_BINS,
        distance_profile,
        profile_distance_matrix,
    )

    cell, nuc, truth, voxel = _toy()
    d = signed_nuclear_distance(nuc, voxel)
    profile = distance_profile(truth.astype(np.float32), d, cell)
    assert profile.shape == (N_BINS,)
    assert abs(profile.sum() - 1.0) < 1e-6

    # A structure at the nuclear surface and one at the cortex must be far
    # apart on the radial axis, and each zero distance from itself.
    from vcell.baselines import geometric_rule

    shell = distance_profile(geometric_rule("nuclear_shell", nuc, cell, voxel), d, cell)
    cortex = distance_profile(geometric_rule("cell_shell", nuc, cell, voxel), d, cell)
    names, matrix = profile_distance_matrix({"shell": shell, "cortex": cortex})
    assert names == ["cortex", "shell"]
    assert np.allclose(np.diag(matrix), 0.0)
    assert matrix[0, 1] == matrix[1, 0] > 0.0
    assert matrix[0, 1] < (DISTANCE_RANGE[1] - DISTANCE_RANGE[0])
