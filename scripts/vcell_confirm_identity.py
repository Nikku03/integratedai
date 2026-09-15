#!/usr/bin/env python3
"""Experiment 2 of docs/PREREG_SCALE.md: the registered 45-way identification.

One fingerprint, registered in advance -- the 512-gene STRING association
profile, alone, because a single block has no fusion rule to choose and the
exploratory run showed that choice moving the answer more than the effect does.
The whole 479-protein qualifying pool, candidate sets of up to 45 where chance
is 2.2%, and retrieval as the primary outcome rather than correlation.

    python scripts/vcell_confirm_identity.py --data-dir .vcell/oc_full
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from vcell_fingerprint import residualise_on_compartment  # noqa: E402

from vcell.descriptor import describe_all, standardise  # noqa: E402
from vcell.fingerprint import (  # noqa: E402
    held_out_correlations,
    retrieve_in_shared_space,
    select_and_fit,
)
from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.opencell import COMPARTMENTS, load_sample  # noqa: E402
from vcell.retrieval import (  # noqa: E402
    protein_clustered_bootstrap,
    retrieval_summary,
)

GRID_X = (8, 16, 32)
GRID_Y = (4, 8)
GRID_RIDGE = (0.2, 1.0)
N_COMPONENTS = 3
FOLDS = 5


def zscore(X, rows):
    mu, sd = X[rows].mean(0), X[rows].std(0)
    sd[sd < 1e-9] = 1.0
    return (X - mu) / sd


def per_compartment_summary(ranks_by_compartment):
    out = {}
    for c, entries in ranks_by_compartment.items():
        ranks = [e[0] for e in entries]
        s = retrieval_summary(ranks)
        hit = np.array([1.0 if r == 1 else 0.0 for r, n in ranks if r > 0 and n > 1])
        gn = np.array([e[1] for e in entries if e[0][0] > 0 and e[0][1] > 1])
        if hit.size:
            m, lo, hi = protein_clustered_bootstrap(hit, gn, seed=1)
            s["top1_lo"], s["top1_hi"] = lo, hi
        out[c] = s
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--permutations", type=int, default=1000)
    args = ap.parse_args()

    D = Path(args.data_dir)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")
    genes = np.array(sorted(set(tiles["gene"].tolist())))
    comp_of = {str(tiles["gene"][i]): str(tiles["compartment"][i])
               for i in range(tiles["gene"].size)}

    cache = D / "descriptors.npz"
    if cache.exists():
        with np.load(cache) as z:
            desc = z["X"]
    else:
        print(f"describing {tiles['target'].shape[0]} tiles ...", flush=True)
        desc = describe_all(tiles["reference"].astype(np.float32),
                            tiles["target"].astype(np.float32))
        np.savez_compressed(cache, X=desc, Xs=standardise(desc))
    Y = np.stack([desc[tiles["gene"] == g].mean(axis=0) for g in genes])

    train_genes = {t.gene for d in sample.values() for t in d["train"]}
    is_train = np.array([g in train_genes for g in genes])

    with np.load(D / "gene_blocks.npz", allow_pickle=False) as z:
        names = [str(g) for g in z["genes"]]
        sp = {g: v for g, v in zip(names, z["string_profile"], strict=True)}
    X = np.stack([sp[g] for g in genes])

    candidate_sets, comp_of_set = [], []
    for c in COMPARTMENTS:
        cands = [t.gene for t in sample[c]["held_out"] if t.gene in set(genes)]
        if len(cands) >= 2:
            candidate_sets.append(cands)
            comp_of_set.append(c)
    print(f"{genes.size} proteins: {int(is_train.sum())} training, "
          f"{int((~is_train).sum())} held out")
    print("candidate sets: " + ", ".join(
        f"{c}={len(s)}" for c, s in zip(comp_of_set, candidate_sets, strict=True)))
    print("chance per set: " + ", ".join(
        f"{1/len(s):.3f}" for s in candidate_sets) + "\n")

    comp_arr = np.array([comp_of[g] for g in genes])
    Xz = zscore(X, is_train)
    Yz = zscore(Y, is_train)
    Xr = zscore(residualise_on_compartment(Xz, comp_arr, is_train), is_train)
    Yr = zscore(residualise_on_compartment(Yz, comp_arr, is_train), is_train)

    fp, cfg = select_and_fit(Xr[is_train], Yr[is_train], GRID_X, GRID_Y,
                             GRID_RIDGE, N_COMPONENTS, FOLDS, args.seed)
    gte = genes[~is_train]
    corr = held_out_correlations(fp, Xr[~is_train], Yr[~is_train])

    def ranks_for(fpx, Xv):
        by_c = defaultdict(list)
        for c, cands in zip(comp_of_set, candidate_sets, strict=True):
            rk = retrieve_in_shared_space(fpx, Xv, Yr[~is_train], gte, [cands])
            present = [g for g in cands if g in set(gte.tolist())]
            for r, g in zip(rk, present, strict=False):
                by_c[c].append((r, g))
        return by_c

    by_c = ranks_for(fp, Xr[~is_train])
    flat = [e[0] for v in by_c.values() for e in v]
    pooled = retrieval_summary(flat)
    hit = np.array([1.0 if r == 1 else 0.0 for r, n in flat if r > 0 and n > 1])
    gn = np.array([e[1] for v in by_c.values() for e in v
                   if e[0][0] > 0 and e[0][1] > 1])
    m, lo, hi = protein_clustered_bootstrap(hit, gn, seed=args.seed)

    # The registered null: identical fingerprints for every candidate must give
    # top-1 of exactly zero under pessimistic tie-breaking.
    Xnull = np.zeros_like(Xr)
    fpn, _ = select_and_fit(Xnull[is_train], Yr[is_train], GRID_X, GRID_Y,
                            GRID_RIDGE, N_COMPONENTS, FOLDS, args.seed)
    null_ranks = [e[0] for v in ranks_for(fpn, Xnull[~is_train]).values() for e in v]
    true_null = retrieval_summary(null_ranks)

    rng = np.random.default_rng(args.seed)
    perm_top1 = np.empty(args.permutations)
    perm_corr = np.empty(args.permutations)
    Xtr, Ytr = Xr[is_train], Yr[is_train]
    Xte = Xr[~is_train]
    for i in range(args.permutations):
        p = rng.permutation(Xtr.shape[0])
        fpp, _ = select_and_fit(Xtr[p], Ytr, GRID_X, GRID_Y, GRID_RIDGE,
                                N_COMPONENTS, FOLDS, args.seed + 1 + i)
        q = rng.permutation(Xte.shape[0])
        perm_corr[i] = abs(held_out_correlations(fpp, Xte[q], Yr[~is_train])[0])
        rk = [e[0] for v in ranks_for(fpp, Xte[q]).values() for e in v]
        perm_top1[i] = retrieval_summary(rk)["top1"]
        if (i + 1) % 100 == 0:
            print(f"  permutation {i+1}/{args.permutations}", flush=True)

    result = {
        "config": cfg,
        "n_proteins": int(genes.size),
        "n_train": int(is_train.sum()),
        "n_held_out": int((~is_train).sum()),
        "candidate_set_sizes": {c: len(s) for c, s in
                                zip(comp_of_set, candidate_sets, strict=True)},
        "heldout_correlations": corr.tolist(),
        "correlation_p": float((perm_corr >= abs(corr[0])).mean()),
        "correlation_null_p95": float(np.percentile(perm_corr, 95)),
        "pooled_top1": pooled["top1"],
        "pooled_top1_lo": lo,
        "pooled_top1_hi": hi,
        "pooled_chance": pooled["chance_top1"],
        "pooled_lift": pooled["top1"] / max(pooled["chance_top1"], 1e-12),
        "pooled_mrr": pooled["mrr"],
        "pooled_chance_mrr": pooled["chance_mrr"],
        "retrieval_p": float((perm_top1 >= pooled["top1"]).mean()),
        "retrieval_null_p95": float(np.percentile(perm_top1, 95)),
        "true_null_top1": true_null["top1"],
        "per_compartment": per_compartment_summary(by_c),
        "n_permutations": args.permutations,
    }
    (D / "confirm_identity.json").write_text(json.dumps(result, indent=1,
                                                        default=float))

    print("\n=== REGISTERED PRIMARY OUTCOME (H4) ===")
    print(f"pooled top-1 {pooled['top1']:.4f} [{lo:.4f}, {hi:.4f}]  "
          f"chance {pooled['chance_top1']:.4f}  lift {result['pooled_lift']:.2f}x")
    print(f"permutation null p95 {result['retrieval_null_p95']:.4f}, "
          f"p = {result['retrieval_p']:.4f}  ({args.permutations} permutations)")
    print(f"MRR {pooled['mrr']:.4f} against chance {pooled['chance_mrr']:.4f}")
    print(f"shared-space correlation {abs(corr[0]):.3f}, "
          f"p = {result['correlation_p']:.4f}")
    print(f"TRUE NULL top-1 = {true_null['top1']:.4f}  (must be exactly 0)")
    print(f"\n{'compartment':14s} {'cands':>5s} {'top1':>20s} {'chance':>7s} {'lift':>6s}")
    for c in COMPARTMENTS:
        s = result["per_compartment"].get(c)
        if not s:
            continue
        print(f"{c:14s} {result['candidate_set_sizes'][c]:5d} "
              f"{s['top1']:7.3f} [{s.get('top1_lo', float('nan')):.3f},"
              f"{s.get('top1_hi', float('nan')):.3f}] {s['chance_top1']:7.3f} "
              f"{s['top1']/max(s['chance_top1'],1e-12):6.2f}x")
    print(f"\nwrote {D/'confirm_identity.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
