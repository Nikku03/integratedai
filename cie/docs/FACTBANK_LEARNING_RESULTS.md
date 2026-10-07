# Teaching the fact bank, then a fair retest: results

**Run on 2026-10-07, after the rules in `docs/FACTBANK_LEARNING_PREREGISTRATION.md` were written and the held-out set
was frozen.**
- Raw results and the learned lessons: `docs/benchmarks/factbank_learning/`.
- Code: `cie/src/cie/factbank/learn.py`, `trained.py`; `cie/src/cie/eval/factbank_split.py`.
- No language model was used anywhere.

## Decision

| Rule | Result |
|---|---|
| 1. Learning helps the fact bank's own answers (v2 − v1 ≥ +0.10, held-out) | **Not met:** 0.567 against 0.578 (−0.011) |
| 2. It holds when the information changes (changed ≥ held-out − 0.05) | **Met:** 0.550 against 0.567 (−0.017) |
| 3. Better evidence near the top (v2 − v1 ≥ +0.05, first 2,000 characters, held-out) | **Met:** 0.886 against 0.722 (+0.164) |
| 4. Not worse than the memory bank (every group, 24,000 characters, held-out) | **Met:** 1.000 in every group, against 0.909, 0.550 and 0.250 |

In short:
- What it learned about **lists** and about **ordering its evidence** carried over to new documents, new wording and
  changed information.
- What it learned about **choosing a single answer** did not. It learned words, not concepts: "due" rather than "a
  deadline".

## What it learned

From the 50 training questions (`lessons.json`; weights of a logistic regression):
- **Finding the document:** keyword rank +4.9, being a meeting's action item +4.4, the question repeating the title
  +2.9, the question repeating the document's own field values ("clues") +2.3.
- **Choosing the answer:**
  - for a value from a sentence, the sentence sharing the question's words +8.6;
  - the field's name sharing the question's words +6.8;
  - the kind of value fitting the question (a date for "when", a person for "who") +4.8;
  - **a value the question already contains is a clue, not the answer −4.1.**
- **Lists:** "list", "every", "keys", "numbers" and plural item nouns mark a list question. Pull-request lists mean
  the author; Jira lists mean the assignee.
- **Its strongest word links:** "due", "item", "linear", "issue", "took" → the due date. These are the training
  questions' fixed wording.

## Results

Own answers (no model): owners and deadlines are the share correct; lists are mean F1.

| | owners | deadlines | lists | mean |
|---|---|---|---|---|
| **held-out** (22 / 20 / 4 questions), v1 untrained | 0.591 | 0.850 | 0.292 | 0.578 |
| held-out, v2 trained | 0.500 | 0.200 | **1.000** | 0.567 |
| **changed information**, v1 | 0.591 | 0.850 | 0.292 | 0.578 |
| changed information, v2 | 0.500 | 0.150 | 1.000 | 0.550 |
| training (in-sample), v1 | 0.654 | 1.000 | 1.000 | 0.885 |
| training (in-sample), v2 | 0.500 | 0.889 | 1.000 | 0.796 |

Answer within the evidence (held-out; mean of the three groups):

| arm | first 2,000 characters | first 24,000 |
|---|---|---|
| fact bank v2 (trained) | **0.886** | **1.000** |
| fact bank v1 | 0.722 | 0.985 |
| plain keyword search | 0.860 | 1.000 |
| plain keyword + vector search | 0.678 | 0.944 |
| memory bank (present) | 0.405 | 0.570 |

The changed set gives the same picture: v2 0.886 / 1.000, bank 0.420 / 0.570.

## What worked

- **Lists, in wording it had never seen:** 4 of 4, against 0.292 for v1. For example, "What PRs has Priya Natarajan
  opened on GitHub? Just the numbers." v1's fixed phrases did not recognise the new wording. v2 had learned what marks a
  list (plural items, "numbers"), and that a pull-request list means its author.
- **Its evidence:**
  - With the likely answers first, the answer is in the first 2,000 characters for 0.886 of the held-out questions.
    That is up from 0.722, and slightly ahead of plain keyword search (0.860).
  - Within 24,000 characters, every answer is there. The present memory bank has 0.570.
- **Changed information:** with 128 people renamed and every date moved by 23 days, every arm scores within 0.02 of
  the held-out set. Nothing depends on remembered names or dates.

## What failed, and why

- **Deadlines fell from 0.850 to 0.200.** It learned that a "when" question wants a date, but it told the due date
  from other dates by the word "due".
  - All 18 training deadline questions contain "due".
  - The reworded test questions say "deadline", "by what date" or "have to finish".
  - It then took a date from a sentence (9 questions), the meeting's date (5) or the last-updated date (2).
- **Owners fell from 0.591 to 0.500.** It fixed 3 questions v1 missed and broke 5 that v1 had right.
- **Even on its own training questions, v2 answers worse than v1** (0.796 against 0.885). These few features cannot
  separate "the due date" from "a date" without the word cue.

**The lesson about learning itself:** 50 examples phrased one way per kind teach the phrasing. "Deadline" means the
due date only if training shows it, or if something already knows the language. Two ways forward:
- train on many differently worded questions;
- let a language model choose which field is asked for, keeping the fact bank for finding and the engine for chaining.

The second is what the memory test's `bank+lookup` arm already does.

## Checks

- **The held-out set was frozen before training:**
  - questions.jsonl sha256 `763c1ada5d09ae87…`; changed copy `691da4d72baf0a3a…`;
  - no document shared with training;
  - its wordings were written before anything was learned.
- **The changed set was reloaded properly.** The present memory bank was reloaded from the changed documents: the first
  run had reused the unchanged tenant, because the document ids are the same, and was redone. The new names appear in
  its evidence.
- **Journals replay:** every journal replays (46 of 46, twice; 50 of 50 on training).
- **A bug found after the run.** The list detector counted words inside quoted titles ("…wifi keys"). It was fixed
  after the run. Rechecked on all three sets, the fix changes no question's decision, so the results above stand
  as run.
- **Tests:** `tests/test_factbank.py`, 6 tests. They cover the rewording and changed-information transforms, and
  learning, saving and loading lessons on a tiny bank.

## Limits

- 46 held-out questions, with only 4 lists; one fictional company.
- The learned parts are small linear models over hand-chosen principles. They cannot invent a principle that is not
  among their features.
