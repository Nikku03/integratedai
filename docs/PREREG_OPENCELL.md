# Pre-registration: can a model tell two proteins in the same compartment apart?

Committed before a single metric is computed. At this point the OpenCell
catalogue has been read (1,310 lines, 80 annotation categories), one image has
been opened to establish the channel order and pixel size, the interaction API
has been confirmed to return hits, and the CPU step time has been benchmarked.
No prediction has been scored against any image.

## Why this experiment exists

[`docs/RESULT_VIRTUAL_CELL.md`](RESULT_VIRTUAL_CELL.md) ended with one finding
and one consequence. The finding: conditioning a model on a protein's annotated
compartment plus a cell's reference channels predicts organelle placement far
better than any atlas or retrieval baseline — and **the prediction depends on
the compartment, not on the protein**. In all three folds where the two could be
separated, feeding a different protein from the same compartment scored as well
or better; for actin, feeding the *untagged control line's* annotation scored
better still.

The consequence: at five structures, each compartment was represented by exactly
one cell line, so "which protein" and "which compartment" were the same
question. That study could not ask the one that matters.

This one can. OpenCell has 1,310 endogenously tagged human proteins with graded
localization annotations, and after QC filtering there are **seven compartments
carrying at least 24 proteins each**. So a protein can be held out while its
compartment stays densely represented, and the question becomes:

$$\text{given the compartment, can the model pick the right protein?}$$

That is a **retrieval** question, not a reconstruction question, and it is
scored as one: rank the candidates, chance is 1/8.

## The one way this is trivially wrong, and the gate that catches it

**Two proteins in the same compartment may simply look the same.** If every ER
protein produces the same reticular pattern at this resolution, then no model
can discriminate them, nothing is learned by failing, and the experiment is
vacuous rather than negative.

So **gate 1 runs first and uses no model at all.** A fixed image descriptor,
with no fitted parameters, is computed for every image tile. Then, within each
compartment's candidate set, leave-one-tile-out nearest-neighbour retrieval:
does a tile's nearest neighbour among the candidates belong to the same protein?
Chance is 1/8.

* If gate 1 is **at chance for a compartment**, that compartment is reported as
  *not identifiable at this resolution* and is excluded from H1. Not a failure
  of any model — a statement about the images.
* If gate 1 is at chance **everywhere**, the study stops and is reported as
  failed, exactly as the entropy study stopped at its gate.

Gate 1 is also the reference the model has to be read against. A descriptor with
no learning and no annotation sets the bar for how much protein-specific signal
is in the pixels at all.

## Fixed parameters — set now, not after

| parameter | value | why this one |
|---|---|---|
| source | OpenCell (Cho et al. 2022), `czb-opencell` public S3 + `opencell.sf.czbiohub.org/api` | 1,310 lines, graded annotations, measured interactomes |
| cell type | HEK293T | what OpenCell is; **not** the WTC-11 of the previous study |
| image | the 2-channel z-**projection** (`*_proj.tif`), channel 0 nucleus (Hoechst), channel 1 target (mNeonGreen) | the 3D stacks are 152 MB each; 672 of them is 102 GB, and this question is about pattern, not about 3D placement |
| pixel size | **0.2 µm**, used at native scale | texture is the signal; resampling it away would decide the result in advance |
| compartments | **cytoplasmic, nucleoplasm, vesicles, er, nucleolus_gc, chromatin, membrane** | every compartment with ≥ 24 sole-dominant proteins after QC |
| compartment membership | the protein's **sole** highest-grade annotation | one protein, one compartment: no protein appears in two candidate sets |
| QC exclusion | any of `low_gfp`, `low_hdr`, `heterogeneous_gfp`, `disk_artifact`, `re_image`, `salvageable_re_sort` | OpenCell's own flags; 410 of 1,310 lines are dropped |
| proteins per compartment | **24** — 16 training, **8 held out** | the candidate set is the 8 held-out proteins, so no candidate has a training advantage |
| FOVs per protein | **4** | ~9 are available for almost every line |
| tiles per FOV | **4** — a 2×2 grid over the central 384×384 | 1,792 training tiles, 896 test tiles |
| tile size | **192 × 192** at native 0.2 µm (38 µm across, a few cells) | 3.2 min/epoch on four CPU cores; 256 px costs 5.0 |
| model | 2D conditional U-Net, base 24, depth 4, FiLM, ~4.6M parameters | the 3D model of the previous study, one dimension down |
| optimiser | Adam, lr 1e-3, batch 8, **20 epochs** | fixed now |
| loss | cross-entropy between unit-mass 2D densities | same as the previous study: where, not how much |
| augmentation | flips in X and Y, and 90° rotations | a projected FOV has no privileged in-plane direction, unlike the previous study's Z axis |
| split | **by protein**, and FOVs of a held-out protein never appear in training | the whole point |
| intervals | **protein-clustered bootstrap**, 1,000 resamples | tiles from one protein are not independent; the previous study's FOV clustering turned out to be a no-op and this is the honest unit here |

## The conditioning, and what makes this test different

Identity enters as a fixed vector again, but it now has to carry
**within-compartment** information, because the compartment block is by
construction identical for every candidate in a fold. Four blocks:

1. **Compartment** — the graded annotation, one-hot-ish over the seven
   compartments plus the minor ones. *Identical across candidates in a fold, so
   it cannot contribute to retrieval at all.*
2. **Abundance** — protein copy number, concentration, RNA abundance
   (OpenCell's own measurements, no images involved).
3. **Protein** — molecular weight, target family, tagging terminus.
4. **Interactome** — the protein's significant interaction partners from
   OpenCell's mass-spectrometry pulldowns: partner count, mean enrichment,
   mean interaction stoichiometry, and a fixed random projection of the
   partner-gene set. Measured by mass spectrometry, so it is
   **image-independent** for the held-out protein.

One leak that would wreck a compartment-level test does not touch this one.
OpenCell's localization annotations were read off OpenCell's own microscopy, so
using them as "prior knowledge" about a held-out protein is circular. **Within a
candidate set every protein carries the same compartment label, so the circular
part is constant and cannot produce a correct ranking.** All discrimination has
to come from blocks 2–4, none of which is image-derived. This is the reason the
within-compartment form of the question is the clean one.

## Hypotheses

**H1 — the registered question.** For held-out proteins, ranking the 8 candidate
identities by how well the model's prediction matches the measured image puts
the true protein first more often than chance (1/8), by more than
protein-clustered sampling error. Reported per compartment, **all seven, whatever
they say**.

**H2 — against the no-model reference.** H1's retrieval accuracy is compared with
gate 1's descriptor k-NN. If the model does not beat a fixed descriptor with no
learning and no annotation, then the conditioning added nothing and the honest
report is that the pixels carry the signal and the model does not reach it.

**H3 — which block carries it.** Ablations, retrained: compartment-only,
compartment+abundance, compartment+protein, compartment+interactome, and all
four. **Compartment-only must land exactly at chance** — every candidate gets a
byte-identical vector, so a result above chance there would mean the retrieval
metric is broken, and that check validates the harness.

**H4 — is it conditioning or is it an average?** A model could score above
chance by ignoring the reference channel and emitting a per-protein average
image. Control: score the candidates using a **mismatched reference tile** from
a different FOV. If accuracy survives that, the model is doing per-protein
template matching, not conditional prediction, and H1 should be read as
retrieval of a learned template.

## What I expect, on the record

Gate 1 passes for `er`, `nucleolus_gc`, `chromatin`, `vesicles` and `membrane`,
and is at or near chance for `cytoplasmic` and `nucleoplasm` — the two diffuse
classes, which are included precisely because they should be the hard ones.

H1 I expect to **fail or barely clear chance**. The previous study found the
conditioning carried compartment and nothing else, and nothing in this design
guarantees that abundance, family and interactome are enough to specify a
spatial pattern. Registering that expectation now so that a positive result
cannot be presented as anticipated and a negative one cannot be presented as
surprising.

The result that would change my mind is H1 clearly above chance **with H4
showing it degrades under a mismatched reference** — that combination would mean
the model is using the protein's non-compartment features together with this
field's geometry, which is the thing the previous study could not find.

## Discipline

* **Split by protein.** No tile, FOV, or image of a held-out protein appears in
  training.
* **Protein-clustered bootstrap** for every interval. 16 tiles from one protein
  are one observation, not sixteen.
* **Paired comparisons.** Every candidate identity is scored on the same tile, so
  model-versus-baseline is a paired test per tile. The previous study published
  marginal intervals where paired tests were needed; not repeated here.
* **All seven compartments reported**, including the ones at chance.
* **Chance stated everywhere.** 1/8 for retrieval; the metric is top-1 accuracy
  and mean reciprocal rank, both with the chance value printed alongside.
* **The harness is validated by a null that must hold** (H3, compartment-only),
  not only by a positive control.
* Fixed seed, recorded.

## What this cannot settle

HEK293T is not WTC-11, the images are projections rather than volumes, there is
no membrane channel and no cell segmentation, so "where in the cell" is a
weaker notion here than in the previous study and the two sets of numbers are
not comparable. This experiment is not a better version of that one. It answers
the single question that one was structurally unable to ask.
