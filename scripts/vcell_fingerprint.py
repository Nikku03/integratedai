#!/usr/bin/env python3
"""Match gene fingerprints to image fingerprints in a shared space.

Everything public that a database knows about a gene except where it is --
STRING functional associations, GO process and function, Reactome pathways, HPA
expression specificity, AlphaFold structure confidence, sequence composition and
topology, an ESM-2 embedding, abundance and interactome -- against the image
fingerprint, by two methods:

* **regress** -- predict the 36-dim image descriptor, as the earlier screen did.
* **match** -- canonical correlation: put both views in one shared space and
  measure whether they still co-vary on proteins the fit never saw. This is what
  identification by fingerprint actually is, and it is far more sensitive: a
  single shared direction is found here and diluted there.

Both are run twice -- on the raw descriptor, and on the descriptor with its
compartment's training mean removed. Only the second is news, because
compartment is already known to be predictable.

    python scripts/vcell_fingerprint.py --data-dir .vcell/oc
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.fingerprint import (  # noqa: E402
    held_out_correlations,
    retrieve_in_shared_space,
    select_and_fit,
)
from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.oc_train import build_vectors, training_families  # noqa: E402
from vcell.opencell import COMPARTMENTS, load_sample  # noqa: E402
from vcell.protein_desc import build_blocks, load_uniprot  # noqa: E402
from vcell.retrieval import retrieval_summary  # noqa: E402

# One grid, used identically for the observed fit and for every permutation, so
# the null absorbs exactly the selection optimism the observed value does.
GRID_X = (8, 16, 32)
GRID_Y = (4, 8)
GRID_RIDGE = (0.2, 1.0)
N_COMPONENTS = 3
FOLDS = 5


def zscore(X: np.ndarray, rows: np.ndarray):
    mu, sd = X[rows].mean(0), X[rows].std(0)
    sd[sd < 1e-9] = 1.0
    return (X - mu) / sd


def residualise_on_compartment(M: np.ndarray, compartment: np.ndarray,
                               is_train: np.ndarray, ridge: float = 1e-3):
    """Remove everything a compartment label can explain, from BOTH views.

    Subtracting each compartment's mean from the image view alone is not enough.
    A gene-level view such as the STRING profile encodes compartment strongly,
    and the training-estimated compartment means leave a residual offset in
    held-out proteins -- so CCA can pair the compartment that is still in the
    description against the compartment that is still in the image and report a
    correlation that has nothing to do with protein identity. Regressing both
    views on the compartment one-hot, with coefficients fitted on training
    proteins only, closes that path.
    """
    levels = sorted(set(compartment.tolist()))
    D = np.zeros((compartment.size, len(levels)), dtype=np.float64)
    for j, lv in enumerate(levels):
        D[compartment == lv, j] = 1.0
    Dtr, Mtr = D[is_train], M[is_train]
    W = np.linalg.solve(Dtr.T @ Dtr + ridge * np.eye(len(levels)), Dtr.T @ Mtr)
    return M - D @ W


def run_match(X, Y, is_train, genes, candidate_sets, seed, n_perm):
    Xtr, Ytr = X[is_train], Y[is_train]
    Xte, Yte = X[~is_train], Y[~is_train]
    fp, cfg = select_and_fit(Xtr, Ytr, GRID_X, GRID_Y, GRID_RIDGE,
                             N_COMPONENTS, FOLDS, seed)
    r = held_out_correlations(fp, Xte, Yte)
    ranks = retrieve_in_shared_space(fp, Xte, Yte, genes[~is_train], candidate_sets)
    summary = retrieval_summary(ranks)

    # Permutation null with the hyperparameter search repeated inside, so the
    # null carries the same selection optimism the observed value does.
    rng = np.random.default_rng(seed)
    null_top, null_top1 = np.empty(n_perm), np.empty(n_perm)
    for i in range(n_perm):
        p = rng.permutation(Xtr.shape[0])
        fpp, _ = select_and_fit(Xtr[p], Ytr, GRID_X, GRID_Y, GRID_RIDGE,
                                N_COMPONENTS, FOLDS, seed + 1 + i)
        q = rng.permutation(Xte.shape[0])
        null_top[i] = abs(held_out_correlations(fpp, Xte[q], Yte)[0])
        rk = retrieve_in_shared_space(fpp, Xte[q], Yte, genes[~is_train],
                                      candidate_sets)
        null_top1[i] = retrieval_summary(rk)["top1"]
    return {
        "config": cfg,
        "train_correlations": fp.correlations.tolist(),
        "heldout_correlations": r.tolist(),
        "top_abs_correlation": float(abs(r[0])),
        "null_p95": float(np.percentile(null_top, 95)),
        "p_value": float((null_top >= abs(r[0])).mean()),
        "retrieval_top1": summary["top1"],
        "retrieval_chance": summary["chance_top1"],
        "retrieval_null_p95": float(np.percentile(null_top1, 95)),
        "retrieval_p_value": float((null_top1 >= summary["top1"]).mean()),
        "n_test": int((~is_train).sum()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--permutations", type=int, default=300,
                    help="permutations for the within-compartment test, the one "
                         "that matters")
    ap.add_argument("--raw-permutations", type=int, default=25,
                    help="the raw column only needs enough to confirm what two "
                         "previous studies already established")
    args = ap.parse_args()

    D = Path(args.data_dir)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")
    with np.load(D / "descriptors.npz") as z:
        desc = z["X"]
    genes = np.array(sorted(set(tiles["gene"].tolist())))
    Y = np.stack([desc[tiles["gene"] == g].mean(axis=0) for g in genes])
    comp = {str(tiles["gene"][i]): str(tiles["compartment"][i])
            for i in range(tiles["gene"].size)}
    train_genes = {t.gene for d in sample.values() for t in d["train"]}
    is_train = np.array([g in train_genes for g in genes])

    # Sequence and annotation blocks, then the gene-level database blocks.
    records = load_uniprot(D / "uniprot.json")
    esm = None
    if (D / "esm.npz").exists():
        with np.load(D / "esm.npz", allow_pickle=False) as z:
            esm = {str(g): v for g, v in zip(z["genes"], z["emb"], strict=True)}
    families = training_families(sample)
    base = build_vectors(sample, families, compartment_form="dominant")
    blocks = build_blocks(records, esm=esm, baseline={g: v[19:] for g, v in base.items()})
    blocks.pop("location_kw", None)  # circular; excluded from every combination here
    with np.load(D / "gene_blocks.npz", allow_pickle=False) as z:
        gene_names = [str(g) for g in z["genes"]]
        for name in z.files:
            if name == "genes":
                continue
            blocks[name] = {g: v for g, v in zip(gene_names, z[name], strict=True)}

    candidate_sets = [[t.gene for t in sample[c]["held_out"] if t.gene in set(genes)]
                      for c in COMPARTMENTS]

    comp_arr = np.array([comp[g] for g in genes])

    combos = {name: [name] for name in blocks}
    combos["EVERYTHING"] = sorted(blocks)
    combos["databases only"] = ["string_profile", "string_channels",
                                "go_process_function", "reactome",
                                "hpa_expression", "alphafold"]
    combos["esm + databases"] = ["esm"] + combos["databases only"]

    print(f"{genes.size} proteins: {int(is_train.sum())} training, "
          f"{int((~is_train).sum())} held out; "
          f"{len(blocks)} fingerprint blocks available\n")
    print(f"{'fingerprint':26s} {'dims':>5s} | {'RAW: corr':>10s} {'p':>6s} "
          f"{'top1':>6s} | {'WITHIN-COMP: corr':>18s} {'p':>6s} {'top1':>6s} "
          f"{'nullp95':>8s} {'chance':>7s}")
    results = {}
    for label, names in combos.items():
        if any(n not in blocks for n in names):
            continue
        X = np.concatenate([np.stack([blocks[n][g] for g in genes]) for n in names],
                           axis=1)
        Xz = zscore(X, is_train)
        Yz = zscore(Y, is_train)
        raw = run_match(Xz, Yz, is_train, genes, candidate_sets,
                        args.seed, args.raw_permutations)
        # Both views residualised on compartment: whatever survives cannot be
        # the compartment in either of them.
        Xr = zscore(residualise_on_compartment(Xz, comp_arr, is_train), is_train)
        Yr = zscore(residualise_on_compartment(Yz, comp_arr, is_train), is_train)
        cen = run_match(Xr, Yr, is_train, genes, candidate_sets,
                        args.seed, args.permutations)
        results[label] = {"dims": int(X.shape[1]), "members": names,
                          "raw": raw, "within_compartment": cen}
        print(f"{label:26s} {X.shape[1]:5d} | {raw['top_abs_correlation']:10.3f} "
              f"{raw['p_value']:6.3f} {raw['retrieval_top1']:6.3f} | "
              f"{cen['top_abs_correlation']:18.3f} {cen['p_value']:6.3f} "
              f"{cen['retrieval_top1']:6.3f} {cen['retrieval_null_p95']:8.3f} "
              f"{cen['retrieval_chance']:7.3f}")

    (D / "fingerprint_match.json").write_text(json.dumps(results, indent=1,
                                                         default=float))
    print(f"\nwrote {D/'fingerprint_match.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
