# Understanding new words without a language model: results

**Run on 2026-10-07**, by the rules in `docs/FACTBANK_WORDS_PREREGISTRATION.md`. Those rules were written before the
word learning was built. The method and its fingerprints were added to that document before the run.
- Raw results: `docs/benchmarks/factbank_words/`.
- Code: `cie/src/cie/factbank/lexicon.py` (learning word meanings) and `Planner.enrich` in
  `cie/src/cie/factbank/plans.py` (using them).

## In short

**It did not work.** On 50 questions where half the words are new, the planner with learned word meanings (v5) answered
0.576 right. Without them (v4) it answered 0.611. The word meanings were learned from 200,000 of the company's own
documents, and they changed two answers, both for the worse.

The reason is the text it learned from. These documents are technical chat, email and tickets about one product:
- They place words by **topic, not by meaning.** "created" sits next to "ticket" and "Jira" ("created a ticket in
  Jira"), and "nearest" sits next to vector search.
- The **plain English words** managers use when they ask questions were too rare or too far from any known word to
  borrow a meaning. Examples: responsible, handling, stage, urgent, ship, tally, soonest, submitted. 72 of the 127 uses of
  new words borrowed nothing.

## Decision

| Rule | Result |
|---|---|
| 1. New words are understood (v5 − v4 ≥ +0.10, new-words set) | **Not met:** 0.576 against 0.611 (−0.035) |
| 2. Principles, not memorisation (new-words set ≥ training − 0.15) | **Not met:** 0.576 against 0.927 (−0.351) |
| 3. It holds when the information changes (changed ≥ new-words set − 0.05) | **Met:** 0.576 against 0.576 |
| 4. No harm where v4 already worked (v5 ≥ v4 − 0.03, retest set and training) | **Met:** retest 0.631 against 0.596; training 0.927 against 0.927 |

## Results

Own answers, no model (the mean is the mean of the three groups):

| | link | combine | compare | mean |
|---|---|---|---|---|
| new-words set, v1 (untrained) | 0.053 | 0.087 | 0.000 | 0.047 |
| new-words set, v4 | 0.263 | 0.696 | 0.875 | 0.611 |
| new-words set, **v5** | 0.158 | 0.696 | 0.875 | **0.576** |
| changed information, v4 / v5 | | | | 0.611 / 0.576 |
| retest set (seen in development), v4 / v5 | | | | 0.596 / 0.631 |
| training questions, v4 / v5 | | | | 0.927 / 0.927 |

**By kind** (new-words set):
- v5 equals v4 on every kind except one: Linear issue → pull request author (5 questions), where it drops from 0.4 to
  0.0.
- The two questions v5 lost ask "Who created that PR?". "created" borrowed "ticket" and "Jira" (0.81 and 0.78 close),
  and the plan moved to a ticket's assignee.

**The right plan was always there.** For all 50 questions, one of the enumerated plans gives the right answer. v5 ranked
it first for 26 and within the top three for 34.

**v4 itself** did about as well on these new wordings (0.611) as on the retest's (0.596). The new words did not make the
questions harder for it than earlier new wordings had.

## What it learned

**The lexicon** (`lexicon_info.json`):
- 200,000 documents, none from any test set;
- 11.5 million sentences and 131 million words;
- 40,000 words kept;
- 60,210 people's names and 16 statuses taken from the documents' own fields.

**What works** (checked on development words only):
- "own" sits near "owns", "owner" and "assign".
- "total" sits near "sum" and "count"; "several" near "many" and "multiple".
- "deadline" sits near "date", "cutoff" and "end of day".
- "due" goes with dates (0.40 above the usual rate), and "author" with people's names.

**What does not:**
- "nearest" sits near vector-search words (knn, hnsw).
- "wrote" sits near names and email words.
- "state" sits near "etcd" and "lease".

**On the test's new words** (looked at after the run):
- 55 of the 127 uses of new words borrowed something, and only a few borrowings were right: "big" → "many", "queue" → "count".
- Several were topical rather than meaningful: "created" → "ticket" and "Jira", "land" → "PR", "target" → "minutes",
  "engine" → "owns".

## What was tried in development

Development used only the training questions and the retest set, which had already been seen.

| | retest set | training, one wording held out at a time |
|---|---|---|
| v4 | 0.596 | 0.752 |
| similarity, anchoring and value-kind features, 20,000 documents | 0.628 | 0.786 |
| the same, 60,000 documents | 0.580 | 0.786 |
| only content words lend meaning | 0.596 | 0.721 |
| plus the value-kind feature | 0.580 | 0.723 |
| leave out every question with the same wording while learning | 0.435 | 0.708 |
| borrowing through associations and value kinds (60,000 documents) | 0.612 | 0.752 |
| 200,000 documents, window 2 | 0.615 | 0.752 |
| **plus borrowing from field-name words (frozen v5)** | **0.631** | **0.752** |

The development gains were small (+0.035 on the retest set, none on the held-out training wordings). The
pre-registration noted before the run that rule 1 might not be met.

## Corrections and limits

- **Two names for one check.** The pre-registration gives "0.688" for v4's held-out-wording check. That is the share of
  questions. The tables here give the mean of the three groups (0.752). The two are the same run.
- **The lexicon file** (12.6 MB) is not committed. Its fingerprint and settings are in `lexicon_info.json`. It also
  holds field-anchoring counts from an earlier version of the code, which are not used.
- **Small numbers.** The test has 50 questions, so one question moves a group's score by 0.04–0.14.

## What could work instead

These are not tested; each would need its own pre-registered test.
- **Ask when unsure, and remember.**
  - When the top plans disagree and the question has words the bank does not know, ask: "Do you mean who it is
    assigned to, or who created it?"
  - Keep the answer as a lesson for that word. Each new word is then learned once, from the person who used it.
- **Plain English counts.** Learn the same counts from a large body of general English (for example Wikipedia),
  besides the company's text. Meaning-level neighbours ("responsible" near "owner", "urgent" near "soon") need text
  where these words are common.
