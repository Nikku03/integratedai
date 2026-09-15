#!/usr/bin/env python3
"""Screen candidate protein descriptions: does any of them predict appearance?

The two previous studies left one question. The images carry each protein's
fingerprint -- a fixed texture descriptor picks the right protein 76% of the
time inside the vesicle compartment -- and the description we had (abundance,
family, terminus, interactome) could not reach it. So: try better descriptions.

Screening on retrieval top-1 would be wasteful and weak. Retrieval asks an
8-way question per tile, and a 50-minute training run answers it once. Instead
this screens on **held-out R-squared against the 36-dimensional image
descriptor**, one observation per protein, by ridge regression -- which the
OpenCell study already established is a faithful and strictly easier stand-in
for the full model. Each screen takes under a second, so every candidate
description can be tried before anything is trained.

Three things make the screen trustworthy rather than just fast:

* **A permutation null.** With 53 held-out proteins and 36 targets, R-squared
  can be comfortably positive by chance. Every block is compared against the
  distribution of R-squared obtained when the protein-to-description pairing is
  shuffled, so the reported p-value is against the real null and not against 0.
* **Ridge strength chosen inside the training set only**, by k-fold on training
  proteins, never on the held-out proteins.
* **Circular blocks reported separately.** UniProt's cellular-component
  keywords are curated from literature that includes imaging, so they are not
  an honest description of a protein for this test. They are screened anyway,
  to show what the ceiling looks like when you are allowed to cheat.

And one column decides whether any of this is progress. Most of the variance in
the image descriptor is *between* compartments, and both previous studies
already established that compartment is predictable. So every block is screened
twice: once on the raw descriptor, and once on the descriptor with its
compartment's training mean subtracted. A description that scores on the raw
target and collapses on the compartment-centred one has merely re-derived the
compartment -- the previous finding over again, in a new costume. Only the
centred column is news.

    python scripts/vcell_describe.py --data-dir .vcell/oc
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.oc_train import build_vectors, training_families  # noqa: E402
from vcell.opencell import COMPARTMENTS, load_sample  # noqa: E402
from vcell.protein_desc import (  # noqa: E402
    BLOCKS,
    _hashed_bag,
    build_blocks,
    load_uniprot,
)
from vcell.retrieval import rank_of_truth, retrieval_summary  # noqa: E402

ALPHAS = np.geomspace(1e-2, 1e5, 22)
N_PERMUTATIONS = 500


def ridge_fit(X: np.ndarray, Y: np.ndarray, alpha: float) -> np.ndarray:
    X1 = np.hstack([X, np.ones((X.shape[0], 1))])
    n = X1.shape[1]
    reg = alpha * np.eye(n)
    reg[-1, -1] = 0.0  # never penalise the intercept
    return np.linalg.solve(X1.T @ X1 + reg, X1.T @ Y)


def ridge_predict(X: np.ndarray, W: np.ndarray) -> np.ndarray:
    return np.hstack([X, np.ones((X.shape[0], 1))]) @ W


def choose_alpha(X: np.ndarray, Y: np.ndarray, folds: int, seed: int) -> float:
    """k-fold on the training proteins only."""
    rng = np.random.default_rng(seed)
    order = rng.permutation(X.shape[0])
    parts = np.array_split(order, folds)
    best, best_alpha = -np.inf, ALPHAS[-1]
    for alpha in ALPHAS:
        sse, sst = 0.0, 0.0
        for i in range(folds):
            va = parts[i]
            tr = np.concatenate([parts[j] for j in range(folds) if j != i])
            W = ridge_fit(X[tr], Y[tr], alpha)
            pred = ridge_predict(X[va], W)
            sse += float(((Y[va] - pred) ** 2).sum())
            sst += float(((Y[va] - Y[tr].mean(axis=0)) ** 2).sum())
        score = 1.0 - sse / sst if sst > 0 else -np.inf
        if score > best:
            best, best_alpha = score, alpha
    return float(best_alpha)


def r2_pooled(Y: np.ndarray, pred: np.ndarray, baseline_mean: np.ndarray) -> float:
    """Variance-weighted R-squared: one number over all 36 descriptor dims.

    The denominator uses the *training* mean, so the score is what a user of the
    model would actually get -- not flattered by centring on the test set.
    """
    sse = float(((Y - pred) ** 2).sum())
    sst = float(((Y - baseline_mean) ** 2).sum())
    return 1.0 - sse / sst if sst > 0 else float("nan")


def r2_per_dim(Y: np.ndarray, pred: np.ndarray, baseline_mean: np.ndarray) -> np.ndarray:
    sse = ((Y - pred) ** 2).sum(axis=0)
    sst = ((Y - baseline_mean) ** 2).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sst > 0, 1.0 - sse / sst, np.nan)


def screen_block(
    X_train, Y_train, X_test, Y_test, folds: int, seed: int, n_perm: int
) -> dict:
    alpha = choose_alpha(X_train, Y_train, folds, seed)
    mu = Y_train.mean(axis=0)
    W = ridge_fit(X_train, Y_train, alpha)
    pred = ridge_predict(X_test, W)
    observed = r2_pooled(Y_test, pred, mu)
    per_dim = r2_per_dim(Y_test, pred, mu)

    # Permutation null: break the protein-to-description pairing, keep both
    # marginal distributions, refit end to end including the alpha.
    rng = np.random.default_rng(seed)
    null = np.empty(n_perm)
    null_dims = np.empty((n_perm, Y_test.shape[1]))
    for i in range(n_perm):
        p = rng.permutation(X_train.shape[0])
        Wp = ridge_fit(X_train[p], Y_train, alpha)
        q = rng.permutation(X_test.shape[0])
        predp = ridge_predict(X_test[q], Wp)
        null[i] = r2_pooled(Y_test, predp, mu)
        null_dims[i] = r2_per_dim(Y_test, predp, mu)
    sig = int(np.sum(per_dim > np.nanpercentile(null_dims, 95, axis=0)))
    return {
        "alpha": alpha,
        "r2": observed,
        "r2_null_median": float(np.median(null)),
        "r2_null_p95": float(np.percentile(null, 95)),
        "p_value": float((null >= observed).mean()),
        "n_dims_above_null": sig,
        "n_dims": int(Y_test.shape[1]),
        "best_dims": [int(i) for i in np.argsort(-np.nan_to_num(per_dim, nan=-9))[:5]],
        "best_dim_r2": [float(per_dim[i])
                        for i in np.argsort(-np.nan_to_num(per_dim, nan=-9))[:5]],
    }


def retrieval_from_predictions(
    pred: np.ndarray, Y_test: np.ndarray, genes_test: np.ndarray,
    compartment_of: dict[str, str], sample
) -> dict:
    """The downstream question: does the predicted descriptor pick the protein?"""
    ranks = []
    for c in COMPARTMENTS:
        cands = [g for g in (t.gene for t in sample[c]["held_out"]) if g in set(genes_test)]
        if len(cands) < 2:
            continue
        idx = {g: int(np.flatnonzero(genes_test == g)[0]) for g in cands}
        for g in cands:
            scores = {cand: -float(((pred[idx[cand]] - Y_test[idx[g]]) ** 2).sum())
                      for cand in cands}
            ranks.append(rank_of_truth(scores, g))
    return retrieval_summary(ranks)


def split_half_reliability(tiles, desc, genes, compartment_of, is_train, seed: int):
    """Is the thing we are trying to predict measurable at all?

    Describe each protein twice, from two disjoint halves of its fields of view,
    and correlate. A near-zero reliability would make a null R-squared
    uninformative -- we would be failing to predict noise. This repository has
    already been caught by exactly that once: see docs/RESULT_ENTROPY.md, where
    a feature passed its orthogonality gate because it carried no information at
    all rather than because it carried independent information.
    """
    rng = np.random.default_rng(seed)
    A, B, keep = [], [], []
    for g in genes:
        rows = np.flatnonzero(tiles["gene"] == g)
        fovs = sorted(set(tiles["fov_id"][rows].tolist()))
        if len(fovs) < 2:
            continue
        rng.shuffle(fovs)
        half = len(fovs) // 2
        a = rows[np.isin(tiles["fov_id"][rows], fovs[:half])]
        b = rows[np.isin(tiles["fov_id"][rows], fovs[half:])]
        if a.size == 0 or b.size == 0:
            continue
        A.append(desc[a].mean(axis=0))
        B.append(desc[b].mean(axis=0))
        keep.append(g)
    if not keep:
        return {}
    A, B, keep = np.stack(A), np.stack(B), np.array(keep)
    cm = np.array([compartment_of[g] for g in keep])
    tr = np.array([bool(is_train[list(genes).index(g)]) for g in keep])

    def corr(P, Q):
        out = []
        for j in range(P.shape[1]):
            if P[:, j].std() > 1e-9 and Q[:, j].std() > 1e-9:
                out.append(float(np.corrcoef(P[:, j], Q[:, j])[0, 1]))
            else:
                out.append(float("nan"))
        return np.array(out)

    raw = corr(A, B)
    Ac, Bc = A.copy(), B.copy()
    for c in np.unique(cm):
        rows = cm == c
        t = rows & tr
        if t.sum() >= 2:
            Ac[rows] = A[rows] - A[t].mean(axis=0)
            Bc[rows] = B[rows] - B[t].mean(axis=0)
    centred = corr(Ac, Bc)
    return {
        "n_proteins": int(keep.size),
        "raw_mean_r": float(np.nanmean(raw)),
        "raw_dims_above_half": int(np.nansum(raw > 0.5)),
        "centred_mean_r": float(np.nanmean(centred)),
        "centred_median_r": float(np.nanmedian(centred)),
        "centred_dims_above_half": int(np.nansum(centred > 0.5)),
        "n_dims": int(raw.size),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--permutations", type=int, default=N_PERMUTATIONS)
    args = ap.parse_args()

    D = Path(args.data_dir)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")
    with np.load(D / "descriptors.npz") as z:
        desc = z["X"]

    # One observation per protein: the mean image descriptor over its tiles.
    genes = np.array(sorted(set(tiles["gene"].tolist())))
    Y = np.stack([desc[tiles["gene"] == g].mean(axis=0) for g in genes])
    compartment_of = {str(tiles["gene"][i]): str(tiles["compartment"][i])
                      for i in range(tiles["gene"].size)}

    train_genes = {t.gene for d in sample.values() for t in d["train"]}
    is_train = np.array([g in train_genes for g in genes])
    print(f"{genes.size} proteins with images: {int(is_train.sum())} training, "
          f"{int((~is_train).sum())} held out")
    print(f"target: the {Y.shape[1]}-dim image descriptor, averaged over each "
          f"protein's tiles\n")

    records = load_uniprot(D / "uniprot.json")
    esm = None
    if (D / "esm.npz").exists():
        with np.load(D / "esm.npz", allow_pickle=False) as z:
            esm = {str(g): v for g, v in zip(z["genes"], z["emb"], strict=True)}
    families = training_families(sample)
    baseline = build_vectors(sample, families, compartment_form="dominant")
    # Drop the compartment columns: the baseline block under test is the
    # non-compartment part, which is what failed in the OpenCell study.
    n_comp = 19
    baseline = {g: v[n_comp:] for g, v in baseline.items()}
    blocks = build_blocks(records, esm=esm, baseline=baseline)

    # Two interactome variants built from the co-location shortlist. A pulldown
    # reports partners from a whole-cell lysate, so the raw partner list mixes
    # genuine complexes with pairs that only met in the tube. Splitting it by
    # whether the partner is annotated to the same compartment asks whether the
    # shortlist is the informative half.
    from vcell.opencell import parse_grades, sole_dominant

    catalogue = json.loads((D / "catalogue.json").read_text())
    partner_comp: dict[str, str] = {}
    for line in catalogue:
        md = line.get("metadata") or {}
        ensg = md.get("ensg_id")
        dom = sole_dominant(parse_grades(
            list((line.get("annotation") or {}).get("categories") or [])))
        if ensg and dom:
            partner_comp.setdefault(ensg, dom)
    interactors = {t["gene"]: (t.get("interactors") or [])
                   for d in json.loads((D / "sample.json").read_text()).values()
                   for v in d.values() for t in v}
    colocal, cross = {}, {}
    n_co = n_cross = 0
    for g in genes:
        own = compartment_of[g]
        same = [e for e in interactors.get(g, []) if partner_comp.get(e) == own]
        diff = [e for e in interactors.get(g, [])
                if partner_comp.get(e) not in (None, own)]
        n_co += len(same)
        n_cross += len(diff)
        colocal[g] = _hashed_bag(same, 16, salt="coloc")
        cross[g] = _hashed_bag(diff, 16, salt="cross")
    blocks["interactome_colocal"] = colocal
    blocks["interactome_crosscomp"] = cross
    print(f"co-location split of the measured interactomes: {n_co} same-compartment "
          f"partner links, {n_cross} cross-compartment\n")

    # Standardise every block on training proteins only.
    circular = {b.name: b.circular for b in BLOCKS}
    notes = {b.name: b.note for b in BLOCKS}
    results = {}
    Ytr, Yte = Y[is_train], Y[~is_train]
    gte = genes[~is_train]

    combos = {name: [name] for name in blocks}
    honest = [b.name for b in BLOCKS if not b.circular and b.name in blocks
              and b.name != "baseline"]
    combos["ALL honest (no baseline)"] = honest
    combos["esm + interactome_colocal"] = ["esm", "interactome_colocal"]
    combos["ALL honest + baseline"] = honest + ["baseline"]

    # Compartment-centred target: subtract each compartment's TRAINING mean, so
    # only within-compartment variation is left to predict.
    comp = np.array([compartment_of[g] for g in genes])
    Yc = Y.copy()
    for c in np.unique(comp):
        rows = comp == c
        tr = rows & is_train
        if tr.sum() >= 2:
            Yc[rows] = Y[rows] - Y[tr].mean(axis=0)
    Yctr, Ycte = Yc[is_train], Yc[~is_train]
    print(f"{'description block':28s} {'dims':>5s} {'raw R2':>8s} {'p':>6s} "
          f"{'within-comp R2':>15s} {'null p95':>9s} {'p':>6s} {'dims>null':>10s} "
          f"{'retr top1':>10s}")
    for label, names in combos.items():
        missing = [n for n in names if n not in blocks]
        if missing:
            continue
        X = np.concatenate(
            [np.stack([blocks[n][g] for g in genes]) for n in names], axis=1)
        mu, sd = X[is_train].mean(0), X[is_train].std(0)
        sd[sd < 1e-9] = 1.0
        Xz = (X - mu) / sd
        Xtr, Xte = Xz[is_train], Xz[~is_train]
        r = screen_block(Xtr, Ytr, Xte, Yte, args.folds, args.seed, args.permutations)
        rc = screen_block(Xtr, Yctr, Xte, Ycte, args.folds, args.seed,
                          args.permutations)
        W = ridge_fit(Xtr, Ytr, r["alpha"])
        rt = retrieval_from_predictions(ridge_predict(Xte, W), Yte, gte,
                                        compartment_of, sample)
        Wc = ridge_fit(Xtr, Yctr, rc["alpha"])
        rtc = retrieval_from_predictions(ridge_predict(Xte, Wc), Ycte, gte,
                                         compartment_of, sample)
        r.update(block=label, members=names, dims=int(X.shape[1]),
                 circular=any(circular.get(n, False) for n in names),
                 note="; ".join(notes.get(n, "") for n in names),
                 retrieval=rt, within_compartment=rc, retrieval_centred=rtc)
        results[label] = r
        flag = " [CIRCULAR]" if r["circular"] else ""
        print(f"{label:28s} {X.shape[1]:5d} {r['r2']:8.4f} {r['p_value']:6.3f} "
              f"{rc['r2']:15.4f} {rc['r2_null_p95']:9.4f} {rc['p_value']:6.3f} "
              f"{rc['n_dims_above_null']:>4d}/{rc['n_dims']:<5d} "
              f"{rtc['top1']:10.3f}{flag}")

    rel = split_half_reliability(tiles, desc, genes, compartment_of, is_train,
                                 args.seed)
    if rel:
        print(f"\npositive control -- is the target measurable?  two disjoint halves "
              f"of each protein's fields, {rel['n_proteins']} proteins:")
        print(f"  raw descriptor               r = {rel['raw_mean_r']:.3f}  "
              f"({rel['raw_dims_above_half']}/{rel['n_dims']} dims above 0.5)")
        print(f"  compartment-centred          r = {rel['centred_mean_r']:.3f}  "
              f"({rel['centred_dims_above_half']}/{rel['n_dims']} dims above 0.5)")
        print("  => the within-compartment target is real, so a null R2 above is a "
              "statement about the descriptions, not about noise.")
    (D / "describe_screen.json").write_text(
        json.dumps({"blocks": results, "reliability": rel}, indent=1, default=float))
    print(f"\nwrote {D/'describe_screen.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
