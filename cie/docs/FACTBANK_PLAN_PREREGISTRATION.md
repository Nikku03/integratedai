# Fixing the planning step: what decides, fixed before the test

> **Draft, being completed:** the development numbers marked DEV_ and the frozen fingerprints are filled in before the test set is drawn.

I wrote this on 2026-10-09:
- **after** developing the fix on the six earlier question sets, all of which I had seen;
- **before** drawing the test set's documents;
- **before** reading the test set's wordings.

Three new writers wrote those wordings and saved them to files that I have not opened. The results go in
`docs/FACTBANK_PLAN_RESULTS.md`.

## Why

The last test (`docs/FACTBANK_LLM_RESULTS.md`) and its review found that the plan learner, not the English, limits the
fact bank on multi-document questions:
- **What training never taught it.** The 48 training questions held no "when is the issue linked from PR #N due?" and
  only two "who opened the pull request". Every version scored 0 on the first kind.
- **Right by coincidence.**
  - None of v4's right answers to "which is due first, A or B?" read both due dates.
  - Some link answers came from reading a different ticket that happened to share the answer.
- **The wrong kind of answer.** It gave a status when asked "which ticket", and an assignee when asked "when".

A diagnosis on the six earlier sets (`cie/src/cie/factbank/plans.py`, run on 297 questions) found the same:
- For every wrong answer, a right plan was among the plans the bank could carry out.
- In most of the wrong link answers, the chosen plan gave the wrong kind of answer.

## What changes

### v9: the planner fixed; no model when a question is asked

1. **Training covers every kind of question** (`build_training_all`, `questions(every_field=True, all_wordings=True)`).
   - It uses the same 50 training documents.
   - It asks about every field each linked issue or ticket has, instead of one drawn at random.
   - It asks each question in all three training wordings, instead of one.
   - The result is 201 training questions instead of 48. `pr_issue/due_date`, never asked before, has 12.
2. **Learning only from plans that are right for the right reason** (`learn_plans(proper=True)`, `rests_on`).
   - In training, a plan counts as right only if two things hold: its answer is right, and it read every fact the answer
     rests on. Those facts are the question's pieces, the keys, values and dates it was built from.
   - Comparing two issues by when they were created, when the question asks which is due first, teaches nothing even
     when it happens to pick the right key.
3. **Two planner rules** (`Planner(rules="v9")`).
   - **The system asked about.** A question that names two systems starts in one and asks about the other. For example,
     "who opened the GitHub pull request that references Linear issue ENG-1?" asks about GitHub. The plan's answer must
     come from that system.
   - **No counting or listing what can only be one thing.** That rules out a plan with no hop, or one with one start and
     only single-valued hops.
4. **Checks when a question is asked** (`Planner.check`). They apply in turn. A check that no remaining plan passes is
   skipped.
   1. **What the question is about.** A question that names something must be answered by a plan that starts from what
      it names. That can be a key, a pull request number, a person or a quoted title.
   2. **A choice.** A question that names two or more things to choose between must be answered by a plan that compares
      exactly those things, with no hop.
   3. **The kind of answer.** The asked kind is a count, an item's key, a person, a date or another value. It is learned
      from the training questions as a naive Bayes model over the question's words (`AskedKind`). The plan must give that
      kind when the lessons are at least 0.9 sure of it.
5. **The glossary of v8**, unchanged (`docs/benchmarks/factbank_llm/glossary.json`).

The plan weights are learned again with all of this in place: `plan_lessons_v9.json`, sha256 in **Frozen** below.

### v10: v9 plus a small model's form

**What the model does:**
- Llama 3.2 3B runs locally (4-bit, CPU, the same model as v7). It does not rewrite the question.
- It fills in a two-line form: what kind of thing the answer is (a person, date, number, ticket key or status), and which
  property it is read from (assignee, due date, status, author, creator, owner or none).
- Its prompt has seven examples. Each is the first training wording of a kind, with made-up keys and names
  (`FORM_SYSTEM` in `cie/src/cie/factbank/reader.py`).
- It never sees a document.

**How the bank uses the form:**
- The form's kind replaces the learned kind in check 3.
- Check 4 applies the field. A plan answering with one value must read that field. A plan choosing an item by date must
  order by it.
- The bank then picks among the plans left with v9's weights, carries the plan out and records what it read.
- Every form is kept in a cache file, keyed by the question and the prompt's fingerprint.

### Also run, for information only

- **v9n:** v9 without the glossary, so no language model was involved at any point.
- **v4:** the plan learner as tested twice before.
- **v8:** the glossary, today's best.

## Development (all on sets I had seen)

**The sets:**
- the 48 training questions;
- the first held-out set;
- the retest;
- the new-words set;
- the general-English blind set;
- the language-model test set.

**How choices were made:** I looked at the failures there and changed the design. These numbers are therefore
optimistic and do not decide anything.

The mean of the five held-out sets (own answers, three-group mean):

| step | right answers | right for the right reason |
|---|---|---|
| v4 (as published) | 0.635 | 0.405 |
| v8, the glossary (as published) | 0.703 | 0.549 |
| + every kind in training (201 questions) | 0.649 | 0.436 |
| + only plans right for the right reason | 0.663 | 0.591 |
| + the glossary | 0.740 | 0.681 |
| + the planner rules and checks 2–3 | 0.879 | 0.870 |
| + plans also start from quoted titles (dropped: it hurt) | 0.865 | 0.856 |
| **+ check 1, what the question is about: v9** | **0.894** | **0.885** |
| v9n (v9 without the glossary) | DEV_V9N | DEV_V9N_R |
| **v10 (v9 + the 3B model's form)** | **DEV_V10** | **DEV_V10_R** |

**On the language-model test set itself:**

| | right answers |
|---|---|
| v4 | 0.586 |
| v8 | 0.601 |
| v9 | 0.933 |
| v10 | DEV_V10_LLM |

The form's prompt was settled on a 30-question sample of the held-out sets:
- **Without examples:** the kind of answer was right for 23 of 30.
- **With the seven training-wording examples:** 30 of 30.

That was the only prompt change.

## The test set (frozen)

**Documents:**
- A new sample of the whole benchmark: `fresh --seed 37`, stratified by source; questions seed 38.
- **Excluded:** every document of every earlier set (`mt5k`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`,
  `mdwords`, `mdblind`, `mdllm`) and the company lexicon's whole 200,000-document sample (`lexsample`).
- The changed-information copy is made by the fixed transform (`factbank_split changed`).

**Wordings:**
- Three new independent agent sessions wrote them, in roles not used before:
  - a finance analyst writing formal sentences;
  - a senior engineer in code review, writing tersely;
  - a marketing coordinator using plain everyday words.
- Each saw only what each question must ask, and saved its wordings to a file itself.
- I have not read those files.
- The same selection rule as before applies: writers 1 and 2 give the pair, and writer 3 stands in for an invalid
  wording. A script applied it without printing anything. No wording needed replacing.

| file | sha256 |
|---|---|
| `writer1.json` | `f755e60e28989478…` |
| `writer2.json` | `07a57423b6c5b0ea…` |
| `writer3.json` | `311e22e04d388a09…` |
| `wordings.json` (the pairs used) | `a4b84da56824b702…` |

## Measure

**Own answers, no model judging, as before:**
- values, dates and single keys must match exactly;
- lists score F1;
- a count must be the right number.

The mean is the mean of the three groups (link, combine, compare).

**New: right for the right reason.**
- An answer counts only if its plan read every fact the answer rests on (the question's pieces).
- This uses what the plan read, recorded with each answer (`Planner.reads`, `rests_on`).
- It is measured for every arm.

## Rules

1. **The fixed planner helps:** v9 − v4 ≥ +0.10, test set.
2. **It helps beyond the glossary:** v9 − v8 ≥ +0.05, test set.
3. **Right for the right reason:** v9 − v4 ≥ +0.10 on the test set, counting only answers whose plan read every fact
   they rest on.
4. **A small model's form adds:** v10 − v9 ≥ +0.05, test set.
5. **Principles, not memorisation:** v9 and v10 each on the test set ≥ the same arm on the 201 training questions it
   learned from − 0.15.
6. **It holds when the information changes:** v9 and v10 each on the changed copy ≥ the same arm on the test set − 0.05.
7. **No harm on what was learned:** v9 and v10 each ≥ v4 − 0.03 on the 48 first training questions.

**How to read differences:**
- One compare question moves the mean by 0.042; one link or combine question by about 0.015–0.02.
- So differences of 0.04 or less are within noise.

**Also reported:**
- v9n on the test set;
- every arm by kind of question;
- v10's time per question, and how often its form's kind differs from the learned one;
- every arm on the earlier sets, for information only.

## Frozen

FROZEN_BLOCK
