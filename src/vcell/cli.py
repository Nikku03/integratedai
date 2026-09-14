"""`vcell` -- the virtual-cell proof of concept.

    vcell prepare  --data-dir DIR      # manifest + fetch + frame the registered sample
    vcell train    --data-dir DIR      # the full registered protocol, all folds
    vcell demo                         # synthetic world, known ground truth, no network
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vcell.knowledge import CONTROL_STRUCTURE, POC_STRUCTURES

DEFAULT_DATA_DIR = Path(".vcell")
SEED = 20260914


def _genes(args: argparse.Namespace) -> list[str]:
    return list(args.structures.split(",")) if args.structures else [
        *POC_STRUCTURES,
        CONTROL_STRUCTURE,
    ]


def cmd_prepare(args: argparse.Namespace) -> int:
    from vcell.fetch import fetch_frames
    from vcell.manifest import (
        METADATA_URL,
        distil_metadata,
        read_manifest,
        sample_cells,
        write_manifest,
    )

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    genes = _genes(args)
    distilled = data_dir / f"cells_{args.tag}.csv" if args.tag else data_dir / "cells_all.csv"

    if not distilled.exists():
        metadata = Path(args.metadata or (data_dir / "metadata.csv"))
        if not metadata.exists():
            print(f"metadata.csv not found at {metadata}.")
            print(f"  curl -o {metadata} {METADATA_URL}    # 1.7 GB")
            return 2
        print(f"distilling {metadata} -> {distilled}")
        kept = distil_metadata(metadata, distilled, genes=set(genes))
        print(f"  {kept} rows for {len(genes)} lines")

    tag = f"{args.tag}_" if args.tag else ""
    for split in ("interphase", "mitotic"):
        manifest = data_dir / f"manifest_{tag}{split}.csv"
        frames = data_dir / f"frames_{tag}{split}.npz"
        if frames.exists() and not args.force:
            print(f"{frames} exists; skipping (use --force to refetch)")
            continue
        if not manifest.exists() or args.force:
            inter, mito = sample_cells(distilled, genes, args.cells, args.mitotic, SEED)
            write_manifest(inter, data_dir / f"manifest_{tag}interphase.csv")
            write_manifest(mito, data_dir / f"manifest_{tag}mitotic.csv")
        cells = read_manifest(manifest)
        fovs = len({c.fov_id for c in cells})
        print(f"{split}: {len(cells)} cells over {fovs} fields of view "
              f"(~{len(cells)*28.5/1024:.1f} GB to download, ~{len(cells)*0.2:.0f} MB kept)")
        counts = fetch_frames(cells, frames, workers=args.workers)
        print(f"  wrote {frames}: " + ", ".join(f"{g}={n}" for g, n in sorted(counts.items())))
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    from vcell.train import run_protocol

    return run_protocol(
        data_dir=Path(args.data_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        folds=args.folds.split(",") if args.folds else None,
        out_dir=Path(args.out or (Path(args.data_dir) / "results")),
        seed=SEED,
        threads=args.threads,
    )


def cmd_demo(args: argparse.Namespace) -> int:
    from vcell.demo import run_demo

    return run_demo(epochs=args.epochs, seed=SEED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vcell", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="fetch and frame the registered cell sample")
    prep.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    prep.add_argument("--metadata", default=None, help="path to Allen metadata.csv")
    prep.add_argument("--structures", default=None, help="comma-separated gene list")
    prep.add_argument("--cells", type=int, default=80, help="interphase cells per line")
    prep.add_argument("--mitotic", type=int, default=20, help="mitotic cells per line")
    prep.add_argument("--workers", type=int, default=4)
    prep.add_argument("--tag", default=None,
                      help="name this sample, e.g. --tag extended (keeps files separate)")
    prep.add_argument("--force", action="store_true")
    prep.set_defaults(func=cmd_prepare)

    tr = sub.add_parser("train", help="run the registered protocol")
    tr.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    tr.add_argument("--epochs", type=int, default=25)
    tr.add_argument("--batch-size", type=int, default=4)
    tr.add_argument("--folds", default=None, help="subset of folds, e.g. LMNB1,TOMM20")
    tr.add_argument("--out", default=None)
    tr.add_argument("--threads", type=int, default=4)
    tr.set_defaults(func=cmd_train)

    dm = sub.add_parser("demo", help="synthetic world with known ground truth, no network")
    dm.add_argument("--epochs", type=int, default=12)
    dm.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
