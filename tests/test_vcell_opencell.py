"""The OpenCell modules: annotation parsing, descriptor, retrieval, and the null."""

import numpy as np
import pytest

from vcell.descriptor import (
    DESCRIPTOR_DIM,
    describe,
    nucleus_mask,
    signed_nucleus_distance,
    standardise,
)
from vcell.opencell import (
    ALL_COMPARTMENTS,
    COMPARTMENTS,
    KNOWLEDGE_BLOCKS,
    QC_FLAGS,
    Target,
    build_targets,
    knowledge_blocks,
    knowledge_dim,
    knowledge_vector,
    parse_grades,
    sole_dominant,
)
from vcell.retrieval import (
    descriptor_retrieval,
    protein_clustered_bootstrap,
    rank_of_truth,
    retrieval_summary,
    score_match,
    unit_mass,
)


def _target(gene="AAA", compartment="er", grades=None, **kw):
    return Target(gene=gene, ensg=f"ENSG{gene}", cell_line_id=1,
                  compartment=compartment, grades=grades or {"er": 3}, **kw)


# --- annotation parsing ---------------------------------------------------
def test_parse_grades_keeps_the_highest_grade():
    assert parse_grades(["er_2", "er_3", "vesicles_1"]) == {"er": 3, "vesicles": 1}
    assert parse_grades(["publication_ready", "pretty"]) == {}


def test_sole_dominant_requires_a_unique_top():
    assert sole_dominant({"er": 3, "vesicles": 2}) == "er"
    # A protein at the top grade in two compartments belongs to neither set:
    # it would otherwise be the right answer in two candidate sets at once.
    assert sole_dominant({"er": 3, "vesicles": 3}) is None
    assert sole_dominant({}) is None


def test_build_targets_applies_qc_and_sole_dominance():
    def line(gene, cats, ensg="ENSG1"):
        return {"annotation": {"categories": cats},
                "metadata": {"ensg_id": ensg, "cell_line_id": 1, "target_name": gene},
                "uniprot_metadata": {"gene_name": gene},
                "abundance_data": {}, "fov_counts": {"num_fovs": 9},
                "best_pulldown": {"id": 1}}
    cat = [
        line("KEEP", ["er_3", "vesicles_1"]),
        line("QCBAD", ["er_3", next(iter(QC_FLAGS))]),
        line("TIED", ["er_3", "vesicles_3"]),
        line("MINOR", ["golgi_3"]),          # not one of the seven candidate sets
    ]
    genes = {t.gene for t in build_targets(cat)}
    assert genes == {"KEEP"}


def test_knowledge_blocks_and_ablation_keep_one_length():
    fams = ["ARF", "SNARE"]
    t = _target(family="ARF", terminus="N", protein_copy_number=1e5,
                protein_concentration=300.0, rna_abundance=20.0,
                interactors=["ENSG00000000001", "ENSG00000000002"],
                interactor_enrichment=3.0, interactor_stoich=0.5)
    blocks = knowledge_blocks(t, fams)
    assert set(blocks) == set(KNOWLEDGE_BLOCKS)
    full = knowledge_vector(t, fams)
    # The advertised length must match the vector actually produced -- the
    # hand-added version of knowledge_dim once dropped a column.
    assert full.shape == (knowledge_dim(fams),)
    assert full.size == sum(v.size for v in blocks.values())
    # An ablation zeroes a block, never shortens the vector: the model is
    # identical across ablations and only what it can know changes.
    for keep in (("compartment",), ("compartment", "interactome")):
        v = knowledge_vector(t, fams, blocks=keep)
        assert v.shape == full.shape
        assert np.isfinite(v).all()
    # Ablating a block must zero exactly that block's columns and leave the
    # kept ones bit-identical -- not rescale or reorder anything.
    comp_only = knowledge_vector(t, fams, blocks=("compartment",))
    n_comp = len(blocks["compartment"])
    assert np.allclose(comp_only[:n_comp], full[:n_comp])
    assert np.count_nonzero(comp_only[n_comp:]) == 0
    assert np.count_nonzero(full[n_comp:]) > 0


def test_unseen_family_falls_into_other_rather_than_a_dead_column():
    # The defect that made the previous study's hold-out folds unanswerable was
    # a conditioning input that was identically zero throughout training.
    fams = ["ARF", "SNARE"]
    known = knowledge_vector(_target(family="ARF"), fams)
    unseen = knowledge_vector(_target(family="NEVER_SEEN"), fams)
    other = knowledge_vector(_target(family=None), fams)
    assert not np.allclose(known, unseen)
    assert np.allclose(unseen, other)  # both land in the same "other" slot


def test_compartment_block_is_identical_within_a_candidate_set():
    # This is what makes the within-compartment test immune to the circularity
    # of OpenCell's image-derived annotations: the circular part is constant.
    fams = ["ARF"]
    a = knowledge_blocks(_target("A", grades={"er": 3}), fams)["compartment"]
    b = knowledge_blocks(_target("B", grades={"er": 3}), fams)["compartment"]
    assert np.allclose(a, b)
    assert len(a) == len(ALL_COMPARTMENTS)
    assert len(COMPARTMENTS) == 7


def test_interactome_hash_is_deterministic_and_set_based():
    fams: list[str] = []
    one = _target(interactors=["ENSG00000000001", "ENSG00000000002"])
    same = _target(interactors=["ENSG00000000002", "ENSG00000000001"])
    other = _target(interactors=["ENSG00000000003"])
    a = knowledge_blocks(one, fams)["interactome"]
    b = knowledge_blocks(same, fams)["interactome"]
    c = knowledge_blocks(other, fams)["interactome"]
    assert np.allclose(a, b)          # order must not matter
    assert not np.allclose(a, c)


# --- the descriptor -------------------------------------------------------
def _synthetic_tile(kind: str, seed: int = 0, size: int = 96):
    """A nucleus channel plus one of three distinguishable target patterns."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:size, 0:size]
    nucleus = np.zeros((size, size), np.float32)
    for cy, cx in ((size * 0.3, size * 0.3), (size * 0.7, size * 0.75)):
        nucleus += np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * (size * 0.1) ** 2)))
    nucleus = np.clip(nucleus, 0, 1).astype(np.float32)
    if kind == "nuclear":
        target = nucleus.copy()
    elif kind == "coarse":
        target = np.zeros((size, size), np.float32)
        for _ in range(6):
            cy, cx = rng.integers(10, size - 10, 2)
            target += np.exp(-(((yy - cy) ** 2 + (xx - cx) ** 2) / (2 * 6.0**2)))
    elif kind == "fine":
        target = np.zeros((size, size), np.float32)
        ys, xs = rng.integers(0, size, (2, 200))
        target[ys, xs] = 1.0
    else:
        raise ValueError(kind)
    target = np.clip(target + 0.02 * rng.standard_normal((size, size)), 0, None)
    return nucleus[None].astype(np.float32), target.astype(np.float32)


def test_descriptor_dimension_and_finiteness():
    ref, tgt = _synthetic_tile("coarse", 0)
    v = describe(ref, tgt)
    assert v.shape == (DESCRIPTOR_DIM,)
    assert np.isfinite(v).all()


def test_descriptor_separates_patterns_it_was_built_to_separate():
    kinds = ("nuclear", "coarse", "fine")
    groups = {k: np.stack([describe(*_synthetic_tile(k, s)) for s in range(4)])
              for k in kinds}
    allrows = np.concatenate(list(groups.values()))
    z = standardise(allrows)
    zs = {k: z[i * 4:(i + 1) * 4] for i, k in enumerate(kinds)}
    for k in kinds:
        within = np.linalg.norm(zs[k][:, None] - zs[k][None, :], axis=-1)
        within = within[np.triu_indices(4, 1)].mean()
        between = min(
            np.linalg.norm(zs[k][:, None] - zs[o][None, :], axis=-1).mean()
            for o in kinds if o != k
        )
        assert within < between, f"{k}: within {within:.2f} !< between {between:.2f}"


def test_nucleus_mask_and_signed_distance():
    ref, _ = _synthetic_tile("coarse", 1)
    mask = nucleus_mask(ref[0])
    assert 0 < mask.mean() < 0.6
    d = signed_nucleus_distance(ref[0])
    assert (d[mask] <= 0).all()
    assert (d[~mask] >= 0).all()


def test_descriptor_handles_an_empty_target():
    ref, _ = _synthetic_tile("coarse", 2)
    v = describe(ref, np.zeros_like(ref[0]))
    assert np.isfinite(v).all()


# --- retrieval ------------------------------------------------------------
def test_score_match_and_unit_mass():
    a = np.random.default_rng(0).random((8, 8)).astype(np.float32)
    assert score_match(a, a) > 0.999
    u = unit_mass(a)
    assert abs(u.sum() - 1.0) < 1e-5
    assert np.isnan(score_match(np.zeros((8, 8)), a))


def test_rank_of_truth_breaks_ties_pessimistically():
    # A model that emits the same field for every identity must score the worst
    # rank, not a lucky first place.
    assert rank_of_truth({"A": 1.0, "B": 0.5, "C": 0.1}, "A") == (1, 3)
    assert rank_of_truth({"A": 0.5, "B": 0.5, "C": 0.5}, "A") == (3, 3)
    assert rank_of_truth({"A": 0.1, "B": 0.5}, "A") == (2, 2)
    assert rank_of_truth({"B": 0.5}, "A")[0] == 0


def test_retrieval_summary_reports_chance():
    s = retrieval_summary([(1, 8), (4, 8), (2, 8), (8, 8)])
    assert s["n"] == 4
    assert s["top1"] == 0.25
    assert abs(s["chance_top1"] - 0.125) < 1e-9
    # Chance MRR over 8 candidates is H_8 / 8.
    assert abs(s["chance_mrr"] - sum(1 / k for k in range(1, 9)) / 8) < 1e-9


def test_random_ranking_lands_at_chance():
    rng = np.random.default_rng(0)
    ranks = [(int(rng.integers(1, 9)), 8) for _ in range(4000)]
    s = retrieval_summary(ranks)
    assert abs(s["top1"] - s["chance_top1"]) < 0.02
    assert abs(s["mrr"] - s["chance_mrr"]) < 0.03


def test_protein_clustered_bootstrap_widens_with_clustering():
    rng = np.random.default_rng(0)
    effect = rng.normal(0, 1.0, 10)
    values = np.concatenate([e + rng.normal(0, 0.05, 8) for e in effect])
    genes = np.repeat([f"g{i}" for i in range(10)], 8)
    _, lo_c, hi_c = protein_clustered_bootstrap(values, genes, n_resamples=400, seed=1)
    _, lo_i, hi_i = protein_clustered_bootstrap(
        values, np.array([f"t{i}" for i in range(values.size)]), n_resamples=400, seed=1)
    assert (hi_c - lo_c) > 1.5 * (hi_i - lo_i)


def test_descriptor_retrieval_excludes_the_same_field():
    # Two tiles of one field are near-copies. If a tile could match its own
    # field-mate, the gate would pass on every compartment for a reason that has
    # nothing to do with the protein. Here each protein has two fields, and
    # within a field the two tiles are byte-identical decoys placed far from the
    # protein's own other field -- so retrieval succeeds only if the decoys are
    # excluded and the cross-field match is used.
    genes = np.array(["A", "A", "A", "A", "B", "B", "B", "B"])
    fovs = np.array(["a1", "a1", "a2", "a2", "b1", "b1", "b2", "b2"])
    X = np.array([
        [0.0, 0.0], [0.0, 0.0],      # A, field a1
        [0.4, 0.0], [0.4, 0.0],      # A, field a2 -- near a1
        [9.0, 9.0], [9.0, 9.0],      # B, field b1
        [9.4, 9.0], [9.4, 9.0],      # B, field b2 -- near b1
    ])
    ranks = descriptor_retrieval(X, genes, fovs, ["A", "B"])
    assert len(ranks) == 8
    assert all(r == 1 for r, _ in ranks)
    assert all(n == 2 for _, n in ranks)


def test_descriptor_retrieval_drops_a_protein_with_one_field():
    # A protein with a single field can never be retrieved once its own field is
    # excluded. Those tiles must be reported as unranked (rank 0) and filtered
    # out of the summary rather than counted as failures.
    genes = np.array(["A", "A", "B", "B"])
    fovs = np.array(["f1", "f1", "f2", "f2"])
    X = np.array([[0.0, 0.0], [0.0, 0.0], [5.0, 5.0], [5.0, 5.0]])
    ranks = descriptor_retrieval(X, genes, fovs, ["A", "B"])
    assert all(r == 0 for r, _ in ranks)
    assert retrieval_summary(ranks)["n"] == 0


@pytest.mark.parametrize("n", [2, 5, 8])
def test_rank_never_exceeds_candidate_count(n):
    scores = {f"g{i}": float(i) for i in range(n)}
    rank, total = rank_of_truth(scores, "g0")
    assert 1 <= rank <= total == n


def test_dominant_compartment_form_is_a_true_null_graded_is_not():
    """The pre-registration's immunity argument holds only for the dominant form.

    The graded form writes every annotation a protein carries, so secondary
    localisations -- which OpenCell read off its own microscopy -- differ
    between candidates in a compartment and are available to a ranking. That
    makes a "compartment-only" run in the graded form not a null, and
    reintroduces exactly the circularity the design claimed to avoid.
    """
    fams: list[str] = []
    candidates = [
        _target("A", grades={"er": 3}),
        _target("B", grades={"er": 3, "vesicles": 1}),
        _target("C", grades={"er": 3, "golgi": 2}),
    ]
    graded = {tuple(np.round(knowledge_blocks(t, fams)["compartment"], 5))
              for t in candidates}
    dominant = {tuple(np.round(
        knowledge_blocks(t, fams, compartment_form="dominant")["compartment"], 5))
        for t in candidates}
    assert len(graded) == 3, "graded form must differ between candidates"
    assert len(dominant) == 1, "dominant form must be identical between candidates"


def test_dominant_form_makes_whole_vectors_identical_under_the_null():
    fams = ["ARF"]
    candidates = [
        _target("A", grades={"er": 3}, family="ARF", protein_copy_number=1e5,
                interactors=["ENSG1"]),
        _target("B", grades={"er": 3, "golgi": 2}, family=None,
                protein_copy_number=9e6, interactors=["ENSG2", "ENSG3"]),
    ]
    vs = [knowledge_vector(t, fams, blocks=("compartment",),
                           compartment_form="dominant") for t in candidates]
    # Under the true null every candidate is byte-identical, so a retrieval
    # cannot do better than chance however the model behaves.
    assert np.allclose(vs[0], vs[1])
    # And the full vector must still separate them, or nothing can be learned.
    full = [knowledge_vector(t, fams, compartment_form="dominant") for t in candidates]
    assert not np.allclose(full[0], full[1])


def test_unknown_compartment_form_raises():
    with pytest.raises(ValueError, match="compartment_form"):
        knowledge_blocks(_target(), [], compartment_form="nonsense")


# --- candidate protein descriptions ---------------------------------------
def test_description_blocks_are_finite_and_fixed_length():
    from vcell.protein_desc import (
        BLOCKS,
        composition_block,
        domains_block,
        function_kw_block,
        location_kw_block,
        lowcomplexity_block,
        topology_block,
    )

    short = {"sequence": {"value": "MAKLV"}, "features": [], "keywords": [],
             "uniProtKBCrossReferences": []}
    rich = {
        "sequence": {"value": "M" + "AILVFWM" * 40 + "KKKRRRDDDEEE" + "PPPPPPPP"},
        "features": [
            {"type": "Transmembrane",
             "location": {"start": {"value": 10}, "end": {"value": 30}}},
            {"type": "Signal", "location": {"start": {"value": 1},
                                            "end": {"value": 22}}},
            {"type": "Lipidation", "location": {"start": {"value": 5},
                                                "end": {"value": 5}}},
            {"type": "Coiled coil", "location": {"start": {"value": 40},
                                                 "end": {"value": 80}}},
            {"type": "Compositional bias",
             "location": {"start": {"value": 100}, "end": {"value": 140}}},
            {"type": "Domain", "location": {"start": {"value": 50},
                                            "end": {"value": 90}},
             "description": "Ras"},
        ],
        "keywords": [
            {"category": "Cellular component", "name": "Golgi apparatus"},
            {"category": "PTM", "name": "Prenylation"},
            {"category": "Molecular function", "name": "Hydrolase"},
        ],
        "uniProtKBCrossReferences": [{"database": "Pfam", "id": "PF00071"}],
    }
    for fn in (composition_block, topology_block, lowcomplexity_block,
               domains_block, function_kw_block, location_kw_block):
        a, b = fn(short), fn(rich)
        assert a.shape == b.shape, fn.__name__
        assert np.isfinite(a).all() and np.isfinite(b).all(), fn.__name__
        assert not np.allclose(a, b), f"{fn.__name__} does not distinguish these"
    # An empty record must not crash any block.
    empty = {"sequence": {"value": ""}, "features": [], "keywords": [],
             "uniProtKBCrossReferences": []}
    for fn in (composition_block, topology_block, lowcomplexity_block,
               domains_block, function_kw_block, location_kw_block):
        assert np.isfinite(fn(empty)).all(), fn.__name__
    # Exactly one block may be marked circular, and it must be the location one.
    circular = [b.name for b in BLOCKS if b.circular]
    assert circular == ["location_kw"]


def test_location_and_function_keywords_do_not_overlap():
    """The circular block must take the location keywords and nothing else."""
    from vcell.protein_desc import _keywords

    rec = {"keywords": [
        {"category": "Cellular component", "name": "Nucleus"},
        {"category": "Cellular component", "name": "Membrane"},
        {"category": "Molecular function", "name": "Hydrolase"},
        {"category": "PTM", "name": "Acetylation"},
    ]}
    loc = set(_keywords(rec, location=True))
    fun = set(_keywords(rec, location=False))
    assert loc == {"Nucleus", "Membrane"}
    assert fun == {"Hydrolase", "Acetylation"}
    assert not (loc & fun)


def test_hashed_bag_is_deterministic_and_order_free():
    from vcell.protein_desc import _hashed_bag

    a = _hashed_bag(["PF00071", "PF12850"], 16, salt="pfam")
    b = _hashed_bag(["PF12850", "PF00071", "PF00071"], 16, salt="pfam")
    c = _hashed_bag(["PF99999"], 16, salt="pfam")
    assert np.allclose(a, b)          # a set, and order cannot matter
    assert not np.allclose(a, c)
    # A different salt must give a different projection, so blocks do not
    # collide with each other in the same buckets.
    assert not np.allclose(a, _hashed_bag(["PF00071", "PF12850"], 16, salt="kwfun"))
    assert np.allclose(_hashed_bag([], 16, salt="pfam"), 0.0)


# --- shared-space fingerprint matching ------------------------------------
def test_cca_finds_a_planted_shared_direction_and_rejects_noise():
    from vcell.fingerprint import fit_cca, held_out_correlations

    rng = np.random.default_rng(0)
    n, p, q = 160, 12, 10
    shared = rng.standard_normal(n)
    X = rng.standard_normal((n, p))
    Y = rng.standard_normal((n, q))
    X[:, 0] += 2.0 * shared
    Y[:, 3] += 2.0 * shared
    tr, te = slice(0, 110), slice(110, n)
    fp = fit_cca(X[tr], Y[tr], k_x=6, k_y=6, ridge=0.1, n_components=2)
    r = held_out_correlations(fp, X[te], Y[te])
    assert abs(r[0]) > 0.5, f"planted shared direction not recovered: {r}"

    # With the pairing destroyed there must be nothing left to find.
    Yp = Y[rng.permutation(n)]
    fpn = fit_cca(X[tr], Yp[tr], k_x=6, k_y=6, ridge=0.1, n_components=2)
    rn = held_out_correlations(fpn, X[te], Yp[te])
    assert abs(rn[0]) < abs(r[0])


def test_residualising_removes_a_group_effect_from_both_views():
    """The leak this closes: compartment left in both views pairs with itself."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from vcell_fingerprint import residualise_on_compartment

    rng = np.random.default_rng(1)
    groups = np.array(["a"] * 40 + ["b"] * 40)
    offset = np.where(groups == "a", 5.0, -5.0)[:, None]
    M = rng.standard_normal((80, 6)) + offset
    is_train = np.zeros(80, bool)
    is_train[:30] = True
    is_train[40:70] = True
    R = residualise_on_compartment(M, groups, is_train)
    # Group means must be near zero afterwards, on held-out rows too.
    for g in ("a", "b"):
        held = (groups == g) & ~is_train
        assert abs(float(R[held].mean())) < 0.6, f"group {g} offset survived"
    assert abs(float(M[groups == "a"].mean() - M[groups == "b"].mean())) > 5.0


def test_retrieval_in_shared_space_is_chance_when_views_are_unrelated():
    from vcell.fingerprint import fit_cca, retrieve_in_shared_space
    from vcell.retrieval import retrieval_summary

    rng = np.random.default_rng(2)
    genes = np.array([f"g{i}" for i in range(64)])
    X = rng.standard_normal((64, 8))
    Y = rng.standard_normal((64, 8))
    fp = fit_cca(X[:40], Y[:40], k_x=4, k_y=4, ridge=1.0, n_components=2)
    sets = [list(genes[i:i + 8]) for i in range(40, 64, 8)]
    ranks = retrieve_in_shared_space(fp, X, Y, genes, sets)
    s = retrieval_summary(ranks)
    assert s["n"] > 0
    # Unrelated views: top-1 must not land far above the 1/8 chance level.
    assert s["top1"] < 0.45, s["top1"]
