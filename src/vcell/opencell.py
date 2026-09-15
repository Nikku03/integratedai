"""OpenCell: 1,310 tagged human proteins, and the within-compartment question.

The previous study (`docs/RESULT_VIRTUAL_CELL.md`) could not separate "which
protein" from "which compartment", because at five structures each compartment
had exactly one cell line. This module builds the sample where they come apart:
seven compartments with 24 proteins each, 16 of them in training and 8 held out
as the candidate set a retrieval has to choose between.

Two things here are worth reading closely.

**Compartment membership is the protein's *sole* highest-grade annotation.** A
protein annotated `er_3` and `vesicles_3` belongs to neither set, because a
protein that appears in two candidate sets makes "the right answer" ambiguous.

**The knowledge vector's compartment block is deliberately useless for the
test.** Every candidate in a fold carries the same compartment label, so that
block contributes nothing to a ranking — which is exactly what makes this test
immune to the circularity that OpenCell's annotations would otherwise introduce,
since those annotations were read off OpenCell's own microscopy. All
discrimination has to come from abundance, protein properties, and the
mass-spectrometry interactome, none of which is image-derived.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import requests

API = "https://opencell.sf.czbiohub.org/api"
S3 = "https://czb-opencell.s3.amazonaws.com"

# OpenCell's own QC flags. 410 of the 1,310 lines carry at least one.
QC_FLAGS = frozenset(
    {"low_gfp", "low_hdr", "heterogeneous_gfp", "disk_artifact", "re_image",
     "salvageable_re_sort"}
)

# Every compartment with >= 24 sole-dominant proteins after QC. Frozen: the
# order fixes the knowledge vector layout.
COMPARTMENTS: tuple[str, ...] = (
    "cytoplasmic",
    "nucleoplasm",
    "vesicles",
    "er",
    "nucleolus_gc",
    "chromatin",
    "membrane",
)

# Minor compartments kept as conditioning features but never used as candidate
# sets -- a protein's secondary localisations are real information about it.
MINOR_COMPARTMENTS: tuple[str, ...] = (
    "golgi", "nuclear_punctae", "centrosome", "cytoskeleton", "cell_contact",
    "nuclear_membrane", "nucleolus_fc_dfc", "mitochondria", "focal_adhesions",
    "big_aggregates", "small_aggregates", "cilia",
)

ALL_COMPARTMENTS = COMPARTMENTS + MINOR_COMPARTMENTS
GRADED = re.compile(r"^(?P<name>.+)_(?P<grade>[123])$")

N_INTERACTOME_HASH = 8  # fixed random projection of the partner-gene set
KNOWLEDGE_BLOCKS = ("compartment", "abundance", "protein", "interactome")


@dataclass
class Target:
    """One OpenCell cell line, with everything known about it that is not an image."""

    gene: str
    ensg: str
    cell_line_id: int
    compartment: str
    grades: dict[str, int]
    family: str | None = None
    terminus: str | None = None
    protein_copy_number: float | None = None
    protein_concentration: float | None = None
    rna_abundance: float | None = None
    n_fovs: int = 0
    pulldown_id: int | None = None
    interactors: list[str] = field(default_factory=list)
    interactor_enrichment: float | None = None
    interactor_stoich: float | None = None

    @property
    def s3_prefix(self) -> str:
        return f"microscopy/raw/{self.gene}_{self.ensg}"


def _get(url: str, timeout: int = 120, retries: tuple[int, ...] = (2, 4, 8, 16)):
    last: Exception | None = None
    for attempt, wait in enumerate((0, *retries)):
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - retry anything transport-shaped
            last = exc
            if attempt == len(retries):
                break
    raise RuntimeError(f"GET {url} failed: {last}")


def fetch_catalogue(cache: Path) -> list[dict]:
    """The whole /api/lines dump, cached on disk."""
    if cache.exists():
        return json.loads(cache.read_text())
    lines = _get(f"{API}/lines")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(lines))
    return lines


def parse_grades(categories: list[str]) -> dict[str, int]:
    """`['er_3', 'vesicles_2']` -> `{'er': 3, 'vesicles': 2}`."""
    out: dict[str, int] = {}
    for c in categories:
        m = GRADED.match(c)
        if m:
            name = m.group("name")
            out[name] = max(out.get(name, 0), int(m.group("grade")))
    return out


def sole_dominant(grades: dict[str, int]) -> str | None:
    """The compartment at the protein's top grade, if there is exactly one."""
    if not grades:
        return None
    top = max(grades.values())
    winners = [c for c, g in grades.items() if g == top]
    return winners[0] if len(winners) == 1 else None


def build_targets(catalogue: list[dict]) -> list[Target]:
    """QC-filtered, sole-dominant-assigned targets in the seven compartments."""
    out = []
    for line in catalogue:
        ann = line.get("annotation") or {}
        cats = list(ann.get("categories") or [])
        if QC_FLAGS.intersection(cats):
            continue
        grades = parse_grades(cats)
        compartment = sole_dominant(grades)
        if compartment not in COMPARTMENTS:
            continue
        md = line.get("metadata") or {}
        up = line.get("uniprot_metadata") or {}
        ab = line.get("abundance_data") or {}
        fc = line.get("fov_counts") or {}
        bp = line.get("best_pulldown") or {}
        gene = up.get("gene_name") or md.get("target_name")
        ensg = md.get("ensg_id")
        if not gene or not ensg:
            continue
        out.append(Target(
            gene=gene, ensg=ensg, cell_line_id=md.get("cell_line_id"),
            compartment=compartment, grades=grades,
            family=md.get("target_family"), terminus=md.get("target_terminus"),
            protein_copy_number=ab.get("protein_copy_number"),
            protein_concentration=ab.get("protein_concentration"),
            rna_abundance=ab.get("rna_abundance"),
            n_fovs=int(fc.get("num_fovs") or 0),
            pulldown_id=bp.get("id"),
        ))
    return out


def attach_interactome(targets: list[Target], cache: Path) -> None:
    """Fill in each target's significant interaction partners, from mass spec.

    Measured by pulldown, not read off an image, so it is legitimate prior
    knowledge about a protein whose images are held out.
    """
    store: dict[str, dict] = json.loads(cache.read_text()) if cache.exists() else {}
    changed = False
    for i, t in enumerate(targets, start=1):
        if t.pulldown_id is None:
            continue
        key = str(t.pulldown_id)
        if key not in store:
            try:
                hits = _get(f"{API}/pulldowns/{t.pulldown_id}/hits")
            except RuntimeError as exc:
                print(f"  no interactome for {t.gene}: {exc}", flush=True)
                store[key] = {"partners": [], "enrichment": None, "stoich": None}
                changed = True
                continue
            sig = hits.get("significant_hits") or []
            partners, enr, sto = [], [], []
            for h in sig:
                for e in h.get("ensg_ids") or []:
                    partners.append(e)
                if h.get("enrichment") is not None:
                    enr.append(float(h["enrichment"]))
                if h.get("interaction_stoich") is not None:
                    sto.append(float(h["interaction_stoich"]))
            store[key] = {
                "partners": sorted(set(partners)),
                "enrichment": float(np.mean(enr)) if enr else None,
                "stoich": float(np.mean(sto)) if sto else None,
            }
            changed = True
            if i % 25 == 0:
                print(f"  interactomes: {i}/{len(targets)}", flush=True)
        rec = store[key]
        t.interactors = list(rec["partners"])
        t.interactor_enrichment = rec["enrichment"]
        t.interactor_stoich = rec["stoich"]
    if changed:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(store))


def list_fovs(target: Target, cache_dir: Path) -> list[str]:
    """The `*_proj.tif` keys for one target, from the public S3 listing."""
    cache = cache_dir / f"{target.gene}_{target.ensg}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    import xml.etree.ElementTree as ET

    keys: list[str] = []
    token = None
    for _ in range(10):
        url = f"{S3}/?list-type=2&prefix={target.s3_prefix}/&max-keys=1000"
        if token:
            url += f"&continuation-token={requests.utils.quote(token, safe='')}"
        for attempt, wait in enumerate((0, 2, 4, 8)):
            if wait:
                time.sleep(wait)
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                break
            except Exception:
                if attempt == 3:
                    raise
        root = ET.fromstring(r.text)
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        keys += [
            k.text for k in root.findall(".//s3:Contents/s3:Key", ns)
            if k.text and k.text.endswith("_proj.tif")
        ]
        nxt = root.find("s3:NextContinuationToken", ns)
        if nxt is None or not nxt.text:
            break
        token = nxt.text
    keys = sorted(keys)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(keys))
    return keys


# --- the knowledge vector -------------------------------------------------
def _interactome_hash(partners: list[str], n: int = N_INTERACTOME_HASH) -> np.ndarray:
    """A fixed random projection of the partner-gene set.

    Deterministic in the gene identifiers and independent of any image: the
    same partner set always gives the same vector, and two proteins sharing
    partners get similar ones. Seeded per gene id, so no global RNG state and
    no dependence on the order targets are processed in.
    """
    out = np.zeros(n, dtype=np.float32)
    for ensg in partners:
        seed = int.from_bytes(ensg.encode()[-8:].rjust(8, b"0"), "big") % (2**32)
        out += np.random.default_rng(seed).standard_normal(n).astype(np.float32)
    return out / np.sqrt(max(len(partners), 1))


def knowledge_blocks(
    target: Target, families: list[str], compartment_form: str = "graded"
) -> dict[str, np.ndarray]:
    """The four blocks, so ablations can drop whole blocks rather than columns.

    `compartment_form="dominant"` keeps only the sole highest-grade compartment,
    which is identical for every candidate in a fold. `"graded"` keeps every
    annotation including secondary ones, which is **not** identical and is
    image-derived -- see the module docstring.
    """
    comp = np.zeros(len(ALL_COMPARTMENTS), dtype=np.float32)
    if compartment_form == "dominant":
        if target.compartment in ALL_COMPARTMENTS:
            comp[ALL_COMPARTMENTS.index(target.compartment)] = 1.0
    elif compartment_form == "graded":
        for name, grade in target.grades.items():
            if name in ALL_COMPARTMENTS:
                comp[ALL_COMPARTMENTS.index(name)] = grade / 3.0
    else:
        raise ValueError(f"compartment_form must be 'graded' or 'dominant', "
                         f"got {compartment_form!r}")

    def log10(x, default=0.0):
        return float(np.log10(x)) if x and x > 0 else default

    abundance = np.array([
        log10(target.protein_copy_number) / 7.0,
        log10(target.protein_concentration) / 5.0,
        log10(target.rna_abundance) / 3.0,
    ], dtype=np.float32)

    # `families` must be the vocabulary of the TRAINING targets only. A family
    # seen for the first time in a held-out protein falls into the trailing
    # "other" slot rather than getting a column that was identically zero
    # throughout training -- which is the exact failure that made the previous
    # study's leave-one-out folds unanswerable.
    fam = np.zeros(len(families) + 1, dtype=np.float32)
    fam[families.index(target.family) if target.family in families else len(families)] = 1.0
    protein = np.concatenate([
        fam,
        np.array([1.0 if target.terminus == "N" else 0.0], dtype=np.float32),
    ])

    interactome = np.concatenate([
        np.array([
            np.log1p(len(target.interactors)) / 5.0,
            (target.interactor_enrichment or 0.0) / 5.0,
            np.clip(target.interactor_stoich or 0.0, 0, 5) / 5.0,
        ], dtype=np.float32),
        _interactome_hash(target.interactors),
    ])
    return {"compartment": comp, "abundance": abundance,
            "protein": protein, "interactome": interactome}


def knowledge_vector(
    target: Target,
    families: list[str],
    blocks: tuple[str, ...] = KNOWLEDGE_BLOCKS,
    compartment_form: str = "graded",
) -> np.ndarray:
    """Concatenate the requested blocks; dropped blocks are zeroed, not removed.

    Zeroing keeps the vector length -- and therefore the model -- identical
    across ablations, so an ablation changes what the model can know and
    nothing else.
    """
    parts = knowledge_blocks(target, families, compartment_form=compartment_form)
    return np.concatenate([
        parts[name] if name in blocks else np.zeros_like(parts[name])
        for name in KNOWLEDGE_BLOCKS
    ])


def knowledge_dim(families: list[str]) -> int:
    """Length of the vector `knowledge_vector` returns, derived block by block.

    Computed from the blocks themselves rather than re-added by hand: the
    hand-added version silently lost the tagging-terminus column and reported
    one less than the vector actually had.
    """
    probe = Target(gene="_", ensg="_", cell_line_id=0, compartment=COMPARTMENTS[0],
                   grades={COMPARTMENTS[0]: 3})
    return int(sum(v.size for v in knowledge_blocks(probe, families).values()))


def choose_sample(
    targets: list[Target],
    n_per_compartment: int,
    n_held_out: int,
    min_fovs: int,
    seed: int,
    held_out_fraction: float | None = None,
) -> dict[str, dict[str, list[Target]]]:
    """Per compartment: `n_per_compartment` targets, split train / held out.

    Selection is a seeded shuffle of the QC-passing pool. Deliberately *not*
    sorted on interactome size or abundance: those are inputs the model is given,
    and selecting the sample on an input would decide part of the result before
    the run. Gene name is not used either, since alphabetical order tracks gene
    families (all the RABs together).
    """
    rng = np.random.default_rng(seed)
    out: dict[str, dict[str, list[Target]]] = {}
    for compartment in COMPARTMENTS:
        pool = sorted(
            (t for t in targets if t.compartment == compartment and t.n_fovs >= min_fovs),
            key=lambda t: t.ensg,
        )
        pick = rng.permutation(len(pool))[:n_per_compartment]
        chosen = [pool[i] for i in sorted(pick)]
        if len(chosen) < n_per_compartment:
            print(f"  {compartment}: only {len(chosen)} targets available")
        # A fraction keeps the candidate set proportional to the compartment,
        # which is the point of using the whole pool: a big compartment should
        # give a harder retrieval, not the same 8-way one.
        k = (max(2, int(round(len(chosen) * held_out_fraction)))
             if held_out_fraction else n_held_out)
        k = min(k, max(0, len(chosen) - 2))
        order = rng.permutation(len(chosen))
        held = [chosen[i] for i in sorted(order[:k])]
        train = [chosen[i] for i in sorted(order[k:])]
        out[compartment] = {"train": train, "held_out": held}
    return out


def save_sample(sample: dict[str, dict[str, list[Target]]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {c: {k: [asdict(t) for t in v] for k, v in d.items()} for c, d in sample.items()},
        indent=1,
    ))


def load_sample(path: Path) -> dict[str, dict[str, list[Target]]]:
    raw = json.loads(path.read_text())
    return {c: {k: [Target(**t) for t in v] for k, v in d.items()} for c, d in raw.items()}
