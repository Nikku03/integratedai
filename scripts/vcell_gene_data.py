#!/usr/bin/env python3
"""Build every image-independent gene-level fingerprint block we can reach.

Everything a public database knows about a gene *except* where it is. The
exclusions are deliberate and load-bearing, because a feature derived from
imaging would make the identification circular:

* **GO cellular component (aspect C) is dropped.** Biological process (P) and
  molecular function (F) are kept.
* **Every Human Protein Atlas subcellular column is dropped** -- "Subcellular
  location", "Subcellular main location", "Subcellular additional location",
  "Secretome location". HPA derives those from immunofluorescence, which is the
  same measurement we are trying to predict.

What is kept, per gene:

* **STRING** -- the functional-association profile over a fixed reference panel
  of the most-connected human genes, plus per-channel degree and strength. The
  closest reachable stand-in for co-essentiality, which DepMap serves behind a
  bot wall.
* **GO** process and function terms.
* **Reactome** pathway membership.
* **HPA** RNA expression specificity across tissues, single-cell types, cancers,
  blood and cell lines, plus protein class.
* **AlphaFold** -- mean and spread of pLDDT, the disordered fraction, and
  compactness. Predicted structure, not observed location.

    python scripts/vcell_gene_data.py --data-dir .vcell/oc
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

STRING_PANEL = 512      # reference genes for the association profile
GO_TERMS = 300
REACTOME_PATHWAYS = 200
HPA_DROP = ("subcellular location", "subcellular main location",
            "subcellular additional location", "secretome location")


def gene_keys(sample: dict) -> dict[str, str]:
    """gene -> uniprot accession, for the sampled proteins."""
    out = {}
    for groups in sample.values():
        for members in groups.values():
            for t in members:
                out[t["gene"]] = t.get("uniprot") or ""
    return out


def build_string(path_links: Path, path_alias: Path, genes: list[str]) -> dict:
    """Association profile over a fixed panel of well-connected genes."""
    # gene symbol -> STRING protein id
    sym2id: dict[str, str] = {}
    id2sym: dict[str, str] = {}
    with gzip.open(path_alias, "rt") as fh:
        next(fh, None)
        for line in fh:
            sid, alias, source = line.rstrip("\n").split("\t")
            if "Ensembl_gene_symbol" in source or source.endswith("gene_name") \
                    or "UniProt_GN" in source or source == "BioMart_HUGO":
                sym2id.setdefault(alias, sid)
                id2sym.setdefault(sid, alias)
    want = {sym2id[g] for g in genes if g in sym2id}
    print(f"  STRING: {len(want)}/{len(genes)} genes mapped to STRING ids", flush=True)

    # One pass: collect edges touching our genes, and global degree for the panel.
    edges: dict[str, dict[str, np.ndarray]] = defaultdict(dict)
    degree: Counter = Counter()
    with gzip.open(path_links, "rt") as fh:
        next(fh, None)
        for line in fh:
            f = line.split()
            if len(f) < 10:
                continue
            a, b = f[0], f[1]
            combined = int(f[9])
            if combined >= 400:
                degree[a] += 1
            if a in want:
                edges[a][b] = np.array(
                    [int(f[2]), int(f[3]), int(f[4]), int(f[5]), int(f[6]),
                     int(f[7]), int(f[8]), combined], dtype=np.float32)
    panel = [p for p, _ in degree.most_common(STRING_PANEL)]
    panel_index = {p: i for i, p in enumerate(panel)}
    print(f"  STRING: reference panel of {len(panel)} genes; "
          f"{sum(len(v) for v in edges.values())} edges collected", flush=True)

    profile, summary = {}, {}
    for g in genes:
        sid = sym2id.get(g)
        v = np.zeros(len(panel), dtype=np.float32)
        chan = np.zeros(8, dtype=np.float32)
        n = 0
        if sid and sid in edges:
            for partner, scores in edges[sid].items():
                if partner in panel_index:
                    v[panel_index[partner]] = scores[7] / 1000.0
                chan += scores / 1000.0
                n += 1
        profile[g] = v
        summary[g] = np.concatenate([chan / max(n, 1),
                                     np.array([np.log1p(n) / 8.0], np.float32)])
    return {"string_profile": profile, "string_channels": summary,
            "panel_size": len(panel)}


def build_go(path: Path, genes: list[str]) -> dict:
    """GO process and function terms. Cellular component is EXCLUDED."""
    per_gene: dict[str, set[str]] = defaultdict(set)
    counts: Counter = Counter()
    kept = dropped = 0
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("!"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 15:
                continue
            symbol, term, aspect = f[2], f[4], f[8]
            if aspect == "C":            # cellular component -- circular here
                dropped += 1
                continue
            kept += 1
            if symbol in set(genes):
                per_gene[symbol].add(term)
                counts[term] += 1
    print(f"  GO: kept {kept} process/function annotations, dropped {dropped} "
          f"cellular-component ones as circular", flush=True)
    terms = [t for t, _ in counts.most_common(GO_TERMS)]
    index = {t: i for i, t in enumerate(terms)}
    out = {}
    for g in genes:
        v = np.zeros(len(terms) + 1, dtype=np.float32)
        mine = per_gene.get(g, set())
        for t in mine:
            if t in index:
                v[index[t]] = 1.0
        v[-1] = np.log1p(len(mine)) / 6.0
        out[g] = v
    print(f"  GO: {len(terms)} terms used; median terms per gene "
          f"{int(np.median([len(per_gene.get(g, [])) for g in genes]))}", flush=True)
    return {"go_process_function": out}


def build_reactome(path: Path, accessions: dict[str, str], genes: list[str]) -> dict:
    per_gene: dict[str, set[str]] = defaultdict(set)
    counts: Counter = Counter()
    acc2gene = {a: g for g, a in accessions.items() if a}
    with open(path) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < 6 or f[5] != "Homo sapiens":
                continue
            g = acc2gene.get(f[0].split("-")[0])
            if g:
                per_gene[g].add(f[1])
                counts[f[1]] += 1
    paths = [p for p, _ in counts.most_common(REACTOME_PATHWAYS)]
    index = {p: i for i, p in enumerate(paths)}
    out = {}
    for g in genes:
        v = np.zeros(len(paths) + 1, dtype=np.float32)
        mine = per_gene.get(g, set())
        for p in mine:
            if p in index:
                v[index[p]] = 1.0
        v[-1] = np.log1p(len(mine)) / 5.0
        out[g] = v
    print(f"  Reactome: {len(paths)} pathways; "
          f"{sum(1 for g in genes if per_gene.get(g))}/{len(genes)} genes annotated",
          flush=True)
    return {"reactome": out}


def build_hpa(path: Path, genes: list[str]) -> dict:
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            text = io.TextIOWrapper(fh, encoding="utf-8")
            header = next(text).rstrip("\n").split("\t")
            header = [h.strip('"') for h in header]
            drop = {i for i, h in enumerate(header) if h.lower() in HPA_DROP}
            print(f"  HPA: dropping {len(drop)} imaging-derived columns: "
                  f"{[header[i] for i in sorted(drop)]}", flush=True)
            numeric_cols = [i for i, h in enumerate(header)
                            if i not in drop and ("score" in h.lower()
                                                  or h.lower().endswith("ntpm")
                                                  or h.lower().endswith("ptpm"))]
            class_col = header.index("Protein class") if "Protein class" in header else None
            spec_cols = [i for i, h in enumerate(header)
                         if i not in drop and h.lower().endswith("specificity")]
            rows: dict[str, list[str]] = {}
            for line in text:
                f = line.rstrip("\n").split("\t")
                if f and f[0] in set(genes):
                    rows[f[0]] = f
    spec_vocab: Counter = Counter()
    class_vocab: Counter = Counter()
    for f in rows.values():
        for i in spec_cols:
            if i < len(f) and f[i]:
                spec_vocab[f"{i}:{f[i]}"] += 1
        if class_col is not None and class_col < len(f):
            for c in f[class_col].split(","):
                if c.strip():
                    class_vocab[c.strip()] += 1
    spec_terms = [t for t, _ in spec_vocab.most_common(40)]
    classes = [c for c, _ in class_vocab.most_common(30)]
    out = {}
    for g in genes:
        f = rows.get(g)
        num = np.zeros(len(numeric_cols), dtype=np.float32)
        spec = np.zeros(len(spec_terms), dtype=np.float32)
        cls = np.zeros(len(classes), dtype=np.float32)
        if f:
            for j, i in enumerate(numeric_cols):
                try:
                    num[j] = float(f[i]) if i < len(f) and f[i] else 0.0
                except ValueError:
                    num[j] = 0.0
            for i in spec_cols:
                key = f"{i}:{f[i]}" if i < len(f) else ""
                if key in spec_terms:
                    spec[spec_terms.index(key)] = 1.0
            if class_col is not None and class_col < len(f):
                for c in f[class_col].split(","):
                    c = c.strip()
                    if c in classes:
                        cls[classes.index(c)] = 1.0
        out[g] = np.concatenate([np.log1p(np.abs(num)) / 5.0, spec, cls])
    print(f"  HPA: {len(rows)}/{len(genes)} genes found; "
          f"{len(numeric_cols)} numeric + {len(spec_terms)} specificity + "
          f"{len(classes)} class features", flush=True)
    return {"hpa_expression": out}


def build_alphafold(accessions: dict[str, str], genes: list[str], cache: Path) -> dict:
    """pLDDT statistics and compactness from the predicted structure."""
    cache.mkdir(parents=True, exist_ok=True)

    def one(gene: str):
        acc = accessions.get(gene)
        if not acc:
            return gene, None
        dest = cache / f"{acc}.pdb"
        if not dest.exists():
            # The model filename carries a version that changes with each
            # AlphaFold release, so ask the API for the current URL rather than
            # hard-coding one -- the v4 path this originally used now 404s.
            url = None
            for wait in (0, 2, 4):
                if wait:
                    time.sleep(wait)
                try:
                    meta = requests.get(
                        f"https://alphafold.ebi.ac.uk/api/prediction/{acc}",
                        timeout=90)
                    if meta.status_code == 404:
                        return gene, None
                    meta.raise_for_status()
                    entries = meta.json()
                    if entries:
                        url = entries[0].get("pdbUrl")
                    break
                except Exception:
                    continue
            if not url:
                return gene, None
            for wait in (0, 2, 4):
                if wait:
                    time.sleep(wait)
                try:
                    r = requests.get(url, timeout=120)
                    if r.status_code == 404:
                        return gene, None
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                    break
                except Exception:
                    continue
            else:
                return gene, None
        if not dest.exists():
            return gene, None
        plddt, coords = [], []
        for line in dest.read_text().splitlines():
            if line.startswith("ATOM") and line[12:16].strip() == "CA":
                try:
                    plddt.append(float(line[60:66]))
                    coords.append([float(line[30:38]), float(line[38:46]),
                                   float(line[46:54])])
                except ValueError:
                    continue
        if not plddt:
            return gene, None
        p = np.array(plddt)
        c = np.array(coords)
        rg = float(np.sqrt(((c - c.mean(0)) ** 2).sum(1).mean()))
        return gene, np.array([
            p.mean() / 100.0, p.std() / 50.0,
            float((p < 50).mean()), float((p < 70).mean()), float((p > 90).mean()),
            rg / 50.0, rg / max(len(p) ** (1 / 3), 1e-6) / 10.0,
            np.log1p(len(p)) / 8.0,
        ], dtype=np.float32)

    out, missing = {}, 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for gene, v in ex.map(one, genes):
            if v is None:
                missing += 1
                out[gene] = np.zeros(8, dtype=np.float32)
            else:
                out[gene] = v
    print(f"  AlphaFold: {len(genes)-missing}/{len(genes)} structures parsed", flush=True)
    return {"alphafold": out}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    ap.add_argument("--gene-data", default=None)
    ap.add_argument("--skip", default="", help="comma-separated sources to skip")
    args = ap.parse_args()

    D = Path(args.data_dir)
    G = Path(args.gene_data or (D.parent / "gene_data"))
    sample = json.loads((D / "sample.json").read_text())
    # Accessions are only needed by the Reactome and AlphaFold blocks, so a
    # sample without a UniProt fetch can still build the rest.
    uniprot = (json.loads((D / "uniprot.json").read_text())
               if (D / "uniprot.json").exists() else {})
    genes = sorted({t["gene"] for d in sample.values() for v in d.values() for t in v})
    accessions = {g: (uniprot.get(g) or {}).get("primaryAccession", "") for g in genes}
    if not uniprot:
        print("  (no uniprot.json; reactome and alphafold need it)", flush=True)
    print(f"building gene-level fingerprints for {len(genes)} proteins\n")

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    blocks: dict[str, dict] = {}
    if "string" not in skip:
        blocks.update({k: v for k, v in build_string(
            G / "string.txt.gz", G / "string_alias.txt.gz", genes).items()
            if k != "panel_size"})
    if "go" not in skip:
        blocks.update(build_go(G / "goa_human.gaf.gz", genes))
    if "reactome" not in skip:
        blocks.update(build_reactome(G / "reactome.txt", accessions, genes))
    if "hpa" not in skip:
        blocks.update(build_hpa(G / "proteinatlas.tsv.zip", genes))
    if "alphafold" not in skip:
        blocks.update(build_alphafold(accessions, genes, G / "af"))

    out = D / "gene_blocks.npz"
    payload = {"genes": np.array(genes)}
    for name, per_gene in blocks.items():
        payload[name] = np.stack([per_gene[g] for g in genes])
    np.savez_compressed(out, **payload)
    print(f"\nwrote {out}")
    for name in blocks:
        print(f"  {name:22s} {payload[name].shape[1]:5d} dims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
