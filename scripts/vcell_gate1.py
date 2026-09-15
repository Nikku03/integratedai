#!/usr/bin/env python3
"""Gate 1 of docs/PREREG_OPENCELL.md, and the plate-restricted batch control.

Both numbers were reported before this script existed -- `gate1.json` was
written by an ad-hoc run and the batch-control table in
`docs/RESULT_PROTEIN_DESCRIPTION.md` was transcribed from console output. This
is the producer for both, so they can be regenerated and checked.

Gate 1 asks whether the fixed 36-number descriptor tells proteins of the *same
compartment* apart, with no model and no fitting. The batch control asks the
same question with the candidate set restricted to proteins grown on one plate,
which is the strongest test of whether gate 1 is reading laboratory logistics
instead of the protein: two lines on the same plate were grown, sorted and
imaged alongside each other.

`well_id` is not testable. OpenCell grows one line per well, so well and protein
are perfectly confounded by design -- the script reports the confound rather
than pretending to control for it.

    python scripts/vcell_gate1.py --data-dir .vcell/oc_full \\
        --out data/vcell/opencell --prefix gate1_full_pool
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.descriptor import describe_all, standardise  # noqa: E402
from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.opencell import COMPARTMENTS, load_sample  # noqa: E402
from vcell.retrieval import (  # noqa: E402
    descriptor_retrieval,
    protein_clustered_bootstrap,
    retrieval_summary,
)


def owners_of(genes, fovs, cands):
    """The gene behind each rank `descriptor_retrieval` returns, in order.

    It iterates the tiles whose gene is a candidate and skips any tile with no
    other-field tile to compare against, so the alignment has to be rebuilt the
    same way rather than by truncating.
    """
    sel = np.flatnonzero(np.isin(genes, cands))
    if sel.size < 2:
        return []
    f = fovs[sel]
    return [str(genes[i]) for k, i in enumerate(sel) if (f != f[k]).any()]


def summarise(ranks, genes_of_rank, seed):
    s = retrieval_summary(ranks)
    hit = np.array([1.0 if r == 1 else 0.0 for r, n in ranks if r > 0 and n > 1])
    gn = np.array([g for (r, n), g in zip(ranks, genes_of_rank, strict=True)
                   if r > 0 and n > 1])
    ci = None
    if hit.size:
        _, lo, hi = protein_clustered_bootstrap(hit, gn, seed=seed)
        ci = [lo, hi]
    return s, ci


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--out", required=True)
    # The committed 8-way run lives under `gate1.json`; the full-pool re-run is
    # `gate1_full_pool.json`. Naming is the caller's so neither clobbers the other.
    ap.add_argument("--prefix", default="gate1")
    ap.add_argument("--seed", type=int, default=20260914)
    args = ap.parse_args()

    D, O = Path(args.data_dir), Path(args.out)
    O.mkdir(parents=True, exist_ok=True)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")

    cache = D / "descriptors.npz"
    if cache.exists():
        with np.load(cache) as z:
            desc = z["Xs"] if "Xs" in z else standardise(z["X"])
    else:
        X = describe_all(tiles["reference"].astype(np.float32),
                         tiles["target"].astype(np.float32))
        np.savez_compressed(cache, X=X, Xs=standardise(X))
        desc = standardise(X)

    genes, fovs = tiles["gene"], tiles["fov_id"]
    plate_of, well_of, comp_of = {}, {}, {}
    for c, d in sample.items():
        for key in ("train", "held_out"):
            for t in d[key]:
                plate_of[t.gene] = t.plate_id
                well_of[t.gene] = t.well_id
                comp_of[t.gene] = c

    # ---- gate 1 ----------------------------------------------------------
    gate1 = {}
    for c in COMPARTMENTS:
        cands = sorted({t.gene for k in ("train", "held_out")
                        for t in sample[c][k]} & set(genes.tolist()))
        if len(cands) < 2:
            continue
        ranks = descriptor_retrieval(desc, genes, fovs, cands)
        s, ci = summarise(ranks, owners_of(genes, fovs, cands), args.seed)
        gate1[c] = {"summary": s, "top1_ci": ci, "candidates": cands}

    # ---- the plate-restricted batch control ------------------------------
    rows, pooled_ranks, pooled_owners = [], [], []
    missing_plate = sorted(g for g in comp_of if not plate_of.get(g))
    by_plate = defaultdict(list)
    for g, p in plate_of.items():
        if p and g in set(genes.tolist()):
            by_plate[(comp_of[g], p)].append(g)
    for (c, plate), cands in sorted(by_plate.items(),
                                    key=lambda kv: (kv[0][0], kv[0][1])):
        cands = sorted(cands)
        if len(cands) < 2:
            continue
        ranks = descriptor_retrieval(desc, genes, fovs, cands)
        if not ranks:
            continue
        owners = owners_of(genes, fovs, cands)
        s, ci = summarise(ranks, owners, args.seed)
        rows.append({"compartment": c, "plate": plate, "candidates": len(cands),
                     "tiles": s["n"], "top1": s["top1"], "top1_ci": ci,
                     "chance": s["chance_top1"], "genes": cands})
        pooled_ranks.extend(ranks)
        pooled_owners.extend(owners)
    pooled, pooled_ci = summarise(pooled_ranks, pooled_owners, args.seed)

    pairs = {(plate_of[g], well_of[g]) for g in well_of
             if plate_of.get(g) and well_of.get(g)}
    control = {
        "per_plate": rows,
        "pooled": {"summary": pooled, "top1_ci": pooled_ci,
                   "n_proteins": len({g for r in rows for g in r["genes"]}),
                   "n_plates": len({r["plate"] for r in rows})},
        "well_confound": {
            "n_proteins_with_well": len(pairs and
                                        [g for g in well_of if well_of.get(g)]),
            "n_distinct_plate_well_pairs": len(pairs),
            "note": "one line per well, so (plate, well) and protein are "
                    "perfectly confounded by design -- as many distinct pairs "
                    "as proteins -- and cannot be controlled for here",
        },
        "proteins_without_plate_id": missing_plate,
    }

    (O / f"{args.prefix}.json").write_text(
        json.dumps(gate1, indent=1, default=float))
    (O / f"{args.prefix}_batch_control.json").write_text(
        json.dumps(control, indent=1, default=float))
    with open(O / "opencell_plate_well.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["gene", "compartment", "plate_id", "well_id"])
        for g in sorted(comp_of):
            w.writerow([g, comp_of[g], plate_of.get(g) or "",
                        well_of.get(g) or ""])

    print(f"{'compartment':14s} {'cands':>5s} {'tiles':>5s} {'top1':>6s} {'chance':>7s}")
    for c, e in gate1.items():
        s = e["summary"]
        print(f"{c:14s} {len(e['candidates']):5d} {s['n']:5d} "
              f"{s['top1']:6.3f} {s['chance_top1']:7.3f}")
    print(f"\nbatch control: {len(rows)} compartment/plate cells, "
          f"{control['pooled']['n_proteins']} proteins, "
          f"{control['pooled']['n_plates']} plates")
    print(f"{'compartment':14s} {'plate':>6s} {'cands':>5s} {'tiles':>5s} "
          f"{'top1':>6s} {'chance':>7s}")
    for r in sorted(rows, key=lambda r: -r["top1"]):
        print(f"{r['compartment']:14s} {r['plate']:>6s} {r['candidates']:5d} "
              f"{r['tiles']:5d} {r['top1']:6.3f} {r['chance']:7.3f}")
    ci = pooled_ci or [float('nan')] * 2
    print(f"\npooled top-1 {pooled['top1']:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]  "
          f"chance {pooled['chance_top1']:.3f}  n = {pooled['n']}")
    print(f"well confound: {control['well_confound']['n_proteins_with_well']} "
          f"proteins in "
          f"{control['well_confound']['n_distinct_plate_well_pairs']} "
          f"distinct (plate, well) pairs")
    if missing_plate:
        print(f"no plate id for {len(missing_plate)} proteins")
    print(f"\nwrote {O/(args.prefix + '.json')}, "
          f"{O/(args.prefix + '_batch_control.json')}, "
          f"{O/'opencell_plate_well.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
