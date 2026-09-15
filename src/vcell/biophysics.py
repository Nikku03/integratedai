"""Size, shape and charge from the predicted structure -- and the diffusion
coefficient they imply.

Every description tried so far has been *informational* -- what a protein is
annotated to do, who it binds, what its sequence looks like. This one is
**physical**: a protein's translational diffusion coefficient follows from its
hydrodynamic radius and its shape by Stokes-Einstein,

    D = kT / (6 pi eta R_h F)

where `F` is the Perrin friction factor for a non-spherical body, and how a
protein partitions in a crowded, membrane-filled interior depends on its
exposed surface charge. Two proteins in the same compartment that diffuse at
different rates and carry different surface charge have a physical reason to end
up distributed differently, which is a mechanism rather than a correlation.

Computed from the AlphaFold model plus the sequence, so nothing here comes from
a micrograph.

**Shape** comes from the gyration tensor of the C-alpha trace. Its eigenvalues
give the radius of gyration, the asphericity, the relative shape anisotropy
(0 for a sphere, 1 for a rod) and an axial ratio, and the axial ratio gives the
Perrin factor.

**Charge** is computed twice: over the whole sequence, and over the *solvent-
exposed* residues only, since buried charges do not meet the cytoplasm.
Exposure is approximated by C-alpha neighbour count, which is the standard cheap
proxy for relative solvent accessibility. The charge *dipole* is included
separately -- a protein with its positives on one face behaves differently from
one with them spread evenly, at the same net charge.

Three honest limits, since this block is physically motivated and therefore
easy to over-trust:

* AlphaFold predicts the **monomer**. A protein that works as part of a complex
  has a far larger true hydrodynamic radius than its monomer implies.
* Intrinsically disordered proteins get unreliable models. That is partly
  self-reporting -- low pLDDT travels with an extended, slowly-diffusing chain --
  but the geometry of such a model is not a real conformation.
* Diffusion in cytoplasm is anomalous and crowding-dependent, not
  Stokes-Einstein. The *ordering* by size and shape survives that; the absolute
  coefficient does not, which is why everything here is reported as a relative
  quantity.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

# Charge at pH 7.4: fully ionised approximation for the strong groups, with
# histidine partly protonated.
CHARGE = {"K": 1.0, "R": 1.0, "H": 0.1, "D": -1.0, "E": -1.0}
# pKa values for the proper isoelectric-point calculation.
PKA_POS = {"K": 10.5, "R": 12.5, "H": 6.0, "N_TERM": 9.6}
PKA_NEG = {"D": 3.9, "E": 4.3, "C": 8.3, "Y": 10.1, "C_TERM": 2.3}

NEIGHBOUR_RADIUS = 10.0     # angstroms, for the exposure proxy
EXPOSED_PERCENTILE = 40.0   # residues below this neighbour-count percentile
RH_OVER_RG = 1.29           # empirical, compact globular proteins

BIOPHYSICS_DIM = 20


def parse_ca_trace(pdb_path: Path) -> tuple[np.ndarray, list[str], np.ndarray]:
    """(coordinates, one-letter residues, pLDDT) for the C-alpha atoms."""
    three_to_one = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C", "GLN": "Q",
        "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I", "LEU": "L", "LYS": "K",
        "MET": "M", "PHE": "F", "PRO": "P", "SER": "S", "THR": "T", "TRP": "W",
        "TYR": "Y", "VAL": "V",
    }
    coords, residues, plddt = [], [], []
    for line in pdb_path.read_text().splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        try:
            coords.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
            plddt.append(float(line[60:66]))
        except ValueError:
            continue
        residues.append(three_to_one.get(line[17:20].strip(), "X"))
    return (np.array(coords, dtype=np.float64), residues,
            np.array(plddt, dtype=np.float64))


def gyration_shape(coords: np.ndarray) -> dict[str, float]:
    """Radius of gyration and shape descriptors from the gyration tensor."""
    if coords.shape[0] < 3:
        return {"rg": float("nan"), "asphericity": float("nan"),
                "anisotropy": float("nan"), "axial_ratio": 1.0,
                "dmax": float("nan")}
    centred = coords - coords.mean(axis=0)
    tensor = (centred.T @ centred) / centred.shape[0]
    vals = np.sort(np.linalg.eigvalsh(tensor))          # l1 <= l2 <= l3
    vals = np.clip(vals, 1e-9, None)
    rg2 = float(vals.sum())
    b = float(vals[2] - 0.5 * (vals[0] + vals[1]))       # asphericity
    c = float(vals[1] - vals[0])                         # acylindricity
    kappa2 = (b**2 + 0.75 * c**2) / (rg2**2) if rg2 > 0 else 0.0
    # Sample Dmax on a subset: the full pairwise matrix is wasteful for long chains.
    idx = (np.linspace(0, coords.shape[0] - 1, min(coords.shape[0], 300))
           .astype(int))
    sub = coords[idx]
    dmax = float(np.sqrt(((sub[:, None] - sub[None, :]) ** 2).sum(-1)).max())
    return {
        "rg": math.sqrt(rg2),
        "asphericity": b / rg2 if rg2 > 0 else 0.0,
        "anisotropy": float(np.clip(kappa2, 0.0, 1.0)),
        "axial_ratio": float(math.sqrt(vals[2] / vals[0])),
        "dmax": dmax,
    }


def perrin_friction(axial_ratio: float) -> float:
    """Translational friction factor of a prolate spheroid, relative to a sphere
    of equal volume (Perrin, 1936).

    Tends to 1 as the axial ratio tends to 1, and grows slowly with elongation;
    a 5:1 rod diffuses roughly 15% slower than a sphere of the same volume. The
    prolate form is used for every protein, which is an approximation for the
    oblate ones -- the friction penalty is similar in magnitude and the ordering
    is what this feature contributes.
    """
    p = max(float(axial_ratio), 1.0 + 1e-9)
    root = math.sqrt(p * p - 1.0)
    return root / (p ** (1.0 / 3.0) * math.log(p + root))


def isoelectric_point(residues: list[str]) -> float:
    """pI by bisection on the Henderson-Hasselbalch net-charge curve."""
    counts = {a: residues.count(a) for a in set(residues)}

    def net(ph: float) -> float:
        q = 1.0 / (1.0 + 10 ** (ph - PKA_POS["N_TERM"]))
        q -= 1.0 / (1.0 + 10 ** (PKA_NEG["C_TERM"] - ph))
        for aa, pka in (("K", PKA_POS["K"]), ("R", PKA_POS["R"]),
                        ("H", PKA_POS["H"])):
            q += counts.get(aa, 0) / (1.0 + 10 ** (ph - pka))
        for aa, pka in (("D", PKA_NEG["D"]), ("E", PKA_NEG["E"]),
                        ("C", PKA_NEG["C"]), ("Y", PKA_NEG["Y"])):
            q -= counts.get(aa, 0) / (1.0 + 10 ** (pka - ph))
        return q

    lo, hi = 0.0, 14.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if net(mid) > 0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def exposure_mask(coords: np.ndarray) -> np.ndarray:
    """Solvent-exposed residues, by C-alpha neighbour count."""
    if coords.shape[0] < 5:
        return np.ones(coords.shape[0], dtype=bool)
    d2 = ((coords[:, None] - coords[None, :]) ** 2).sum(-1)
    neighbours = (d2 < NEIGHBOUR_RADIUS**2).sum(axis=1) - 1
    return neighbours <= np.percentile(neighbours, EXPOSED_PERCENTILE)


def describe_protein(pdb_path: Path) -> np.ndarray | None:
    """The 20-number biophysical fingerprint, or None if the model is unusable."""
    coords, residues, plddt = parse_ca_trace(pdb_path)
    n = coords.shape[0]
    if n < 10:
        return None
    shape = gyration_shape(coords)
    rg = shape["rg"]
    friction = perrin_friction(shape["axial_ratio"])
    r_h = RH_OVER_RG * rg
    # Stokes-Einstein, relative: D ∝ 1 / (R_h * F). Scaled by the value a
    # 30 kDa globular protein would give, so the number reads as a ratio.
    d_rel = 1.0 / max(r_h * friction, 1e-9) * 20.0
    # How compact is it, against the globular expectation Rg ≈ 2.2 * N^0.38 Å.
    rg_globular = 2.2 * n**0.38
    charges = np.array([CHARGE.get(a, 0.0) for a in residues])
    exposed = exposure_mask(coords)
    surface_charge = float(charges[exposed].sum())
    centred = coords - coords.mean(axis=0)
    dipole = float(np.linalg.norm((charges[:, None] * centred).sum(axis=0)))
    n_exposed = max(int(exposed.sum()), 1)
    return np.array([
        # size and shape
        rg / 50.0,
        r_h / 60.0,
        shape["dmax"] / 200.0,
        shape["asphericity"],
        shape["anisotropy"],
        min(shape["axial_ratio"], 8.0) / 8.0,
        friction,
        rg / max(rg_globular, 1e-9),                 # >1 means extended
        (shape["dmax"] / max(rg, 1e-9)) / 6.0,       # elongation, shape-only
        np.log1p(n) / 8.0,
        # the diffusion coefficient those imply
        d_rel,
        math.log10(max(d_rel, 1e-6)) / 2.0,
        # charge
        float(charges.sum()) / 50.0,
        float(charges.sum()) / n,
        isoelectric_point(residues) / 14.0,
        surface_charge / 40.0,
        surface_charge / n_exposed,
        dipole / 500.0,
        float(np.array([1.0 if a in "KR" else 0.0 for a in residues])[exposed].mean()),
        float(np.array([1.0 if a in "DE" else 0.0 for a in residues])[exposed].mean()),
    ], dtype=np.float32)


def split_blocks(vector: np.ndarray) -> dict[str, np.ndarray]:
    """The three physically distinct sub-blocks, so each can be tested alone."""
    return {
        "shape": vector[:10],
        "diffusion": vector[10:12],
        "charge": vector[12:20],
    }
