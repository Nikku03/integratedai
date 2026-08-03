# Study: the ADRN model

An outside read of [`nikku03/cell@claude/vectorize-gex-propensity-zp09w8`](https://github.com/nikku03/cell/tree/claude/vectorize-gex-propensity-zp09w8/adrn_package)
`adrn_package/` — 38 experiment scripts, 5 physics modules, one harness, 40 JSON
result artifacts, at commit `7096bac`. No data files ship with it, so `results/`
is the auditable record and nothing here was re-run.

The package is unusually honest — its own README opens by telling you what it is
*not*, and lists its measured negatives so you do not repeat them. This study
takes that at face value and checks the headline claims against the JSON, which
is the only thing a reader can actually verify.

---

## Verdict at a glance

| question | answer |
|---|---|
| Does "ADRN" name one thing? | **No.** A neural architecture and a biology pipeline share the name. |
| Does the neural ADRN work? | **No.** 0/6 pre-registered gates on its own nominated tasks. |
| Does the ADRN *mechanism* carry the biology result? | **No.** Conjunction growth ties its own shuffle, its own random control, and a rotation that was supposed to destroy it. |
| Does the biology pipeline beat its baselines? | **Yes, clearly.** 0.2327/0.2893 vs a 0.1737/0.2003 frequency prior, controls all resolved. |
| What is doing the work? | **A ridge on 696 named annotation channels.** No ADRN component is in the headline model. |
| How much headroom is left? | **~11–15%** of the floor→ceiling range consumed. The cap is representational, not statistical. |
| Anything worth importing here? | **`harness/robustness.py`.** 126 lines, domain-agnostic, and it addresses a hole in our own pre-registrations. |

---

## 1. Two different things are called ADRN

This is the first thing to get straight, because the package's headline number
and the package's name come from different objects.

**ADRN-the-architecture** (`code/adrn_control_suite.py`, spec sections 21–22) is
a neuromorphic model: dendritic branches, eligibility traces, fast/slow weight
timescales, adaptive halting, structural plasticity. Every one of those
mechanisms is about *time*.

**ADRN-the-pipeline** (`code/adrn_ko_conjunctions.py` and descendants) is a
static tabular predictor:

```
gene → binary named annotation channels → ridge → mixture over 60 NMF
components → score over 8,246 genes → top 20
```

plus "ADRN-3 conjunction growth": build products of channels, score each by
`|mean(product × residual)| · √n`, keep the top 64 of 20,000 candidates.

The task is Replogle K562 genome-wide Perturb-seq — 5,120 perturbations ×
8,246 genes. For a held-out knockout, name the 20 genes that move.
Metric: precision@20 on two sealed 200-knockout cohorts, predictions committed
before answers were opened.

The leakage discipline is genuinely strict and worth stating, because it makes
the positive result credible: both sealed cohorts are removed *before* the NMF
is factorised, not just the knockout being predicted; channel *selection* is by
training frequency only; the binarisation threshold is the training median only;
conjunctions are grown on the training residual only; the held-out knockout's
own profile row is never read.

---

## 2. The neural ADRN failed its own positive control

`adrn_control_suite.py` runs before any biology, on the three tasks the ADRN
spec itself nominates, against baselines built to a matched ~12,000-parameter
budget (realised: 11,018–11,986, printed per arm). Unit of replication is the
seed — 4 independent inits and data draws. Gate: beat the best baseline by more
than `MDE = 3·sd/√n`.

```
                          ADRN    best baseline           gap      MDE   gate
1 temporal XOR          0.5317    0.7749 (Transformer)  -0.2432   0.2575  FAIL
2 delayed association   0.9980    1.0000 (GRU)          -0.0020   0.0024  FAIL
3 context-dependent map 0.5815    1.0000 (GRU)          -0.4185   0.3810  FAIL
```

Plus three ablation gates ("dendrites contribute"), all FAIL — removing
dendrites *helps* on tasks 1 and 3 (+0.0171, +0.0259). **0/6.**

**Being fair about what this does and does not show.** The formal verdict is
0/6, but the three tasks are not equally informative:

- **Task 2 is saturated.** MLP, GRU and ADRN are all at or within 0.2% of 1.0000.
  A task at ceiling adjudicates nothing, and the author's own docstring says so
  about an earlier version. Counting it as a FAIL is defensible bookkeeping but
  it is not evidence.
- **Task 1 was solved by exactly one arm.** MLP 0.545, GRU 0.485, LIF 0.513,
  ADRN 0.532 — all at chance. Only the Transformer clears it, at 0.7749 with
  sd 0.197 across per-seed values `[0.883, 0.756, 0.955, 0.506]`. So this is not
  "ADRN loses to a GRU"; it is "nothing recurrent solved three-way parity at
  this budget, and the one arm that did is high-variance."
- **Task 3 is the clean loss.** GRU 1.0000, ADRN 0.5815 — near chance on a
  gating task built to favour branch gating and apical context. This one counts.

So the honest reading is *one decisive refutation, one uninformative tie, one
task nobody but the Transformer solved* — not three independent defeats. That
is still fatal to the claim being tested. The file's own framing is the right
one: if the primitive cannot carry its advantage on tasks designed for it, then
any null it produces on static tabular biology is uninterpretable, because a
broken implementation and an inapplicable mechanism look identical there.

---

## 3. The ADRN mechanism does not carry the biology result either

`adrn_ko_conjunctions.py` pre-registers, in the file, before running:

> SUCCEEDS only if `adrnconj` > frequency AND > `adrnshuf` AND > `adrnlin`, and
> `adrnrot` loses most of the gain.

From `results/adrn_ko_compare.json`, paired per-knockout, 10,000-sample
bootstrap:

```
contrast                      cohort 1                     cohort 2
conj - linear   (mechanism)   +0.0095 [+0.0022,+0.0172]    +0.0040 [-0.0032,+0.0115]
conj - shuffled (noise)       +0.0100 [-0.0013,+0.0225]    +0.0065 [-0.0020,+0.0150]
conj - random   (structure)   +0.0025 [-0.0053,+0.0108]    +0.0055 [-0.0010,+0.0120]
conj - rotated  (alignment)   +0.0052 [-0.0053,+0.0163]    +0.0025 [-0.0083,+0.0130]
```

Three of four conditions fail on both cohorts; the fourth resolves on one.

The rotation result is the most damaging, because the entire premise of the file
is that ADRN-3 needs an axis-aligned named basis — the docstring argues at
length that a PCA rotation "deletes the object the mechanism searches for," and
that this explains ADRN's earlier failure on principal-component inputs. The
rotated arm grew **64 conjunctions, the same as the aligned arm**, and scored
within noise of it. The diagnosis that motivated the work does not reproduce.

`adrn_ko_stability.py` explains why, and it is the sharpest single artifact in
the package:

```
threshold 4.0, keeping top 64 of 20,000 candidates
  score at rank 1  7.4342   rank 64  6.6144   rank 65  6.6008   rank 200  5.9101
  gap between last kept and first dropped:            0.0136
  candidates within 1% of the rank-64 score:          78
  candidates clearing the threshold at all:           912
seed spread (4 independent candidate pools)
  pairwise overlap of the grown 64-sets: [7, 6, 9, 5, 8, 3]   mean 6.33
  overlap expected by chance:                                 0.20
```

912 candidates clear the bar and 64 are kept. The rank-64/rank-65 gap is 0.0136
on scores near 6.6. Four independent pools rediscover ~10% of each other's set.
The growth rule is not identifying specific biological products — it is drawing
an arbitrary sample from a large equivalence class of near-tied features, which
is exactly why shuffling, randomising and rotating all produce the same score.

**Consequence: the package's headline model contains no ADRN component.**
`chan2a` — the 0.2327/0.2893 arm the README leads with — is built in
`adrn_ko_channels2.py`, where the arms go straight from channel matrix to
`ridge_fit`. There are no conjunctions in it at all.

---

## 4. What actually works, and it is the boring part

Stripped of the mechanism, the result stands up well.

```
arm                             cohort 1   cohort 2   what it is
chan2a (696 named channels)       0.2327     0.2893   the deployed model
chan2a + DepMap co-dependency     0.2540     0.3128   best measured block
adrnlin (170 named channels)      0.2127     0.2620   same model, fewer channels
incumbent nbr (neighbour xfer)    0.1886     0.2293
incumbent basis                   0.1873     0.2013
frequency baseline                0.1737     0.2003   "predict what always moves"
chan2perm (rows permuted)         0.1233     0.1535   leakage control
```

A 20-gene list with ~4.7–6.3 correct against ~3.2–4.0 free from the frequency
prior. Every control resolves in the right direction, and the permuted arm lands
*below* the frequency baseline rather than at it, which is the signature of a
control that is actually destroying signal rather than leaking it.

The decisive contrasts say the lever was **vocabulary, not modelling**:

```
chan2a - adrnlin  (more channels)   +0.0210 RESOLVED   +0.0265 RESOLVED
trees - chan2a    (nonlinearity)    +0.0010 ns         +0.0035 ns
adrn - ridge      (programme model) -0.0072 RESOLVED negative
e2e_full - chan2a (end-to-end)      -0.0548 RESOLVED   -0.0825 RESOLVED
chan2b - chan2a   (measured priors) +0.0007 ns         -0.0032 ns
```

Going 9 lesion channels → 170 → 696 paid. Gradient-boosted trees, a learned
programme model, and end-to-end learning all tied or lost. And `chan2b` tying
`chan2a` is a good sign for the honesty of the framing: the Tier B arm that adds
DepMap viability, protein abundance and FBA essentiality — measurements rather
than curation — adds nothing, so the "predicts from annotation" claim survives
its own strongest attack. The author separated those tiers *before* seeing the
result, specifically so that a gain from lookup could not be reported as biology.

The off-annotation gate matters too: the model predicts movers that lie outside
the knocked-out gene's own annotations at 0.1696/0.2107 against a chance rate of
0.0028/0.0052. It is not merely echoing the input dossier back.

---

## 5. The ceiling map, which is where the real news is

`adrn_ko_ceiling.py` prices the result before anyone optimises past it.

```
                                    cohort 1   cohort 2
ABSOLUTE (best 20 with answers)       0.6330     0.7097
basis oracle (through the 60 NMF)     0.4440     0.5222
profile-NN oracle (retrieval)         0.4053     0.4680
TWIN CEILING (any channel function)   0.5365     0.6212
  DEPLOYED adrnconj                   0.2222     0.2660
  frequency floor                     0.1737     0.2003
  → fraction of twin range covered      10.8%      14.7%
```

And the identifiability numbers, which are the ones to remember:

- **99/200 and 89/200** sealed knockouts have an *exact* channel twin in
  training. Mean cosine to nearest training neighbour in channel space: 0.95.
- Two knockouts that are **identical on paper share 6.9% / 6.4%** of their
  actual movers (Jaccard).

That last line is the whole story. Roughly half the held-out knockouts are
indistinguishable to the representation, and when they are indistinguishable
their true answers barely overlap. No estimator can separate them. The binding
constraint is the annotation vocabulary, not the model class — which is
consistent with everything in §4, where every attempt to improve the *model*
tied and the one thing that paid was more *channels*.

---

## 6. Which extra data sources survive a sweep

This is where `harness/robustness.py` earns its place, and the finding is a
methodological one.

```
block                            verdict        cells
DepMap co-dependency             ROBUST         +17 / -0 of 18, sign-consistent
PPI vs rewired twin              DIRECTIONAL    +22 / -0 of 36 (24 needed)
PPI vs no-PPI                    DIRECTIONAL    +17 / -0 of 36
ESM-2 sequence embeddings        GATE FAIL      0.2320/0.2818 vs chan2a 0.2327/0.2893
```

The PPI story is the one to internalise. It was first reported at
**+0.0140 / +0.0152**, having survived three separate attacks on its control:
degree preserved exactly, 98.2% of edges rewired, three seeds stable, leakage
ratio 1.05×. Every one of those checks passed and every one was necessary. Then
a sweep over the SVD rank showed the effect lived in **one of six (edge-set ×
rank) cells** — the configuration that happened to be run first. `SVD_K = 128`
was a line written without deliberation and it was carrying the entire finding.

ESM-2 is a clean, useful negative: sequence embeddings beat their own shuffle
(+0.0298/+0.0360, PASS) — so protein sequence does carry signal — but adding
them to annotation channels makes the model slightly *worse*. Everything ESM-2
knows, the annotation already knew. Stratified, the only place it helped was the
11 cohort-1 knockouts that have exact channel twins (+0.0364), and that reversed
on cohort 2 (−0.0316, n=19). Which is what n≈15 does.

Data scaling is bending: +0.0286 per doubling at 250→500 training knockouts,
+0.0152 per doubling at 3,200→4,720. More of the same data is not the answer,
which is the same conclusion the ceiling map reaches from the other direction.

---

## 7. The part worth importing

`harness/robustness.py` — 126 lines, no domain dependencies, numpy only.

The argument it makes is that control checks all ask **"is the null valid?"** and
none of them asks **"is this robust to defaults I chose without thinking?"**
Those are different questions, and only the second catches a result that is
really the argmax of an unswept space. `Sweeper` enforces the second
structurally:

- refuses an axis with fewer than two values (a one-value sweep raises at
  construction, not at report time);
- refuses a config that is not in the declared grid;
- **raises on a verdict from a single cell**;
- the ladder — ROBUST / DIRECTIONAL / FRAGILE / NULL / HARMFUL — is fixed in the
  module before any numbers arrive, so it cannot be renegotiated once they are.

`FRAGILE` is the load-bearing rung: resolved somewhere but sign-inconsistent, or
resolved in exactly one cell of four or more. That is what the argmax of an
unswept space looks like, and the report string says in words that it must not
be reported as a finding.

**Why this is relevant to us.** Our `docs/PREREGISTRATION_*.md` files commit to
thresholds, directions and sample sizes before the result — which is the right
discipline and it caught the clinical-readout rule (`+9.86%` on 11 trades →
`−2.20%` on 940). But they pre-register a *point*, not a *grid*. The burn-rank
window, the latency split boundary, the `rvol` gate, the triple-barrier
horizon, the ADV floor — each of those is a value someone picked once. A rule
that survives its null but only at one window length is the same object as
`SVD_K = 128`, and we currently have no structural way to notice.

The author's own caveat should be carried across: `Sweeper` counts
`config × cohort` cells as independent, but two cohorts within a config share a
fitted model and are correlated, so resolved-cell counts are optimistic.
Sign-consistency across cells is the more trustworthy signal. For us the
analogous trap is counting overlapping time windows as independent cells.

---

## 8. Defects found

Three, all in the reporting layer rather than the science. None changes a
measured number.

**8.1 — The README mislabels the ceiling's `absolute` row.** It is reported as
"same-knockout re-measurement — 0.6330 / 0.7100", which reads as an assay
reproducibility figure, i.e. a noise ceiling. It is not.
`adrn_ko_ceiling.py:123` computes it as `min(20, |truth|)/20` — the best
possible 20-gene list given the answers, bounded below 1.0 only because many
knockouts have fewer than 20 movers. It is a truth-size artifact. The file's own
docstring names it correctly ("the best possible 20 genes, chosen with the
answers in hand"); the README does not. This is the row that makes the deployed
model look furthest from the achievable, so the wrong name is not a neutral
slip.

**8.2 — A corrected label survives in the printed ceiling table.** The docstring
was fixed in place — "THIS WAS FIRST WRITTEN AS A CEILING AND IT IS NOT ONE" —
but the report table still prints `channel_nn` under the column "what it bounds"
with the text *"any function of the named channels"*, which is the retracted
claim. Because the deployed model beats it, the shipped log contains two
`fraction of the channel_nn range covered by the deployed model: nan%` lines
with a "cap" below the floor. Correcting the prose and leaving the table is how
a retracted claim gets re-read as current.

**8.3 — The README's negatives list omits the two most consequential ones.**
It lists, helpfully and unprompted: drug-response transfer, cross-cell-type
pooling, end-to-end learning, encoder equivalence, ESM-2, data scaling. It does
not list that the ADRN conjunction mechanism failed three of four pre-registered
conditions, or that the ADRN positive control went 0/6. Both are in the code
docstrings and both are in the JSON, so nothing is hidden — but a reader of the
README alone would conclude that the ADRN mechanism is part of what earns
0.2327, and it is not. For a document whose stated purpose is "read the scope
section before benchmarking it," this is the omission most likely to waste the
reader's time.

---

## 9. What I would take from this

1. **The `Sweeper` discipline, ported to our pre-registrations.** Declare the
   grid of undeliberated defaults alongside the threshold. This is the highest-
   value transfer and it is 126 lines.
2. **The tier separation habit.** Splitting "curation" from "looked-up
   measurement" *before* running, so a gain from lookup cannot be reported as
   reasoning, is directly analogous to splitting point-in-time features from
   anything with a restatement path. We do this for timing; we do not do it as
   explicitly for provenance.
3. **Pricing the ceiling before optimising.** The identifiability measurement —
   how often are two items indistinguishable to the representation, and when
   they are, how much do their outcomes actually agree — is a cheap, general
   diagnostic. Our analogue: how often do two catalyst events share a feature
   vector, and when they do, do their forward returns agree at all? If the answer
   is 6%, no model change matters and the honest next step is new features.
4. **Nothing from the physics side.** `physics/extrude.py`'s gate failed on the
   author's own numbers (shuffled control 0.6806 vs real 0.6779, net
   −0.0027 ± 0.0052), and the package says so up front.
