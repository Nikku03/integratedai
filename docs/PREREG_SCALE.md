# Pre-registration: 25 structures in one virtual cell, and a 45-way protein identification

Committed before any metric from either experiment. At the time of writing the
two samples have been selected and the images are still downloading; nothing has
been scored.

Two confirmatory tests, each fixing a claim that an earlier exploratory run left
underdetermined.

---

# Experiment 1 — does the virtual cell hold at 25 structures?

## What is being confirmed

[`RESULT_VIRTUAL_CELL.md`](RESULT_VIRTUAL_CELL.md) reported H4, the joint virtual
cell, as its one clean positive: five structures predicted onto a single cell's
geometry reproduced the pairwise radial arrangement measured between real
structures imaged in *different* cells, at correlation 0.990 over 10 pairs and
0.959 over the 6 pairs excluding the nuclear structure.

Ten pairs is a weak test of an arrangement claim, and four of those ten involved
the single nuclear structure. The Allen collection has **25 tagged lines**, and
the knowledge vector in `vcell.knowledge` was built to cover all 25 from the
start, so the same model can be asked for any of them without a change to the
conditioning layout.

**25 structures give 300 pairs.** That is the test.

## Fixed parameters

| parameter | value |
|---|---|
| structures | **all 25** Allen lines (the 9 already fetched plus the 16 remaining) |
| cells per line | **80** interphase, same QC filter as before (`cell_stage == M0`, `outlier == No`, `edge_flag == 0`) |
| model | one `seen` fold, the same 3D U-Net at base 12, depth 3, FiLM, grid (24, 48, 48) |
| epochs | **25**, Adam 1e-3, batch 4 — unchanged |
| split | by FOV, 20% held out, as before |
| conditioning | the existing fixed 24-d annotation vector, unchanged |
| arrangement metric | Wasserstein-1 between structures' signed-nuclear-distance profiles, unchanged |
| seed | 20260915 |

## Hypotheses

**H1 — the arrangement holds.** Over all **300** pairs, the correlation between
the measured pairwise-W1 matrix and the virtual cell's stays above **0.85**, and
Spearman above **0.75**.

**H2 — it is not carried by the nuclear/cytoplasmic split.** Restricted to pairs
where both structures are cytoplasmic, and again to pairs where both are
nuclear, the correlation stays above **0.70** in each. This is the version of the
check that mattered at five structures and it is registered here rather than
added afterwards.

**H3 — per-structure accuracy does not collapse with breadth.** The mean
volume-matched Dice over the 25 structures, on held-out cells, stays within
**20% relative** of the five-structure study's mean over its five. A model
spread across 25 conditions could get worse at each; if it does, the virtual
cell is broader and shallower and that is the finding.

## The registered failure mode

At five structures the arrangement was dominated by one contrast — nuclear
against cytoplasmic. With 300 pairs spanning nucleolus, chromatin, nuclear
envelope, nuclear pores, speckles, centrosome, ER, Golgi, mitochondria,
endolysosome, peroxisome, plasma membrane, junctions and the cytoskeleton, a
correlation near 0.99 is no longer available for free. **If H1 lands between
0.85 and 0.99, the honest reading is that the original 0.990 was inflated by
having only one strong contrast**, not that the model got worse.

---

# Experiment 2 — the 45-way identification

## What is being confirmed

[`RESULT_PROTEIN_DESCRIPTION.md`](RESULT_PROTEIN_DESCRIPTION.md) found exactly
one description that identifies a protein within its compartment: the **STRING
functional-association profile**, at top-1 0.245 against a chance of 0.132
(p = 0.017), with a shared-space correlation of 0.385 (p = 0.000).

Three things made that suggestive rather than established, and all three are
addressed here rather than argued with:

1. It was **one combination out of sixteen**, and p = 0.017 does not survive
   correction for sixteen. → **One fingerprint is registered in advance.**
2. The candidate sets held **8 proteins**, so chance was 12.5% and the margin was
   0.11. → **The whole qualifying pool is used**, giving candidate sets up to
   **45**, where chance is 2.2% and a fluke cannot reach it.
3. Combinations moved wildly with an arbitrary fusion rule. → **No combination
   is tested.** A single block has no fusion rule to choose.

## Fixed parameters

| parameter | value |
|---|---|
| proteins | **all 479** QC-passing sole-dominant targets across the 7 compartments |
| split | **one third held out per compartment**, seeded: 320 training, 159 held out |
| candidate sets | the held-out proteins of each compartment: **45, 36, 28, 15, 15, 12, 8** |
| chance | **0.022 to 0.125** per compartment, reported per compartment and pooled |
| the fingerprint | **`string_profile` alone** — the 512-gene STRING association profile. Nothing else. |
| method | regularised CCA, PCA-reduced per view, components and ridge by 5-fold on training proteins only |
| grid | k_x ∈ (8, 16, 32), k_y ∈ (4, 8), ridge ∈ (0.2, 1.0) — unchanged, and used identically inside every permutation |
| compartment removal | **both views** residualised on the compartment one-hot, training-fitted |
| permutations | **1,000** |
| images | 4 fields per protein, 192×192 tiles at native 0.2 µm, the 36-d descriptor, all unchanged |
| seed | 20260915 |

## Hypotheses

**H4 — identification, on a harder test.** Pooled over compartments, top-1
retrieval exceeds chance by more than the 1,000-fold permutation null, with the
protein-clustered interval excluding chance. **This is the registered primary
outcome, and it is retrieval, not correlation** — the earlier run showed GO
reaching a correlation of 0.370 at p = 0.000 while identifying proteins at less
than half of chance, so correlation alone is not evidence of identification.

**H5 — it scales the right way.** Top-1 will fall in absolute terms as candidate
sets grow from 8 to 45; what must hold is the **ratio to chance**. Registered
prediction: a lift of at least **2×** pooled. The earlier 0.245 against 0.132 was
1.9×.

**H6 — the mechanism is complex co-membership.** Held-out proteins that have a
co-located measured interaction partner in the training set are identified
better than those that do not. The split is already fixed in
[`compartment_interactions.csv`](../data/vcell/opencell/compartment_interactions.csv)
and is not chosen after the fact. **If H6 fails while H4 passes, the feature
works for a reason I do not understand**, which is worth saying plainly.

**The true null must hold.** Every candidate given an identical fingerprint must
return top-1 of exactly zero, by the same pessimistic tie-breaking that made the
OpenCell null exact. If it does not, nothing else in the run counts.

## What would falsify

H4 failing at 45-way while it passed at 8-way is the most likely single outcome,
and it would mean the earlier result was the best of sixteen tries on a small
candidate set — i.e. a multiple-comparisons artefact, which is what a
confirmatory test is for. That outcome will be reported as the headline if it
happens.

## Discipline

* Split by protein; no image of a held-out protein reaches training.
* Protein-clustered bootstrap for every interval.
* Chance printed next to every retrieval number.
* One fingerprint, one primary outcome, registered here.
* The 25-structure and 479-protein samples are **supersets** of the earlier ones,
  so neither experiment can be a re-roll of a favourable draw.
