"""Candidate descriptions of a protein, and which of them are honest.

The two studies before this one converged on a single gap: compartment
annotation predicts where a protein sits, and nothing in "how abundant it is,
what family it belongs to, and what it binds" predicts which protein it is.
The images demonstrably carry each protein's fingerprint -- a fixed texture
descriptor picks the right one 76% of the time in vesicles -- so what is
missing is a *description* that reaches it.

This module builds candidate descriptions, each as a named block, and each
tagged with whether it is honest for this test.

**The circularity rule.** A description is circular if it was derived, even
indirectly, from looking at where the protein is. UniProt's "Cellular
component" keywords are curated from the literature, which includes imaging, so
they are circular here and are kept in their own block, `location_kw`, reported
separately and never mixed into an honest total. Everything else -- amino-acid
composition, transmembrane topology, signal peptides, lipidation, coiled coils,
low-complexity regions, Pfam domains, non-location keywords, and a protein
language-model embedding of the bare sequence -- follows from the sequence or
from biochemistry, not from a micrograph.

That distinction is the whole point. A circular block that predicts well tells
us nothing; an honest block that predicts well is the thing worth having.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"

# Kyte & Doolittle (1982) hydropathy.
HYDROPATHY = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}
# Disorder-promoting residues (Dunker et al.).
DISORDER_PROMOTING = set("PESKQRGA")
CHARGED_POS, CHARGED_NEG = set("KR"), set("DE")


@dataclass
class Block:
    name: str
    circular: bool
    note: str


BLOCKS: tuple[Block, ...] = (
    Block("baseline", False,
          "abundance + family + terminus + interactome -- the known failure"),
    Block("composition", False, "amino-acid frequencies, length, charge, hydropathy"),
    Block("topology", False, "transmembrane passes, signal peptide, lipidation, glycosylation"),
    Block("lowcomplexity", False, "coiled coils, compositional bias, homopolymer runs"),
    Block("domains", False, "hashed Pfam bag"),
    Block("function_kw", False, "hashed UniProt keywords, EXCLUDING cellular component"),
    Block("location_kw", True,
          "hashed UniProt CELLULAR COMPONENT keywords -- curated from literature "
          "including imaging, so circular for this test"),
    Block("esm", False, "mean-pooled ESM-2 embedding of the bare sequence"),
)
HONEST_BLOCKS = tuple(b.name for b in BLOCKS if not b.circular)


def _hashed_bag(items: list[str], n: int, salt: str) -> np.ndarray:
    """Fixed hashing of a set of string labels into n dimensions.

    Deterministic across runs and machines -- `hash()` is salted per process, so
    it is not used. Signed buckets keep unrelated labels from piling up.
    """
    out = np.zeros(n, dtype=np.float32)
    for item in set(items):
        h = hashlib.sha256(f"{salt}:{item}".encode()).digest()
        out[h[0] % n] += 1.0 if h[1] % 2 else -1.0
    return out / np.sqrt(max(len(set(items)), 1))


def _features(record: dict, kinds: set[str]) -> list[dict]:
    return [f for f in record.get("features") or [] if f.get("type") in kinds]


def _span_len(f: dict) -> int:
    loc = (f.get("location") or {})
    start = ((loc.get("start") or {}).get("value")) or 0
    end = ((loc.get("end") or {}).get("value")) or 0
    return max(0, int(end) - int(start) + 1) if start and end else 0


def sequence_of(record: dict) -> str:
    return ((record.get("sequence") or {}).get("value") or "").upper()


def composition_block(record: dict) -> np.ndarray:
    seq = sequence_of(record)
    n = max(len(seq), 1)
    counts = np.array([seq.count(a) for a in AMINO_ACIDS], dtype=np.float32) / n
    gravy = float(np.mean([HYDROPATHY.get(c, 0.0) for c in seq])) if seq else 0.0
    pos = sum(seq.count(c) for c in CHARGED_POS) / n
    neg = sum(seq.count(c) for c in CHARGED_NEG) / n
    disorder = sum(seq.count(c) for c in DISORDER_PROMOTING) / n
    aromatic = sum(seq.count(c) for c in "FWY") / n
    return np.concatenate([
        counts,
        np.array([np.log10(n) / 4.0, gravy / 4.5, pos, neg, pos - neg,
                  disorder, aromatic], dtype=np.float32),
    ])


def topology_block(record: dict) -> np.ndarray:
    seq = sequence_of(record)
    n = max(len(seq), 1)
    tm = _features(record, {"Transmembrane"})
    signal = _features(record, {"Signal"})
    lipid = _features(record, {"Lipidation"})
    glyc = _features(record, {"Glycosylation"})
    # Strongest hydrophobic 19-residue window in the N-terminal 70 residues: a
    # sequence-only proxy for a targeting signal, independent of curation.
    head = seq[:70]
    best = 0.0
    if len(head) >= 19:
        vals = np.array([HYDROPATHY.get(c, 0.0) for c in head], dtype=np.float32)
        kernel = np.ones(19, dtype=np.float32) / 19.0
        best = float(np.convolve(vals, kernel, mode="valid").max())
    kw = {k.get("name", "") for k in record.get("keywords") or []}
    return np.array([
        min(len(tm), 12) / 12.0,
        sum(_span_len(f) for f in tm) / n,
        1.0 if signal else 0.0,
        (_span_len(signal[0]) / 40.0) if signal else 0.0,
        best / 4.5,
        min(len(lipid), 4) / 4.0,
        1.0 if "Prenylation" in kw else 0.0,
        1.0 if "GPI-anchor" in kw else 0.0,
        min(len(glyc), 8) / 8.0,
        1.0 if "Transmembrane helix" in kw else 0.0,
    ], dtype=np.float32)


def lowcomplexity_block(record: dict) -> np.ndarray:
    seq = sequence_of(record)
    n = max(len(seq), 1)
    coil = _features(record, {"Coiled coil"})
    bias = _features(record, {"Compositional bias"})
    run = 1
    best_run = 1
    for i in range(1, len(seq)):
        run = run + 1 if seq[i] == seq[i - 1] else 1
        best_run = max(best_run, run)
    return np.array([
        min(len(coil), 5) / 5.0,
        sum(_span_len(f) for f in coil) / n,
        min(len(bias), 5) / 5.0,
        sum(_span_len(f) for f in bias) / n,
        min(best_run, 12) / 12.0,
    ], dtype=np.float32)


def domains_block(record: dict, n: int = 16) -> np.ndarray:
    pfam = [x["id"] for x in record.get("uniProtKBCrossReferences") or []
            if x.get("database") == "Pfam" and x.get("id")]
    names = [f.get("description", "") for f in _features(record, {"Domain"})]
    return _hashed_bag(pfam + names, n, salt="pfam")


def _keywords(record: dict, location: bool) -> list[str]:
    out = []
    for k in record.get("keywords") or []:
        is_location = k.get("category") == "Cellular component"
        if is_location == location:
            out.append(k.get("name", ""))
    return [k for k in out if k]


def function_kw_block(record: dict, n: int = 16) -> np.ndarray:
    return _hashed_bag(_keywords(record, location=False), n, salt="kwfun")


def location_kw_block(record: dict, n: int = 8) -> np.ndarray:
    """CIRCULAR. Kept only so its advantage over the honest blocks can be shown."""
    return _hashed_bag(_keywords(record, location=True), n, salt="kwloc")


def build_blocks(
    records: dict[str, dict],
    esm: dict[str, np.ndarray] | None = None,
    baseline: dict[str, np.ndarray] | None = None,
) -> dict[str, dict[str, np.ndarray]]:
    """`{block name: {gene: vector}}` for every block that can be built."""
    out: dict[str, dict[str, np.ndarray]] = {}
    builders = {
        "composition": composition_block,
        "topology": topology_block,
        "lowcomplexity": lowcomplexity_block,
        "domains": domains_block,
        "function_kw": function_kw_block,
        "location_kw": location_kw_block,
    }
    for name, fn in builders.items():
        out[name] = {g: fn(r) for g, r in records.items()}
    if esm:
        out["esm"] = dict(esm)
    if baseline:
        out["baseline"] = dict(baseline)
    return out


def load_uniprot(path: Path) -> dict[str, dict]:
    return json.loads(path.read_text())
