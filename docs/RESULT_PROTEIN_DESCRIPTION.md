# Screen: what a protein is, versus what it looks like. One fingerprint survives

**Exploratory, not pre-registered.** Two parts. Part one screens eight
descriptions by predicting the image descriptor, and **none of them works**.
Part two adds every gene-level database within reach and changes the method from
prediction to shared-space matching, and **one fingerprint clears both tests**:
a protein's STRING functional-association profile identifies it within its
compartment at 0.245 against a chance of 0.132. That result is suggestive rather
than established, for four reasons set out at the end of part two, and the
confirmatory version needs pre-registering.

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

### What to do next, in order

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
