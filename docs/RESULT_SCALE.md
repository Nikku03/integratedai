# Result: the two registered scale-ups

Reports [`PREREG_SCALE.md`](PREREG_SCALE.md) as registered. Every hypothesis in
that document appears below with its registered threshold next to the number,
whether it passed or not.

**Both experiments are complete. Experiment 1 passed all three of its
hypotheses; Experiment 2's registered primary outcome failed.** The two together
say the same thing the project has said throughout: the compartment is
predictable and the protein is not.

---

# Experiment 1 — 25 structures in one virtual cell

## Verdict

| hypothesis | registered threshold | observed | |
|---|---|---|---|
| **H1** the arrangement holds over 300 pairs | Pearson > **0.85**, Spearman > **0.75** | **0.985** / **0.959** | **PASS** |
| **H2** not carried by the nuclear/cytoplasmic split | Pearson > **0.70** within each block | cytoplasmic **0.796** (153 pairs), nuclear **0.964** (21 pairs) | **PASS** |
| **H3** accuracy does not collapse with breadth | mean Dice within **20% relative** of the five-structure mean | 0.244 vs 0.280, **−12.9%** | **PASS** |

All three pass. This is the first registered experiment in the project where
that happens, and the reasons it is weaker than it looks are in the two
subsections after the tables.

## What was run

2,000 Allen cells over all **25** tagged lines (80 interphase cells each, same
QC filter), 1,600 training / 400 held out by FOV, the same 826k-parameter 3D
U-Net at grid (24, 48, 48), 25 epochs, seed 20260915 — every parameter as
registered. Final training KL 0.1648. The joint virtual cell is built on the
**400 held-out** cells' geometries.

## H1 / H2 — the pairwise arrangement

Wasserstein-1 between structures' signed-nuclear-distance profiles, measured
between structures imaged in *different* cells and predicted onto *one* cell:

| pair set | pairs | Pearson | Spearman | MAE | measured range |
|---|---|---|---|---|---|
| all pairs | **300** | **0.985** | 0.959 | 0.129 µm | 0.05 – 3.35 µm |
| cytoplasmic only | 153 | **0.796** | 0.782 | 0.140 µm | 0.08 – 1.20 µm |
| nuclear only | 21 | 0.964 | 0.978 | 0.076 µm | 0.05 – 1.19 µm |

**At 30× the pairs, the pooled correlation barely moved** — 0.985 against the
five-structure study's 0.990 over 10 pairs. The arrangement claim is the one
thing in this project that got *harder* to test and did not degrade.

**But the registered concern was right, and H2 is where it shows.** Restricted
to the 153 cytoplasm–cytoplasm pairs, the correlation falls to **0.796** from the
five-structure study's 0.959 over its 6 non-nuclear pairs. It clears the
registered 0.70, so H2 passes as written — but the pooled 0.985 *is*
substantially carried by the nuclear/cytoplasmic contrast, exactly as
[`PREREG_SCALE.md`](PREREG_SCALE.md) warned. The honest summary: the model knows
which side of the nuclear envelope a structure lives on very well, and orders
structures *within* the cytoplasm considerably less well. The cytoplasmic MAE of
0.140 µm against a measured spread of only 1.12 µm is about 12% of the full
range, against 6% for the nuclear pairs over a comparable span.

## H3 — per-structure accuracy across 25 conditions

Volume-matched Dice on held-out cells, 16 per structure, against the
parameter-free annotation rule and against each structure's own measured chance
level (the base rate its voxel count implies):

| structure | Dice | rule | chance | lift |
|---|---|---|---|---|
| LMNB1 | 0.501 | 0.516 | 0.095 | 5.29× |
| NPM1 | 0.473 | 0.100 | 0.040 | 11.84× |
| FBL | 0.471 | 0.048 | 0.030 | 15.92× |
| AAVS1 *(control)* | 0.455 | 0.220 | 0.172 | **2.65×** |
| TJP1 | 0.378 | 0.065 | 0.007 | 53.68× |
| LAMP1 | 0.372 | 0.081 | 0.047 | 7.92× |
| CTNNB1 | 0.359 | 0.043 | 0.034 | 10.47× |
| SEC61B | 0.326 | 0.244 | 0.110 | 2.97× |
| NUP153 | 0.317 | 0.141 | 0.031 | 10.06× |
| SON | 0.306 | 0.056 | 0.021 | 14.44× |
| ATP2A2 | 0.270 | 0.183 | 0.112 | 2.41× |
| TOMM20 | 0.262 | 0.137 | 0.088 | 2.98× |
| HIST1H2BJ | 0.261 | 0.122 | 0.052 | 4.99× |
| ACTB | 0.224 | 0.106 | 0.035 | 6.43× |
| ACTN1 | 0.216 | 0.105 | 0.029 | 7.36× |
| MYH10 | 0.209 | 0.117 | 0.036 | 5.83× |
| ST6GAL1 | 0.204 | 0.013 | 0.021 | 9.70× |
| TUBA1B | 0.155 | 0.150 | 0.112 | **1.39×** |
| GJA1 | 0.119 | 0.012 | 0.004 | 30.01× |
| RAB5A | 0.039 | 0.006 | 0.006 | 6.91× |
| DSP | 0.030 | 0.000 | 0.001 | 57.99× |
| SMC1A | 0.028 | 0.008 | 0.003 | 8.93× |
| SLC25A17 | 0.015 | 0.004 | 0.005 | 2.73× |
| PXN | **0.000** | 0.009 | 0.002 | 0.00× |
| CETN2 | **0.000** | 0.000 | 0.000 | 0.00× |

Mean Dice **0.2436** [0.1792, 0.3024]. The five-structure study's mean over its
five real structures (ACTB 0.193, SEC61B 0.344, TOMM20 0.223, LMNB1 0.482,
TUBA1B 0.157) is 0.2798, so the change is **−12.9%** and H3 passes as
registered. The verdict is somewhat sensitive to how the comparison is drawn:
over the 24 real structures alone (0.2306) it is −17.6%, still inside the
threshold; against a baseline that also includes the AAVS1 control (0.3057) it
is −20.3%, marginally outside. Only the first is the registered comparison.
**Breadth cost roughly an eighth of the accuracy, not a collapse** — that is the
finding, and it is robust to the two-thirds of readings that pass.

### Three things the table says that the verdicts do not

**Six of 25 structures essentially failed.** CETN2 (centrosome) and PXN (focal
adhesions) score **exactly 0.000**; SLC25A17 (peroxisomes) 0.015, SMC1A
(cohesin) 0.028, DSP (desmosomes) 0.030, RAB5A (early endosomes) 0.039. Their
base rates are the giveaway — CETN2 occupies 0.018% of the cell's voxels and PXN
0.18%. At a (24, 48, 48) grid a centrosome is well under one voxel, so this is
at least as much a resolution ceiling as a model failure, and the mean of 0.244
is an average over conditions where the target is physically representable and
conditions where it is not. Nothing in H3 distinguishes the two.

**The structureless control is still fourth on raw Dice.** AAVS1 — a safe-harbour
locus with no tagged structure — scores 0.455, above 21 of the 24 real
structures. On lift over its own base rate it drops to 2.65×, 22nd of 25, which
is what a channel with no structure in it should do. This reproduces the trap
that [`RESULT_VIRTUAL_CELL.md`](RESULT_VIRTUAL_CELL.md) had to correct gate 4
for, now at 25 structures, and confirms that **raw volume-matched Dice is not
interpretable across structures with different base rates.** Only the lift column
means anything in comparisons.

**Lift is inflated where Dice is near zero.** DSP's 57.99× comes from a Dice of
0.0299 against a base rate of 0.0005. A high ratio on a near-zero numerator is
not an achievement, and a reader scanning the lift column alone would rank DSP
first. Both columns have to be read together: the structures that are genuinely
well predicted are the ones with a substantial Dice *and* a substantial lift —
NPM1, FBL, TJP1, LAMP1, CTNNB1, NUP153, SON.

**LMNB1 is still beaten by the parameter-free rule** (0.501 against 0.516), as it
was at five structures. The nuclear envelope remains the one structure a
one-line geometric rule predicts better than the model.

## What Experiment 1 settles

The virtual cell **scales to 25 structures without collapsing**, and the joint
arrangement — structures measured in different cells, predicted into one — holds
over 300 pairs at 0.985. That is the project's strongest positive result and it
is now registered rather than exploratory.

What it does not show: that the model orders structures well *within* the
cytoplasm (0.796, and the weakest block), that small or punctate structures are
predictable at this resolution (six are not), or that anything here identifies a
*protein* rather than a *compartment* — Experiment 2 is the test of that, and it
failed.

---

# Experiment 2 — the 45-way identification

## Verdict

| hypothesis | registered threshold | observed | |
|---|---|---|---|
| **H4** identification | top-1 above the 1,000-permutation null, interval excluding chance | 0.0392 vs chance 0.0458, p = 0.722 | **FAIL** |
| **H5** it scales | lift ≥ **2×** pooled | **0.86×** | **FAIL** |
| **H6** mechanism is co-membership | with-partner identified better than without | 0.69× vs 0.98×, p = 0.693 | **FAIL** |
| **true null** | exactly 0.0000 | **0.0000** | **PASS** |

**The headline is the one `PREREG_SCALE.md` registered as most likely: the 8-way
STRING result does not reproduce at 43-way.** That document said "H4 failing at
45-way while it passed at 8-way is the most likely single outcome, and it would
mean the earlier result was the best of sixteen tries on a small candidate set
… That outcome will be reported as the headline if it happens." It happened.

## What was actually run

| | registered | run |
|---|---|---|
| proteins | 479 | **461** — 18 lost to image download/QC (12 training, 6 held out): BOP1, BRD2, CANX, DCP1B, DDX39B, FAM241A, HDAC1, LDHA, MBOAT7, NAPG, POLR2A, PRPF8, RAD17, RBM28, RPS18, RPS6KA1, SLX9, SMN1 |
| split | 320 / 159 | **308 / 153**, the registered seeded split with those 18 removed |
| candidate sets | 45, 36, 28, 15, 15, 12, 8 | **43, 35, 27, 15, 14, 11, 8** |
| fingerprint | `string_profile` alone | unchanged |
| permutations | 1,000 | 1,000 |
| compartment removal | both views, training-fitted | unchanged |
| seed | 20260915 | unchanged |

The 18 drops are image-side and independent of the fingerprint, so they shrink
the test rather than bias it. Selected hyperparameters: k_x = 32, k_y = 8,
ridge = 1.0.

## H4 — the registered primary outcome: fail

```
pooled top-1   0.0392  [0.0131, 0.0719]   chance 0.0458   lift 0.86x
permutation null p95   0.0784             p = 0.722  (1000 permutations)
MRR            0.1779                     chance MRR 0.1614  (1.10x)
shared-space correlation 0.246            p = 0.001
TRUE NULL top-1 = 0.0000                  (required: exactly 0)
```

Six held-out proteins out of 153 identified correctly, where chance gives seven.
The protein-clustered interval [0.013, 0.072] contains chance and does not
exclude it. The permutation null's 95th percentile is 0.078 — twice the observed
value. On the registered primary outcome this is not a weak effect, it is no
effect.

**The correlation is significant and the identification is not** — 0.246 at
p = 0.001, with held-out canonical correlations [0.246, 0.242, 0.009]. Two solid
directions and a dead third. This is the third time in this project that a
significant shared-space correlation has come with useless retrieval, and it is
why `PREREG_SCALE.md` registered retrieval as the primary outcome rather than
correlation. Had the primary outcome been correlation, this experiment would be
reported as a pass.

**The true null is exact.** Giving every candidate an identical fingerprint
returns top-1 of exactly 0.0000 under pessimistic tie-breaking, as registered.
The machinery is sound; the result is a real negative, not a broken pipeline.

## Per compartment

| compartment | candidates | top-1 | correct | chance | lift | interval |
|---|---|---|---|---|---|---|
| membrane | 8 | **0.250** | 2/8 | 0.125 | 2.00× | [0.000, 0.500] |
| cytoplasmic | 43 | 0.047 | 2/43 | 0.023 | 2.00× | [0.000, 0.116] |
| nucleoplasm | 27 | 0.037 | 1/27 | 0.037 | 1.00× | [0.000, 0.111] |
| vesicles | 35 | 0.029 | 1/35 | 0.029 | 1.00× | [0.000, 0.086] |
| er | 15 | 0.000 | 0/15 | 0.067 | 0.00× | [0.000, 0.000] |
| nucleolus_gc | 14 | 0.000 | 0/14 | 0.071 | 0.00× | [0.000, 0.000] |
| chromatin | 11 | 0.000 | 0/11 | 0.091 | 0.00× | [0.000, 0.000] |

Three compartments identify nothing at all. Every interval includes chance.

**The one place the 8-way effect reappears is the one candidate set of size 8.**
Membrane gives 2 of 8 against an expected 1, a 2.00× lift — almost exactly the
1.9× that part two of `RESULT_PROTEIN_DESCRIPTION.md` reported at 8-way.
Cytoplasmic matches that lift at 43-way, on 2 correct out of 43. Both are two
successes. Neither interval excludes chance, and a 2× lift from two hits is what
a small-numbers coincidence looks like. The honest reading is that the earlier
result was measured where two lucky hits buy a 2× lift, and that the effect does
not survive being asked a harder question — not that identification works at 8
candidates and fails at 43.

## H5 — it scales the right way: fail

Registered prediction: the absolute top-1 falls as candidate sets grow, but the
lift over chance holds at **2× or better**. Observed lift is **0.86×** — below
chance, not merely below the threshold. H5 was conditional on H4 and fails with
it.

## H6 — the mechanism is complex co-membership: fail

The registered mechanism test: held-out proteins with a co-located measured
interaction partner in the training set should be identified better than those
without. 58 of the 153 held-out proteins have one.

| group | n | top-1 | correct | chance | lift | MRR/chance | mean rank |
|---|---|---|---|---|---|---|---|
| with a co-located training partner | 58 | 0.034 | 2 | 0.050 | **0.69×** | 0.994 | 12.67 |
| without | 95 | 0.042 | 4 | 0.043 | **0.98×** | 1.177 | 12.68 |

Difference in lift **−0.29×** (p = 0.693), difference in MRR ratio −0.18
(p = 0.726), over 10,000 permutations of the has-partner label *within
compartment*, holding every rank fixed. The group that should have done better
did slightly worse, well inside noise. Mean rank is 12.67 against 12.68 — the
two groups are indistinguishable.

`PREREG_SCALE.md` said "if H6 fails while H4 passes, the feature works for a
reason I do not understand." H6 and H4 both failed, which is the coherent
outcome: there is no effect whose mechanism needs explaining.

**One deviation to record.** The prereg pointed at
[`compartment_interactions.csv`](../data/vcell/opencell/compartment_interactions.csv)
as fixing the split "and not chosen after the fact." Its *pairs* are fixed and
were used as registered, but its `a_split` column was written for the earlier
53-protein sample and disagrees with the registered split on 165 of its 471
rows. The label was therefore recomputed from the same source — an OpenCell
measured partner sharing the protein's dominant compartment — against the
registered split, in [`scripts/vcell_h6_mechanism.py`](../scripts/vcell_h6_mechanism.py).
That is the prereg's stated definition; the file it pointed at could not supply
it directly. Both the direction and the p-value are far from significance, so
the choice does not carry the result.

## What Experiment 2 settles

**Nothing tested in this project identifies which protein produced an image,
given its compartment.** Four studies have now asked it: annotation-conditioned
prediction, eight hand-built descriptions by regression, sixteen fingerprint
combinations by shared-space matching, and a 20-number physical fingerprint from
AlphaFold structures. The two results that looked like exceptions were a small
candidate set (this experiment) and a correlation mistaken for an identification
(`go_process_function`, and now `string_profile` itself).

What remains true and is not weakened by this:

* **The images do carry protein-specific signal.** Gate 1 of
  [`RESULT_OPENCELL.md`](RESULT_OPENCELL.md) discriminates within compartment
  without any model — vesicles 0.762 against a chance of 0.125 — with a
  split-half reliability of 0.537 and survival of a same-plate batch control.
  The signal is in the pixels. No *description* reaches it.
* **The compartment is predictable and the protein is not.** That separation has
  held across every study and is the project's most reproducible finding.
* **The irreducible confound stands.** OpenCell grows one line per well, so
  protein and clone cannot be separated in this dataset at all. A positive
  result here would have needed multiple independent clones per protein or a
  transient-expression design before it could be believed, and this is not a
  positive result.
