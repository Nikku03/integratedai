#!/usr/bin/env python3
"""Run the registered OpenCell within-compartment discrimination protocol.

    python scripts/vcell_opencell.py --data-dir .vcell/oc --blocks all
    python scripts/vcell_opencell.py --data-dir .vcell/oc --blocks compartment

`--blocks compartment` is the registered null of H3: every candidate in a fold
then carries a byte-identical vector, so retrieval must land exactly at chance.
If it does not, the retrieval metric is broken and nothing else in the run means
anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.oc_frames import load_tiles  # noqa: E402
from vcell.oc_train import (  # noqa: E402
    build_vectors,
    model_retrieval,
    ridge_descriptor_retrieval,
    save_json,
    summarise_with_interval,
    train,
    training_families,
)
from vcell.opencell import COMPARTMENTS, KNOWLEDGE_BLOCKS, load_sample  # noqa: E402

# (blocks kept, compartment form). The "dominant" form one-hots only the sole
# highest-grade compartment, which is identical for every candidate in a fold.
# The "graded" form also encodes secondary annotations, which differ between
# candidates and are image-derived -- so a "compartment-only" run in the graded
# form is NOT a null, which is what the first pass of this study got wrong.
BLOCK_SETS = {
    "all": (KNOWLEDGE_BLOCKS, "graded"),
    "compartment": (("compartment",), "graded"),
    "compartment+abundance": (("compartment", "abundance"), "graded"),
    "compartment+protein": (("compartment", "protein"), "graded"),
    "compartment+interactome": (("compartment", "interactome"), "graded"),
    # The true null: every candidate gets a byte-identical vector.
    "dominant": (("compartment",), "dominant"),
    # The non-circular H1: nothing image-derived can distinguish the candidates.
    "noncircular": (KNOWLEDGE_BLOCKS, "dominant"),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    ap.add_argument("--blocks", default="all", choices=sorted(BLOCK_SETS))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--seed", type=int, default=20260914)
    ap.add_argument("--skip-ridge", action="store_true")
    args = ap.parse_args()

    D = Path(args.data_dir)
    tiles = load_tiles(D / "tiles.npz")
    sample = load_sample(D / "sample.json")
    families = training_families(sample)
    blocks, compartment_form = BLOCK_SETS[args.blocks]
    vectors = build_vectors(sample, families, blocks=blocks,
                            compartment_form=compartment_form)
    distinct = len({tuple(np.round(v, 5)) for v in vectors.values()})
    print(f"compartment form: {compartment_form}; "
          f"{distinct} distinct vectors over {len(vectors)} proteins")
    cond_dim = len(next(iter(vectors.values())))

    present = set(tiles["gene"].tolist())
    train_genes = [t.gene for d in sample.values() for t in d["train"] if t.gene in present]
    train_rows = np.flatnonzero(np.isin(tiles["gene"], train_genes))
    print(f"blocks={args.blocks} ({', '.join(blocks)}) cond_dim={cond_dim}")
    print(f"{train_rows.size} training tiles from {len(train_genes)} proteins; "
          f"{tiles['target'].shape[0] - train_rows.size} held-out tiles")

    model = train(tiles, train_rows, vectors, cond_dim, args.epochs, args.batch_size,
                  args.seed, threads=args.threads, log_prefix=f"[{args.blocks}] ")
    out_dir = D / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_dir / f"model_{args.blocks}.pt")

    descriptors = None
    if not args.skip_ridge and (D / "descriptors.npz").exists():
        with np.load(D / "descriptors.npz") as z:
            descriptors = z["Xs"]

    results = {}
    print(f"\n{'compartment':14s} {'cands':>5s} {'tiles':>6s} {'model top1':>22s} "
          f"{'chance':>7s} {'MRR':>6s} {'mismatched ref':>15s} {'ridge top1':>11s}")
    for c in COMPARTMENTS:
        cands = [t.gene for t in sample[c]["held_out"] if t.gene in present]
        if len(cands) < 2:
            continue
        rows = np.flatnonzero(np.isin(tiles["gene"], cands))
        ranks, records = model_retrieval(model, tiles, rows, cands, vectors, seed=args.seed)
        genes = [r["gene"] for r in records]
        s = summarise_with_interval(ranks, genes, seed=args.seed)

        mranks, mrecords = model_retrieval(model, tiles, rows, cands, vectors,
                                           mismatch_reference=True, seed=args.seed)
        ms = summarise_with_interval(mranks, [r["gene"] for r in mrecords], seed=args.seed)

        rs = {}
        if descriptors is not None:
            rranks = ridge_descriptor_retrieval(descriptors, tiles, train_rows, rows,
                                                cands, vectors)
            rs = summarise_with_interval(
                rranks, [str(tiles["gene"][r]) for r in rows], seed=args.seed)

        results[c] = {"candidates": cands, "model": s, "mismatched_reference": ms,
                      "ridge_descriptor": rs, "records": records}
        print(f"{c:14s} {len(cands):5d} {s['n']:6d} {s['top1']:7.3f} "
              f"[{s['top1_lo']:.3f},{s['top1_hi']:.3f}] {s['chance_top1']:7.3f} "
              f"{s['mrr']:6.3f} {ms['top1']:15.3f} "
              f"{(rs.get('top1', float('nan'))):11.3f}")

    save_json({"blocks": list(blocks), "compartment_form": compartment_form,
               "cond_dim": cond_dim,
               "n_train_tiles": int(train_rows.size), "results": results},
              out_dir / f"retrieval_{args.blocks}.json")
    print(f"\nwrote {out_dir/f'retrieval_{args.blocks}.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
