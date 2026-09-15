# Result: the two registered scale-ups

Reports [`PREREG_SCALE.md`](PREREG_SCALE.md) as registered. Every hypothesis in
that document appears below with its registered threshold next to the number,
whether it passed or not.

**Experiment 2 is complete and its registered primary outcome failed.**
Experiment 1 is still running and its section is marked as such.

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

---

# Experiment 1 — 25 structures in one virtual cell

**Still running.** The model is training on 2,000 cells over the 25 Allen lines
(AAVS1, ACTB, ACTN1, ATP2A2, CETN2, CTNNB1, DSP, FBL, GJA1, HIST1H2BJ, LAMP1,
LMNB1, MYH10, NPM1, NUP153, PXN, RAB5A, SEC61B, SLC25A17, SMC1A, SON, ST6GAL1,
TJP1, TOMM20, TUBA1B) at the registered 25 epochs, after which H1, H2 and H3 are
scored over the 300 pairs. This section will be filled in from that run and from
nothing else.
