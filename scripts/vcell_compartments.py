#!/usr/bin/env python3
"""List the sampled proteins by compartment, and shortlist plausible interactions.

Two proteins can only bind each other if they are in the same place. OpenCell
measures interactions by mass spectrometry on a whole-cell lysate, so a pulldown
reports partners without regard to whether the pair was ever co-located -- the
list mixes genuine complexes with indirect associations and with proteins that
only met in the tube.

Intersecting the measured partners with the localisation annotations turns that
list into a shortlist: pairs that are both **measured to interact** and
**annotated to the same compartment**. Those are the candidates for a direct
physical interaction; the rest are not ruled out, but they need an explanation
beyond the pulldown.

Partner localisation is resolved against the **full 1,310-line OpenCell
catalogue**, not just the 168 sampled proteins, so coverage is as good as the
dataset allows. Partners with no OpenCell line cannot be placed at all and are
counted separately rather than quietly dropped.

    python scripts/vcell_compartments.py --data-dir .vcell/oc
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.opencell import (  # noqa: E402
    COMPARTMENTS,
    MINOR_COMPARTMENTS,
    parse_grades,
    sole_dominant,
)


def catalogue_localisation(catalogue: list[dict]) -> dict[str, tuple[str, str]]:
    """ENSG -> (gene, dominant compartment) over every line with annotations.

    QC-flagged lines are kept here on purpose: a line whose imaging was too dim
    to analyse can still carry a usable localisation call, and excluding it would
    shrink partner coverage for no gain.
    """
    out: dict[str, tuple[str, str]] = {}
    for line in catalogue:
        md = line.get("metadata") or {}
        up = line.get("uniprot_metadata") or {}
        ensg = md.get("ensg_id")
        gene = up.get("gene_name") or md.get("target_name")
        if not ensg or not gene:
            continue
        grades = parse_grades(list((line.get("annotation") or {}).get("categories") or []))
        dominant = sole_dominant(grades)
        if dominant:
            out.setdefault(ensg, (gene, dominant))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=".vcell/oc")
    ap.add_argument("--out-dir", default="data/vcell/opencell")
    args = ap.parse_args()

    D = Path(args.data_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalogue = json.loads((D / "catalogue.json").read_text())
    sample = json.loads((D / "sample.json").read_text())
    loc = catalogue_localisation(catalogue)
    print(f"localisation resolved for {len(loc)} of {len(catalogue)} OpenCell lines\n")

    # The sampled proteins, by compartment.
    targets: dict[str, list[dict]] = {}
    by_gene: dict[str, dict] = {}
    for compartment, groups in sample.items():
        rows = []
        for split, members in groups.items():
            for t in members:
                rec = {**t, "split": "held-out" if split == "held_out" else "training"}
                rows.append(rec)
                by_gene[t["gene"]] = rec
        targets[compartment] = sorted(rows, key=lambda r: (r["split"], r["gene"]))

    with open(out_dir / "compartment_members.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["compartment", "gene", "ensg", "split", "secondary_localisations",
                    "n_interactors", "protein_copy_number"])
        for c in COMPARTMENTS:
            for r in targets.get(c, []):
                secondary = ";".join(
                    f"{k}:{v}" for k, v in sorted((r.get("grades") or {}).items())
                    if k != c
                )
                w.writerow([c, r["gene"], r["ensg"], r["split"], secondary,
                            len(r.get("interactors") or []),
                            r.get("protein_copy_number") or ""])

    # The shortlist: measured partner AND same annotated compartment.
    pairs: list[dict] = []
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in COMPARTMENTS:
        for r in targets.get(c, []):
            for ensg in r.get("interactors") or []:
                placed = loc.get(ensg)
                if placed is None:
                    coverage[c]["unplaceable"] += 1
                    continue
                partner_gene, partner_comp = placed
                if partner_gene == r["gene"]:
                    continue
                coverage[c]["placed"] += 1
                if partner_comp == c:
                    coverage[c]["same_compartment"] += 1
                    pairs.append({
                        "compartment": c,
                        "protein": r["gene"],
                        "split": r["split"],
                        "partner": partner_gene,
                        "partner_in_sample": partner_gene in by_gene,
                    })
                else:
                    coverage[c]["other_compartment"] += 1

    # Deduplicate A-B / B-A.
    seen, unique = set(), []
    for p in pairs:
        key = (p["compartment"], *sorted((p["protein"], p["partner"])))
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    with open(out_dir / "compartment_interactions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["compartment", "protein_a", "protein_b", "a_split",
                    "b_in_sample"])
        for p in sorted(unique, key=lambda p: (p["compartment"], p["protein"],
                                               p["partner"])):
            w.writerow([p["compartment"], p["protein"], p["partner"], p["split"],
                        p["partner_in_sample"]])

    print(f"{'compartment':14s} {'proteins':>8s} {'train':>6s} {'held':>5s} "
          f"{'partners':>9s} {'placed':>7s} {'same-comp':>10s} {'share':>6s} "
          f"{'pairs':>6s}")
    for c in COMPARTMENTS:
        cov = coverage[c]
        placed = cov["placed"]
        same = cov["same_compartment"]
        rows = targets.get(c, [])
        n_pairs = sum(1 for p in unique if p["compartment"] == c)
        share = f"{same/placed:.2f}" if placed else "n/a"
        print(f"{c:14s} {len(rows):8d} "
              f"{sum(1 for r in rows if r['split']=='training'):6d} "
              f"{sum(1 for r in rows if r['split']=='held-out'):5d} "
              f"{placed + cov['unplaceable']:9d} {placed:7d} {same:10d} "
              f"{share:>6s} {n_pairs:6d}")

    print("\n=== members, by compartment ===")
    for c in COMPARTMENTS:
        rows = targets.get(c, [])
        train = [r["gene"] for r in rows if r["split"] == "training"]
        held = [r["gene"] for r in rows if r["split"] == "held-out"]
        print(f"\n{c}  ({len(rows)} proteins)")
        print(f"  training  : {', '.join(sorted(train))}")
        print(f"  held out  : {', '.join(sorted(held))}")

    print("\n=== shortlist: measured partners that share a compartment ===")
    for c in COMPARTMENTS:
        mine = [p for p in unique if p["compartment"] == c]
        if not mine:
            print(f"\n{c}: none")
            continue
        print(f"\n{c}  ({len(mine)} pairs)")
        grouped: dict[str, list[str]] = defaultdict(list)
        for p in mine:
            grouped[p["protein"]].append(
                p["partner"] + ("*" if p["partner_in_sample"] else "")
            )
        for protein in sorted(grouped):
            print(f"  {protein:10s} -> {', '.join(sorted(grouped[protein]))}")
    print("\n  * = the partner is itself one of the sampled proteins")
    print(f"\nwrote {out_dir/'compartment_members.csv'} and "
          f"{out_dir/'compartment_interactions.csv'}")
    print(f"minor compartments not used as candidate sets: "
          f"{', '.join(MINOR_COMPARTMENTS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
