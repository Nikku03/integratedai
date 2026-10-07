# Can the fact bank replace the memory bank? Results

**Run on 2026-10-07, after the rules in `docs/FACTBANK_PREREGISTRATION.md` were written.**
- Raw results: `docs/benchmarks/factbank50/`.
- Code: `cie/src/cie/factbank/` (the bank), `cie/src/cie/eval/factbank_test.py` (the test).
- The set is 50 documents and 50 questions: owners 26, deadlines 18, lists 6.
- No language model was used: every score is a code check.

## Decision

| Rule | Result |
|---|---|
| 1. Not worse at the evidence budget (fact bank − bank ≥ −0.03 in every group, 24,000 characters) | **Met:** +0.154 owners, +0.500 deadlines, +0.417 lists |
| 2. Better near the top (fact bank − bank ≥ +0.10 on the mean, first 2,000 characters) | **Met:** +0.392 |
| 3. Answers without a model (≥ 0.70 on the mean) | **Met:** 0.885 |
| 4. Smaller (at most a third of the bank's storage) | **Not met:** 1.81 MB against 3.04 MB, or 60% |

**Replace: not decided.** The rule required 1, 2 and 4, and storage missed its bar. On everything else the fact bank
is far ahead of the present memory bank.

## Answer within the evidence

| arm | first 2,000 chars | first 6,000 | first 24,000 |
|---|---|---|---|
| memory bank (present) | 0.375 | 0.414 | 0.630 |
| **fact bank** | **0.767** | **0.962** | **0.987** |
| plain keyword search over the raw documents | 0.823 | 0.972 | 1.000 |
| plain keyword + vector search | 0.684 | 0.765 | 1.000 |

Scores are the mean of the three groups. Per group, at 24,000 characters:

| arm | owners | deadlines | lists |
|---|---|---|---|
| memory bank | 0.808 | 0.500 | 0.583 |
| fact bank | 0.962 | 1.000 | 1.000 |

- **Where the present bank fails, the fact bank doesn't.**
  - The bank's evidence did not contain the due date for 9 of the 18 deadline questions, all of them Linear issues;
    their date is a field the bank's evidence did not show.
  - It missed some or all of the pull requests in 4 of the 5 lists of a person's pull requests.
  - The fact bank stores every field as a sourced fact and puts the matching facts first.
- **At 50 documents, plain keyword search does as well.** It finds every answer within 24,000 characters, and
  is slightly ahead in the first 2,000 (0.823 against 0.767). With 50 documents finding the right one is easy. This
  repeats an earlier finding: the present bank's search does no better than plain keywords. Whether the fact bank holds
  up when search is hard needs the 5,000-document haystack.

## Answers from the fact bank alone, with no model

| owners | deadlines | lists (mean F1) | mean |
|---|---|---|---|
| 0.654 (17 of 26) | 1.000 (18 of 18) | 1.000 (6 of 6) | 0.885 |

- **Every deadline and every list was answered exactly.**
  - Deadlines: 10 Linear due dates and 8 meeting action items.
  - Lists: 5 lists of a person's pull requests and 1 of their Jira tickets. The engine found them by hopping from the
    person to their documents.
  - No list filtered by status or by date window happened to be among the 50 questions. The unit tests cover both.
- **The 9 wrong owner answers:**
  - 3 asked for a document's title (a pull request, a page, an account), and got a field of the right document instead
    (author, space, tier).
  - 5 asked for one field and got another that shares words with the question. For example, "deployment
    requirements" for "forecast close month", and "reviewers" for an item "in review".
  - 1 has its answer only in the text (an incident number a bot posted in Slack), and the wrong document was
    chosen.
  - Choosing the right field is what a language model would do better.

## Cost and checks

| | memory bank | fact bank |
|---|---|---|
| storage, these 50 documents | 3.04 MB | 1.81 MB |
| build | 1 min 40 s (with vectors) | 0.5 s |
| search, median | 150 ms | 5 ms |

- **The fact bank's 1.81 MB:**
  - facts: 43% (each repeats its claim text and context);
  - the copy of the documents' text for content search: 25%;
  - the keyword index: 12%.

  A contentless index and shorter claims would shrink it. That was not part of this test.
- **The checker passes:** every fact has a source, a confidence and its dependencies.
- **The journal replays:** for all 50 questions, the journal alone rebuilds exactly what the engine wrote.
- **No contradictions** were found in these 50 documents: no two sources disagreed about one entity's field.
- **The cell bank's 90-day staleness rule flags 1,956 of 1,969 facts.** The documents span several years, so for company
  records the rule needs a different reference (for example, the record's own update cycle).

## What this means

- **The present bank has a real gap: document fields are missing from its evidence.** The fact bank closes it.
- **The pre-registered rule does not allow replacing the bank yet**, because of storage. Two things should come before
  a switch:
  1. the same test on the 5,000-document haystack, where search is hard;
  2. a model answering from each arm's evidence on Colab.

  If storage is to be judged again, the rule should be set before the smaller layout is built.
- **Fair-test warning.** The owner and deadline answers are field values, and the fact bank stores fields as facts,
  so this test favours it.
