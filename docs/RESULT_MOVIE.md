# Result: a movie from fixed cells, and the direction does survive it

Reports [`PREREG_MOVIE.md`](PREREG_MOVIE.md) as registered, on 2,599 mitotic
cells across 8 Allen lines — nearly every mitotic cell those lines have.

## Verdict

| hypothesis | registered threshold | observed | |
|---|---|---|---|
| **H1** the direction replicates | median split-half direction cosine > **0.30**, positive for ≥ 5 of 7 lines | **+0.581**, positive **7 of 7** | **PASS** |
| **H2** density replicates better than direction | density r > 0.80 for every line, and above its direction cosine everywhere | r ≤ 0.80 on 4 of 7 lines; direction beats density in 2 of 21 | **FAIL** |
| **H3** the structureless control is worse | AAVS1 below the real-line median | +0.249 against +0.581 | **PASS** |
| **H4** not freely diffusing | ratio to the free-diffusion timescale > **100** everywhere | **6,818 to 147,653** | **PASS** |
| **H5** direction is not simply down-gradient | diffusive cosine within ±0.5 everywhere | within ±0.5 in **20 of 21** | **FAIL** |

**The registered failure mode did not happen.** `PREREG_MOVIE.md` predicted the
pilot's outcome — densities replicating while directions did not — and said that
would settle stage 4 of the original plan negatively. Instead the direction field
replicates across a split of the same cells at a median cosine of 0.581, and
**H2 fails in the favourable direction**: the arrows turned out to be as
reliable as the pictures, and in two cases more so.

That is a new capability rather than a new negative. **A direction field can be
measured from fixed cells**, given an ordered stage axis and enough cells per
stage. It is not a trajectory and cannot become one — see the limits at the end.

## What the movie is

Each frame is a stage mean: every cell's protein channel renormalised to unit
mass inside its own cell mask, then averaged over the cells caught at that
stage. Four stages, in the order the biology runs them.

| line | interphase | prophase / prometaphase | metaphase | anaphase / telophase |
|---|---|---|---|---|
| TOMM20 | 82 | 136 | 96 | 176 |
| NUP153 | 82 | 152 | 59 | 192 |
| TUBA1B | 82 | 99 | 66 | 199 |
| NPM1 | 82 | 119 | 67 | 184 |
| LMNB1 | 82 | 97 | 47 | 151 |
| ACTN1 | 82 | 108 | 32 | 155 |
| ATP2A2 | 82 | 80 | 34 | 142 |
| AAVS1 *(control)* | 82 | 68 | 38 | 113 |

Each GIF shows one real cell (the cell whose density correlates best with its
own stage mean), the stage mean beside it, and the transport field leaving that
stage. The frames between two stages are the reconstruction advected along its
own flux and are labelled *advected, not measured* in the movie itself.

## H1 — the direction replicates

Each stage's cells split in two; both stage means and both flux fields rebuilt
from disjoint halves; the outcome is the mass-weighted cosine between the two
velocity fields.

| line | interphase→prophase | prophase→metaphase | metaphase→anaphase | median |
|---|---|---|---|---|
| LMNB1 | +0.526 | +0.896 | **+0.943** | **+0.896** |
| NPM1 | +0.539 | **+0.949** | +0.798 | +0.798 |
| ATP2A2 | −0.028 | +0.606 | +0.675 | +0.606 |
| NUP153 | +0.353 | +0.906 | +0.581 | +0.581 |
| TOMM20 | −0.040 | +0.565 | +0.394 | +0.394 |
| ACTN1 | +0.202 | +0.825 | +0.308 | +0.308 |
| TUBA1B | +0.234 | +0.822 | −0.034 | +0.234 |
| AAVS1 *(control)* | −0.122 | +0.608 | +0.249 | +0.249 |

Median over the 7 real lines **+0.581** against a registered 0.30, all 7
positive against a registered 5. Pooled over all 21 real (line, transition)
pairs the median is +0.565 and 18 of 21 are positive.

**The pattern across columns is consistent and worth reading.** The
prophase→metaphase column is the strongest everywhere — 5 of 7 lines above 0.6,
four above 0.8 — and the interphase→prophase column is the weakest, with the two
negatives. Interphase is hours long and prophase minutes, so "the interval
between them" is the least well defined of the three, and the transport across
it is correspondingly the least reproducible. That is a property of the stage
axis, not of the method.

## H3 — the control, and why the floor is not zero

AAVS1 is a safe-harbour locus with no tagged structure, so its channel is
background. It clears H3 as registered (+0.249 against +0.581) but **it does not
replicate at zero**, and its prophase→metaphase cosine of +0.608 is higher than
the worst transition of every real line.

That matters and bounds the claim. A cell changes shape dramatically through
mitosis, and every channel in it redistributes for that reason alone. Some of
what replicates in the real lines is cell-shape change common to all of them.
**The right reading of H1 is therefore comparative:** the real lines carry
direction over and above a structureless channel, by a median of 0.581 to 0.249,
not that 0.581 is all protein-specific transport.

## H4 — these are assembled structures, not diffusing molecules

Using each protein's own AlphaFold structure — `D = kT/(6πηR_h F)` with
`R_h = 1.29 Rg`, η = 4.0 cP, giving 4.5 µm²/s for LMNB1 up to 19.7 for TUBA1B —
the diffusive timescale is the time free diffusion would need to produce the
density change actually observed. Against the assumed stage durations:

**every line and transition is between 6,800× and 148,000× slower than free
diffusion of its own monomer.** The slowest ratio is LMNB1 metaphase→anaphase at
6,818×; the fastest is TUBA1B interphase→prophase at 147,653×.

Free diffusion would erase these patterns in well under a second. They persist
for tens of minutes and change on that timescale instead. **The protein is not
moving as a free molecule at any point in this data** — it is held in an
assembly, and the redistribution is the assembly's, not the molecule's. This is
the one place the AlphaFold physics earns its keep, and it earns it by saying
the model of free diffusion does not apply.

*Caveat on the coefficient.* AlphaFold gives the monomer's shape, so `D` is the
free monomer's. For ACTB or TUBA1B, most of the protein is polymerised and its
real mobility is far lower. That makes the ratios upper bounds — the true
excess over the *effective* diffusion is smaller, though still large. And every
ratio scales as 1/η; η = 4.0 cP is stated as an assumption, not measured here.

## H5 — the direction against the concentration gradient

The mass-weighted cosine between the reconstructed flux and `−∇ρ` is +0.895 for
pure diffusive spreading on synthetic data and −0.895 for its reverse (both are
committed regression tests). Measured, 20 of 21 fall within ±0.5, so the
transport generally runs *across* the gradient rather than along it — but H5 was
registered as "every line and transition" and one pair is outside, so it fails
as written. The interesting part is which pairs sit at the two ends.

**The spindle assembling, moving mass uphill.** TUBA1B prophase→metaphase:
cosine **−0.46** with **90% of the mass moving up its own concentration
gradient**, a displacement of 2.20 µm per stage, and a split-half of **+0.82**.
Diffusion cannot move mass up a gradient. Something has to be paying for it, and
at this point in mitosis the thing paying is spindle assembly. It is the
strongest uphill signal in the table and it replicates.

**The nucleolus disassembling, nearly pure spreading.** NPM1 prophase→metaphase
is the opposite: cosine **+0.599** — the one H5 violation — with only **3% of
the mass uphill**, the **largest displacement in the table at 3.23 µm**, and the
**highest split-half of all at +0.949**. Nucleophosmin leaving a dissolving
nucleolus and dispersing is what diffusive spreading looks like, and it is
measured as such.

**Those two are the most reliable direction fields in the study and they are
opposite in character.** Both match the known biology without being told it.
That is the strongest evidence in this document that the reconstruction is
measuring something real: a method that produced noise, or that imposed one
shape on everything, could not separate a spindle from a nucleolus.

Full table:

| line | transition | displacement µm/stage | diffusive cosine | mass uphill | slower than free D | split-half direction |
|---|---|---|---|---|---|---|
| NPM1 | prophase→metaphase | **3.23** | +0.60 | 3% | 7,297× | **+0.95** |
| TUBA1B | prophase→metaphase | 2.20 | **−0.46** | **90%** | 22,697× | +0.82 |
| NUP153 | prophase→metaphase | 2.06 | +0.26 | 27% | 21,473× | +0.91 |
| LMNB1 | metaphase→anaphase | 2.06 | +0.18 | 34% | 6,818× | **+0.94** |
| ACTN1 | prophase→metaphase | 1.93 | +0.12 | 38% | 39,943× | +0.83 |
| LMNB1 | prophase→metaphase | 1.39 | +0.17 | 35% | 17,789× | +0.90 |
| ATP2A2 | metaphase→anaphase | 1.27 | −0.04 | 50% | 21,509× | +0.68 |
| NPM1 | metaphase→anaphase | 1.07 | +0.14 | 38% | 31,040× | +0.80 |
| NPM1 | interphase→prophase | 0.86 | +0.23 | 28% | 22,985× | +0.54 |
| ACTN1 | metaphase→anaphase | 0.75 | +0.12 | 43% | 44,008× | +0.31 |
| NUP153 | metaphase→anaphase | 0.66 | +0.24 | 29% | 24,848× | +0.58 |
| ACTN1 | interphase→prophase | 0.64 | −0.05 | 55% | 88,245× | +0.20 |
| TUBA1B | interphase→prophase | 0.63 | +0.06 | 48% | 147,653× | +0.23 |
| TOMM20 | metaphase→anaphase | 0.63 | −0.02 | 51% | 60,055× | +0.39 |
| TOMM20 | prophase→metaphase | 0.62 | +0.14 | 39% | 65,429× | +0.57 |
| ATP2A2 | interphase→prophase | 0.62 | −0.15 | 62% | 88,810× | −0.03 |
| TOMM20 | interphase→prophase | 0.57 | +0.09 | 42% | 103,700× | −0.04 |
| ATP2A2 | prophase→metaphase | 0.56 | +0.20 | 36% | 57,900× | +0.61 |
| NUP153 | interphase→prophase | 0.50 | −0.07 | 55% | 53,281× | +0.35 |
| LMNB1 | interphase→prophase | 0.47 | −0.02 | 51% | 31,441× | +0.53 |
| TUBA1B | metaphase→anaphase | 0.39 | +0.11 | 35% | 35,258× | −0.03 |

LMNB1 is worth one line on its own: its displacement grows monotonically through
mitosis, 0.47 → 1.39 → 2.06 µm per stage, with split-half rising 0.53 → 0.90 →
0.94. The nuclear lamina coming apart and dispersing is the cleanest single
trajectory in the study.

## Three defects the solver had, all of which returned numbers

Recorded because each produced plausible-looking output rather than an error,
and all three are now regression tests in `tests/test_vcell_metrics.py`:

1. **A sign error.** Continuity gives `div(ρ∇φ) = +(ρ₁−ρ₀)`; the first version
   used the negative and every velocity pointed backwards. Caught by a synthetic
   translation whose direction is known.
2. **Conjugate gradients on a negative-definite operator.** A Laplacian is
   negative semidefinite; CG requires positive definiteness. It broke down and
   returned displacements of **10¹⁵ µm**.
3. **A Neumann problem over a disconnected mask.** A mitotic cell mask genuinely
   comes apart, and segmentation leaves single-voxel specks besides. Each piece
   adds a null direction, and solving the whole mask at once diverges — every
   failing case had more than one connected component and the two that worked
   had exactly one. Now solved per component, with mass that no flux can move
   reported rather than absorbed.

A non-converging solve is refused rather than reported.

## What this does and does not settle

**Settled: direction is measurable from fixed cells.** With an ordered stage
axis and ~50–200 cells per stage, the minimum-dissipation transport between
consecutive stage means replicates across a split of the same cells, separates a
spindle from a nucleolus, and is bounded below by a structureless control. Stage
4 of the original plan — "make it move over time" — is reachable in the sense of
*direction*, which the project had recorded as unreachable.

**Not settled, and not reachable on this data:**

* **A trajectory.** Every stage is a different set of cells. The flux is the
  transport that carries the population mean forward; no molecule took that
  path, and nothing here can say what one cell did. Getting that needs live
  timelapse.
* **A real velocity.** The interval between two stages is assumed, not measured
  (20 / 18 / 12 min), so every µm/stage figure is a displacement per interval
  and scales linearly with whatever the interval really is. The interphase→
  prophase interval is the worst defined and is also where replication is
  weakest.
* **Molecular kinetics.** Stage 5 remains untouched. Nothing here models
  binding, polymerisation or turnover; H4 says only that free diffusion is the
  wrong model, not what the right one is.
* **Protein identity.** This is orthogonal to the identification question. The
  movie is built from a channel that was measured, not predicted — nothing here
  weakens or strengthens [`RESULT_SCALE.md`](RESULT_SCALE.md).

## How it would actually be recorded

The honest answer to "how can it be recorded" has two halves, and only one of
them is software.

**The output, here.** `scripts/vcell_movie.py` writes an animated GIF per line
plus [`movie_physics.json`](../data/vcell/movie_physics.json) carrying every
number in this document. GIF because no encoder is available in this
environment; the frames are rendered through matplotlib, so an MP4 is one
`ffmpeg` call away wherever one exists. The per-frame densities and the flux
fields are reproducible from the committed script and the fetch manifest.

**The measurement, to get a real movie.** What is missing is not analysis but
acquisition, and the requirements are specific: the same cell imaged
repeatedly in 3D through a division, which means live-cell spinning-disk or
lattice light-sheet at roughly 1–2 minute intervals over ~90 minutes, at low
enough illumination that the cell still divides normally. Allen's own
`hipsc_single_cell_image_dataset` is fixed by construction — the crops are
segmented from fixed, stained plates — so no reprocessing of it yields a
trajectory. Their timelapse collections, and any lattice light-sheet series of
the same tagged lines, are the data that would. With that in hand this same
`vcell.flux` code applies unchanged and to much stronger effect: consecutive
real timepoints make the interval known, so the velocities become µm/s rather
than µm/stage, and the split-half control becomes a comparison between cells
rather than between halves of a population.
