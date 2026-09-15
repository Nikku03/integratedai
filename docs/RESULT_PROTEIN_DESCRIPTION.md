# Screen: what a protein is, versus what it looks like. One fingerprint survives

**Exploratory, not pre-registered.** Three parts. Part one screens eight
descriptions by predicting the image descriptor, and **none of them works**.
Part two adds every gene-level database within reach and changes the method from
prediction to shared-space matching, and **one fingerprint clears both tests**:
a protein's STRING functional-association profile identifies it within its
compartment at 0.245 against a chance of 0.132. Part three tries to improve it
by combining fingerprints, and **nothing survives that**: adding ESM-2 destroys
STRING's signal, and the combinations that do look good reverse when an
arbitrary fusion choice is changed. The one result left standing is the
single-block STRING profile, which is suggestive rather than established for
four reasons set out at the end of part two, and needs pre-registering.

**On discipline.** The two studies before this
([`RESULT_VIRTUAL_CELL.md`](RESULT_VIRTUAL_CELL.md),
[`RESULT_OPENCELL.md`](RESULT_OPENCELL.md)) were registered in advance. This is a
screen — its job is to find out which descriptions are worth registering a
confirmatory test on. Every number carries a permutation null, and the honest
reading of a screen is "nothing here justifies the next experiment yet", which
is what it returned.

Run with `scripts/vcell_describe.py` (part one), `scripts/vcell_gene_data.py`
and `scripts/vcell_fingerprint.py` (part two). 162 OpenCell proteins with
images, 109 training and 53 held out, reusing the tiles and the protein split
from the OpenCell study. Data in
[`describe_screen.json`](../data/vcell/opencell/describe_screen.json) and
[`fingerprint_match.json`](../data/vcell/opencell/fingerprint_match.json).

## Why a screen and not a study

The OpenCell result left a specific gap: the images carry each protein's
fingerprint (a fixed texture descriptor picks the right protein 76% of the time
inside the vesicle compartment) and the description available — abundance,
family, terminus, interactome — could not reach it. The obvious next move is a
better description. The non-obvious part is that testing one costs 50 minutes
of training, so testing eight costs a day.

It doesn't have to. The OpenCell study established that a **ridge regression
from the description to the 36-dimensional image descriptor** is a faithful and
strictly easier stand-in for the full model: 36 numbers instead of a
36,864-pixel field, same information, and it failed in the same place. So each
candidate can be screened in under a second, one observation per protein, and
only a winner gets trained.

## The screen

| description block | dims | raw R² | p | **within-compartment R²** | null p95 | p | retrieval top-1 |
|---|---|---|---|---|---|---|---|
| **esm** — ESM-2 embedding of the bare sequence | 480 | **0.253** | 0.000 | **−0.035** | 0.014 | 0.262 | 0.226 |
| location_kw — UniProt cellular component *(circular)* | 8 | 0.151 | 0.000 | 0.000 | 0.000 | 0.204 | 0.151 |
| composition — amino-acid frequencies, charge, hydropathy | 27 | 0.127 | 0.000 | 0.000 | 0.000 | 0.274 | 0.151 |
| baseline — abundance + family + terminus + interactome | 51 | 0.106 | 0.000 | 0.004 | 0.014 | 0.266 | 0.170 |
| function_kw — UniProt keywords, location excluded | 16 | 0.098 | 0.000 | 0.000 | 0.000 | 0.076 | 0.170 |
| lowcomplexity — coiled coils, compositional bias, runs | 5 | 0.095 | 0.000 | 0.005 | 0.013 | 0.202 | 0.132 |
| topology — TM passes, signal peptide, lipidation | 10 | 0.080 | 0.002 | −0.000 | 0.009 | 0.458 | 0.151 |
| domains — hashed Pfam bag | 16 | 0.003 | 0.214 | −0.011 | 0.018 | 0.646 | 0.094 |
| ALL honest blocks (ESM + the five sequence blocks) | 554 | 0.265 | 0.000 | −0.036 | 0.011 | 0.232 | 0.208 |
| ALL honest + baseline | 605 | **0.302** | 0.000 | −0.033 | 0.010 | 0.224 | 0.245 |

Retrieval chance is 0.132. Every p-value is against a 500-fold permutation null
that breaks the protein-to-description pairing and refits end to end, because
with 53 held-out proteins and 36 targets an R² of a few percent happens by
accident.

## What it says

**The raw column is a real, large signal, and it is not the one we need.**
ESM-2 — a 35M-parameter language model shown nothing but the amino-acid
sequence — predicts a quarter of the variance in how a protein's images look,
on proteins it never saw. That is worth noting on its own: it **beats the
circular block**, UniProt's curated cellular-component keywords, 0.253 to
0.151. A protein's bare sequence is a better predictor of its appearance than a
human-curated location label.

**The within-compartment column is zero everywhere, and that is the answer.**
Subtract each compartment's mean and every block collapses: ESM-2 from 0.253 to
−0.035, the honest combination to −0.036, the best of anything to 0.005 at
p = 0.202. So the whole raw signal was *which compartment* — the thing both
previous studies already established is predictable. Nothing here predicts how
a protein looks **given** its compartment.

**Pfam domains predict nothing at any level** (raw R² 0.003, p = 0.214) — the
only block that fails even at compartment scale, which is a small surprise given
that domains are how protein families are usually described.

## The control that makes the null mean something

A null result is worthless if the target is unmeasurable, and this repository
has already been caught by exactly that: in
[`RESULT_ENTROPY.md`](RESULT_ENTROPY.md) a feature passed its orthogonality
gate because it carried no information at all rather than independent
information.

So: describe each protein twice, from two **disjoint halves** of its fields of
view, and correlate.

| target | split-half reliability | dims above r = 0.5 |
|---|---|---|
| raw protein descriptor | **r = 0.750** | 33 / 36 |
| compartment-centred descriptor | **r = 0.537** | 19 / 36 |

Two independent halves of the same protein agree at 0.54 on the
compartment-centred descriptor. **The within-compartment target is real and
reliably measurable.** The zeros above are therefore a statement about the
descriptions, not about noise.

## What this changes

The gap is now located precisely, and it is narrower than "we need a better
description". Everything tried here — sequence composition, transmembrane
topology, signal peptides, lipidation, coiled coils, low-complexity regions,
Pfam domains, non-location keywords, abundance, interactome, and a protein
language model — carries compartment and nothing finer. Meanwhile the
appearance being predicted is stable to r = 0.54 across independent fields.

Two readings were open, and one of them has now been closed.

1. **The description is still wrong.** A 35M-parameter ESM-2 is the smallest of
   its family; mean-pooling throws away all positional structure; and
   sub-compartment localisation may depend on things none of these blocks
   encode — copy number *in this cell line*, competition for a shared receptor,
   post-translational state, or partners' abundances rather than their
   identities. **Still open.**
2. **The appearance is not protein character at all** but batch character —
   reproducible clone, plate and passage effects, in which case no per-protein
   description could ever predict it and the r = 0.537 reliability is
   bookkeeping. **Tested and largely closed**, below.

### The batch control, and one confound that cannot be removed

Reading 2 matters enough to test, because if the appearance is a plate
signature then this entire line of attack — and gate 1 of the OpenCell study —
is measuring laboratory logistics.

OpenCell grows one tagged line per well, so across the 162 proteins there are
**162 distinct (plate, well) pairs**: protein and clone are perfectly
confounded, and no analysis of this dataset can separate "this protein looks
like this" from "this clone looks like this". That is a property of the
experimental design, not of the analysis, and it bounds every identifiability
claim here and in the OpenCell study.

Plates, however, are shared — 21 plates across the sample, with several
candidates of a compartment on the same plate. So gate 1 can be re-run with the
candidate set restricted to **one plate**: a protein's own fields against a
compartment-mate grown, sorted and imaged alongside it.

| compartment | plate | candidates | tiles | top-1 | chance |
|---|---|---|---|---|---|
| cytoplasmic | P0013 | 2 | 24 | 0.917 [0.800, 1.000] | 0.500 |
| nucleoplasm | P0018 | 4 | 32 | 0.812 [0.583, 0.950] | 0.250 |
| nucleolus_gc | P0011 | 2 | 18 | 0.778 [0.333, 1.000] | 0.500 |
| vesicles | P0002 | 2 | 23 | 0.696 [0.692, 0.700] | 0.500 |
| cytoplasmic | P0014 | 2 | 28 | 0.679 [0.615, 0.733] | 0.500 |
| membrane | P0003 | 2 | 21 | 0.619 [0.571, 0.643] | 0.500 |
| er | P0004 | 2 | 29 | 0.552 [0.385, 0.688] | 0.500 |
| chromatin | P0017 | 5 | 40 | 0.450 [0.294, 0.571] | 0.200 |
| nucleolus_gc | P0012 | 3 | 16 | 0.250 [0.000, 0.333] | 0.333 |
| **pooled** | | **24 proteins** | **231** | **0.641 [0.546, 0.732]** | **0.402** |

The pooled interval clears chance. **Plate identity does not explain gate 1** —
two proteins from the same plate are still told apart from their images. The
well-level confound stands and cannot be tested with this data; separating
protein from clone needs either multiple independent clones per protein or a
transient-expression design.

So the target being predicted is real (r = 0.537 across independent fields),
survives the strongest batch control available, and remains unpredicted by every
description tried.

### Shortlisting the interactome by co-location: a good list, not a useful feature

A mass-spec pulldown reports partners from a whole-cell lysate, so the raw
partner list mixes genuine complexes with pairs that only met in the tube. Two
proteins can only bind if they are in the same place, so intersecting the
measured partners with the localisation annotations should give a cleaner
feature. The shortlist is in
[`compartment_interactions.csv`](../data/vcell/opencell/compartment_interactions.csv),
with the members of each compartment in
[`compartment_members.csv`](../data/vcell/opencell/compartment_members.csv).

| compartment | proteins | measured partner links | placeable | same compartment | share | shortlisted pairs |
|---|---|---|---|---|---|---|
| cytoplasmic | 24 | 945 | 217 | 138 | 0.64 | 135 |
| nucleoplasm | 24 | 849 | 160 | 76 | 0.47 | 70 |
| vesicles | 24 | 169 | 50 | 38 | 0.76 | 36 |
| er | 24 | 335 | 111 | 74 | 0.67 | 69 |
| nucleolus_gc | 24 | 538 | 113 | 20 | 0.18 | 19 |
| chromatin | 24 | 1654 | 327 | 161 | 0.49 | 134 |
| membrane | 24 | 209 | 29 | 10 | 0.34 | 8 |

Partner localisation is resolved against all 1,310 OpenCell lines, of which 857
carry an unambiguous dominant compartment; partners with no OpenCell line cannot
be placed and are counted, not dropped. Note how much the filter removes —
only 18% of placeable nucleolar links and 34% of plasma-membrane links survive
it.

**The shortlist is biologically clean.** It recovers known complexes without
being told about any of them: the CCT/TRiC chaperonin (CCT3–CCT4/5/6A), SWI/SNF
(SMARCB1/C1/E1–ARID1A/B–SMARCD1/2), RNA polymerase II (POLR2C–POLR2A/D/G), the
proteasome lid and core (PSMB4/PSMD7–PSMA5/PSMC2/4/5/PSMD1/2/13), V-ATPase
(ATP6V1A–ATP6V0A1/0D1/1B2/1H), Commander/CCC (CCDC93–CCDC22–COMMD1/2/4/6–VPS29),
the EMC (EMC1/2/3–EMC4/7/8/9–MMGT1), the oligosaccharyltransferase complex
(DDOST/STT3A/STT3B–RPN1/RPN2/DAD1/OSTC), endosomal SNAREs
(STX7/STX12–VAMP8–VTI1B–STX8), and most of the U2 spliceosome
(SF3A1/SF3B1–SF3B2/3/5/6–SNRNP40–SNRPD2). As a list of who can actually
interact with whom, it works.

**And it is not a better feature.** Screened the same way, the co-located
partner set scores *worse* than predicting the training mean:

| block | raw R² | p | within-compartment R² | p |
|---|---|---|---|---|
| interactome, co-located partners only | **−0.358** | 0.998 | −0.079 | 0.936 |
| interactome, cross-compartment partners only | 0.003 | 0.256 | −0.030 | 0.574 |
| esm + co-located interactome | 0.202 | 0.000 | −0.040 | 0.280 |
| esm alone, for comparison | 0.253 | 0.000 | −0.035 | 0.262 |

Adding the shortlist to ESM-2 makes it worse (0.253 → 0.202). Two reasons, and
the first disqualifies the block regardless of its score: the co-located set is
*constructed from the protein's own compartment label*, so it is circular by
construction and could not have been used as an honest feature anyway. Second,
it is a sparse, strongly bimodal signal — a protein in a large co-located
complex gets a dense vector, a protein with none gets zeros — and that mapping
does not transfer to held-out proteins.

So the shortlist answers a real biological question and does not answer this
one. Worth keeping for what it is; not worth carrying as a description.

## Part two: all the gene data, matched in a shared space

The screen above failed in a way that suggested two things were wrong with it,
not one. It used a handful of features, and it asked the question backwards.

**More data.** Six new image-independent blocks, 1,726 description dimensions in
total: **STRING** functional associations (score profile over a 512-gene
reference panel, plus per-channel strength), **GO** biological process and
molecular function, **Reactome** pathways, **HPA** expression specificity across
tissues, cell types, cancers and cell lines, and **AlphaFold** confidence and
compactness. DepMap co-essentiality would have been the best single source and
is unreachable — the portal is behind a bot wall and the figshare mirror returns
403 — so the STRING profile stands in for it.

The exclusions are load-bearing. **GO cellular component is dropped** (280,334
annotations, against 626,111 process and function ones kept) and so are all four
**HPA subcellular columns**, because HPA derives those from immunofluorescence —
the same measurement being predicted. UniProt's location keywords stay out of
every combination.

**Matching, not predicting.** Regressing the 36-dim image descriptor spreads a
shared signal over 36 regressions and asks the description to explain exposure
and cell density too. Identification by fingerprint is **canonical correlation**:
put both views in one shared space and measure whether they still co-vary on
proteins the fit never saw. Components and ridge are chosen by 5-fold on
training proteins only, over one grid used identically for the observed fit and
for all 300 permutations, so the null carries the same selection optimism the
observed value does.

**One leak closed first.** The initial version residualised only the image view
by compartment. A gene-level view like the STRING profile encodes compartment
strongly, and training-estimated compartment means leave a residual offset in
held-out proteins, so the method could pair leftover compartment against
leftover compartment. Both views are now residualised on the compartment
one-hot with training-fitted coefficients. Everything below is after that.

### Result

53 held-out proteins, 7 candidate sets, retrieval chance 0.132, 300
permutations, 16 combinations tested (Bonferroni threshold 0.0031).

| fingerprint | dims | shared-space corr | p | retrieval top-1 | p | chance |
|---|---|---|---|---|---|---|
| **string_profile** | 512 | **0.385** | **0.000** | **0.245** | **0.017** | 0.132 |
| EVERYTHING | 1726 | **0.453** | **0.000** | 0.189 | 0.137 | 0.132 |
| go_process_function | 301 | **0.370** | **0.000** | 0.057 | 0.980 | 0.132 |
| baseline | 51 | 0.370 | 0.003 | 0.113 | 0.730 | 0.132 |
| alphafold | 8 | 0.314 | 0.013 | 0.208 | 0.067 | 0.132 |
| string_channels | 9 | 0.193 | 0.160 | 0.245 | 0.013 | 0.132 |
| esm + databases | 1601 | 0.163 | 0.250 | 0.226 | 0.030 | 0.132 |
| topology | 10 | 0.229 | 0.113 | 0.189 | 0.127 | 0.132 |
| reactome | 201 | 0.109 | 0.423 | 0.075 | 0.940 | 0.132 |
| **esm** | 480 | 0.085 | 0.553 | 0.151 | 0.330 | 0.132 |
| hpa_expression | 90 | 0.082 | 0.510 | 0.057 | 0.977 | 0.132 |
| databases only | 1121 | 0.078 | 0.583 | 0.189 | 0.110 | 0.132 |
| lowcomplexity | 5 | 0.069 | 0.657 | 0.132 | 0.460 | 0.132 |
| domains | 16 | 0.033 | 0.830 | 0.132 | 0.593 | 0.132 |
| composition | 27 | 0.008 | 0.957 | 0.113 | 0.727 | 0.132 |
| function_kw | 16 | 0.000 | 1.000 | 0.113 | 0.733 | 0.132 |

**The method change was the substantive one.** Under regression every block gave
a within-compartment R² of zero. Under shared-space matching, five clear the
permutation null on the correlation, three of them past Bonferroni. Regressing
36 outputs was diluting a signal that was there.

**One fingerprint clears both tests: STRING functional associations.** Shared
correlation 0.385 (p = 0.000, past Bonferroni) *and* identification 0.245
against a chance of 0.132 (p = 0.017). It is the first description in three
studies to beat the within-compartment null at identifying the protein. That is
also mechanistically the one to expect: STRING associations partly encode
complex membership, and members of a complex genuinely co-localise at
sub-compartment scale — the co-location shortlist above recovered CCT, SWI/SNF,
the proteasome, V-ATPase, the EMC and the OST complex without being told about
any of them.

### Four things that stop this being a claim

1. **The retrieval p does not survive multiple testing.** 0.017 against a
   Bonferroni threshold of 0.0031 over 16 combinations. Suggestive, not
   established.
2. **A significant correlation is not a usable identification, and this run
   proves it.** `go_process_function` has one of the strongest correlations
   (0.370, p = 0.000) and a retrieval of **0.057** — less than half of chance.
   A real shared direction can be actively wrong for ranking. Anyone reading
   only the correlation column would conclude GO works.
3. **Two of the five "significant" correlations look like noise on inspection.**
   `baseline`'s held-out components are [0.370, −0.135, 0.017] — one direction
   and nothing behind it, with below-chance retrieval. `alphafold`'s held-out
   correlations (0.314) *exceed its training* correlations (0.139), which with 8
   dimensions means instability, not signal. `EVERYTHING` gives [0.453, 0.06,
   0.491] — a near-zero middle component between two strong ones, the signature
   of unstable canonical directions.
4. **The effect is modest even taken at face value.** 0.245 against 0.132 is
   right roughly one time in four instead of one in eight, on 53 proteins in
   candidate sets of 8.

And the earlier headline does not survive: **ESM-2 alone fails this test**
(0.085, p = 0.553). Its raw R² of 0.253 really was all compartment.

## Part three: combining ESM-2 with STRING, and why no combination survives

The obvious next move was to put the two best-motivated fingerprints together: a
sequence language model and the functional-association profile that was the only
block to clear both tests. The cached ESM-2 embeddings were reused, not
recomputed.

**Concatenation.** ESM destroys it, exactly as predicted before the run, and one
result was not predicted:

| fingerprint | dims | corr | p | retrieval | p | held-out components |
|---|---|---|---|---|---|---|
| string_profile + string_channels | 521 | **0.494** | **0.000** | 0.226 | 0.047 | [+0.49, +0.26, +0.31] |
| string_profile | 512 | 0.385 | 0.000 | **0.245** | **0.017** | [+0.38, +0.27, +0.25] |
| string_channels | 9 | 0.193 | 0.160 | 0.245 | 0.013 | [+0.19, +0.29, −0.03] |
| esm + string (both) | 1001 | 0.113 | 0.423 | 0.151 | 0.423 | [+0.11, +0.32, +0.19] |
| esm + string_profile | 992 | 0.099 | 0.473 | 0.170 | 0.253 | [+0.10, +0.33, +0.18] |
| esm | 480 | 0.085 | 0.553 | 0.151 | 0.330 | [+0.09, +0.16, +0.06] |

Adding ESM takes STRING from 0.385 (p = 0.000) to 0.099 (p = 0.473). The two
STRING blocks together reach 0.494, above either alone.

**Then the same combinations with an equal component budget.** Concatenation is
not a fair fusion: measured on these views, ESM-2 carries ~22 effective
dimensions against the STRING profile's ~7.6, so a joint PCA spends its budget
on ESM. Giving each block 8 components first should fix that. It does something
worse — it **inverts the ranking**:

| fingerprint | concat corr | p | blockwise corr | p |
|---|---|---|---|---|
| string_profile + string_channels | **0.494** | **0.000** | 0.174 | 0.210 |
| esm + string (both) | 0.113 | 0.423 | **0.300** | **0.033** |
| esm + string_profile | 0.099 | 0.473 | 0.197 | 0.120 |

The best combination under one fusion rule is the worst under the other, and
both rules are defensible. **That is an analysis-sensitivity failure, and it
disqualifies every combination here**, including the 0.494 that looked like the
strongest result in this document a paragraph ago.

The mechanism is visible in the components. CCA orders its directions by
training correlation, so the first should be the strongest held out as well.
It usually is not: blockwise gives [+0.17, +0.32, +0.38], [+0.20, +0.10, +0.46]
and [+0.30, +0.12, +0.44] — the *third* component is the strongest in all three.
The canonical directions do not keep their order out of sample, so "the first
held-out canonical correlation" is a noisy statistic, and which fingerprint wins
depends on an arbitrary preprocessing choice. At 109 training proteins the
multi-view fusion is underdetermined.

### What does survive

**Only the single-block STRING profile**, and for a reason that is structural
rather than lucky: with one block there is no fusion rule to choose, so the
result cannot move with it. Correlation 0.385 (p = 0.000, past Bonferroni) and
identification 0.245 against a chance of 0.132 (p = 0.017), unchanged by
anything in part three.

Retrieval is also the more stable of the two measures across fusion rules —
string_profile + string_channels gives 0.226 concatenated and 0.245 blockwise,
against correlations of 0.494 and 0.174 for the same pair. That is another
reason to treat identification, not correlation, as the headline number.

So the answer to "what do we get in total" is: **nothing reliable from
combining.** ESM-2 adds no complementary information to STRING under either
fusion rule that also keeps STRING's own signal, and the apparent gains from
combining STRING with itself do not survive a change of fusion. The
confirmatory experiment should register **one** fingerprint — the STRING
profile — and if it ever tests a combination, it must pre-register the fusion
rule, because that choice is worth more than the effect being measured.

### What to do next, in order

*Written at the end of part three. Items 1 and 2 were then carried out and
are answered in part four and in the registered scale-up; read them together.*

The situation has changed from "nothing works" to "one thing might", which
calls for a confirmatory test rather than more screening.

1. **Pre-register the STRING retrieval, and make it a harder test.** The
   suggestive result is one combination out of sixteen at p = 0.017. The
   confirmatory form should fix STRING as the single registered fingerprint in
   advance, and enlarge the candidate sets: the cytoplasmic compartment alone
   has 135 qualifying proteins, so chance can be 1/50 rather than 1/8, where a
   real effect is unmistakable and a fluke cannot survive. The true null
   (identical vectors for all candidates) goes in from the start.
2. **Test the mechanism, because it is checkable.** If STRING works through
   complex co-membership, then its retrieval should be much stronger for
   held-out proteins that have a co-located partner in the training set than for
   those that do not — and the co-location shortlist in
   [`compartment_interactions.csv`](../data/vcell/opencell/compartment_interactions.csv)
   already labels which is which. If that split shows nothing, the mechanism is
   something else and the feature is less trustworthy than it looks.
3. **Report the correlation and the retrieval together, always.** This run is
   the argument for it: GO reaches a correlation of 0.370 at p = 0.000 while
   identifying proteins at less than half of chance. Either number alone is
   misleading.
4. **Do not chase the remaining blocks.** ESM-2 alone, composition, topology,
   domains, keywords, Reactome and HPA expression are all at the null on the
   question that matters. A larger sequence model is worth one try, but the
   evidence now points at functional-association data rather than at sequence.
5. **Remember the irreducible confound.** OpenCell grows one line per well, so
   protein and clone cannot be separated in this dataset at all. Everything here
   is bounded by that, and a confirmatory result would want either multiple
   independent clones per protein or a transient-expression design.

## Part four: the physical fingerprint — AlphaFold size, shape, charge and diffusion

The request behind this part was specific: fetch each protein's predicted 3D
structure, measure its size, shape and charge, and let those imply a different
diffusion rate for every protein. The reasoning is sound — a small compact
protein and a long thin one do not spread through a cell the same way, and that
difference is physical rather than annotation-derived, so it cannot be a
compartment label in disguise.

**What was built.** AlphaFold DB models for **477 of 479** proteins (PRKDC and
TRRAP have no model), read as Cα traces, reduced to a 20-number fingerprint in
[`src/vcell/biophysics.py`](../src/vcell/biophysics.py) and split into three
registered blocks:

* **`bio_shape` (10 dims)** — radius of gyration, hydrodynamic radius, maximum
  dimension, asphericity, relative shape anisotropy, axial ratio, Perrin
  friction factor, compactness against the globular expectation
  `Rg ≈ 2.2·N^0.38`, elongation `Dmax/Rg`, and `log(N)`.
* **`bio_diffusion` (2 dims)** — the Stokes–Einstein coefficient those imply,
  `D = kT/(6πηR_h·F)` with `R_h ≈ 1.29·Rg` and `F` the Perrin factor for the
  equivalent ellipsoid, expressed as a ratio to a 30 kDa globular protein, and
  its log.
* **`bio_charge` (8 dims)** — net charge, charge per residue, isoelectric point
  by Henderson–Hasselbalch bisection, total and per-residue *surface* charge
  (solvent exposure from Cα neighbour counts), the charge dipole magnitude, and
  the exposed K/R and D/E fractions.

**The numbers are real and they spread.** Radius of gyration runs from 13.7 Å
(PFN1, profilin) to 110 Å (RNF40), a factor of 8. Axial ratio runs 1.15 (RBM33)
to 8.0 (VAMP8) and the Perrin friction factor with it, 1.00 to 2.25. The implied
diffusion coefficient therefore spans a factor of **10**: slowest RNF40, UTRN,
BET1L, EEA1, STIM1; fastest PFN1, LAMTOR2, TRAPPC2, VPS29, AP2S1 — which is the
right ordering, small adaptor and cargo subunits at the fast end, long coiled
tethers at the slow end. Isoelectric point runs 4.1 (PPM1G) to 12.2 (RPL13).
Nothing about the block is degenerate.

### Result

The full 461-protein pool this time, not the 53-protein subset of part two:
**308 training, 153 held out**, candidate sets of 43/35/27/15/14/11/8 by
compartment, pooled chance **0.046** (7 correct out of 153 by luck).
**300 permutations**, both views residualised on compartment, same CCA grid
re-selected inside every permutation. Bonferroni threshold over 7 blocks is
**0.0071**.

| block | dims | shared corr | p | top-1 | correct / 153 | p | null p95 |
|---|---|---|---|---|---|---|---|
| biophysics + string | 532 | **0.276** | **0.000** | 0.065 | 10 | 0.133 | 0.078 |
| string_profile | 512 | **0.246** | **0.000** | 0.039 | 6 | 0.703 | 0.072 |
| bio_shape + bio_charge | 18 | 0.176 | 0.053 | 0.033 | 5 | 0.837 | 0.072 |
| biophysics (all 20) | 20 | 0.175 | 0.040 | 0.026 | 4 | 0.923 | 0.072 |
| bio_shape | 10 | 0.148 | 0.097 | 0.065 | 10 | 0.130 | 0.072 |
| bio_charge | 8 | 0.139 | 0.093 | 0.059 | 9 | 0.220 | 0.072 |
| **bio_diffusion** | 2 | 0.045 | 0.603 | 0.039 | 6 | 0.720 | 0.072 |

**No block identifies a protein above its own permutation null. Not one.** The
best identification in the table is 10 correct out of 153 where luck gives 7 and
the 95th percentile of the shuffled null reaches 11. Every retrieval p-value is
above 0.13.

**The diffusion rate specifically does not work.** `bio_diffusion` is the
weakest block in the study: correlation 0.045 at p = 0.603, identification at
chance. Collapsing size and shape into one physically-motivated scalar throws
away whatever little the ten shape numbers carried — the physics is right, but
two numbers cannot distinguish 43 proteins that already share a compartment.

**Two blocks clear Bonferroni on correlation only**: `string_profile` (0.246)
and `biophysics + string` (0.276). So biophysics does add **+0.030** of shared
correlation on top of STRING, and adds it with better-conditioned held-out
components ([0.276, 0.241, 0.06] against STRING's [0.246, 0.242, 0.009]) — a
genuine second direction rather than one direction and noise. It buys no
identification. Part two's lesson repeats exactly: a significant correlation is
not a usable identification.

### A correction to something I said earlier

Reporting from a 4-permutation smoke test while the real pass was running, I
told the user that shape and charge looked better than diffusion and that
separating them out rather than collapsing to a diffusion rate "was the right
call." **The 300-permutation result does not support that.** `bio_shape` is at
p = 0.097 and `bio_charge` at p = 0.093 — neither significant — and
`bio_shape + bio_charge` *identifies worse* (0.033, 5 correct) than `bio_shape`
alone (0.065, 10 correct) and worse than chance. The separation I claimed was
vindicated is not distinguishable from noise in either direction. Four
permutations cannot support a comparison between blocks and I should not have
drawn one from them.

### One discipline fault to record

This screen ran `string_profile` on the same 461-protein pool, the same seeded
split and the same within-compartment protocol as registered Experiment 2 of
[`PREREG_SCALE.md`](PREREG_SCALE.md), because it was included as the comparison
column. **That means the registered primary quantity was observed here, through
an unregistered route, before the registered run finished.** Nothing in the
registered analysis was chosen after the fact — the script, split seed, single
fingerprint, 1,000 permutations and retrieval-as-primary were all committed
beforehand and are unchanged — so the registered result stands as specified and
is reported in its own document. But the peek happened and belongs on the
record.

What it shows is worth stating plainly in advance of that report: at 43-way,
`string_profile` identifies held-out proteins at **0.039 against a chance of
0.046** — below chance, p = 0.703. Part two's 0.245-against-0.132 at 8-way does
not reproduce when the candidate set grows. That is the outcome
[`PREREG_SCALE.md`](PREREG_SCALE.md) registered as the most likely single result
and said would be reported as the headline if it happened.

### What this leaves

The physical fingerprint was the best-motivated idea in the study — image-
independent by construction, immune to the annotation circularity that
disqualified GO cellular component and the HPA subcellular columns, and
measuring a property that demonstrably varies tenfold across the pool. It still
does not identify a protein within its compartment. Combined with STRING failing
to replicate at 43-way, the honest summary of the whole description study is
that **nothing tested so far identifies which protein produced an image, given
its compartment** — and the two things that looked like exceptions were a small
candidate set and a correlation mistaken for an identification.
