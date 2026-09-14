#!/usr/bin/env python3
"""Render the tables for docs/RESULT_OPENCELL.md from the run's own JSON.

Every number in that document comes out of here, so none is transcribed by hand.

    python scripts/vcell_opencell_result.py --data-dir .vcell/oc
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.opencell import COMPARTMENTS  # noqa: E402
from vcell.retrieval import protein_clustered_bootstrap  # noqa: E402

BLOCK_ORDER = ("dominant", "compartment", "compartment+abundance",
               "compartment+protein", "compartment+interactome", "all", "noncircular")
BLOCK_LABEL = {
    "dominant": "dominant compartment only (the true null)",
    "compartment": "graded compartment only (not a null)",
    "compartment+abundance": "+ abundance",
    "compartment+protein": "+ protein properties",
    "compartment+interactome": "+ interactome",
    "all": "all four blocks, graded compartment",
    "noncircular": "all four blocks, dominant compartment (non-circular)",
}


def load(results: Path) -> dict[str, dict]:
    out = {}
    for b in BLOCK_ORDER:
        p = results / f"retrieval_{b}.json"
        if p.exists():
            out[b] = json.loads(p.read_text())
    return out


def gate1_table(gate1: dict) -> str:
    lines = ["| compartment | candidates | tiles | descriptor top-1 | chance | MRR | chance | gate 1 |",
             "|---|---|---|---|---|---|---|---|"]
    for c in COMPARTMENTS:
        if c not in gate1:
            continue
        g = gate1[c]
        s, ci = g["summary"], g["top1_ci"]
        verdict = "**fails**" if ci[0] <= s["chance_top1"] else "passes"
        lines.append(
            f"| {c} | {len(g['candidates'])} | {s['n']} | "
            f"**{s['top1']:.3f}** [{ci[0]:.3f}, {ci[1]:.3f}] | {s['chance_top1']:.3f} | "
            f"{s['mrr']:.3f} | {s['chance_mrr']:.3f} | {verdict} |"
        )
    return "\n".join(lines) + "\n"


def headline_table(runs: dict[str, dict], gate1: dict, block: str = "all") -> str:
    if block not in runs:
        return f"_no run for {block}_\n"
    res = runs[block]["results"]
    lines = ["| compartment | n | model top-1 | chance | mismatched ref | ridge | descriptor (gate 1) | verdict |",
             "|---|---|---|---|---|---|---|---|"]
    for c in COMPARTMENTS:
        if c not in res:
            continue
        r = res[c]
        m, mm, rg = r["model"], r["mismatched_reference"], r.get("ridge_descriptor") or {}
        g1 = gate1.get(c, {}).get("summary", {})
        above = m["top1_lo"] > m["chance_top1"]
        gate_failed = (
            gate1.get(c, {}).get("top1_ci", [1, 1])[0] <= g1.get("chance_top1", 0)
        )
        verdict = ("not identifiable (gate 1)" if gate_failed
                   else ("**above chance**" if above else "at chance"))
        lines.append(
            f"| {c} | {m['n']} | {m['top1']:.3f} [{m['top1_lo']:.3f}, {m['top1_hi']:.3f}] | "
            f"{m['chance_top1']:.3f} | {mm['top1']:.3f} | "
            f"{rg.get('top1', float('nan')):.3f} | {g1.get('top1', float('nan')):.3f} | "
            f"{verdict} |"
        )
    return "\n".join(lines) + "\n"


def ablation_table(runs: dict[str, dict]) -> str:
    present = [b for b in BLOCK_ORDER if b in runs]
    lines = ["| compartment | " + " | ".join(BLOCK_LABEL[b] for b in present) + " | chance |",
             "|---" * (len(present) + 2) + "|"]
    for c in COMPARTMENTS:
        cells, chance = [], float("nan")
        for b in present:
            r = runs[b]["results"].get(c)
            if r is None:
                cells.append("n/a")
                continue
            cells.append(f"{r['model']['top1']:.3f}")
            chance = r["model"]["chance_top1"]
        lines.append(f"| {c} | " + " | ".join(cells) + f" | {chance:.3f} |")
    # Pooled over compartments, weighting every tile equally.
    pooled = []
    for b in present:
        tiles = [(r["model"]["top1"], r["model"]["n"]) for r in runs[b]["results"].values()]
        num = sum(t * n for t, n in tiles)
        den = sum(n for _, n in tiles)
        pooled.append(f"**{num/den:.3f}**" if den else "n/a")
    lines.append("| **pooled** | " + " | ".join(pooled) + " | |")
    return "\n".join(lines) + "\n"


def pooled_with_interval(runs: dict[str, dict], block: str, exclude: tuple[str, ...] = ()):
    """Top-1 pooled over compartments, with a protein-clustered interval."""
    if block not in runs:
        return None
    hits, genes, chance = [], [], []
    for c, r in runs[block]["results"].items():
        if c in exclude:
            continue
        for rec in r["records"]:
            if rec["rank"] > 0 and rec["n_candidates"] > 1:
                hits.append(1.0 if rec["rank"] == 1 else 0.0)
                genes.append(rec["gene"])
                chance.append(1.0 / rec["n_candidates"])
    if not hits:
        return None
    m, lo, hi = protein_clustered_bootstrap(np.array(hits), np.array(genes), seed=1)
    return {"top1": m, "lo": lo, "hi": hi, "chance": float(np.mean(chance)),
            "n_tiles": len(hits), "n_proteins": len(set(genes))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    args = ap.parse_args()
    D = Path(args.data_dir)
    gate1 = json.loads((D / "gate1.json").read_text())
    runs = load(D / "results")

    print("## Gate 1 — is a protein identifiable from its own pixels?\n")
    print(gate1_table(gate1))
    print("\n## H1 — the registered question, full knowledge vector (graded compartment)\n")
    print(headline_table(runs, gate1, "all"))
    print("\n## H1, non-circular — nothing image-derived can separate the candidates\n")
    print(headline_table(runs, gate1, "noncircular"))
    print("\n## H3 — which block carries it\n")
    print(ablation_table(runs))
    print("\n## Pooled\n")
    for block in BLOCK_ORDER:
        p = pooled_with_interval(runs, block)
        q = pooled_with_interval(runs, block, exclude=("er",))
        if p:
            print(f"- **{BLOCK_LABEL[block]}**: top-1 {p['top1']:.3f} "
                  f"[{p['lo']:.3f}, {p['hi']:.3f}] against chance {p['chance']:.3f} "
                  f"({p['n_tiles']} tiles, {p['n_proteins']} proteins)"
                  + (f"; excluding ER {q['top1']:.3f} [{q['lo']:.3f}, {q['hi']:.3f}]"
                     if q else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
