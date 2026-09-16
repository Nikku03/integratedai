#!/usr/bin/env python3
"""Biophysical fingerprints for the 25 Allen tagged lines.

`scripts/vcell_biophysics.py` builds these for an OpenCell sample, where the
accessions already exist in `uniprot.json`. The Allen lines have no such file,
so this resolves gene -> reviewed human accession against UniProt first, then
reuses the same AlphaFold fetch and the same 20-number fingerprint.

AAVS1 is the safe-harbour control locus, not a protein, and is expected to
resolve to nothing. That is the correct answer for it.

    python scripts/vcell_allen_biophysics.py --out data/vcell --cache .vcell/af_allen
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from vcell_biophysics import fetch_one  # noqa: E402

from vcell.biophysics import describe_protein, split_blocks  # noqa: E402
from vcell.knowledge import PROTEINS  # noqa: E402

UNIPROT = "https://rest.uniprot.org/uniprotkb/search"

# Column names for the 20 numbers `describe_protein` returns, in its order.
COLUMNS = [
    "rg_over_50", "rh_over_60", "dmax_over_200", "asphericity", "anisotropy",
    "axial_ratio_over_8", "perrin_friction", "compactness_vs_globular",
    "elongation_over_6", "log1p_n_over_8",
    "diffusion_relative", "log10_diffusion_over_2",
    "net_charge_over_50", "charge_per_residue", "isoelectric_over_14",
    "surface_charge_over_40", "surface_charge_per_exposed", "dipole_over_500",
    "exposed_kr_fraction", "exposed_de_fraction",
]
# The scale each column was divided by in `describe_protein`, so the CSV can
# carry physical units rather than the model's normalised numbers.
PHYSICAL = {
    "rg_angstrom": ("rg_over_50", 50.0),
    "rh_angstrom": ("rh_over_60", 60.0),
    "dmax_angstrom": ("dmax_over_200", 200.0),
    "axial_ratio": ("axial_ratio_over_8", 8.0),
    "n_residues_est": ("log1p_n_over_8", None),
    "net_charge": ("net_charge_over_50", 50.0),
    "isoelectric_point": ("isoelectric_over_14", 14.0),
    "surface_charge": ("surface_charge_over_40", 40.0),
    "charge_dipole": ("dipole_over_500", 500.0),
}


def resolve(gene: str) -> str | None:
    """The reviewed human accession for a gene symbol, or None."""
    for query in (f"gene_exact:{gene} AND organism_id:9606 AND reviewed:true",
                  f"gene:{gene} AND organism_id:9606 AND reviewed:true"):
        try:
            r = requests.get(UNIPROT, timeout=60, params={
                "query": query, "fields": "accession,gene_primary",
                "format": "json", "size": 5})
            r.raise_for_status()
            hits = r.json().get("results") or []
        except Exception as exc:
            print(f"  {gene}: uniprot query failed ({exc})", flush=True)
            return None
        for h in hits:
            names = {(g.get("geneName") or {}).get("value") for g in h.get("genes") or []}
            if gene in names:
                return h["primaryAccession"]
        if hits:
            return hits[0]["primaryAccession"]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    args = ap.parse_args()

    O, C = Path(args.out), Path(args.cache)
    O.mkdir(parents=True, exist_ok=True)
    C.mkdir(parents=True, exist_ok=True)

    genes = sorted(PROTEINS)
    acc_path = O / "allen_accessions.json"
    accessions = json.loads(acc_path.read_text()) if acc_path.exists() else {}
    for g in genes:
        if g in accessions:
            continue
        accessions[g] = resolve(g)
        print(f"  {g} -> {accessions[g]}", flush=True)
    acc_path.write_text(json.dumps(accessions, indent=1, sort_keys=True))

    rows, vectors, ok = [], {}, []
    for g in genes:
        acc = accessions.get(g)
        if not acc:
            print(f"{g}: no accession (expected for AAVS1)", flush=True)
            continue
        pdb = fetch_one(acc, C)
        if pdb is None:
            print(f"{g}: no AlphaFold model for {acc}", flush=True)
            continue
        v = describe_protein(pdb)
        if v is None:
            print(f"{g}: model unusable", flush=True)
            continue
        vectors[g] = v
        ok.append(g)
        d = dict(zip(COLUMNS, [float(x) for x in v], strict=True))
        row = {"gene": g, "accession": acc}
        for name, (col, scale) in PHYSICAL.items():
            row[name] = (round(float(np.expm1(d[col] * 8.0)))
                         if scale is None else round(d[col] * scale, 3))
        row["perrin_friction"] = round(d["perrin_friction"], 4)
        row["compactness_vs_globular"] = round(d["compactness_vs_globular"], 4)
        row["diffusion_relative"] = round(d["diffusion_relative"], 4)
        rows.append(row)

    if not rows:
        print("nothing described")
        return 1
    with open(O / "allen_biophysics.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: r["gene"]))
    X = np.stack([vectors[g] for g in ok])
    np.savez_compressed(O / "allen_biophysics.npz", genes=np.array(ok),
                        **split_blocks(X), biophysics=X)

    print(f"\n{len(ok)} of {len(genes)} Allen lines described")
    print(f"{'gene':12s} {'acc':>8s} {'Rg A':>7s} {'axial':>6s} "
          f"{'D rel':>6s} {'pI':>5s}")
    for r in sorted(rows, key=lambda r: -r["diffusion_relative"]):
        print(f"{r['gene']:12s} {r['accession']:>8s} {r['rg_angstrom']:7.1f} "
              f"{r['axial_ratio']:6.2f} {r['diffusion_relative']:6.3f} "
              f"{r['isoelectric_point']:5.2f}")
    print(f"\nwrote {O/'allen_biophysics.csv'}, {O/'allen_biophysics.npz'}, "
          f"{acc_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
