# Pre-registration: can a model place a protein it has never seen inside a cell it has never seen?

Committed before a single metric is computed. At the time of writing, the
manifest has been read (215,081 cells, 25 cell lines) and the CPU step time has
been benchmarked, but no image has been scored against any prediction.

## The idea, and the one way it is trivially wrong

Every cell in the Allen hiPSC single-cell collection carries the same two
reference channels -- DNA and cell membrane -- plus **exactly one** tagged
structure. That is the whole opportunity and the whole constraint. It means the
dataset is 215,081 observations of the map

$$ f(\text{cell geometry}, \text{protein identity}) \rightarrow \rho_i(x,y,z) $$

with real ground truth on the right-hand side, and it means no cell anywhere in
the collection contains two tagged structures at once.

So the experiment is: give a model this cell's DNA and membrane, name a protein,
and make it produce that protein's density field. Then hold out a protein
**entirely** -- not held-out cells of a known protein, the protein itself -- and
ask again.

The trivial way for this to be worthless is that **the reference channels already
contain the answer.** The nuclear envelope is, to a good approximation, the
boundary of the DNA channel. A plasma-membrane protein is the boundary of the
membrane channel. A model that scores well on those has rediscovered a
morphological operation we handed it in the input, and reporting that as
"the AI inferred the missing structure" would be self-deception. That is
**gate two** below, it is a hand-built rule with no free parameters, and it can
kill any individual structure on its own.

## What is not being claimed

The original framing of this experiment was `DNA + membrane + ER -> mitochondria`,
compared against the real TOM20 image of the same cell. **That comparison does
not exist in any public dataset at this scale**, because it would require a cell
line tagged for both structures at once, and the collection is one tag per line.
Every version of "give it protein A, ask for protein B in the same cell" runs
into the same wall. What is registered here is the test that survives the
constraint: condition on the shared geometry and the protein's annotation, not
on another protein's image.

Three further things stay out of scope and are named so that their absence is
not later read as a result:

* **Time.** Criterion 3 of the original plan -- correct movement -- needs the
  transmitted-light timelapse, which carries no DNA or membrane channel in this
  form. Registered as a later stage, not attempted here.
* **Abundance.** Every channel is normalised per cell, so the target is a
  *relative* density field. The model is asked where a protein is, never how
  much of it there is.
* **Ultrastructure.** At the registered canonical resolution (below) a voxel is
  roughly a micron. Individual filaments and cristae are not resolved and are
  not being predicted. The claim under test is compartment-level placement and
  coarse morphology.

## Fixed parameters -- set now, not after

| parameter | value | why this one |
|---|---|---|
| cell line source | Allen hiPSC single-cell image dataset, WTC-11 | one parental line, shared reference channels, per-cell crops over HTTPS |
| structures | **ACTB, TUBA1B, SEC61B, TOMM20, LMNB1** | the five of the original plan: actin, microtubules, ER, mitochondria, nuclear envelope |
| control line | **AAVS1**, always in training | untagged safe-harbour mEGFP: a structure channel with no structure, and therefore the score floor |
| cells per line | **80** interphase, plus **20** mitotic held out | 480 interphase cells total; 100 mitotic cells never trained on |
| QC filter | `cell_stage == M0`, `outlier == No`, `edge_flag == 0` | interphase, not flagged, not on a colony edge |
| canonical grid | **(Z, Y, X) = (24, 48, 48)** | 0.31 s/training step on 4 CPU cores; the whole protocol is ~80 min. (32, 64, 64) is the same code on a GPU and costs 5 h here |
| input channels | **2**: DNA, membrane (raw intensity, per-cell normalised) | the only two channels every cell in the collection shares |
| conditioning | the fixed **24-d annotation vector** of `vcell.knowledge` | see below -- no learned per-line embedding, anywhere |
| model | 3D U-Net, base 12, depth 3, FiLM conditioning, ~826k parameters | small enough to train six times on a laptop |
| optimiser | Adam, lr 1e-3, batch 4, **25 epochs** | fixed before the first run |
| augmentation | flips in X and Y only | Z is the optical axis and is not interchangeable with it; the frame already fixes in-plane orientation, so these are the label-preserving transforms left |
| split | **by FOV**, never by cell | cells from one field share illumination, colony and neighbours; a random cell split leaks |
| intervals | **FOV-clustered bootstrap**, 1,000 resamples | the direct analogue of the day-clustered bootstrap used elsewhere in this repository |

### The canonical frame

Fixed now, because every baseline in this study depends on it and a frame chosen
later could be chosen to favour one of them.

1. Crop to the bounding box of the cell's membrane segmentation.
2. Rotate in-plane so the membrane's largest XY principal axis lies along X.
3. Resolve the two remaining 180° ambiguities by the nuclear centroid's offset
   from the cell centroid: flip X so that offset is non-negative in x, then flip
   Y likewise. Degenerate for a perfectly centred nucleus, harmless there.
4. Resample to (24, 48, 48) by linear interpolation.
5. Normalise each channel per cell to `[0, 1]` after clipping at its own 1st and
   99.9th percentile.

Step 2 exists to make the atlas baseline **strong**. Averaging structures over
random orientations produces a blur that any model would beat, which would
flatter the model for free.

### Metrics

Five numbers per cell, all computed inside the cell mask, all reported for the
model and for every baseline.

1. **Pearson r** between predicted and true normalised intensity.
2. **Dice** against Allen's own `struct_segmentation`, with the prediction
   thresholded at **matched volume** -- the top-*k* predicted voxels where *k* is
   the true mask's voxel count. Volume matching removes the threshold as a free
   parameter, so Dice measures placement alone.
3. **Centre-of-mass displacement**, in units of the canonical cell radius.
4. **Nuclear-distance Wasserstein-1**, in microns: the density-weighted
   histogram of signed distance to the nuclear surface, predicted against true.
   This is the Earth-mover distance of the original plan, taken in the one
   coordinate that carries most of the placement information.
5. **Fraction of density inside the nucleus** -- one interpretable number that
   separates a nuclear structure from a cytoplasmic one.

## The conditioning, and its honest limit

Protein identity enters as a fixed 24-dimensional vector built from public
annotation only: 17 coarse GO compartments, transmembrane passes, membrane
anchoring, whether the protein polymerises, order-of-magnitude abundance,
molecular weight, nucleic-acid binding, and a control flag. Sources are cited in
`src/vcell/knowledge.py`.

A compartment annotation is a **strong prior**, and this needs saying plainly:
the vector for LMNB1 says "nuclear envelope", which is most of the answer to
"which compartment". The held-out-structure result must be read as *given the
compartment, can the model place and shape it in this cell's geometry* -- not as
the model deducing the compartment from nothing. What annotation cannot supply is
where that compartment sits in **this** cell, or what shape it takes there, and
metrics 2-4 are chosen to isolate exactly that.

The reason conditioning is a fixed vector rather than a learned embedding table
is not elegance. A table indexed by cell line has no row for a line that was
never trained on, so a model built around one could not be *asked* the
leave-one-structure-out question.

## Gates -- each can end the study, or end it for one structure

**Gate 1 -- the atlas gate.** The model must beat the **per-structure voxelwise
mean** in the canonical frame, on held-out cells. The atlas is the same
prediction for every cell of a structure; beating it is the minimum evidence
that anything cell-specific was learned. *If the model does not beat the atlas,
the study is reported as failed.*

**Gate 2 -- the geometric-rule gate.** For each structure the model must beat a
hand-built rule computed from the reference channels alone, with no free
parameters: a shell just inside the nuclear surface, a shell just inside the cell
surface, the nuclear interior, and the cytoplasm, whichever is best for that
structure. *A structure where the rule wins is reported as a structure the model
did not learn*, however good its raw correlation looks. LMNB1 is expected to be
the hard case here and is named in advance.

**Gate 3 -- the identity gate.** Feeding the knowledge vector of a *different*
protein must make the score materially worse. *If shuffling identity costs
nothing, the model is ignoring protein identity* and the conditional framing is
decoration.

**Gate 4 -- the control floor.** AAVS1 is a channel with no structure in it.
Whatever score it earns is the score that means nothing was learned. A structure
scoring near the AAVS1 floor is not a success regardless of its absolute number.

## Hypotheses

**H1 -- seen structures, unseen cells.** For structures in training, on cells
from held-out FOVs, the model beats the atlas, the geometric rule, and a
reference-only model with conditioning ablated.

**H2 -- the unseen structure. The actual question.** Trained on four structures
plus the control, with the fifth's images never seen, the model's prediction for
the fifth beats (a) the generic atlas -- the mean over all *trained* structures,
which is the only atlas available when the structure is unknown -- and (b) the
geometric rule. Five folds, one per structure, **all five reported**.

**H3 -- identity is used.** Gate 3, stated as a hypothesis: the shuffled-identity
control degrades by more than FOV-clustered sampling error.

**H4 -- the joint virtual cell.** Consistency check, weaker evidential status,
and labelled as such. Predict all five structures onto one cell's frame and
compare the pairwise spatial overlaps against the overlaps measured between real
images of each pair mapped into the same frame from *different* cells. This is
the only form in which the original "combine proteins measured in different
cells" idea can be tested, because the paired ground truth does not exist.

**H5 -- mitosis.** 100 mitotic cells (`M1M2`, `M3`, `M4M5`), never trained on,
scored with the interphase-trained model. The prediction is *not* that it works.
The nuclear envelope disassembles in mitosis, so a model that learned "LMNB1 =
boundary of the DNA channel" should fail a mitotic cell in a specific, readable
way. Either outcome is informative; the direction is registered now so that
whichever way it lands cannot be narrated as a success.

## Discipline

* **Split by FOV, never by cell.** Same field means shared illumination, shared
  colony, shared neighbours. A random cell split leaks and would manufacture H1.
* **Per-cell normalisation only.** No statistic of any kind crosses from the test
  set into the normalisation of a training image, and in the leave-one-out folds
  nothing about the held-out line -- not its intensity scale, not its volume
  distribution -- touches training.
* **FOV-clustered bootstrap** for every interval.
* **All five folds reported whole**, not the best one. Five folds at 5% will hand
  back a "discovery" by construction.
* **Every baseline reported for every structure**, including the ones that beat
  the model.
* **Fixed seed, recorded**; the synthetic world in `vcell.synthetic` has known
  ground truth and exists so the metric and frame code can be verified before
  being pointed at real images.

## What would make this different from an image generator

An image generator asked for "mitochondria in a cell" produces something that
looks like mitochondria in a cell, and there is no way to be wrong. Here the
target is a specific measured field in a specific measured cell, the prediction
is scored against it voxel by voxel, and four separate baselines are standing by
to explain the score away. Gate 2 in particular is designed to take the result
back: if a shell rule built from the input channels does as well, then nothing
was inferred, and the honest report is that the reference channels already
contained the structure.
