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


# --- vcell.flux: the transport reconstruction ------------------------------
#
# Each of these is a case where the answer is known in advance, and each of the
# last three is a defect the solver actually had: a sign error that pointed
# every velocity backwards, conjugate gradients run on a negative-definite
# operator, and a Neumann problem solved over a mask with more than one
# connected component. All three returned numbers rather than failing.

def _grid():
    import numpy as np
    z, y, x = np.mgrid[0:16, 0:32, 0:32]
    return z, y, x, (0.4, 0.2, 0.2)


def _blob(centre_y, scale=3.0):
    import numpy as np
    z, y, x, _ = _grid()
    f = np.exp(-(((z - 8) / scale) ** 2 + ((y - centre_y) / scale) ** 2
                 + ((x - 16) / scale) ** 2))
    return f / f.sum()


def _spread(scale):
    import numpy as np
    z, y, x, _ = _grid()
    f = np.exp(-(((z - 8) / (3 * scale)) ** 2 + ((y - 16) / (3 * scale)) ** 2
                 + ((x - 16) / (3 * scale)) ** 2))
    return f / f.sum()


def test_flux_recovers_a_translation_with_the_right_sign():
    """A blob shifted +4 voxels at 0.2 um must give +0.8 um of velocity in +y."""
    import numpy as np

    from vcell.flux import solve_flux
    _, _, _, spacing = _grid()
    mask = np.ones((16, 32, 32), bool)
    r0, r1 = _blob(12.0), _blob(16.0)
    f = solve_flux(r0, r1, mask, spacing)
    assert f.converged and f.residual < 1e-6
    w = 0.5 * (r0 + r1)
    mean = [float((w * v).sum() / w.sum()) for v in f.velocity]
    assert mean[1] > 0.7, f"velocity must point +y, got {mean}"
    assert abs(mean[1] - 0.8) < 0.1, f"magnitude should be ~0.8 um, got {mean[1]}"
    assert abs(mean[0]) < 1e-3 and abs(mean[2]) < 1e-3


def test_flux_alignment_separates_diffusion_from_its_reverse():
    """Spreading is what diffusion does; concentrating is what it cannot do."""
    import numpy as np

    from vcell.flux import diffusive_alignment, solve_flux
    _, _, _, spacing = _grid()
    mask = np.ones((16, 32, 32), bool)
    a, b = _spread(1.0), _spread(1.4)
    out = diffusive_alignment(solve_flux(a, b, mask, spacing), a, b, mask, spacing)
    assert out["cosine"] > 0.8 and out["uphill_mass_fraction"] < 0.05
    back = diffusive_alignment(solve_flux(b, a, mask, spacing), b, a, mask, spacing)
    assert back["cosine"] < -0.8 and back["uphill_mass_fraction"] > 0.95


def test_flux_of_no_change_is_exactly_zero():
    import numpy as np

    from vcell.flux import solve_flux
    _, _, _, spacing = _grid()
    mask = np.ones((16, 32, 32), bool)
    r = _blob(14.0)
    f = solve_flux(r, r.copy(), mask, spacing)
    assert f.converged
    assert f.mass_weighted_speed == 0.0


def test_flux_solves_a_disconnected_mask():
    """A mitotic cell mask comes apart, and one Neumann null space per piece
    diverges if the whole mask is solved at once."""
    import numpy as np

    from vcell.flux import solve_flux
    z, y, x, spacing = _grid()
    mask = np.zeros((16, 32, 32), bool)
    mask[:, 2:12, 2:30] = True
    mask[:, 20:30, 2:30] = True

    def pair(c1, c2):
        f = np.exp(-(((y - c1) / 2.0) ** 2 + ((x - 10) / 3.0) ** 2
                     + ((z - 8) / 3.0) ** 2)) * (y < 16)
        f = f + np.exp(-(((y - c2) / 2.0) ** 2 + ((x - 20) / 3.0) ** 2
                         + ((z - 8) / 3.0) ** 2)) * (y >= 16)
        f = np.where(mask, f, 0.0)
        return f / f.sum()

    f = solve_flux(pair(5, 23), pair(9, 27), mask, spacing)
    assert f.n_components == 2
    assert f.converged and f.residual < 1e-6
    assert f.unmoveable_mass_fraction < 1e-6
    assert f.mass_weighted_speed > 0.5


def test_flux_reports_mass_it_cannot_move():
    """Mass appearing inside a disconnected piece is not transport, and has to
    be reported rather than absorbed into the solution."""
    import numpy as np

    from vcell.flux import solve_flux
    mask = np.zeros((16, 32, 32), bool)
    mask[:, 2:12, 2:30] = True
    mask[:, 20:30, 2:30] = True
    r0 = np.where(mask, 0.0, 0.0)
    r0[:, 2:12, 2:30] = 1.0
    r1 = np.zeros_like(r0)
    r1[:, 2:12, 2:30] = 1.0
    r1[:, 20:30, 2:30] = 1.0     # half the mass has teleported across the gap
    r0 /= r0.sum()
    r1 /= r1.sum()
    f = solve_flux(r0, r1, mask, (0.4, 0.2, 0.2))
    assert f.n_components == 2
    assert f.unmoveable_mass_fraction > 0.1, (
        "a density change that no flux can produce must be reported")
