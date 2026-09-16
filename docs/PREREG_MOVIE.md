# Pre-registration: a movie from fixed cells, and whether direction survives it

Committed before any number from the large sample. At the time of writing, 2,599
mitotic cells across 8 Allen lines have been *selected* and the crops are still
downloading; the only flux numbers seen so far come from the 260-cell pilot,
which is reported in the result document as the pilot and is what motivated this
registration.

## The question

Neither Allen nor OpenCell has a time axis, so "make it move over time" — stage
4 of the original plan — was recorded as unreachable on this data. That is
correct for a *trajectory* of one cell. It is not obviously correct for a
*direction*, because the Allen collection carries `cell_stage`: an ordered
four-value axis (interphase, prophase/prometaphase, metaphase,
anaphase/telophase) with different cells caught at each point.

Averaging within a stage gives four measured densities in a known order. Between
two of them, the continuity equation has a unique minimum-dissipation solution
(`src/vcell/flux.py`): the curl-free flux `J = -rho grad(phi)` with
`div(rho grad phi) = rho1 - rho0` and no flux through the cell boundary. **That
flux is a direction field, and this experiment asks whether it is a measurement
or an artefact.**

## Why it might not be

Three reasons, all of which the analysis has to survive:

1. **Each stage is a different set of cells.** The flux is the transport that
   carries the population mean forward. It is not the path any molecule took,
   and no result here can be reported as one.
2. **A stage mean over few cells is noise.** The pilot had 1 to 12 cells per
   (gene, stage). Stage-mean densities replicated across a split at only
   r = 0.02 to 0.53, and direction cosines came out near zero with inconsistent
   signs.
3. **The reconstruction is a differential operator applied to a noisy field.**
   Solving a Poisson equation for `phi` and then differentiating it can turn
   small density errors into large velocity errors. A reliable density does not
   imply a reliable direction, which is why both are measured separately below.

## Fixed parameters

| parameter | value |
|---|---|
| lines | **8**: TOMM20, NUP153, TUBA1B, NPM1, LMNB1, ACTN1, ATP2A2, and **AAVS1** as the structureless control |
| mitotic cells | every QC-passing mitotic cell the Allen metadata offers per line, capped at 400 — **2,599** selected: 68–150 prophase, 32–94 metaphase, 113–199 anaphase |
| interphase cells | the 80 per line already fetched |
| frame | the existing canonical cell frame, grid (24, 48, 48), voxel 0.393 × 0.407 × 0.634 µm |
| density | per cell, protein channel renormalised to unit mass inside that cell's own mask, then averaged within stage |
| mask per transition | union of the two stages' majority-occupancy masks, solved per connected component, components under 32 voxels dropped and their mass reported |
| diffusion coefficient | Stokes–Einstein from each protein's own AlphaFold model, `D = kT/(6 pi eta R_h F)`, `R_h = 1.29 Rg`, **eta = 4.0 cP**, T = 310.15 K — 4.5 µm²/s (LMNB1) to 19.7 µm²/s (TUBA1B) |
| stage durations | 20 / 18 / 12 min, used **only** for the timescale ratio and labelled wherever it appears |
| split | halves of each stage's cells, seeded 20260916 |
| seed | 20260916 |

## Hypotheses

**H1 — the direction replicates.** For each (gene, transition), each stage's
cells are split in two, both stage means and both flux fields are rebuilt from
disjoint halves, and the mass-weighted cosine between the two velocity fields is
the outcome. **Registered threshold: the median split-half direction cosine over
the 7 real lines exceeds 0.30, and is positive for at least 5 of 7.** This is
the primary outcome and it is the direction field, not the density.

**H2 — the density replicates better than the direction.** Registered
prediction: the split-half Pearson r between stage-mean densities exceeds 0.80
at this sample size, *and* exceeds the split-half direction cosine for every
line. If H2 holds and H1 fails, the pictures in the movie are trustworthy and
the arrows are not, which is a different and more useful finding than "the data
are too noisy".

**H3 — the structureless control is worse.** AAVS1 has no tagged structure, so
its channel is background. Registered prediction: its split-half direction cosine
is below the median of the 7 real lines. If AAVS1 matches them, whatever is
replicating is not the protein.

**H4 — these structures are not freely diffusing.** For every line, the ratio of
the assumed stage duration to the diffusive timescale
(`tau = <|rho1 - rho0|> / (D <|lap rho|>)`) exceeds **100**. Free diffusion of
the monomer is orders of magnitude faster than the observed redistribution, so
the prediction is that the pattern is held against diffusion by assembly rather
than produced by it. The pilot gave ratios of 12,000 to 141,000, so this is the
one hypothesis registered as confirmatory of something already seen — and its
falsification condition is any line at or below 100.

**H5 — the direction is not simply down-gradient.** The mass-weighted cosine
between the reconstructed flux and `-grad(rho)` is +0.895 for pure diffusive
spreading on synthetic data and -0.895 for its reverse (both in
`tests/test_vcell_metrics.py`). Registered prediction: the measured values fall
**between -0.5 and +0.5** for every line and transition, i.e. the transport runs
across the concentration gradient rather than along it. Pure spreading would put
them near +0.9.

## What would falsify the whole approach

**H1 failing while H2 passes** is the outcome the pilot points to, and it would
mean direction is not recoverable from stage-binned fixed cells at this
resolution *at any sample size this dataset can supply* — 2,599 cells is nearly
every mitotic cell the 8 lines have. That will be reported as the headline if it
happens, and it settles stage 4 of the original plan negatively on this data
rather than leaving it open.

**H1 passing** would mean a direction field can be measured without a time axis,
which is a genuinely new capability for this project and would need an
independent confirmation on a held-out set of lines before it is a claim.

## Discipline

* The solver is validated on five synthetic cases with known answers, three of
  which are defects it actually had (a sign error, conjugate gradients on a
  negative-definite operator, and a disconnected mask); all five are regression
  tests committed before this run.
* A non-converging solve is refused, not reported. The pilot's diverged solves
  returned displacements of 1e15 µm.
* Every quantity that depends on the assumed stage durations or on the assumed
  cytoplasmic viscosity is labelled at the point of use.
* The advected frames between measured stages are the reconstruction's own
  prediction, not data, and are labelled in the movie itself.
