# Fixing the planning step: the same test on another 50 documents

**Section 1 was written on 2026-10-09, before the new documents were drawn.** The results are added below it after the
run, in a separate commit.

## 1. What decides (fixed before the run)

### Why

The planner test (`docs/FACTBANK_PLAN_RESULTS.md`) scored:
- v9: 0.975
- v4: 0.510
- v8: 0.722

Its review warned that the 0.975 was partly a lucky draw of wordings. This run asks whether the same results come out on
50 different documents.

### Nothing changes but the documents

**The system, unchanged since the freeze:**
- The same code. `cie/src` has not changed since commit `7017046`.
- The same lessons: `plan_lessons_v9.json` (`00e63e5fbca8cee8…`), `plan_lessons_v9n.json` (`1b68d133783a7958…`), and
  v4's and v8's as before.
- The same glossary, v10 prompt (`bf3f84a670bd43be`) and model (`llama3.2:3b`, manifest `a80c4f17acd55265…`).

**The questions:**
- The same blind wordings: `docs/benchmarks/factbank_plan/wordings.json`, the pairs from writers 1 and 2.
- Each question's wording is drawn from its pair at random, as before.
- The same seven rules, applied to the new set.

**The documents:**
- A new sample of the whole benchmark: `fresh --seed 41`, questions seed 42.
- **Excluded:** every document of every earlier set, now including the first planner test's (`mdplan`). The full list is
  `mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`, `mdwords`, `mdblind`, `mdllm`, `mdplan` and the
  lexicon's 200,000-document sample (`lexsample`).
- The changed-information copy is made by the same fixed transform.

**The script:** `docs/benchmarks/factbank_plan/run_replication.sh`. It is the frozen run script with the seed, the output
folder and the exclusion list changed, plus the single-writer runs below.

### What counts as "the same results"

1. **The same verdicts:** rules 1, 2, 3, 5, 6 and 7 are all met again on the new set. Rule 4 (v10 − v9 ≥ +0.05) is
   reported but not required: on the first test it could not be met.
2. **The level holds:** v9 on the drawn wordings scores at least 0.925, within 0.05 of the first test's 0.975.

### Also reported (information only)

- Every arm's score next to its first-test score, by group and by kind.
- **The same questions in a single writer's wording**, as run after the first test:
  - writer 1 only;
  - writer 2 only;
  - writer 3 (the stand-in, plain words) only.
- How often v10's form was used, and the model's time.

**How to read differences:** one link or combine question moves the mean by about 0.015–0.02, and one compare question
by 0.042. So differences of 0.04 or less are within noise.

## 2. Results (added after the run)

**Run on 2026-10-09**, 8 seconds after the pre-registration was committed (`9c268e6`).
- **Raw results, forms and review:** `docs/benchmarks/factbank_plan/replication/`.
- **The new set:** 50 documents, none from any earlier set (205,337 documents excluded). A re-draw reproduces it exactly.

### In short

**It replicates.** On 50 different documents, with nothing else changed:
- v9 scored 0.979 (first test: 0.975);
- the same six rules were met.

v8, v9 and v10 gave the same results within noise:

| arm | first test | replication | difference |
|---|---|---|---|
| v4, the plan learner before | 0.510 | **0.580** | +0.070: beyond noise |
| v8, the glossary | 0.722 | 0.720 | −0.002 |
| **v9, the planner fixed** | **0.975** | **0.979** | +0.004 |
| v9n (v9 without the glossary) | 0.975 | 0.958 | −0.017 |
| **v10, v9 + the 3B model's form** | **0.975** | **1.000** | +0.025 |

The table compares the drawn wordings. **Compared like for like, the picture is the same but less flattering:**
- **The first test's 0.975 was its luckiest draw.** Averaged over every way its wordings could have been drawn, v9 scores
  0.949 there. On the new set the average is 0.979, the same as the drawn score.
- **The new set has fewer of v9's weakest kind of question:** 3 linked-ticket questions against 7. Re-scored at the
  first test's mix of kinds, v9 is 0.959 here.
- So, fairly read, v9 holds at about 0.95–0.98 on new documents with these wordings.

### Decision

| What counts as "the same results" | Result |
|---|---|
| Rules 1, 2, 3, 5, 6 and 7 met again | **Met** |
| v9 on the drawn wordings ≥ 0.925 | **Met:** 0.979 |

| Rule | First test | Replication |
|---|---|---|
| 1. The fixed planner helps (v9 − v4 ≥ +0.10) | Met: +0.465 | **Met:** 0.979 against 0.580 (+0.399) |
| 2. It helps beyond the glossary (v9 − v8 ≥ +0.05) | Met: +0.253 | **Met:** 0.979 against 0.720 (+0.259) |
| 3. Right for the right reason (v9 − v4 ≥ +0.10, and v9 ≥ its own score − 0.05) | Met | **Met:** 0.979 against 0.471; 0.979 against 0.979 |
| 4. A small model's form adds (v10 − v9 ≥ +0.05) | Not met: 0.000 | **Not met:** +0.021 |
| 5. Principles, not memorisation (test ≥ training − 0.15) | Met | **Met:** 0.979 and 1.000 against 0.993 |
| 6. It holds when the information changes | Met | **Met:** changed copy 0.979 and 1.000, the same as the test set |
| 7. No harm on what was learned | Met | **Met:** carried over (see below) |

**Not all six are new evidence.**
- The replication did not re-answer the training questions. Rule 7 and the training side of rule 5 re-score the first
  test's stored answers. With the code, lessons and training questions frozen, they could not differ.
- Rule 6 is a weak check for this planner: its plans read names and dates from the documents.
- The new evidence is rules 1 to 3 and the level check on 50 new documents. All clear their thresholds by far.
- The level check could not have failed through the choice of wordings: over every possible draw of these 50 questions,
  v9 scores 0.958 to 1.000.

### Results

Own answers (three-group mean):

| | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|
| v4 | 0.250 | 0.615 | 0.875 | 0.580 | 0.471 |
| v8 | 0.438 | 0.846 | 0.875 | 0.720 | 0.678 |
| **v9** | 0.938 | 1.000 | 1.000 | **0.979** | **0.979** |
| v9n | 0.875 | 1.000 | 1.000 | 0.958 | 0.958 |
| **v10** | 1.000 | 1.000 | 1.000 | **1.000** | **1.000** |
| changed copy, v4 / v8 / v9 / v10 | | | | 0.567 / 0.720 / 0.979 / 1.000 | |

**By kind** (number right; the counts are small):

| kind | v4 | v8 | v9 | v10 |
|---|---|---|---|---|
| pull request → Linear issue | 3/8 | 4/8 | 8/8 | 8/8 |
| Linear issue → pull request author | 0/5 | 2/5 | 5/5 | 5/5 |
| ticket → linked ticket | 1/3 | 1/3 | 2/3 | 3/3 |
| a person's issue count | 9/9 | 9/9 | 9/9 | 9/9 |
| a person's first issue due | 2/8 | 8/8 | 8/8 | 8/8 |
| an action item's owner → their issues | 5/9 | 5/9 | 9/9 | 9/9 |
| which of two is due first | 7/8 | 7/8 | 8/8 | 8/8 |

**v9's one miss** is `ticket_link-status-038`: "Ticket ENG-4823 is linked to another ticket. Could you please tell me
where that other ticket currently stands?"
- **The same words as the first test's miss.** The text is word for word the first test's `ticket_link-status-039`, on
  a different document. The benchmark reuses ticket keys, so the expected answer differs: "In Progress" here, "In
  Review" there.
- **The same cause.** The bank's lessons are unsure what "where it stands" asks for, and v9 reads the assignee.
- **v10 gets it right.** The model's form says "status". This time the other ticket is reached through `dependencies`;
  in the first test it was `parent_issue`, which v9 never learned.
- **That one question is all of v10's +0.021.**

**The glossary mattered on one question this time:** `pr_issue-status-036` ("What stage is…"). v9n read the assignee and
v9 read the status. The same wording was the glossary's whole gain in the first test's writer-1 run. So v9 = v9n on the
first test was a product of its draw.

**v4 rose from 0.510 to 0.580.**
- This comes from the questions, not the wording. Averaged over every possible draw, v4 scores 0.504 on the first test
  and 0.619 here.
- The rise is in counts (4 of 8, then 9 of 9) and action items (3 of 8, then 5 of 9).
- It supports the first review's point that v4's 0.510 came from those particular questions.

### The same questions in each writer's wording (information only)

| wording | first test v9 | replication v9 | first test v10 | replication v10 |
|---|---|---|---|---|
| as drawn | 0.975 | 0.979 | 0.975 | 1.000 |
| writer 1 only (formal) | 0.922 | 0.958 | 0.975 | 1.000 |
| writer 2 only (terse) | 0.975 | 1.000 | 0.975 | 1.000 |
| writer 3 only (plain words) | 0.872 | 0.878 | 0.924 | 0.962 |

- **Writer 1's rise (0.922 to 0.958) is not v9 doing better.** On both sets v9 misses every question in writer 1's
  "where that other ticket currently stands": 4 of 4, then 2 of 2. The new set has fewer of them. Re-scored at the first
  test's mix of kinds, writer 1 gives 0.930.
- **The plain-words failures recur at similar rates:**
  - **"Supposed to be done by":** v9 reads the status every time, 0 of 7 across both sets; v10 gets 7 of 7.
  - **Action items that never say "Linear":** these are answered from the meeting notes. v9 and v10 get 3 of 9 wrong
    here, and 4 of 8 in the first test.
- **v10 never scored below v9.** That holds across both tests, as drawn, changed and in every writer's wording: 500
  question-runs. All of its gains come from two wordings: writer 1's "currently stands" and writer 3's "supposed to be
  done by".

### What the review found

Two reviewers checked the numbers and protocol, and the interpretation. A third tried to refute each finding
(`replication/review.json`).
- **Everything reproduces, and the protocol was followed.**
  - The fact-bank code, lessons, glossary, wordings, prompt and model are the frozen ones.
  - The single-writer sets hold the same questions and answers.
  - v10's forms were made by the model during the run. Its one different form, on the cold first call, did not change
    the answer.
- **The questions are fewer than 50 independent checks.**
  - **Keys and names recur.** Two ticket keys (ENG-4821, ENG-4823) and one person's name recur from the first test, on
    different documents with different answers.
  - **Some questions are word for word the same.** Three are identical to first-test questions:
    `issue_pr_author-author-031`, `person_first-006` and `ticket_link-status-038`.
  - **They cluster.** 33 questions are linked through shared documents.
  - **This is not a leak.** Documents, not keys, are excluded, the lessons were frozen before either set was drawn, and
    no key or value from the new questions appears in the lessons.
- **The replication reused the wordings.** It shows that the first test's results, and its wording failures, recur on
  new documents. It says nothing new about unfamiliar wording. That still needs new writers.

### What this shows

- **The fixed planner's result is not a fluke of one set of documents.** On new documents it is again far ahead of the
  old planner and the glossary, and its answers again read the right facts.
- **The headline is about 0.95–0.98, not a perfect score.** It depends on the wording and the mix of questions.
- **The small model's form never hurts.** It fixes two known wording gaps, "currently stands" and "supposed to be done
  by", but not the "ticket" that names no system.

**Next**, as before:
- teach the bank that "ticket" means a Linear or Jira item;
- test with new writers and a larger bank;
- test kinds of question it was never taught.
