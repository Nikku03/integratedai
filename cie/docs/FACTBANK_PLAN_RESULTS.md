# Fixing the planning step: results

**Run on 2026-10-09**, by the rules in `docs/FACTBANK_PLAN_PREREGISTRATION.md`. The design was frozen at commit `7017046`,
before the test set was drawn or its blind wordings were read.
- **Raw results, the model's forms, the writers' wordings, the development summary and the review:**
  `docs/benchmarks/factbank_plan/`.
- **Code:**
  - `cie/src/cie/factbank/plans.py` (`Planner(rules="v9")`, `check`, `reads`, `rests_on`, `AskedKind`);
  - `cie/src/cie/factbank/reader.py` (`Former`, v10's form);
  - `cie/src/cie/eval/factbank_multi.py` (`build_training_all`, `plan_test`).

## In short

**Fixing the planning step worked.** On 50 new questions over 50 new documents:

| arm | right answers |
|---|---|
| v4, the plan learner before | 0.510 |
| v8, the glossary, the best so far | 0.722 |
| **v9, the planner fixed (no model when a question is asked)** | **0.975** |

**Its right answers are right for the right reason.**
- Counting only answers whose plan read the facts they rest on, v9 scores 0.968 and v4 scores 0.385.
- On the "which is due first" questions, v9 compares the two due dates every time.

**Six of the seven pre-registered rules are met.**
- The one not met is that the small model's form adds 0.05 (v10 = v9 = 0.975).
- On this test the bank's own lessons were sure what kind of answer was asked for in 49 of 50 questions. The model filled
  in a form for all 50 (2.3 s each on average), but the bank used it on only one question.

**But 0.975 is partly the luck of the wording draw.** The review found this, and I checked it after the run:
- Each question was asked in one of two blind wordings, drawn at random. The draw happened to favour v9.
- Asked the same 50 questions in a single writer's wording, v9 scores 0.922 (the formal writer), 0.975 (the terse
  writer) and 0.872 (the plain-words writer, the stand-in).
- In every wording v9 stays far ahead of v4 and v8.
- On the less familiar wordings, v10's form adds about 0.05 (0.975 and 0.924).
- A fair expectation for new wordings is about 0.92 for v9 and 0.96 for v10, not 0.975.

**What this means:** the plan picker was the bottleneck, and fixing it fixed most of the multi-document questions. The
small model helps where the wording is unusual, so it is worth keeping for that, but it is no longer the main lever.

## Decision

| Rule | Result |
|---|---|
| 1. The fixed planner helps (v9 − v4 ≥ +0.10) | **Met:** 0.975 against 0.510 (+0.465) |
| 2. It helps beyond the glossary (v9 − v8 ≥ +0.05) | **Met:** 0.975 against 0.722 (+0.253) |
| 3. Right for the right reason (v9 − v4 ≥ +0.10, and v9 ≥ its own right answers − 0.05) | **Met:** 0.968 against 0.385; 0.968 against 0.975 |
| 4. A small model's form adds (v10 − v9 ≥ +0.05) | **Not met:** 0.975 against 0.975 (0.000). With v9 at 0.975 the most v10 could add was 0.025, and with one unsure question about 0.018: the ceiling the pre-registration warned of |
| 5. Principles, not memorisation (test ≥ training − 0.15) | **Met:** v9 0.975 and v10 0.975 against 0.993 each |
| 6. It holds when the information changes (changed ≥ test − 0.05) | **Met:** v9 and v10 0.975 against 0.975 |
| 7. No harm on what was learned (≥ v4 − 0.03 on the first 48 training questions) | **Met:** v9 0.993 and v10 0.993 against 0.927 |

## Results

Own answers, no model judging (the mean is the mean of the three groups):

| | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|
| test set, v1 (untrained) | 0.105 | 0.000 | 0.000 | 0.035 | – |
| test set, v4 | 0.263 | 0.391 | 0.875 | 0.510 | 0.385 |
| test set, v8 (glossary) | 0.421 | 0.870 | 0.875 | 0.722 | 0.639 |
| test set, **v9** | 0.947 | 0.978 | 1.000 | **0.975** | **0.968** |
| test set, v9n (v9 without the glossary) | 0.947 | 0.978 | 1.000 | 0.975 | 0.968 |
| test set, **v10** (v9 + the 3B model's form) | 0.947 | 0.978 | 1.000 | **0.975** | 0.968 |
| changed copy, v4 / v8 / v9 / v10 | | | | 0.510 / 0.722 / 0.975 / 0.975 | |
| first 48 training questions, v4 / v9 / v10 | | | | 0.927 / 0.993 / 0.993 | 0.743 / 0.986 / 0.986 |
| 201 training questions, v4 / v9 / v10 | | | | 0.822 / 0.993 / 0.993 | 0.638 / 0.986 / 0.986 |

**By kind of question** (test set, share right):

| kind | n | v4 | v8 | v9 | v10 |
|---|---|---|---|---|---|
| pull request → Linear issue (assignee, due date, status) | 7 | 0.29 | 0.57 | **1.00** | **1.00** |
| Linear issue → pull request author | 5 | 0.00 | 0.20 | **1.00** | **1.00** |
| ticket → linked ticket | 7 | 0.43 | 0.43 | 0.86 | 0.86 |
| a person's issue count | 8 | 0.50 | 1.00 | 1.00 | 1.00 |
| a person's first issue due | 7 | 0.29 | 1.00 | 1.00 | 1.00 |
| an action item's owner → their issues | 8 | 0.38 | 0.63 | 0.94 | 0.94 |
| which of two is due first | 8 | 0.88 | 0.88 | 1.00 | 1.00 |

**The two misses** (both fail in every wording tried):
- **An action item** (`action_owner_issues-021`). It asked for the list of the owner's tickets. The quoted action item
  itself contains the word "date", and v9 orders the owner's issues by due date instead of listing them. It returns 1 of
  the 3 keys, which scores 0.5 on the list.
- **A linked ticket's status** (`ticket_link-status-039`: "Ticket ENG-4823 is linked to another ticket. Could you please
  tell me where that other ticket currently stands?"). It fails for two separate reasons:
  - **The wording.** This was the one question where the bank's lessons were unsure of the kind of answer (person 0.53,
    other 0.47), and v9 answered with a ticket key. v10 asked the model, which correctly said "status".
  - **The link.** The other ticket is reached through `parent_issue`, a relation v9 never chose on its training questions,
    which used `dependencies` 48 times and `linked_issues` 18. So v10 read the status of the wrong ticket.

**The changed copy:**
- The fixed transform renames every person and moves every date 23 days later. Keys, statuses, links and counts stay the
  same, and so does the order of any two dates.
- So 15 questions change (a renamed person), and 13 expected answers change: 10 names and 3 due dates.
- v9 and v10 give the new value on all 13.
- Every arm scores exactly as on the original. That is expected: the plans read names and dates, they do not remember
  them.
- It shows nothing about new wordings, or about changed statuses, links or counts.

### v10: the model's form

| | test set |
|---|---|
| questions where the bank's own lessons were unsure of the kind of answer, so the form was used | 1 of 50 |
| questions where the form's kind differs from the lessons' (when they were sure) | 0 |
| answers that differ from v9 | 1 (the linked-ticket status above; both wrong) |
| the model's time per question (it fills in a form for every question, before the bank checks how sure it is) | mean 2.3 s, median 1.9 s, at most 21 s (4 CPU cores, no GPU) |
| the bank's time per question | median 0.18 s |

### The same questions in other blind wordings (after the run; information only)

This was not part of the decision. The review raised it, and I ran it after the test: the same 50 questions and answers,
asked in one writer's wording only.

| wording | v4 | v8 | v9 | v9n | v10 | form used (lessons unsure) |
|---|---|---|---|---|---|---|
| as drawn (the test) | 0.510 | 0.722 | 0.975 | 0.975 | 0.975 | 1 |
| writer 1 only (a finance analyst, formal) | 0.527 | 0.652 | 0.922 | 0.887 | **0.975** | 9 |
| writer 2 only (a senior engineer, terse) | 0.481 | 0.742 | 0.975 | 0.975 | 0.975 | 0 |
| writer 3 only (a marketing coordinator, plain words; the stand-in) | 0.547 | 0.638 | 0.872 | 0.843 | **0.924** | 3 |

**Where the drop comes from:**
- The test used 17 of the 20 pair wordings. The three it never used cost v9 nothing.
- v9's drop with writer 1 alone (0.975 to 0.922) comes from one wording: writer 1's linked-ticket status ("where that
  other ticket currently stands"). There the lessons are unsure of the kind of answer, and v9 answers with an assignee
  on three more tickets.
- Asked in the training wordings, v9 also scores 0.975, missing the same two questions. In the wordings of the earlier
  sets it scores 0.922–0.940.
- The 50 questions are fewer than 50 independent checks: ENG-4821 underlies 5 of them, and two pairs of action-item
  questions share their expected keys.

**What fails in plain words:**
- **"When is the ticket supposed to be done by?"** v9's lessons do not know this asks for a date, and it reads the status.
  The model's form says "date", and v10 gets all three right.
- **"Whoever got the X to-do in the Y meeting, can you list the ticket IDs?"** This never says "Linear". The bank reads
  "meeting" as the system asked about and answers from the meeting notes. It gets 4 of the 8 wrong, and so does v10.
  - The bank does not know that "ticket" means Linear or Jira.
  - No training or earlier question tested this.

### The earlier sets (seen in development; information only)

| set | v4 | v8 | v9n | v9 | v10 |
|---|---|---|---|---|---|
| first held-out | 0.653 | 0.549 | 0.882 | 0.980 | 0.980 |
| retest | 0.596 | 0.800 | 0.968 | 0.984 | 0.968 |
| new words | 0.611 | 0.669 | 0.802 | 0.877 | **0.947** |
| general-English blind | 0.727 | 0.898 | 0.977 | 0.958 | 0.977 |
| language-model test | 0.586 | 0.601 | 0.983 | 0.983 | 0.983 |
| **mean of the five** | 0.635 | 0.703 | 0.922 | 0.956 | **0.971** |

These are optimistic: their failures guided the design. Development step by step is in
`docs/benchmarks/factbank_plan/development.json` and in the pre-registration.

## What the review found

**Before the test:** an independent review found nine problems in the uncommitted code and protocol. All were fixed
before freezing; see the pre-registration.

**After the test:** three reviewers checked:
- the numbers;
- how hard the test was;
- the protocol.

A fourth reviewer tried to refute each finding (`review.json`).

1. **Every number and rule verdict reproduces, and the inputs match the freeze.**
   - The test set was drawn after the freeze commit and shares no document with any excluded set.
   - The frozen lessons, prompt and wordings are the ones used.
2. **The headline depends on the wording draw** (above). The rule verdicts do not: in every wording, v9 − v4 ≥ 0.31 and
   v9 − v8 ≥ 0.20.
3. **Rule 4 says little.**
   - With 49 of 50 questions sure, the form had no room to add on this draw.
   - On the other wordings it adds +0.053 and +0.052.
   - So "not met" means "this test could not show it", not "the form does not help".
4. **v9 = v9n = v10 is a product of the draw**, not of a fault. On the other wordings the glossary adds +0.035 and +0.029.
   So "no language model is needed" does not follow from this test.
5. **The test's words were not very new.**
   - Per question, about a third of the content words (0.33) were absent from the training wordings. That is level with
     the first held-out set and the retest (0.32), and below the new-words, blind and language-model sets (0.41–0.48).
   - Of the 60 content-word types in the 20 test wordings, only 6 had not appeared in the training or any development
     wording: confirm, gimme, provide, refs, respond, titled.
   - That is not a leak: v9 learns words only from training, and v9n, with no glossary, scored the same. But it makes this
     test a weaker test of unfamiliar wording than the new-words set.
6. **v4's low score (0.510) means these 50 questions are hard for v4, not that the test is hard.**
   - It does not come from the mix of kinds: v4's rates on the earlier sets predict 0.623 for this mix.
   - It comes from these particular questions. v4 gets 0 of 5 pull-request authors and 0 of 3 linked-ticket assignees
     in every wording.
   - Asked in an earlier set's wording, v4 scores 0.10–0.20 lower on these questions than on that set, while v9 does not
     drop the same way.
   - So v4's low score should not be read as a sign that the test was hard.
7. **The right answers read the right things.**
   - Every v9 answer counted right reads the right entity.
   - The linked-ticket answers rely on the 50-document bank. All six right ones follow `dependencies` to 2–4 tickets, of
     which only the gold one is a document in this bank; the others are bare keys with no fields, so "one value" returns
     the gold value.
   - In the full benchmark many of those keys have several documents (ENG-4821 has 52). There the same plan would
     usually find different values and give no answer.
8. **Smaller points:**
   - The three-group mean gives the 8 compare questions a third of the weight, and compare is v4's best group. Per
     question, v4 scores 0.42 (21 of 50 fully right), v8 0.70 (35) and v9 and v10 0.97 (48). So v9 − v4 is +0.55 per
     question against +0.465. Every rule verdict is the same either way.
   - The frozen `plan_lessons_v9.json` names its glossary by an absolute scratch path. That file is byte-identical
     (sha256 `0dd7d0bc…`) to `docs/benchmarks/factbank_llm/glossary.json`. Loading the lessons from the repository alone
     needs the path changed.
   - The pre-registration's development table puts 0.929 against "v10's form used only where the lessons are unsure".
     That step scored 0.926 (`development.json`, run G). The 0.929 is the same design after the training set was
     rebuilt to contain the first 48 (run H).

## What this shows

- **The plan picker was the bottleneck, and it is fixed** for the kinds of question the bank was taught. That took
  three things:
  - teaching every kind;
  - learning only from plans right for the right reason;
  - checking each plan against what the question names and asks for.
- **No language model is needed for this when the wording is ordinary.** v9n, with no model anywhere, matches v9 on the
  test.
- **A small model helps where the wording is unusual.** "Supposed to be done by" and "what lands soonest" are examples.
  Used only where the bank is unsure:
  - it never scored below v9 on the test or its other wordings;
  - it added about 0.05 on the less familiar ones;
  - on one earlier set it lost a question (the retest: 0.984 against 0.968).

**What is not solved:**
- **"Ticket" without a system name.** In plain words, "ticket" with no system named sends action-item questions to the
  meeting notes.
- **Picking out "the other ticket"** in a bank where a ticket links to several.
- **Kinds of question never taught.** The bank answers only the seven kinds it was taught.

**Next** (each needs its own pre-registered test):
- teach the bank that "ticket" means a Linear or Jira item when no system is named;
- test on a larger bank (500 documents or more), so links reach several things;
- test new kinds of question, to see whether the planner's principles carry over to questions it was never taught.

## Reproduce

```bash
python -m cie.eval.factbank_multi trainall --work $TRAIN --out $TRAIN9          # the 201 training questions
python -m cie.eval.factbank_multi train --work $TRAIN9 --single lessons.json --plans plan_lessons_v9.json --rules v9 --proper --glossary glossary.json
python -m cie.eval.factbank_multi train --work $TRAIN9 --single lessons.json --plans plan_lessons_v9n.json --rules v9 --proper
bash docs/benchmarks/factbank_plan/run_test.sh   # draws the test set, answers with every arm, scores the rules
# v10 needs Ollama serving llama3.2:3b for new forms; the forms in docs/benchmarks/factbank_plan/forms/ replay without it
```
