# Result: the pixels know which protein it is; the annotation does not

Pre-registered in [`docs/PREREG_OPENCELL.md`](PREREG_OPENCELL.md). 168 OpenCell
targets across 7 compartments, 1,516 tiles at native 0.2 µm, seven trained
models, retrieval against a chance of 1/8.

Every number comes from `scripts/vcell_opencell.py` and
`scripts/vcell_opencell_result.py` reading the run's own JSON, committed under
[`data/vcell/opencell/`](../data/vcell/opencell/).

## The short version

| registered item | verdict |
|---|---|
| **gate 1** — is a protein identifiable from its own pixels? | **passes for 5 of 7 compartments.** ER fails; nucleolus GC is indeterminate |
| **H1** — can the model pick the right protein from annotation? | **fails in every compartment**, in both the circular and non-circular forms |
| **H2** — against the no-model reference | the fixed descriptor reaches 0.76 where the model reaches chance |
| **H3** — which knowledge block carries it | **none of them.** Every ablation sits at chance |
| **H3's null** — the harness check | **the registered null was not a null.** Fixed, re-run, and the corrected null is exact |
| **H4** — conditioning or template? | **uninformative**, because the model never discriminates in the first place |

One sentence: **within a compartment, proteins are individually recognisable
from their images — and abundance, protein family and a measured interactome
cannot find them.** The registered expectation was that H1 would fail or barely
clear chance. It failed.

## Gate 1 — the question that had to come first

A fixed 36-dimensional descriptor (nuclear-distance profile, granulometry,
intensity-distribution shape, radial power spectrum), no learning, no
annotation. Nearest neighbour within the 8-protein candidate set, tiles from a
tile's own field of view excluded — without that exclusion two tiles cut from
one image match on shared illumination and the gate passes everywhere for a
reason that has nothing to do with the protein.

| compartment | candidates | tiles | descriptor top-1 | chance | MRR | chance | gate 1 |
|---|---|---|---|---|---|---|---|
| vesicles | 8 | 80 | **0.762** [0.652, 0.875] | 0.125 | 0.860 | 0.340 | passes |
| nucleoplasm | 8 | 53 | **0.604** [0.297, 0.797] | 0.125 | 0.727 | 0.340 | passes |
| membrane | 8 | 84 | **0.417** [0.254, 0.568] | 0.125 | 0.626 | 0.340 | passes |
| chromatin | 8 | 70 | **0.386** [0.265, 0.473] | 0.125 | 0.584 | 0.340 | passes |
| cytoplasmic | 8 | 94 | **0.340** [0.265, 0.430] | 0.125 | 0.562 | 0.340 | passes |
| nucleolus_gc | 6 | 44 | 0.568 [0.133, 0.831] | 0.167 | 0.721 | 0.408 | **indeterminate** |
| er | 7 | 82 | 0.195 [0.065, 0.317] | 0.143 | 0.434 | 0.370 | **fails** |

**This refutes the registered expectation in both directions.** On the record
before the run: *"Gate 1 passes for `er`, `nucleolus_gc`, `chromatin`,
`vesicles` and `membrane`, and is at or near chance for `cytoplasmic` and
`nucleoplasm` — the two diffuse classes, which are included precisely because
they should be the hard ones."*

The opposite happened on both counts. **ER fails**: Sec61β, EMC2, EMC3, DDOST,
ARF4 and the rest all paint the same reticulum at 0.2 µm, and a descriptor
cannot tell them apart. **The two diffuse classes pass comfortably**, because
"cytoplasmic" and "nucleoplasm" are not a morphology, they are a residual
category — a grab-bag whose members happen to look individually distinctive.
The compartments I expected to be hard are the identifiable ones, and the
compartment I expected to be easy is the unanswerable one.

`nucleolus_gc` is reported as indeterminate rather than as a pass: the point
estimate is 3.4× chance but only 6 of its 8 candidates survived tiling and
44 tiles is not enough to separate the interval from chance.

So for five compartments the pixels demonstrably carry protein-specific signal,
and the experiment is a real test rather than a vacuous one.

### Addendum: gate 1 at the full pool, and a reproducible batch control

Both numbers in this section and the batch-control table in
[`RESULT_PROTEIN_DESCRIPTION.md`](RESULT_PROTEIN_DESCRIPTION.md) were originally
transcribed from an ad-hoc run: `gate1.json` had no producing script and the
plate assignments the batch control needs were never carried on the sample
record at all. [`scripts/vcell_gate1.py`](../scripts/vcell_gate1.py) is now the
producer for both, `Target` carries `plate_id` and `well_id`, and
[`opencell_plate_well.csv`](../data/vcell/opencell/opencell_plate_well.csv)
commits the assignments. Re-running on the **461-protein** pool used by the
scale-up rather than the original 8-way sample makes the test far harder, and it
gets stronger rather than weaker.

**Gate 1 now passes 7 of 7, with candidate sets of 25 to 130** — every interval
excluding chance, where the 8-way version passed 5 of 7:

| compartment | candidates | tiles | descriptor top-1 | chance | lift | MRR | chance MRR |
|---|---|---|---|---|---|---|---|
| membrane | 25 | 252 | **0.310** [0.196, 0.432] | 0.040 | 7.7× | 0.453 | 0.153 |
| nucleolus_gc | 41 | 268 | **0.179** [0.088, 0.276] | 0.024 | 7.3× | 0.320 | 0.105 |
| vesicles | 107 | 1033 | **0.178** [0.142, 0.217] | 0.009 | **19.1×** | 0.313 | 0.049 |
| chromatin | 35 | 303 | **0.162** [0.109, 0.216] | 0.029 | 5.7× | 0.288 | 0.118 |
| nucleoplasm | 80 | 737 | **0.117** [0.082, 0.154] | 0.012 | 9.3× | 0.247 | 0.062 |
| er | 43 | 434 | **0.104** [0.063, 0.156] | 0.023 | 4.5× | 0.218 | 0.101 |
| cytoplasmic | 130 | 1419 | **0.039** [0.028, 0.054] | 0.008 | 5.1× | 0.117 | 0.042 |

**ER and nucleolus_gc, the two that did not pass at 8-way, both pass here.** The
8-way failures were sample-size failures, not evidence of absence: ER at 7
candidates and 82 tiles gave 0.195 [0.065, 0.317] against a chance of 0.143 —
an interval too wide to separate — and at 43 candidates and 434 tiles it gives
0.104 [0.063, 0.156] against 0.023. The point estimate fell and the conclusion
reversed, which is what a bigger candidate set is supposed to do to a real
effect. Cytoplasmic identifies one protein in 26 correctly where luck gives one
in 130.

**The batch control also strengthens.** Restricting each candidate set to
proteins grown on a single plate — 71 compartment/plate cells over 435 proteins
and 21 plates, 4,191 tiles:

pooled top-1 **0.375** [0.346, 0.407] against a chance of **0.165**, a lift of
2.3× with the interval nowhere near chance. The original control reported
0.641 [0.546, 0.732] against 0.402 on 24 proteins and 231 tiles; this is 18×
the tiles and the same conclusion. **Plate identity does not explain gate 1.**

**And the irreducible confound is now measured exactly rather than asserted:**
479 proteins occupy **479 distinct (plate, well) pairs**. One line per well, so
protein and clone are perfectly confounded by construction. Everything above is
bounded by that — gate 1 establishes that these cell lines are distinguishable
from their images within a compartment, and cannot establish that the
distinguishing signal is the *protein* rather than the clone. That needs
multiple independent clones per protein or a transient-expression design, and
no analysis of this dataset can substitute.

**Why this matters for the rest of the project.** Gate 1 at 130-way and
Experiment 2 of [`RESULT_SCALE.md`](RESULT_SCALE.md) at 43-way ran on the same
461 proteins, the same compartments and the same images. The images identify the
protein at 4.5–19× chance with no model and no fitting. No *description* of the
protein — 1,726 dimensions across 16 fingerprints, plus AlphaFold biophysics —
identifies it above chance at all. The gap between those two sentences is the
project's central finding, and it is now measured on one pool at one scale.

## H1 — and it fails

Volume of evidence first, then the two forms it was run in.

**Graded compartment block** (the form originally implemented — see the section
below on why it is circular):

| compartment | n | model top-1 | chance | mismatched ref | ridge | descriptor | verdict |
|---|---|---|---|---|---|---|---|
| cytoplasmic | 94 | 0.096 [0.010, 0.189] | 0.125 | 0.138 | 0.213 | 0.340 | at chance |
| nucleoplasm | 54 | 0.185 [0.104, 0.274] | 0.125 | 0.056 | 0.222 | 0.604 | at chance |
| vesicles | 80 | 0.100 [0.015, 0.202] | 0.125 | 0.062 | 0.212 | 0.762 | at chance |
| chromatin | 70 | 0.257 [0.100, 0.406] | 0.125 | 0.071 | 0.071 | 0.386 | at chance |
| membrane | 84 | 0.095 [0.024, 0.172] | 0.125 | 0.107 | 0.226 | 0.417 | at chance |
| nucleolus_gc | 44 | 0.295 [0.118, 0.562] | 0.167 | 0.182 | 0.318 | 0.568 | gate 1 indeterminate |
| er | 82 | 0.122 [0.062, 0.190] | 0.143 | 0.220 | 0.171 | 0.195 | gate 1 failed |

**Dominant compartment block — the non-circular form, in which nothing
image-derived can separate the candidates:**

| compartment | n | model top-1 | chance | mismatched ref | ridge | verdict |
|---|---|---|---|---|---|---|
| cytoplasmic | 94 | 0.138 [0.046, 0.240] | 0.125 | 0.181 | 0.234 | at chance |
| nucleoplasm | 54 | 0.093 [0.016, 0.194] | 0.125 | 0.130 | 0.185 | at chance |
| vesicles | 80 | 0.225 [0.075, 0.374] | 0.125 | 0.113 | 0.200 | at chance |
| chromatin | 70 | 0.143 [0.012, 0.370] | 0.125 | 0.100 | 0.086 | at chance |
| membrane | 84 | 0.131 [0.053, 0.227] | 0.125 | 0.119 | 0.143 | at chance |
| nucleolus_gc | 44 | 0.045 [0.000, 0.114] | 0.167 | 0.114 | 0.091 | **below chance** |
| er | 82 | 0.134 [0.062, 0.218] | 0.143 | 0.232 | 0.159 | at chance |

Every protein-clustered interval contains the chance value, in both forms, in
every compartment. Pooled over all tiles: **0.150 [0.101, 0.202]** graded and
**0.138 [0.091, 0.188]** non-circular, against a chance of 0.131.

Vesicles is the case worth staring at. A descriptor with no learning picks the
right protein 76% of the time. The model, given that protein's abundance,
family, tagging terminus and 32-partner interactome, picks it 10–23% of the
time — which is 1/8. The information is in the image and it is not in the
annotation.

### H2 — the no-model reference, and the fair version of it

The registered comparison is against gate 1's descriptor, and it is not a fair
fight: the descriptor gets to look at **real images** of every candidate and
match a test tile against them, while the model has never seen an image of any
held-out protein. Gate 1 is therefore a statement about how much signal exists,
not a bar the model was expected to reach.

So I added a comparison the registration did not contain, because without it the
result cannot be localised: a **ridge regression from the knowledge vector to
the 36-dimensional descriptor**, fitted on training proteins only. It has exactly
the model's information and a far easier job — 36 numbers instead of a
36,864-pixel field.

It also lands at chance. Every ridge interval above contains the chance value
(the largest, cytoplasmic non-circular at 0.234 [0.112, 0.362], has a lower
bound below 0.125). **That is the diagnostic result of this study.** The failure
is not the architecture, not the resolution, not the 2D projection, and not the
loss. A linear map from this annotation to a compact summary of the image cannot
discriminate either. The annotation does not contain the answer.

### H4 — uninformative, and why that is the honest report

H4 asked whether an above-chance H1 would survive a mismatched reference tile,
which would mean the model was template-matching rather than conditioning.
There is no above-chance H1 to interrogate. The mismatched-reference numbers
move in both directions (ER *rises* from 0.134 to 0.232; nucleoplasm falls from
0.185 to 0.056) and that scatter is what chance looks like at these sample
sizes. H4 is reported as not answerable in this run rather than as a pass.

## The registered null was not a null

The pre-registration's central claim was that the within-compartment design is
immune to the circularity of OpenCell's annotations:

> *"Within a candidate set every protein carries the same compartment label, so
> the circular part is constant and cannot produce a correct ranking. All
> discrimination has to come from blocks 2–4, none of which is image-derived.
> This is the reason the within-compartment form of the question is the clean
> one."*

**That claim is false as it was implemented**, and the registered H3 null is what
exposed it. `knowledge_blocks` wrote *every* graded annotation a protein carries,
not only its dominant one. Secondary localisations differ between candidates —
measured, without reference to any outcome:

| compartment | distinct compartment blocks among its 8 candidates |
|---|---|
| cytoplasmic | 7 |
| membrane | 7 |
| nucleoplasm | 6 |
| nucleolus_gc | 5 |
| vesicles | 4 |
| er | 4 |
| chromatin | 3 |

Those secondaries were read off OpenCell's own microscopy. So the "compartment
only" run was not a null, and the graded runs had an image-derived channel the
registration said they did not have.

The fix is `compartment_form="dominant"`: one-hot the sole highest-grade
compartment, which is verified identical for all candidates in all seven
compartments. That run is an exact null:

| | top-1 | MRR | 1/n | chance top-1 |
|---|---|---|---|---|
| all seven compartments | **0.000** | **= 1/n exactly** | 1/n | 0.125–0.167 |

Identical vectors produce identical predictions; `rank_of_truth` breaks ties
against the model, so every candidate takes the worst rank and top-1 is zero
rather than 1/8. The ridge baseline is 0.000 there too. The retrieval metric
cannot be gamed by a model that ignores its conditioning — which is what the
null was registered to establish, and what the graded version failed to.

One caution against over-reading the discovery. The graded null's highest
compartment, `nucleolus_gc` at 0.341 against a chance of 0.167, has an interval
of [0.048, 0.630] and is **not** itself significantly above chance. The defect is
established by construction — the blocks demonstrably differ, and the corrected
null is exactly zero — not by that number.

## H3 — which block carries it: none

| compartment | true null | graded compartment only | + abundance | + protein | + interactome | all four (graded) | all four (non-circular) | chance |
|---|---|---|---|---|---|---|---|---|
| cytoplasmic | 0.000 | 0.064 | 0.106 | 0.138 | 0.106 | 0.096 | 0.138 | 0.125 |
| nucleoplasm | 0.000 | 0.130 | 0.130 | 0.074 | 0.130 | 0.185 | 0.093 | 0.125 |
| vesicles | 0.000 | 0.100 | 0.113 | 0.150 | 0.125 | 0.100 | 0.225 | 0.125 |
| er | 0.000 | 0.085 | 0.110 | 0.146 | 0.220 | 0.122 | 0.134 | 0.143 |
| nucleolus_gc | 0.000 | 0.341 | 0.364 | 0.295 | 0.318 | 0.295 | 0.045 | 0.167 |
| chromatin | 0.000 | 0.086 | 0.186 | 0.157 | 0.171 | 0.257 | 0.143 | 0.125 |
| membrane | 0.000 | 0.107 | 0.119 | 0.036 | 0.190 | 0.095 | 0.131 | 0.125 |
| **pooled** | **0.000** | **0.114** | **0.146** | **0.134** | **0.171** | **0.150** | **0.138** | **0.131** |

Pooled with protein-clustered intervals: abundance 0.146 [0.091, 0.206],
protein properties 0.134 [0.083, 0.191], interactome 0.171 [0.116, 0.230], all
four 0.150 [0.101, 0.202], non-circular 0.138 [0.091, 0.188]. Chance is 0.131.
**Every interval contains chance.** The interactome is the best of them by point
estimate and still does not clear it, which is the one mildly encouraging
number in the table and not enough to build on.

## What this settles, and what it does not

**Settled.** The conclusion of the previous study — that annotation-conditioned
prediction carries the compartment and not the protein — was not an artefact of
having one cell line per compartment. Given 24 proteins in a compartment, 16 of
them in training, and a candidate set of 8 held-out proteins with a measured
interactome each, the model still cannot say which one it is looking at. And
this is not a limit of the generative framing: a linear map to a 36-number
summary fails identically.

**Not settled, and the honest caveats.**

* **It is a negative result about *this* annotation**, not about protein
  identity in general. A learned sequence representation, a richer interactome
  embedding, or transcript-level features might carry what these blocks do not.
  What is ruled out is compartment + abundance + family + terminus + partner-set
  hash.
* **Projections, not volumes.** The 152 MB-per-field 3D stacks were out of
  budget. ER proteins in particular differ in ways a Z-projection flattens.
* **HEK293T, not WTC-11**, so these numbers do not compare with the previous
  study's.
* **Small candidate sets.** Eight candidates means chance is 12.5% and a
  protein-clustered interval over ~7 proteins per compartment is wide. A larger
  candidate set would be a sharper test; the cytoplasmic pool alone has 135
  qualifying proteins.
* **20 of 168 targets have no interactome**, partly genuine and partly because
  the OpenCell pulldown endpoint returned 500s during the fetch.
* **The image service is down.** Every `/api/rois/…` and `/api/fovs/…/proj`
  endpoint returns 500; the public `czb-opencell` S3 bucket is what made this
  runnable.

## The lesson, and it is not the one I expected

I built gate 1 to protect against a vacuous negative — the possibility that two
proteins in one compartment simply look the same, making failure meaningless.
It found the opposite of what I predicted, and in finding it turned the study
from "can the model do this" into a sharper question: **the signal is
demonstrably there, so what is missing is a description of a protein that
predicts what it looks like.**

Between the two studies, the same thing has now been measured twice from
opposite directions. Compartment annotation predicts placement well and protein
identity not at all; and at the level where compartment is held constant,
nothing in an annotation-shaped description of a protein predicts anything. The
gap is not in the model. It is that "abundance, family, and who it binds" is not
a description of a spatial pattern, and a compartment label is.

The next experiment that would move this is therefore not a bigger model or a
third dataset. It is a conditioning vector built from something that plausibly
determines localisation at sub-compartment scale — a protein language-model
embedding of the sequence, targeting-signal predictions, transmembrane topology,
disorder — tested by exactly this retrieval, against exactly this chance level,
with the true null in place from the start.
