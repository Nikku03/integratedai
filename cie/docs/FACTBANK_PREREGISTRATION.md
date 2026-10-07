# Can the fact bank replace the memory bank? What decides, fixed before the run

I wrote this on 2026-10-07, before the fact bank had answered any of these questions. The results go in
`docs/FACTBANK_RESULTS.md`.

## What is tested

The **fact bank** (`cie/src/cie/factbank/`) is the memory bank of the Nikku03/cell repository rebuilt for company
documents. The cell bank stores cell biology; what carries over is its design.

From `memory_bank/facts` and its checker:
- one atomic, sourced fact per claim, with a confidence level (measured, inferred, estimated, assumed);
- a checker that refuses a broken bank;
- plain files and SQLite, with no vectors.

From the v2 engine, `rem/atlas/cellbank2.py`:
- facts looked up by their subject;
- one hop at a time, with each result written down and never decided again;
- weighted votes when facts disagree, with exact ties recorded as contradictions;
- a per-hop decay of 0.863 for ranking;
- a journal that must replay to the same state.

It is compared with the **present memory bank** (`bank`: its own search with every default), and with plain search over
the raw documents (`plain-words`: keywords; `plain`: keywords and vectors).

## Data

EnterpriseRAG-Bench's fictional company. `python -m cie.eval.factbank_test select` (seed 7) chooses:
- **50 questions** from the memory test's set, all with code-checkable answers:
  - owners: 26, the benchmark's metadata questions;
  - deadlines: 18;
  - lists: 6.
- **50 documents:** every gold document of those questions.

Conflict questions are left out: only the judge model can score them, and no model runs in this test.

## Measures

1. **Answer within the evidence:** whether the expected answer is in the first 2,000, 6,000 and 24,000 characters of
   each arm's evidence.
   - Owners: the field value.
   - Deadlines: the date.
   - Lists: the share of the expected keys.

   24,000 characters is what the answering model reads in the memory test.
2. **Answers from the fact bank alone, with no model:** its answer is checked by the memory test's own code check.
   Owners and deadlines score the share correct; lists score the mean F1.
3. **Cost:**
   - storage for these 50 documents (the bank's rows and keyword index against the fact bank's SQLite file);
   - build time;
   - median search time.
4. **Checks:**
   - the fact bank's checker passes;
   - every question's journal replays to the state the engine wrote.

## Rules

Decided on point estimates. A group mean is over its questions, and "the mean" is the mean of the three groups.

1. **Not worse at the evidence budget:** fact bank − bank ≥ −0.03 in every group, within 24,000 characters.
2. **Better near the top:** fact bank − bank ≥ +0.10 on the mean, within the first 2,000 characters.
3. **Answers without a model:** the fact bank's own answers score ≥ 0.70 on the mean.
4. **Smaller:** the fact bank takes at most a third of the bank's storage.

**Replace** if rules 1, 2 and 4 are met. Rule 3 says whether, beyond that, it can answer field questions with no model
at all.

## What each outcome means

- **Replace met.** The fact bank becomes the memory for company records. Before the product's default changes, it
  must hold on the 5,000-document haystack and with a model answering on Colab, because 50 documents make search easy.
- **Rule 1 not met.** The present bank stays. The fact bank's useful parts (sourced facts, the checker, the journal)
  are considered for adding to it instead.

## Known limits

- **It favours the fact bank.** The owner and deadline answers are field values, and the fact bank stores fields as
  facts. The memory test's pre-registration notes the same limit for its lookup arm.
- **Text is not parsed into facts.** Only fields and meeting action items are; answers that live only in prose are
  reached through the documents' text, which the fact bank appends after its facts.
- **Small.** 50 questions and 50 documents, one fictional company; six list questions.
