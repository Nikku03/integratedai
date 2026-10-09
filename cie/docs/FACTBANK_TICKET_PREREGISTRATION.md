# A ticket means Linear or Jira: what decides, fixed before the test

> **Draft, under review:** the design is frozen only by the commit that removes this line.

I wrote this on 2026-10-09:
- **after** building the rule and trying it on every earlier set, all of which I had seen;
- **before** drawing the test set's documents;
- **before** reading its wordings.

Three new writers wrote those wordings and saved them to files that I have not opened. The results go in
`docs/FACTBANK_TICKET_RESULTS.md`.

## Why

The planner test and its replication found one failure that no fix had touched (`docs/FACTBANK_PLAN_RESULTS.md`,
`docs/FACTBANK_PLAN_REPLICATION.md`).
- **The question:** "Whoever got the X to-do in the Y meeting, can you list the ticket IDs assigned to them?"
- **What goes wrong:** it names no tracker. The bank reads "meeting" as the system asked about and answers from the
  meeting notes.
- **How often:** v9 got 4 of 8 such questions wrong on the first test and 3 of 9 on the replication.

## What changes

### v11: v9, plus "a ticket is a Linear or Jira item"

- **The rule** (`TICKET_WORD`, `TICKET_SYSTEMS`, `Planner.systems_named`, `in_system`, `own_systems` in
  `cie/src/cie/factbank/plans.py`):
  - The words "ticket", "tickets", "issue" and "issues" name a system of their own, "ticket".
  - A Linear or Jira item belongs to it.
  - It comes after any system the question names by name, so "the Linear ticket" still asks about Linear.
- **How the checks use it:**
  - A question that starts in a meeting and says "tickets" asks about the ticket trackers. The system check (check 2)
    then keeps only plans whose answer comes from Linear or Jira.
  - A question that starts from a Linear or Jira item is already in "ticket".
- **The switch:** it is on only when the lessons say so (`PlanLessons.tickets`). Every earlier version, v9 and v10
  included, is unchanged.
- **The weights** are learned again on the same 201 training questions, in the same way as v9 (`--tickets`):
  `plan_lessons_v11.json`.

### v12: v10 with the same rule

It is v11's lessons plus the 3B model's form, used only where the bank's lessons are unsure. The prompt and model are
unchanged.

### The others, as before

v4, v8, v9 and v10 are frozen and unchanged.

## Development (all on sets I had seen)

Three-group mean of own answers:

| set | v9 | v11 | v10 | v12 |
|---|---|---|---|---|
| first 48 training questions | 0.993 | 1.000 | 0.993 | 1.000 |
| 201 training questions | 0.993 | 1.000 | 0.993 | 1.000 |
| first held-out | 0.980 | 0.980 | 0.980 | 0.980 |
| retest | 0.984 | **0.968** | 0.968 | 0.968 |
| new words | 0.877 | 0.877 | 0.947 | 0.965 |
| general-English blind | 0.958 | 0.963 | 0.977 | 0.981 |
| language-model test | 0.983 | 0.983 | 0.983 | 0.983 |
| planner test | 0.975 | 0.975 | 0.975 | 0.975 |
| replication | 0.979 | 0.979 | 1.000 | 1.000 |
| **planner test, plain-words writer** | 0.872 | **0.923** | 0.924 | **0.975** |
| **replication, plain-words writer** | 0.878 | **0.917** | 0.962 | **1.000** |

**What changed, question by question:**
- **The plain-words action items.** v11 now answers from the owner's tickets on all 7 that v9 answered from the
  meeting notes. One of them still scores 0.5: its action item contains the word "date", so it is ordered by date
  instead of listed.
- **A side effect of the new weights.** Four "list the owner's issues" questions in training and on the blind set,
  which v9 answered with only the first one due, are now listed.
- **One loss.** On the retest, "ENG-421987 is connected to another ticket. Whose name is on that one?" is now answered
  with a ticket key instead of a person.

**A check made before the test:** "tickets" could rightly include Jira tickets, while the test's expected answers count
only Linear issues. In every earlier set, none of the people asked about has a Jira ticket assigned, so the two agree.
This will be checked again on the test set and reported.

## The test set (frozen)

**Documents:**
- A new sample: `fresh --seed 43`, questions seed 44.
- **Excluded:** every earlier set's documents (`mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`,
  `mdwords`, `mdblind`, `mdllm`, `mdplan`, `mdrep`) and the lexicon's 200,000-document sample.
- The changed copy is made by the same fixed transform.

**Wordings:**
- Three new independent agent sessions wrote them, in roles not used before:
  - a recruiter checking an engineering team's workload;
  - a customer success manager before a renewal call;
  - an operations intern on their second day.
- **The brief named no tracker.** Earlier briefs said "Linear issue", and writers copied it. This brief says "ticket"
  and "pull request" only, so the writers chose for themselves whether to name a tool.
- Each writer saved its wordings to a file itself. I have not read them.
- The same selection rule applies: writers 1 and 2 give the pair, and writer 3 stands in for an invalid wording. A
  script applied it and printed only that none was replaced.

| file | sha256 |
|---|---|
| `writer1.json` | `72dfe31b04a68681…` |
| `writer2.json` | `45f01702ccd3a9bf…` |
| `writer3.json` | `1b5f8dc0b00219ee…` |
| `wordings.json` (the pairs used) | `987b6267cab35bb7…` |

## Measure

As before:
- own answers, no model judging;
- the three-group mean;
- right for the right reason.

**Also measured:**
- the share right on the action-item questions;
- the share right on all other questions, per question.

## Rules

1. **The ticket rule answers action items when no tracker is named:** v11 − v9 ≥ +0.25 on the test set's action-item
   questions.
2. **No harm on the other questions:** v11 ≥ v9 − 0.03 on the test set's other questions, per question.
3. **The same with the small model's form:** v12 − v10 ≥ +0.25 on the test set's action-item questions.
4. **No harm on the earlier sets:** v11 ≥ v9 − 0.01 and v12 ≥ v10 − 0.01, on the mean of the seven earlier held-out sets
   as drawn. This is known from development, so it is a guard rather than a test.
5. **Principles, not memorisation:** v11 and v12 on the test set ≥ their score on the 201 training questions − 0.15.
6. **It holds when the information changes:** v11 and v12 on the changed copy ≥ the test set − 0.05.
7. **No harm on what was learned:** v11 and v12 ≥ v4 − 0.03 on the first 48 training questions.

**Rules 1 and 2 decide whether the ticket rule works.**

**If few questions name no tracker,** rule 1 has little to measure. How many of the test's action-item questions name
no tracker will be reported.

**Also reported:**
- every arm on the whole test set and by kind;
- the same questions in each writer's wording;
- whether any person asked about has Jira tickets;
- v12's form use and the model's time.

## Frozen

| what | sha256 / value |
|---|---|
| code | the commit that adds this document |
| `plan_lessons_v11.json` (201 questions, glossary, tickets) | `24fd475135cfed46…` |
| `plan_lessons_v9.json`, `plan_lessons_v4.json`, `plan_lessons_v8.json` | as before (`00e63e5f…`, `74715075…`, `ad549716…`) |
| v12's form prompt and model | as v10 (`bf3f84a670bd43be`, `llama3.2:3b` `a80c4f17…`) |
| the run script | `docs/benchmarks/factbank_ticket/run_ticket.sh` |
