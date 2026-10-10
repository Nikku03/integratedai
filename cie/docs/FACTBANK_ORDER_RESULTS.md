# All of them when the question asks for several: results

**Run on 2026-10-10**, by the rules in `docs/FACTBANK_ORDER_PREREGISTRATION.md`. The design was frozen at commit
`e7b7530` (00:32 UTC); the test set was drawn after it, at 00:35.
- **Raw results, wordings, forms and reviews:** `docs/benchmarks/factbank_order/`.

## In short

**The check works: all seven pre-registered rules were met.**
- **On the 8 action-item questions,** v13 scored 1.000 against v11's 0.667. That is +0.333, more than twice the +0.15
  required.
- **On the other 42 questions** nothing changed: both score 1.000.
- **On the whole test set,** v13 scored 1.000 against v11's 0.958.
- **The same in each writer's wording alone:** v13 scored 1.000, and v11 0.958, for writers 1, 2 and 3.

**What the result rests on, read plainly:**
- **A small sample.** The gain comes from 6 questions about 5 people.
  - Two owners appear twice each, with the same answer both times.
  - One of them, Priya Shah, was already answered right by v11 both times.
- **Easy wordings for the check.** All three writers asked for several by saying "keys". Every question asking for the
  first one due used "which one" with "first", "soonest" or "sooner".
  - So the check's guards were barely tested here.
  - All three designs built during development would have given the same answers on this test.
- **The main evidence of no harm is still the reviewers' rewordings,** made before the freeze. On 1,072 questions asking
  for an order, none changed.

## Decision

| Rule | Result |
|---|---|
| 1. All of them when several are asked for (v13 − v11 ≥ +0.15, action items) | **Met:** 1.000 against 0.667 (+0.333) |
| 2. No harm on the other questions (v13 ≥ v11 − 0.03, and no question asking for an order worse) | **Met:** 1.000 against 1.000; none worse |
| 3. The same with the small model's form (v14 − v12 ≥ +0.15) | **Met:** +0.333, the same 6 questions as rule 1 |
| 4. No harm on the earlier sets (guard, known) | **Met:** v13 0.969 against v11 0.960; v14 0.982 against v12 0.974 |
| 5. Principles, not memorisation | **Met:** 1.000 against 1.000 |
| 6. It holds when the information changes | **Met:** the changed copy scores the same, 1.000 |
| 7. No harm on what was learned (known) | **Met:** 1.000 against v4's 0.927 |

**Rules 1 and 3 could be judged:** v11 scored 0.667 on the action items, below the 0.85 limit.

## Results

Own answers, three-group mean:

| | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|
| v4 | 0.619 | 0.571 | 0.750 | 0.647 | 0.589 |
| v8 | 0.810 | 0.667 | 0.750 | 0.742 | 0.669 |
| v9 | 1.000 | 0.754 | 1.000 | 0.918 | 0.873 |
| v11 | 1.000 | 0.873 | 1.000 | 0.958 | 0.905 |
| v12 | 1.000 | 0.873 | 1.000 | 0.958 | 0.905 |
| **v13** | 1.000 | **1.000** | 1.000 | **1.000** | **1.000** |
| **v14** | 1.000 | **1.000** | 1.000 | **1.000** | **1.000** |

**By kind,** every version from v9 on scores 1.000 on every kind except the action items:

| action items (8) | v4 | v8 | v9 | v11 | v12 | v13 | v14 |
|---|---|---|---|---|---|---|---|
| own answers | 0.375 | 0.125 | 0.354 | 0.667 | 0.667 | **1.000** | **1.000** |

### The action items, question by question

v13 differs from v11 on 6 of the 50 answers, all action items. In each, v11 answered with the owner's first ticket due,
and v13 with all of them.

| question | owner | wording drawn | v11 | v13 |
|---|---|---|---|---|
| `action_owner_issues-014` | Samir Patel | writer 1 | 0.5 | **1.0** |
| `action_owner_issues-015` | Ava Martinez | writer 1 | 0.667 | **1.0** |
| `action_owner_issues-029` | Jordan Lee | writer 2 | 0.5 | **1.0** |
| `action_owner_issues-030` | Samir Patel | writer 1 | 0.5 | **1.0** |
| `action_owner_issues-037` | Avery Chen | writer 1 | 0.5 | **1.0** |
| `action_owner_issues-043` | Sofia Patel | writer 1 | 0.667 | **1.0** |
| `-023` and `-036` | Priya Shah | | 1.0 | 1.0 |

- **Priya Shah's two tickets are due the same day,** so there is no single "first one due". v11 already listed both, and
  the check had nothing to change.
- **Samir Patel's two questions** have the same answer. Counting each owner once, the gain is +0.361.
- **v11 makes the same mistake in every writer's wording,** on the same 6 questions. So the room for the check came from the
  documents (owners with several tickets due on different days), not from the wording draw.
- **The diagnosis holds on new documents.** For the 5 people asked about in both ways, v11's answer to "which tickets do
  they have?" is exactly the right answer to "which is due first?". v13 answers both kinds right.

**What made the check act:** the writers' wordings were
- writer 1 (a project manager): "Which ticket keys are assigned to that person?"
- writer 2 (a support engineer on call): "what ticket keys are assigned to them?"
- writer 3 (a VP on a phone): "what tickets do they own? Send me the keys."

All three say "keys". For writers 1 and 2 it is the only signal the check reads. The other signals ("list", "all", "which
tickets") were not tested here.

### The questions that ask for an order

No answer changed on the 14 questions that ask for an order (8 "which of two is due first", 6 "a person's first issue due").

**How hard that test was:**
- **Out of reach on 11 of the 14:** they do not ask for several things, so the check could not act on them whatever its
  guards did.
- **Guarded on the other 3:** they use writer 1's "Of all the tickets assigned to P, which one is due first? Please give me
  its ticket key." "All" reads as asking for several, but "which one" and "first" both keep the check off.
- **If both guards were removed,** those 3 would go from right to wrong. Removing either guard alone changes nothing.

So the test confirms that the guards work together on one wording, not that each protects on its own. The evidence for that
is the reviewers' rewordings before the freeze:
- 1,072 questions that ask for an order: none changed;
- 249 of them kept the check off through the word of order alone.

### The same questions in each writer's wording (information only)

| wording | v11, action items | v13, action items | v11, whole set | v13, whole set |
|---|---|---|---|---|
| writer 1 only (project manager) | 0.667 | **1.000** | 0.958 | **1.000** |
| writer 2 only (support engineer) | 0.667 | **1.000** | 0.958 | **1.000** |
| writer 3 only (VP on a phone) | 0.667 | **1.000** | 0.958 | **1.000** |

These re-ask the same 50 questions about the same documents in other words. They show the result does not depend on
which writer was drawn. They are not new evidence from other people or facts.

### v14 and the small model

v14 gives the same answers as v13, and v12 the same as v11, on every question in every folder.
- **Form use:** the form was used for the kind of answer on none of the 50 drawn questions, and on 5 in writer 3's
  wording, with no change in answers.
- **Model time:** 1.9 seconds per question (median).
- **What it means:** rule 3 repeats rule 1, as the pre-registration said it would.

## What the review found

Two reviewers checked the numbers and protocol, and the interpretation. A third tried to refute each finding
(`docs/benchmarks/factbank_order/review.json`).

**The protocol was followed:**
- The test set was drawn once, after the freeze. Its documents share none with any earlier set or the lexicon sample.
- The code, lessons, wordings, prompt and model are the frozen ones.
- Every answer and every rule reproduces from the raw files.
- v14's forms were made by the model during the run.

**The selection rule replaced one wording:** writer 2's "linked ticket's assignee" used `{k}` twice and was replaced by
writer 3's.

**Limits of what the test shows:**
- **Few independent checks:** 6 changed answers, from 5 people.
- **One trigger tested:** every action item was caught through "keys".
- **Guards under little pressure:** only 3 of the 14 ordering questions asked for several at all.
- **Familiar wordings:** the new writers' wordings were close to wordings seen in development. One compare wording was word
  for word an earlier writer's. Part of this comes from the brief, which earlier writers also had.
  - So the test confirms the check on close relatives of the development wordings. It does not show that the word lists
    generalise to unfamiliar phrasing.
- **The reviewers' rewordings covered every form the writers used, and harder ones.** They remain the main evidence of no
  harm.
- **None of the known limits came up:**
  - no word of order in passing;
  - no "ID's";
  - no curly quotes;
  - no way of asking for several that the check misses.

  They are still untested on independent wordings.

**A small correction:** the report's "median" model time is the 26th of 50 values (1.89 s). The true median is 1.88 s.

## What this shows

- **The mistake from the ticket test is fixed where it appears.** "Which ticket keys are assigned to them?" now gets all of
  the owner's tickets, not the first one due. That held on new documents, in three new writers' wordings, and on the
  changed copy.
- **It did no harm anywhere it was measured:**
  - no other answer changed on the test set;
  - no question that asks for an order changed in the reviewers' 1,072 rewordings;
  - no earlier set got worse.
- **The evidence is narrower than the scores suggest.** 1.000 on 50 questions rests on 6 changed answers. The new writers
  happened to phrase things in the ways the check already handled.

**Next** (each needs its own pre-registered test):
- test with writers who are not given the word "ticket", to see other ways of asking for several;
- the remaining known limit: when the "first one due" plan is dropped, an unrelated plan can win ("Send me the ID's");
- match system names as whole words, so "Driver" is not read as Google Drive;
- test "or Jira" on a set that has Jira tickets.

## Reproduce

`plan_lessons_v13.json` is `plan_lessons_v11.json` with `"orders": true` added; the weights are v11's.

```bash
bash docs/benchmarks/factbank_order/run_order.sh   # draws the test set, answers with every arm, scores the rules
```
