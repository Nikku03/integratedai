# Screen: eight descriptions of a protein, including a language model. None works

**Exploratory, not pre-registered.** The two studies before this
([`RESULT_VIRTUAL_CELL.md`](RESULT_VIRTUAL_CELL.md),
[`RESULT_OPENCELL.md`](RESULT_OPENCELL.md)) were registered in advance. This is a
screen — its job is to find out which descriptions are worth registering a
confirmatory test on. Every number carries a permutation null, and the honest
reading of a screen is "nothing here justifies the next experiment yet", which
is what it returned.

Run with `scripts/vcell_describe.py`. 162 OpenCell proteins with images, 109
training and 53 held out, reusing the tiles and the protein split from the
OpenCell study. Data in [`data/vcell/opencell/describe_screen.json`](../data/vcell/opencell/describe_screen.json).

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

### What to do next, in order

1. **A larger sequence model, with position kept.** ESM-2 35M mean-pooled is the
   weakest useful version of this feature. `esm2_t33_650M` with per-residue
   states preserved is the obvious next try, and the screen here runs it in
   seconds once embedded — no training needed to find out.
2. **Only then register a confirmatory test.** If a block clears the
   within-compartment permutation null in this screen, the confirmatory form is
   the registered retrieval against a chance of 1/8, with the true null in place
   from the start, as in [`PREREG_OPENCELL.md`](PREREG_OPENCELL.md).
3. **If nothing clears it, say so and stop.** The screen is cheap precisely so
   that a null can be established over many candidates rather than assumed after
   one. Eight descriptions, one of them a language model, is not yet enough to
   call the question closed — but it is enough to stop guessing and to say that
   the obvious features are not the answer.
