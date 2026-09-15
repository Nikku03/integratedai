#!/usr/bin/env python3
"""H6 of docs/PREREG_SCALE.md: is the mechanism complex co-membership?

The registered hypothesis: held-out proteins that have a co-located measured
interaction partner in the training set are identified better than those that do
not. This reproduces Experiment 2's fit exactly -- same split, same seed, same
residualisation, same grid -- and then splits the held-out proteins by that
label rather than refitting anything.

The label comes from the same source as
`data/vcell/opencell/compartment_interactions.csv`: an OpenCell measured
interaction partner whose own dominant compartment matches the protein's. It is
recomputed against the registered split rather than read from that file's
`a_split` column, which was written for the earlier 53-protein sample and
disagrees with the registered one on 165 of its 471 rows.

The null permutes the has-partner label among held-out proteins *within
compartment*, holding every rank fixed, so it asks exactly one question: does
knowing a protein has a training partner predict that it was identified?

    python scripts/vcell_h6_mechanism.py --data-dir .vcell/oc_full
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

from vcell_confirm_identity import FOLDS, GRID_RIDGE, GRID_X, GRID_Y  # noqa: E402
from vcell_confirm_identity import N_COMPONENTS, zscore  # noqa: E402
from vcell_fingerprint import residualise_on_compartment  # noqa: E402

from vcell.descriptor import describe_all, standardise  # noqa: E402
from vcell.fingerprint import retrieve_in_shared_space, select_and_fit  # noqa: E402
from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.opencell import COMPARTMENTS, load_sample  # noqa: E402
from vcell.retrieval import protein_clustered_bootstrap, retrieval_summary  # noqa: E402


def group_stats(entries, seed, interval=True):
    """`entries` are ((rank, n_candidates), gene) for one group."""
    ranks = [e[0] for e in entries]
    if not ranks:
        return {"n": 0}
    s = retrieval_summary(ranks)
    hit = np.array([1.0 if r == 1 else 0.0 for r, n in ranks if r > 0 and n > 1])
    gn = np.array([e[1] for e in entries if e[0][0] > 0 and e[0][1] > 1])
    out = {
        "n": len(ranks),
        "top1": s["top1"],
        "top1_count": int(round(s["top1"] * len(ranks))),
        "chance_top1": s["chance_top1"],
        "lift": s["top1"] / max(s["chance_top1"], 1e-12),
        "mrr": s["mrr"],
        "chance_mrr": s["chance_mrr"],
        "mrr_ratio": s["mrr"] / max(s["chance_mrr"], 1e-12),
        "mean_rank": s["mean_rank"],
    }
    if interval and hit.size:
        _, lo, hi = protein_clustered_bootstrap(hit, gn, seed=seed)
        out["top1_lo"], out["top1_hi"] = lo, hi
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--permutations", type=int, default=10000)
    args = ap.parse_args()

    D = Path(args.data_dir)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")
    genes = np.array(sorted(set(tiles["gene"].tolist())))
    in_pool = set(genes.tolist())
    comp_of = {str(tiles["gene"][i]): str(tiles["compartment"][i])
               for i in range(tiles["gene"].size)}

    cache = D / "descriptors.npz"
    if cache.exists():
        with np.load(cache) as z:
            desc = z["X"]
    else:
        desc = describe_all(tiles["reference"].astype(np.float32),
                            tiles["target"].astype(np.float32))
        np.savez_compressed(cache, X=desc, Xs=standardise(desc))
    Y = np.stack([desc[tiles["gene"] == g].mean(axis=0) for g in genes])

    # --- the registered fit, reproduced exactly -----------------------------
    train_genes = {t.gene for d in sample.values() for t in d["train"]}
    is_train = np.array([g in train_genes for g in genes])

    with np.load(D / "gene_blocks.npz", allow_pickle=False) as z:
        names = [str(g) for g in z["genes"]]
        sp = {g: v for g, v in zip(names, z["string_profile"], strict=True)}
    X = np.stack([sp[g] for g in genes])

    candidate_sets, comp_of_set = [], []
    for c in COMPARTMENTS:
        cands = [t.gene for t in sample[c]["held_out"] if t.gene in in_pool]
        if len(cands) >= 2:
            candidate_sets.append(cands)
            comp_of_set.append(c)

    comp_arr = np.array([comp_of[g] for g in genes])
    Xr = zscore(residualise_on_compartment(zscore(X, is_train), comp_arr, is_train), is_train)
    Yr = zscore(residualise_on_compartment(zscore(Y, is_train), comp_arr, is_train), is_train)
    fp, cfg = select_and_fit(Xr[is_train], Yr[is_train], GRID_X, GRID_Y,
                             GRID_RIDGE, N_COMPONENTS, FOLDS, args.seed)
    gte = genes[~is_train]

    by_c = defaultdict(list)
    for c, cands in zip(comp_of_set, candidate_sets, strict=True):
        rk = retrieve_in_shared_space(fp, Xr[~is_train], Yr[~is_train], gte, [cands])
        present = [g for g in cands if g in set(gte.tolist())]
        for r, g in zip(rk, present, strict=False):
            by_c[c].append((r, g))

    # --- the H6 label -------------------------------------------------------
    # gene of every ENSG in the pool, and its dominant compartment
    gene_of_ensg, comp_of_gene = {}, {}
    for c, d in sample.items():
        for key in ("train", "held_out"):
            for t in d[key]:
                gene_of_ensg[t.ensg] = t.gene
                comp_of_gene[t.gene] = c
    # sample.json was written before the pulldowns were fetched, so the partner
    # lists come from the interactome cache, keyed by pulldown id.
    store = json.loads((D / "interactomes.json").read_text())
    interactors = {}
    for c, d in sample.items():
        for key in ("train", "held_out"):
            for t in d[key]:
                rec = store.get(str(t.pulldown_id)) if t.pulldown_id else None
                interactors[t.gene] = list((rec or {}).get("partners") or [])

    partners_in_training = {}
    for g in gte.tolist():
        c = comp_of_gene[g]
        hits = []
        for ensg in interactors.get(g, []):
            p = gene_of_ensg.get(ensg)
            if p and p != g and p in train_genes and comp_of_gene.get(p) == c:
                hits.append(p)
        partners_in_training[g] = sorted(set(hits))

    groups = {"with_partner": [], "without_partner": []}
    per_comp_labels = {}
    for c, entries in by_c.items():
        labels = []
        for r, g in entries:
            key = "with_partner" if partners_in_training[g] else "without_partner"
            groups[key].append((r, g))
            labels.append(key == "with_partner")
        per_comp_labels[c] = (np.array(labels), entries)

    with_s = group_stats(groups["with_partner"], args.seed)
    without_s = group_stats(groups["without_partner"], args.seed)

    # --- the null: shuffle the label within compartment ---------------------
    rng = np.random.default_rng(args.seed)
    obs = with_s.get("lift", 0.0) - without_s.get("lift", 0.0)
    obs_mrr = with_s.get("mrr_ratio", 0.0) - without_s.get("mrr_ratio", 0.0)
    perm_lift = np.empty(args.permutations)
    perm_mrr = np.empty(args.permutations)
    for i in range(args.permutations):
        a, b = [], []
        for c, (labels, entries) in per_comp_labels.items():
            p = rng.permutation(labels.size)
            for j, idx in enumerate(p):
                (a if labels[j] else b).append(entries[idx])
        sa = group_stats(a, args.seed, interval=False)
        sb = group_stats(b, args.seed, interval=False)
        perm_lift[i] = sa.get("lift", 0.0) - sb.get("lift", 0.0)
        perm_mrr[i] = sa.get("mrr_ratio", 0.0) - sb.get("mrr_ratio", 0.0)

    result = {
        "config": cfg,
        "n_held_out": int(gte.size),
        "definition": "a measured OpenCell interaction partner, in the training "
                      "set, with the same dominant compartment",
        "with_partner": with_s,
        "without_partner": without_s,
        "lift_difference": obs,
        "lift_difference_p": float((perm_lift >= obs).mean()),
        "mrr_ratio_difference": obs_mrr,
        "mrr_ratio_difference_p": float((perm_mrr >= obs_mrr).mean()),
        "n_permutations": args.permutations,
        "partner_counts": {g: len(v) for g, v in sorted(partners_in_training.items())},
        "per_compartment": {
            c: {"with_partner": int(labels.sum()), "n": int(labels.size)}
            for c, (labels, _) in per_comp_labels.items()
        },
    }
    (D / "h6_mechanism.json").write_text(json.dumps(result, indent=1, default=float))

    print("=== H6: does a co-located training partner help? ===")
    print(f"{gte.size} held-out proteins: {with_s['n']} with a co-located "
          f"training partner, {without_s['n']} without")
    print(f"\n{'group':18s} {'n':>4s} {'top1':>6s} {'ct':>4s} {'chance':>7s} "
          f"{'lift':>6s} {'mrr/chance':>11s} {'mean rank':>10s}")
    for nm, s in (("with partner", with_s), ("without partner", without_s)):
        if not s["n"]:
            print(f"{nm:18s} {0:4d}  (empty group)")
            continue
        print(f"{nm:18s} {s['n']:4d} {s['top1']:6.3f} {s['top1_count']:4d} "
              f"{s['chance_top1']:7.3f} {s['lift']:6.2f}x {s['mrr_ratio']:11.3f} "
              f"{s['mean_rank']:10.2f}")
    print(f"\nlift difference {obs:+.3f}x, p = {result['lift_difference_p']:.4f}")
    print(f"MRR-ratio difference {obs_mrr:+.3f}, "
          f"p = {result['mrr_ratio_difference_p']:.4f}  "
          f"({args.permutations} label permutations)")
    print(f"\n{'compartment':14s} {'with':>5s} / {'n':<5s}")
    for c in COMPARTMENTS:
        if c in result["per_compartment"]:
            e = result["per_compartment"][c]
            print(f"{c:14s} {e['with_partner']:5d} / {e['n']:<5d}")
    print(f"\nwrote {D/'h6_mechanism.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
