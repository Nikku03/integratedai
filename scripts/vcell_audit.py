#!/usr/bin/env python3
"""Everything the result document reports, computed with the right tests.

Written after an adversarial review of a first draft of the result document
refuted all twelve of its headline claims. Three of those refutations were
methodological and are fixed here rather than argued with.

1. **Paired, not marginal.** `vcell train` reports a bootstrap interval per
   predictor. Comparing two predictors by whether their marginal intervals
   overlap is the wrong test and much too conservative: every predictor is
   scored on the *same cells*, so the comparison is paired. Several differences
   the marginal intervals call ambiguous are clean when done paired, and one --
   the model against the atlas on TUBA1B -- is thin either way.

2. **The registered criterion, not a convenient one.** H1, H2 and H6 are
   registered as beating specific baselines, not as beating chance. Lift over
   chance was introduced after the run and is useful, but it is not what was
   registered, and the registered verdicts are computed here separately.

3. **Tie-breaking.** `dice_volume_matched` takes the top k voxels with
   argpartition, which breaks ties by array index. Five of the six geometric
   rules emit binary fields where every voxel in the shell is tied, so their
   score depends on an arbitrary index order. Recomputed here with random
   tie-breaking over repeated draws, to check whether the gate-2 comparisons
   move.

It also reports two things the review found nobody had checked: whether the
registered FOV split does anything at all, and what the plate structure does
across it.

    python scripts/vcell_audit.py --data-dir .vcell
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from vcell.baselines import RULE_NAMES, annotation_rule, geometric_rule  # noqa: E402
from vcell.dataset import load_frames, split_by_fov  # noqa: E402
from vcell.metrics import HIGHER_IS_BETTER, METRIC_NAMES  # noqa: E402

N_BOOT = 10000


def paired_bootstrap(
    a: np.ndarray, b: np.ndarray, seed: int = 0, n: int = N_BOOT
) -> tuple[float, float, float, float, int]:
    """(mean difference a-b, lo, hi, share of resamples <= 0, n cells).

    Resamples cells, not predictors, and keeps each cell's pair together. With
    one cell per field of view -- which is what this sample turned out to be --
    a FOV-clustered bootstrap and a cell bootstrap are the same thing, and this
    is that thing, done paired.
    """
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]
    if a.size == 0:
        return (float("nan"),) * 4 + (0,)
    d = a - b
    rng = np.random.default_rng(seed)
    draws = d[rng.integers(0, d.size, size=(n, d.size))].mean(axis=1)
    return (
        float(d.mean()),
        float(np.percentile(draws, 2.5)),
        float(np.percentile(draws, 97.5)),
        float((draws <= 0).mean()),
        int(d.size),
    )


def load_records(path: Path) -> dict:
    rows = json.loads(path.read_text())
    index: dict = defaultdict(dict)
    for r in rows:
        index[(r["fold"], r["gene"], r["predictor"])][r["cell_id"]] = r
    return index


def aligned(index, fold, gene, p_a, p_b, metric):
    a_rows = index.get((fold, gene, p_a), {})
    b_rows = index.get((fold, gene, p_b), {})
    cells = sorted(set(a_rows) & set(b_rows))
    if not cells:
        return np.array([]), np.array([])
    return (
        np.array([a_rows[c][metric] for c in cells], dtype=float),
        np.array([b_rows[c][metric] for c in cells], dtype=float),
    )


# --- 1. the registered verdicts -------------------------------------------
# H1: beat the atlas, the geometric rule, AND the conditioning-ablated model.
# H2/H6: beat the generic (pooled) atlas AND the geometric rule.
REGISTERED = {
    "seen": ("atlas_own_structure", "atlas_pooled", "rule_annotation", "reference_only"),
    "mitotic": ("atlas_own_structure", "atlas_pooled", "rule_annotation", "reference_only"),
    "loso": ("atlas_pooled", "rule_annotation"),
    "covered": ("atlas_pooled", "rule_annotation"),
}


def registered_verdicts(index, seed: int) -> list[dict]:
    out = []
    folds = sorted({k[0] for k in index})
    for fold in folds:
        kind = fold.split("_")[0] if "_" in fold else fold
        baselines = REGISTERED.get(kind, ("atlas_pooled", "rule_annotation"))
        for gene in sorted({k[1] for k in index if k[0] == fold}):
            row = {"fold": fold, "gene": gene, "beaten_by": [], "beats": [],
                   "not_separated": []}
            for base in baselines:
                a, b = aligned(index, fold, gene, "model", base, "dice")
                if a.size == 0:
                    continue
                mean, lo, hi, _, n = paired_bootstrap(a, b, seed=seed)
                row["n_cells"] = n
                entry = {"baseline": base, "diff": mean, "lo": lo, "hi": hi}
                if lo > 0:
                    row["beats"].append(entry)
                elif hi < 0:
                    row["beaten_by"].append(entry)
                else:
                    row["not_separated"].append(entry)
            row["passes_registered"] = not row["beaten_by"] and not row["not_separated"]
            out.append(row)
    return out


# --- 2. every paired comparison on every metric ----------------------------
def all_paired(index, seed: int) -> list[dict]:
    out = []
    for fold in sorted({k[0] for k in index}):
        for gene in sorted({k[1] for k in index if k[0] == fold}):
            others = sorted(
                {k[2] for k in index if k[0] == fold and k[1] == gene} - {"model"}
            )
            for base in others:
                for metric in METRIC_NAMES:
                    a, b = aligned(index, fold, gene, "model", base, metric)
                    if a.size == 0:
                        continue
                    mean, lo, hi, p_le0, n = paired_bootstrap(a, b, seed=seed)
                    # Sign so that positive always means the model is better.
                    flip = 1.0 if HIGHER_IS_BETTER[metric] else -1.0
                    out.append({
                        "fold": fold, "gene": gene, "baseline": base, "metric": metric,
                        "model_better_by": flip * mean,
                        "lo": flip * (lo if flip > 0 else hi),
                        "hi": flip * (hi if flip > 0 else lo),
                        "n_cells": n,
                        "share_cells_model_better": float(
                            np.mean((a > b) if HIGHER_IS_BETTER[metric] else (a < b))
                        ),
                    })
    return out


# --- 3. normalisations of Dice --------------------------------------------
def normalisations(controls: list[dict]) -> list[dict]:
    out = []
    for r in controls:
        p = r["chance_dice"]
        d = r["dice"]
        out.append({
            "fold": r["fold"], "gene": r["gene"], "chance": p, "dice": d,
            "lift": d / p if p > 0 else float("nan"),
            "lift_ceiling": 1.0 / p if p > 0 else float("nan"),
            "share_of_ceiling": d if p <= 0 else (d / p) / (1.0 / p),
            "excess": (d - p) / (1.0 - p) if p < 1 else float("nan"),
        })
    return out


# --- 4. does the registered split do anything? -----------------------------
def split_audit(data_dir: Path, seed: int) -> dict:
    frames = load_frames(data_dir / "frames_interphase.npz")
    n = frames["gene"].size
    fovs = frames["fov_id"]
    cells_per_fov = np.array([int((fovs == f).sum()) for f in np.unique(fovs)])
    train_idx, test_idx = split_by_fov(frames, test_fraction=0.2, seed=seed)

    plates: dict[str, str] = {}
    for name in ("manifest_interphase.csv", "manifest_extended_interphase.csv"):
        path = data_dir / name
        if path.exists():
            with open(path, newline="") as fh:
                for row in csv.DictReader(fh):
                    plates[row["cell_id"]] = row["plate_id"]
    train_plates = {plates.get(c) for c in frames["cell_id"][train_idx]} - {None}
    test_plates = {plates.get(c) for c in frames["cell_id"][test_idx]} - {None}
    return {
        "n_cells": int(n),
        "n_fovs": int(np.unique(fovs).size),
        "max_cells_per_fov": int(cells_per_fov.max()),
        "fov_split_is_a_cell_split": bool(cells_per_fov.max() == 1),
        "n_train": int(train_idx.size), "n_test": int(test_idx.size),
        "n_plates_total": len(set(plates.values())),
        "n_plates_train": len(train_plates), "n_plates_test": len(test_plates),
        "n_plates_shared": len(train_plates & test_plates),
        "plates_test_only": len(test_plates - train_plates),
    }


# --- 5. does index-order tie-breaking flatter the rules? -------------------
def tie_break_audit(data_dir: Path, draws: int = 12, seed: int = 0) -> list[dict]:
    """Rescore the geometric rules with random tie-breaking instead of argpartition."""
    frames = load_frames(data_dir / "frames_interphase.npz")
    rng = np.random.default_rng(seed)
    out = []
    for gene in sorted(set(frames["gene"].tolist())):
        rows = np.flatnonzero(frames["gene"] == gene)[:24]
        rule = annotation_rule(gene)
        index_order, randomised = [], []
        for row in rows:
            cell = frames["cell_mask"][row]
            truth = frames["struct_mask"][row]
            field = geometric_rule(rule, frames["nuc_mask"][row], cell,
                                   frames["voxel_micron"][row])
            inside = np.flatnonzero(cell.ravel())
            t = truth.ravel()[inside]
            k = int(t.sum())
            if k == 0 or k == inside.size:
                continue
            s = field.ravel()[inside]
            index_order.append(t[np.argpartition(-s, k - 1)[:k]].sum() / k)
            for _ in range(draws):
                jitter = s + rng.random(s.size) * 1e-6
                randomised.append(t[np.argpartition(-jitter, k - 1)[:k]].sum() / k)
        if index_order:
            out.append({
                "gene": gene, "rule": rule, "n_cells": len(index_order),
                "dice_index_order": float(np.mean(index_order)),
                "dice_random_ties": float(np.mean(randomised)),
                "n_tied_rules": sum(
                    1 for r in RULE_NAMES if r not in ("perinuclear",)
                ),
            })
    return out


# --- 6. mitosis, by stage --------------------------------------------------
def mitotic_by_stage(index, records_path: Path) -> list[dict]:
    rows = json.loads(records_path.read_text())
    out = []
    by = defaultdict(list)
    for r in rows:
        if r["fold"] == "mitotic" and r["predictor"] in ("model", "rule_annotation"):
            by[(r["gene"], r["cell_stage"], r["predictor"])].append(r)
    for (gene, stage, predictor), group in sorted(by.items()):
        out.append({
            "gene": gene, "cell_stage": stage, "predictor": predictor,
            "n_cells": len(group),
            **{
                m: float(np.nanmean([g[m] for g in group]))
                for m in METRIC_NAMES
            },
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default=".vcell")
    parser.add_argument("--results", default=None)
    parser.add_argument("--seed", type=int, default=20260914)
    parser.add_argument("--skip-ties", action="store_true")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    results = Path(args.results or (data_dir / "results"))
    index = load_records(results / "records.json")
    controls = json.loads((results / "controls.json").read_text())

    audit = {
        "registered_verdicts": registered_verdicts(index, args.seed),
        "paired": all_paired(index, args.seed),
        "normalisations": normalisations(controls),
        "split": split_audit(data_dir, args.seed),
        "mitotic_by_stage": mitotic_by_stage(index, results / "records.json"),
        "tie_break": [] if args.skip_ties else tie_break_audit(data_dir, seed=args.seed),
    }
    (results / "audit.json").write_text(json.dumps(audit, indent=1))

    s = audit["split"]
    print("=== does the registered FOV split do anything? ===")
    print(f"  {s['n_cells']} cells over {s['n_fovs']} fields of view, "
          f"at most {s['max_cells_per_fov']} cell per field")
    print(f"  -> the FOV split is a plain random cell split: {s['fov_split_is_a_cell_split']}")
    print(f"  plates: {s['n_plates_total']} total, {s['n_plates_shared']} shared across "
          f"the split, {s['plates_test_only']} test-only")

    print("\n=== registered verdicts (paired per-cell Dice, model vs registered baselines) ===")
    print(f"{'fold':16s} {'gene':8s} {'n':>4s}  verdict")
    for r in audit["registered_verdicts"]:
        lost = ", ".join(f"{e['baseline']} ({e['diff']:+.3f})" for e in r["beaten_by"])
        tied = ", ".join(f"{e['baseline']} ({e['diff']:+.3f})" for e in r["not_separated"])
        verdict = "PASS" if r["passes_registered"] else "FAIL"
        detail = "; ".join(x for x in (f"beaten by {lost}" if lost else "",
                                       f"not separated from {tied}" if tied else "") if x)
        print(f"{r['fold']:16s} {r['gene']:8s} {r.get('n_cells',0):>4d}  {verdict}"
              + (f" -- {detail}" if detail else ""))

    print("\n=== three normalisations of Dice, seen fold ===")
    print(f"{'gene':8s} {'chance':>7s} {'dice':>7s} {'lift':>7s} {'ceiling':>8s} {'excess':>7s}")
    for r in audit["normalisations"]:
        if r["fold"] != "seen":
            continue
        print(f"{r['gene']:8s} {r['chance']:7.3f} {r['dice']:7.3f} {r['lift']:7.2f} "
              f"{r['lift_ceiling']:8.2f} {r['excess']:7.3f}")

    if audit["tie_break"]:
        print("\n=== geometric rule Dice: index-order vs random tie-breaking ===")
        for r in audit["tie_break"]:
            print(f"  {r['gene']:8s} rule={r['rule']:18s} "
                  f"index {r['dice_index_order']:.3f}  random {r['dice_random_ties']:.3f}  "
                  f"delta {r['dice_random_ties']-r['dice_index_order']:+.3f}")

    print(f"\nwrote {results/'audit.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
