"""What we are allowed to know about a protein without looking at its images.

The whole leave-one-structure-out test rests on this file. If protein identity
entered the model as a learned embedding indexed by cell line, then a held-out
line's embedding would be untrained noise and the "predict a structure you have
never seen" question would be meaningless -- the model would have no way to
represent the query. So identity enters as a **fixed vector built from public
annotation**: which compartments the protein is annotated to, how many
transmembrane passes it has, whether it polymerises, roughly how abundant it
is, and how big it is.

Sources, all annotation rather than imaging:

* Compartment assignments follow the GO cellular-component terms carried by
  each gene in UniProt, collapsed onto the 17 coarse compartments below. The
  structure each Allen cell line is *intended* to mark is documented at
  https://www.allencell.org/cell-catalog.html and in Roberts et al. (2017),
  Mol. Biol. Cell 28:2854 -- the gene-editing paper for these lines.
* `copies_per_cell` is an order-of-magnitude figure from whole-proteome
  quantification (PaxDb consensus / Itzhak et al. 2016, eLife 5:e16950). It is
  coarse-binned to a log10 decade on purpose: it is context, not a lever, and
  the study does not hinge on its accuracy to better than ~3x.
* `mw_kda` is the mature polypeptide mass from UniProt, not the glycosylated
  apparent mass.

An honest caveat, stated here rather than buried: a compartment annotation is
a *strong* prior. Telling the model "nuclear envelope" hands it most of the
answer to "which compartment", and the held-out-structure result has to be read
with that in mind. What annotation cannot hand over is where that compartment
sits in *this particular cell's* geometry, or what shape it takes there, and
that is what the metrics in `vcell.metrics` are built to isolate.

AAVS1 is the untagged safe-harbour control line: mEGFP inserted at the AAVS1
locus with no fusion partner, so its "structure" channel is freely diffusing
protein. It is the floor. Whatever score a structureless channel earns is the
score that means nothing was learned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# The 17 coarse compartments, in fixed order. Adding one changes the vector
# layout and therefore invalidates any trained checkpoint, so the order is
# frozen.
COMPARTMENTS: tuple[str, ...] = (
    "nucleoplasm",
    "chromatin",
    "nucleolus",
    "nuclear_envelope",
    "nuclear_pore",
    "nuclear_speckle",
    "cytosol",
    "actin_cytoskeleton",
    "microtubule",
    "centrosome",
    "endoplasmic_reticulum",
    "golgi",
    "mitochondrion",
    "endolysosome",
    "peroxisome",
    "plasma_membrane",
    "cell_junction",
)

SCALAR_FEATURES: tuple[str, ...] = (
    "n_transmembrane",
    "membrane_anchored",
    "polymer_forming",
    "log10_copies_per_cell",
    "mw_kda",
    "nucleic_acid_binding",
    "is_control",
)

KNOWLEDGE_DIM = len(COMPARTMENTS) + len(SCALAR_FEATURES)  # 24


@dataclass(frozen=True)
class ProteinRecord:
    """Annotation for one Allen cell line."""

    gene: str
    protein: str
    structure: str
    compartments: tuple[str, ...]
    n_transmembrane: int = 0
    membrane_anchored: bool = False
    polymer_forming: bool = False
    log10_copies_per_cell: float = 5.0
    mw_kda: float = 50.0
    nucleic_acid_binding: bool = False
    is_control: bool = False
    weights: dict[str, float] = field(default_factory=dict)

    def compartment_vector(self) -> np.ndarray:
        """Multi-hot over COMPARTMENTS, L1-normalised.

        `weights` lets an annotation say a protein is *mostly* somewhere --
        beta-catenin is a junctional protein that also has a cytosolic and a
        nuclear pool -- without pretending those pools are equal.
        """
        v = np.zeros(len(COMPARTMENTS), dtype=np.float32)
        for name in self.compartments:
            v[COMPARTMENTS.index(name)] = float(self.weights.get(name, 1.0))
        total = v.sum()
        return v / total if total > 0 else v

    def vector(self) -> np.ndarray:
        """The full fixed knowledge vector. Scalars are scaled to ~[0, 1]."""
        scalars = np.array(
            [
                np.log1p(self.n_transmembrane) / 2.5,
                float(self.membrane_anchored),
                float(self.polymer_forming),
                self.log10_copies_per_cell / 7.0,
                min(self.mw_kda, 400.0) / 400.0,
                float(self.nucleic_acid_binding),
                float(self.is_control),
            ],
            dtype=np.float32,
        )
        return np.concatenate([self.compartment_vector(), scalars])


# All 25 lines in the hiPSC single-cell image dataset, so the same conditioning
# scales from the five-structure proof of concept to the full collection without
# a change to the vector layout.
PROTEINS: dict[str, ProteinRecord] = {
    "ACTB": ProteinRecord(
        "ACTB", "beta-actin", "actin filaments",
        ("actin_cytoskeleton", "cytosol", "nucleoplasm"),
        polymer_forming=True, log10_copies_per_cell=7.0, mw_kda=42.0,
        weights={"actin_cytoskeleton": 3.0, "cytosol": 1.0, "nucleoplasm": 0.3},
    ),
    "TUBA1B": ProteinRecord(
        "TUBA1B", "alpha-tubulin", "microtubules",
        ("microtubule", "cytosol"),
        polymer_forming=True, log10_copies_per_cell=6.5, mw_kda=50.0,
        weights={"microtubule": 3.0, "cytosol": 1.0},
    ),
    "SEC61B": ProteinRecord(
        "SEC61B", "Sec61 subunit beta", "endoplasmic reticulum",
        ("endoplasmic_reticulum",),
        n_transmembrane=1, membrane_anchored=True,
        log10_copies_per_cell=5.3, mw_kda=10.0,
    ),
    "TOMM20": ProteinRecord(
        "TOMM20", "Tom20", "mitochondria",
        ("mitochondrion",),
        n_transmembrane=1, membrane_anchored=True,
        log10_copies_per_cell=5.5, mw_kda=16.0,
    ),
    "LMNB1": ProteinRecord(
        "LMNB1", "lamin B1", "nuclear envelope",
        ("nuclear_envelope",),
        membrane_anchored=True, polymer_forming=True,
        log10_copies_per_cell=5.7, mw_kda=66.0,
    ),
    "AAVS1": ProteinRecord(
        "AAVS1", "free mEGFP (safe-harbour control)", "none -- diffuse",
        ("cytosol", "nucleoplasm"),
        log10_copies_per_cell=6.0, mw_kda=27.0, is_control=True,
        weights={"cytosol": 2.0, "nucleoplasm": 1.0},
    ),
    "ATP2A2": ProteinRecord(
        "ATP2A2", "SERCA2", "endoplasmic reticulum",
        ("endoplasmic_reticulum",),
        n_transmembrane=10, membrane_anchored=True,
        log10_copies_per_cell=5.4, mw_kda=110.0,
    ),
    "ST6GAL1": ProteinRecord(
        "ST6GAL1", "sialyltransferase 1", "Golgi",
        ("golgi",),
        n_transmembrane=1, membrane_anchored=True,
        log10_copies_per_cell=4.7, mw_kda=47.0,
    ),
    "LAMP1": ProteinRecord(
        "LAMP1", "LAMP-1", "lysosomes",
        ("endolysosome",),
        n_transmembrane=1, membrane_anchored=True,
        log10_copies_per_cell=5.3, mw_kda=45.0,
    ),
    "RAB5A": ProteinRecord(
        "RAB5A", "Rab5a", "early endosomes",
        ("endolysosome", "cytosol", "plasma_membrane"),
        membrane_anchored=True, log10_copies_per_cell=5.1, mw_kda=24.0,
        weights={"endolysosome": 3.0, "cytosol": 1.0, "plasma_membrane": 0.5},
    ),
    "SLC25A17": ProteinRecord(
        "SLC25A17", "PMP34", "peroxisomes",
        ("peroxisome",),
        n_transmembrane=6, membrane_anchored=True,
        log10_copies_per_cell=4.3, mw_kda=34.0,
    ),
    "FBL": ProteinRecord(
        "FBL", "fibrillarin", "nucleolus (dense fibrillar component)",
        ("nucleolus",),
        log10_copies_per_cell=5.5, mw_kda=34.0, nucleic_acid_binding=True,
    ),
    "NPM1": ProteinRecord(
        "NPM1", "nucleophosmin", "nucleolus (granular component)",
        ("nucleolus", "nucleoplasm", "cytosol"),
        log10_copies_per_cell=6.3, mw_kda=33.0, nucleic_acid_binding=True,
        weights={"nucleolus": 3.0, "nucleoplasm": 1.0, "cytosol": 0.3},
    ),
    "SON": ProteinRecord(
        "SON", "SON", "nuclear speckles",
        ("nuclear_speckle", "nucleoplasm"),
        log10_copies_per_cell=4.9, mw_kda=264.0, nucleic_acid_binding=True,
        weights={"nuclear_speckle": 3.0, "nucleoplasm": 1.0},
    ),
    "HIST1H2BJ": ProteinRecord(
        "HIST1H2BJ", "histone H2B type 1-J", "chromatin",
        ("chromatin", "nucleoplasm"),
        log10_copies_per_cell=6.8, mw_kda=14.0, nucleic_acid_binding=True,
        weights={"chromatin": 3.0, "nucleoplasm": 1.0},
    ),
    "SMC1A": ProteinRecord(
        "SMC1A", "cohesin subunit SMC1A", "chromatin (cohesin)",
        ("chromatin", "nucleoplasm"),
        log10_copies_per_cell=5.2, mw_kda=143.0, nucleic_acid_binding=True,
        weights={"chromatin": 2.0, "nucleoplasm": 1.0},
    ),
    "NUP153": ProteinRecord(
        "NUP153", "nucleoporin 153", "nuclear pores",
        ("nuclear_pore", "nuclear_envelope", "nucleoplasm"),
        log10_copies_per_cell=4.7, mw_kda=154.0,
        weights={"nuclear_pore": 3.0, "nuclear_envelope": 1.0, "nucleoplasm": 0.5},
    ),
    "CETN2": ProteinRecord(
        "CETN2", "centrin-2", "centrioles",
        ("centrosome", "cytosol"),
        log10_copies_per_cell=4.6, mw_kda=20.0,
        weights={"centrosome": 4.0, "cytosol": 1.0},
    ),
    "ACTN1": ProteinRecord(
        "ACTN1", "alpha-actinin-1", "actin bundles",
        ("actin_cytoskeleton", "plasma_membrane", "cytosol"),
        log10_copies_per_cell=5.8, mw_kda=103.0,
        weights={"actin_cytoskeleton": 3.0, "plasma_membrane": 1.0, "cytosol": 1.0},
    ),
    "MYH10": ProteinRecord(
        "MYH10", "myosin IIB heavy chain", "actomyosin bundles",
        ("actin_cytoskeleton", "cytosol"),
        polymer_forming=True, log10_copies_per_cell=5.2, mw_kda=229.0,
        weights={"actin_cytoskeleton": 3.0, "cytosol": 1.0},
    ),
    "DSP": ProteinRecord(
        "DSP", "desmoplakin", "desmosomes",
        ("cell_junction", "plasma_membrane"),
        log10_copies_per_cell=4.8, mw_kda=332.0,
        weights={"cell_junction": 3.0, "plasma_membrane": 1.0},
    ),
    "GJA1": ProteinRecord(
        "GJA1", "connexin-43", "gap junctions",
        ("cell_junction", "plasma_membrane"),
        n_transmembrane=4, membrane_anchored=True,
        log10_copies_per_cell=4.9, mw_kda=43.0,
        weights={"cell_junction": 3.0, "plasma_membrane": 1.0},
    ),
    "TJP1": ProteinRecord(
        "TJP1", "ZO-1", "tight junctions",
        ("cell_junction", "plasma_membrane"),
        log10_copies_per_cell=5.1, mw_kda=195.0,
        weights={"cell_junction": 3.0, "plasma_membrane": 1.0},
    ),
    "CTNNB1": ProteinRecord(
        "CTNNB1", "beta-catenin", "adherens junctions",
        ("cell_junction", "plasma_membrane", "cytosol", "nucleoplasm"),
        log10_copies_per_cell=5.9, mw_kda=85.0,
        weights={"cell_junction": 3.0, "plasma_membrane": 1.0, "cytosol": 1.0,
                 "nucleoplasm": 0.5},
    ),
    "PXN": ProteinRecord(
        "PXN", "paxillin", "focal adhesions",
        ("cell_junction", "plasma_membrane", "cytosol"),
        log10_copies_per_cell=5.2, mw_kda=64.0,
        weights={"cell_junction": 3.0, "plasma_membrane": 1.0, "cytosol": 1.0},
    ),
}

# The five structures of the registered proof of concept, plus the control line
# that stays in training in every fold as the score floor.
POC_STRUCTURES: tuple[str, ...] = ("ACTB", "TUBA1B", "SEC61B", "TOMM20", "LMNB1")
CONTROL_STRUCTURE = "AAVS1"


def knowledge_vector(gene: str) -> np.ndarray:
    """The fixed 24-d annotation vector for one cell line."""
    try:
        return PROTEINS[gene].vector()
    except KeyError as exc:  # pragma: no cover - guards typos in configs
        raise KeyError(f"no annotation for {gene!r}; known: {sorted(PROTEINS)}") from exc


def knowledge_matrix(genes: list[str] | tuple[str, ...]) -> np.ndarray:
    return np.stack([knowledge_vector(g) for g in genes])
