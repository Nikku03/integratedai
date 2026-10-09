# Fixing the planning step: what decides, fixed before the test

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

A diagnosis on the six earlier sets (297 questions) found the same:
- For every wrong answer, a right plan was among the plans the bank could carry out.
- In most of the wrong link answers, the chosen plan gave the wrong kind of answer.

## What changes

### v9: the planner fixed; no model when a question is asked

1. **Training covers every kind of question** (`build_training_all`; `questions(every_field=True, all_wordings=True)`).
   - It uses the same 50 training documents.
   - It asks about every field each linked issue or ticket has, instead of one drawn at random.
   - It asks each question in all three training wordings.
   - The result is 201 questions instead of 48. They include all of the 48: the random draws are kept in step.
     `pr_issue/due_date`, never asked before, has 12.
2. **Learning only from plans right for the right reason** (`learn_plans(proper=True)`, `rests_on`).
   - In training, a plan counts as right only if its answer is right **and** it read every fact the answer rests on (the
     question's pieces), each in its role:
     - a ticket key or pull request number must be one of the things the plan ends at;
     - a date, status or name must be a value of the plan's field on them, or a person the plan went through.
   - Comparing two issues by when they were created, when asked which is due first, teaches nothing. Neither does reading
     another ticket's assignee who happens to be the author.
3. **Two planner rules** (`Planner(rules="v9")`).
   - **The system asked about.** For each start, the system asked about is worked out: a question that names two systems
     starts in one and asks about the other (`target_system`).
   - **No counting or listing what can only be one thing.** That rules out a plan with no hop, or one with one start and
     only single-valued hops.
4. **Checks when a question is asked** (`Planner.check`). They apply in turn, and a check that no remaining plan passes
   is skipped.
   1. **What the question is about.** A question that names something (a key, a pull request number, a person, a quoted
      title) must be answered by a plan that starts from something it names.
   2. **The system asked about.** A question that starts in one system and asks about another must be answered from the
      other. For example, "who opened the GitHub pull request that references Linear issue ENG-1?" must be answered from
      GitHub.
   3. **A choice.** A question that names two or more things to choose between must be answered by a plan that compares
      exactly those things, with no hop.
   4. **The kind of answer.** The kinds are a count, an item's key, a person, a date or another value.
      - The asked kind is learned from the training questions as a naive Bayes model over the question's words
        (`AskedKind`).
      - It is used when the lessons are at least 0.9 sure of it.
      - A person's name read as a label counts as a person (`kind9`).
5. **The glossary of v8**, unchanged (`docs/benchmarks/factbank_llm/glossary.json`).

The plan weights are learned again with all of this in place (`plan_lessons_v9.json`).

### v10: v9, helped by a small model's form where the bank's own lessons are unsure

**What the model does:**
- Llama 3.2 3B runs locally (4-bit, CPU, the same model as v7). It does not rewrite the question.
- It fills in a two-line form: what kind of thing the answer is (a person, date, number, ticket key or status), and which
  property it is read from (assignee, due date, status, author, creator, owner or none).
- Its prompt has seven examples. Each is the first training wording of a kind, with made-up keys and names
  (`FORM_SYSTEM` in `cie/src/cie/factbank/reader.py`).
- It never sees a document.

**How the bank uses the form:**
- The form's kind is used only when the bank's learned kind is not sure.
- The form's field is used only when the form's kind is the one being used (check 5):
  - a plan answering with one value must read that field;
  - a plan choosing an item by date must order by it.
- The bank picks among the plans left with v9's weights, carries the plan out and records what it read.
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
optimistic and decide nothing.

**The steps, in order** (mean of the five held-out sets; own answers, three-group mean):

| step | right answers |
|---|---|
| v4 (as published) | 0.635 |
| v8, the glossary (as published) | 0.703 |
| + every kind in training (201 questions) | 0.649 |
| + only plans right for the right reason (first, looser check) | 0.663 |
| + the glossary | 0.740 |
| + the planner rules, the choice check and the learned kind check | 0.879 |
| + plans also start from quoted titles (dropped: it hurt) | 0.865 |
| + check 1, what the question is about | 0.894 |
| + v10's form, replacing the learned kind | 0.898 |
| + v10's form used only where the lessons are unsure | 0.929 |
| + the review's fixes (below): v9 | **0.956** |
| + the review's fixes: v10 | **0.971** |

**Where things stand, as frozen**, with the final measure:

| arm | right answers, five held-out sets | right for the right reason | right answers, language-model test set |
|---|---|---|---|
| v4 | 0.635 | 0.392 | 0.586 |
| v8 | 0.703 | 0.532 | 0.601 |
| v9n | 0.922 | 0.913 | 0.983 |
| **v9** | **0.956** | **0.943** | **0.983** |
| **v10** | **0.971** | **0.954** | **0.983** |

**The form's prompt** was settled on a 30-question sample of the held-out sets:
- **Without examples:** the kind of answer was right for 23 of 30.
- **With the seven training-wording examples:** 30 of 30.

That was the only prompt change.

## A review before freezing

Three independent reviewers checked the uncommitted code, the evaluation and the protocol. A fourth tried to refute
each finding. What held up was fixed before anything was frozen. Each fix is in the development table above.

1. **The check that a plan read the right facts was too loose.** A key only passed through on the way counted, so some
   coincidences counted as right for the right reason, in training and in the measure. It now checks each piece in its
   role (item 2 above).
2. **A "who" answer read as a person's label counted as an item's key** when the asked kind was learned. It now counts as
   a person (`kind9`). The v4 to v8 features keep the old kind.
3. **The system rule was not enforced.** A plan ending outside the asked system kept no filter and could still win. It
   is now check 2.
4. **The choice check bound only plans answering with an item.** It now binds every plan.
5. **The 201 training questions used different "which is due first" pairs from the 48.** The random draws went out of
   step. They now contain the 48.
6. **The measure gave a partly right list partial credit for the right reason.** It is now all or nothing, as in
   development.
7. **v10's model time and the learned kind were not recorded** with each answer. They are now.
8. **One test compared the new code with itself.** It now pins the questions the earlier code gave.
9. **The memory-test set (`mt50`) was missing from the exclusions.** Two of its Linear documents could have been drawn.
   It is now excluded.

## The test set (frozen)

**Documents:**
- A new sample of the whole benchmark: `fresh --seed 37`, stratified by source; questions seed 38.
- **Excluded:**
  - every document of every earlier set: `mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`, `mdwords`,
    `mdblind` and `mdllm` (their changed copies share their documents);
  - the company lexicon's whole 200,000-document sample (`lexsample`).
- The changed-information copy is made by the fixed transform (`factbank_split changed`).

**Wordings:**
- Three new independent agent sessions wrote them, in roles not used before:
  - a finance analyst writing formal sentences;
  - a senior engineer in code review, writing tersely;
  - a marketing coordinator using plain everyday words.
- Each saw only what each question must ask, and saved its wordings to a file itself.
- I have not read those files.
- The same selection rule as before applies: writers 1 and 2 give the pair, and writer 3 stands in for an invalid
  wording.
- A script applied the rule. It printed only how many wordings were replaced (none) and how many each kind has (two).

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
- An answer counts (as 1) only if it is wholly right **and** its plan read every fact it rests on, each in its role
  (`rests_on`).
- This uses what the plan read, recorded with each answer (`Planner.reads`).
- It is measured the same way for every arm.

**Its limits:**
- A value can still match by coincidence when it is read from the right field of the right thing.
- v9 and v10 were trained on this criterion; v4 and v8 were not. So it says how often an arm is right by coincidence, and
  rule 3 counts only alongside rule 1.

## Rules

1. **The fixed planner helps:** v9 − v4 ≥ +0.10, test set.
2. **It helps beyond the glossary:** v9 − v8 ≥ +0.05, test set.
3. **Right for the right reason**, test set, counting only answers right for the right reason. Both must hold:
   - v9 − v4 ≥ +0.10;
   - v9 ≥ v9's own right answers − 0.05.
4. **A small model's form adds:** v10 − v9 ≥ +0.05, test set.
5. **Principles, not memorisation:** v9 and v10 each on the test set ≥ the same arm on the 201 training questions it
   learned from − 0.15.
6. **It holds when the information changes:** v9 and v10 each on the changed copy ≥ the same arm on the test set − 0.05.
7. **No harm on what was learned:** v9 and v10 each ≥ v4 − 0.03 on the 48 first training questions.

**How to read differences:**
- One compare question moves the mean by 0.042; one link or combine question by about 0.015–0.02.
- So differences of 0.04 or less are within noise.
- On the earlier sets v9 and v10 are close to the ceiling. So rule 4 can only be met if the new wordings leave v9 more
  room.

**Also reported:**
- v9n on the test set;
- every arm by kind of question;
- v10's model time per question, and how often its form's kind differs from the learned one;
- every arm on the earlier sets, for information only.

## Frozen

| what | sha256 / value |
|---|---|
| code | the commit that adds this document |
| `plan_lessons_v9.json` (201 questions, glossary) | `00e63e5fbca8cee8…` |
| `plan_lessons_v9n.json` (201 questions, no glossary) | `1b68d133783a7958…` |
| `plan_lessons_v4.json`, `plan_lessons_v8.json` (as before) | `747150754ce6ad27…`, `ad54971605f3864b…` |
| the 201 training questions | `21a50695ed68e0c7…` |
| glossary | `0dd7d0bc2a7788d5…` |
| v10's form prompt (`form_fingerprint`) | `bf3f84a670bd43be` |
| model | `llama3.2:3b`, Q4_K_M, manifest sha256 `a80c4f17acd55265…`; temperature 0, seed 0, at most 60 tokens |
| kind-of-answer floor | 0.9 |
