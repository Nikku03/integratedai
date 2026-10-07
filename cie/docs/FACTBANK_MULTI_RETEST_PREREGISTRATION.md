# Questions that need several documents: the retest of the revised planner. What decides, fixed before the run

I wrote this on 2026-10-07. The first test (`docs/FACTBANK_MULTI_PREREGISTRATION.md`) failed three of its four rules. The
results and the diagnosis are in `docs/FACTBANK_MULTI_RESULTS.md`. The planner was then revised (v4) using the training
questions only. The first held-out set has been seen, so it cannot judge the revision. This retest uses **new documents and
new wordings**. Its results go in the same results file.

## What changed (v4)

All changes are in `cie/src/cie/factbank/plans.py` (`rules="v4"`, `FEATURES_V4`). The first test's planner is still there
(`rules="v3"`). It reproduces the first test's lessons and answers exactly.

1. **The clue rule, split.** An answer that the question already contains counts against a plan. The one exception is a
   question that offers a choice: one that names two or more things that are not people ("A or B: which is due first?").
   v3 had one weight for both cases. The training set's compare questions made that weight positive, so 42 of the 48
   training answers were copied from the question.
2. **The kind of answer, learned from the question's words.** The question words are kept (who, how many, which…). The
   score is how much more often a word came with a count, a key, a date, a person or another value than these come in
   general. It replaces v3's fixed patterns, which read "which is due first? Give the key" as a question asking for a date.
3. **No walking back.**
   - Every hop must reach something new.
   - A plan may not follow a relation and then its inverse (`assignee` → `assignee_of`).
   - A plan may not read a field that points back where it came from.
   - A plan may not answer with only what it started from or passed through.
4. **One value means one value.** Every entity reached must agree on it. v3 read the first entity's value.
5. **The named system.** One more weight: the answer comes from the system the question names (Linear, GitHub…).

**Checks on the training set only:**
- 0.917 of the training questions answered right, in-sample, against 0.309 for v3.
- 0.688 when each of the three training wordings is held out in turn and the plans are learned from the other two.
- In that wording check, "how many" questions scored 0. Each training wording counts with a different word ("how many",
  "the number of", "count"). Without a language model, a new word for counting cannot be understood.

The final v4 lessons are learned from the same 48 training questions as v3:
`plan_lessons_v4.json`, sha256 `747150754ce6ad27…`.

## Data (frozen)

**Pool.** A new sample of the whole benchmark (511,958 documents):
- 20,000 documents, stratified by source, seed 13;
- none of them is among the 5,089 documents of the earlier 5,000-document haystack, which holds every document used
  before;
- only the sources whose documents link to each other are kept (Linear, GitHub, Jira, Fireflies): 2,322 documents.

**The retest set** is built from this pool with `python -m cie.eval.factbank_multi fresh`. It has 50 documents and
50 questions. It shares no document with the training set, the first held-out set or the two single-document sets.

| | documents | questions | link | combine | compare | sha256 of questions.jsonl |
|---|---|---|---|---|---|---|
| retest | 50 | 50 | 21 | 21 | 8 | `86f855bdd8b9ddc7…` |
| retest, changed information | 50 | 50 | 21 | 21 | 8 | `82913d4a7cce74c7…` |

By kind:
- pull request → Linear issue: 8;
- Linear issue → pull request author: 4;
- ticket → linked ticket: 9;
- a person's issue count: 6;
- a person's first issue due: 6;
- an action item's owner → their issues: 9;
- which of two is due first: 8.

The changed copy renames 118 people and moves every ISO date 23 days later, in the documents, the questions and the
answers.

**A first draw was discarded** before any answer was computed. It came from what was left of the 5,000-document
haystack, which had no unused pull request ↔ Linear pairs. That draw had 42 documents, 35 questions, no pull request
questions and only one action item question.

**Wordings.** A third pair of wordings per kind (`RETEST` in `cie/src/cie/eval/factbank_multi.py`). For example:
- "How many Linear issues does P currently own?"
- "Which deadline is sooner, the one for A or the one for B?"
- "Who owns the other ticket that K is connected to?"

I wrote them after the first test and before this set was drawn. I had seen v4's training checks and the words its
associations had learned. I wrote what a person would ask and did not check the wordings against the training words.

## Arms

| arm | |
|---|---|
| v1 | the fact bank's engine, untrained |
| v2 | with the single-document lessons |
| v3 | the plans as first tested (lessons from the 48 training questions) |
| **v4** | the revised planner (lessons from the same 48 training questions) |

The memory bank and the plain-search arms are not rerun. The first test already met its rule on gathering the
fragments (rule 4), and v4 changes only which plan is chosen.

## Measure

Own answers, no model, as in the first test:
- values and dates must match exactly;
- lists score F1;
- a count must be the right number.

The mean is the mean of the three groups (link, combine, compare).

## Rules

1. **Learned plans answer multi-document questions:** v4 − v1 ≥ +0.20, retest set.
2. **The revision helps on new data:** v4 − v3 ≥ +0.20, retest set.
3. **Principles, not memorisation:** v4 on the retest set ≥ v4 on its training questions − 0.15.
4. **It holds when the information changes:** v4 on the changed retest set ≥ v4 on the retest set − 0.05.

## Known limits

- **Designed after the first results.** v4 was designed after I had seen the first held-out results, including which
  plans won there. The fixes were developed and checked on the training questions only. That is why this retest uses
  new documents and new wordings.
- **Template questions.** The questions still follow templates, and there are 4–9 questions per kind.
- **No language model.** A word that no training question used can be understood only through field names.
