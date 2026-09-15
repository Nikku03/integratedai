#!/usr/bin/env python3
"""Fetch AlphaFold models for a sample and build the biophysical fingerprint.

Size, shape, surface charge, and the diffusion coefficient Stokes-Einstein
implies from them -- see `vcell.biophysics` for the physics and its limits.

    python scripts/vcell_biophysics.py --data-dir .vcell/oc_full
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.biophysics import BIOPHYSICS_DIM, describe_protein, split_blocks  # noqa: E402


def fetch_one(acc: str, cache: Path) -> Path | None:
    dest = cache / f"{acc}.pdb"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    url = None
    for wait in (0, 2, 5):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(f"https://alphafold.ebi.ac.uk/api/prediction/{acc}",
                             timeout=90)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            entries = r.json()
            if entries:
                url = entries[0].get("pdbUrl")
            break
        except Exception:
            continue
    if not url:
        return None
    for wait in (0, 2, 5):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, timeout=150)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--cache", default=None)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    D = Path(args.data_dir)
    cache = Path(args.cache or (D.parent / "gene_data" / "af"))
    cache.mkdir(parents=True, exist_ok=True)
    accessions = json.loads((D / "accessions.json").read_text())
    genes = sorted(accessions)
    print(f"{len(genes)} proteins; {len(list(cache.glob('*.pdb')))} structures cached")

    def job(gene: str):
        return gene, fetch_one(accessions[gene], cache)

    paths: dict[str, Path | None] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        for i, (gene, path) in enumerate(ex.map(job, genes), start=1):
            paths[gene] = path
            if i % 50 == 0:
                print(f"  {i}/{len(genes)}", flush=True)
    missing = [g for g, p in paths.items() if p is None]
    print(f"structures: {len(genes)-len(missing)}/{len(genes)} available"
          + (f"; missing {missing[:6]}{'...' if len(missing) > 6 else ''}"
             if missing else ""))

    vectors, failed = {}, []
    for gene, path in paths.items():
        v = describe_protein(path) if path else None
        if v is None or not np.isfinite(v).all():
            failed.append(gene)
            vectors[gene] = np.zeros(BIOPHYSICS_DIM, dtype=np.float32)
        else:
            vectors[gene] = v
    print(f"described {len(genes)-len(failed)}/{len(genes)}"
          + (f"; unusable models zeroed: {len(failed)}" if failed else ""))

    order = sorted(vectors)
    full = np.stack([vectors[g] for g in order])
    sub = {name: np.stack([split_blocks(vectors[g])[name] for g in order])
           for name in ("shape", "diffusion", "charge")}
    out = D / "biophysics.npz"
    np.savez_compressed(out, genes=np.array(order), biophysics=full,
                        **{f"bio_{k}": v for k, v in sub.items()})
    print(f"\nwrote {out}")
    print(f"  biophysics      {full.shape[1]:3d} dims")
    for k, v in sub.items():
        print(f"  bio_{k:11s} {v.shape[1]:3d} dims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
