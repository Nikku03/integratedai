# A ticket means Linear or Jira: what decides, fixed before the test

I wrote this on 2026-10-09:
- **after** building the rule and trying it on every earlier set, all of which I had seen;
- **after** an independent review of the rule, which found two problems that are now fixed;
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
- **How often:** in the reruns of the plain-words writer's wording, v9 got 4 of 8 such questions wrong on the first test
  and 3 of 9 on the replication.

## What changes

### v11: v9, plus "a ticket is a Linear or Jira item"

**The rule** (`TICKET_WORD`, `TICKET_SYSTEMS`, `Planner.systems_named`, `in_system`, `own_systems` in
`cie/src/cie/factbank/plans.py`):
- The words "ticket", "tickets", "issue" and "issues" name a system of their own, "ticket".
- It comes after any system the question names by name, so "the Linear ticket" still asks about Linear.
- **What belongs to it:**
  - every Linear or Jira item;
  - a ticket key that the bank has no document for, such as an `ENG-123` named only in a link.
- **What it changes:**
  - A question that starts outside the trackers and says "tickets" (a meeting's action item, a pull request) asks
    about the trackers. The system check (check 2) then keeps only plans whose answer comes from Linear or Jira.
  - A question that starts from a Linear or Jira item and names no other system is planned exactly as v9 plans it.

**The switch:** it is on only when the lessons say so (`PlanLessons.tickets`). Every earlier version, v9 and v10
included, gives the same answers as before; I checked this on every earlier set.

**The weights:** they are learned again on the same 201 training questions, in the same way as v9 (`--tickets`):
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
| first 48 training questions | 0.993 | 0.993 | 0.993 | 0.993 |
| 201 training questions | 0.993 | 0.993 | 0.993 | 0.993 |
| first held-out | 0.980 | 0.980 | 0.980 | 0.980 |
| retest | 0.984 | 0.984 | 0.968 | 0.968 |
| new words | 0.877 | 0.877 | 0.947 | 0.965 |
| general-English blind | 0.958 | 0.958 | 0.977 | 0.977 |
| language-model test | 0.983 | 0.983 | 0.983 | 0.983 |
| planner test | 0.975 | 0.975 | 0.975 | 0.975 |
| replication | 0.979 | 0.979 | 1.000 | 1.000 |
| **planner test, plain-words writer** | 0.872 | **0.923** | 0.924 | **0.975** |
| **replication, plain-words writer** | 0.878 | **0.917** | 0.962 | **1.000** |

**What changed, question by question.** v11 differs from v9 only on the plain-words action items:
- **The fix works on the very template it was built for.** v11 answers all 7 from the owner's tickets, where v9
  answered from the meeting notes.
- **One still scores 0.5.** Its action item contains the word "date", so it is ordered by date instead of listed.
- **Those 7 are one writer's one template,** the one the rule was built to fix.

v12 differs from v10 on the same 7, and on one new-words question that it now gets right by coincidence.

## The review before freezing

Three reviewers checked the rule, the scoring and the protocol, and a fourth tried to refute each finding
(`docs/benchmarks/factbank_ticket/prefreeze_review.json`). What held up, and what was done:

1. **"Ticket" dropped linked keys that have no document.** On linked-ticket questions this narrowed two disagreeing keys
   to one, so a plan answering with a ticket key became possible. It caused the one development loss, on the retest.
   - **Fixed:** such keys now belong to "ticket".
   - **Fixed:** a question that starts from a ticket and names no other system is planned as in v9.
2. **Rule 1 did not say which questions "name no tracker".** It is now judged on the action-item questions that contain
   neither "Linear" nor "Jira", with a minimum count (below).
3. **Promised reports were not computed by the frozen code.** The Jira check, the single-writer runs and v12's form use
   now are.
4. **A known limit, not fixed.** A question about a pull request or a meeting that only mentions a ticket in passing is
   now answered from the tracker. For example, "who authored PR #N, the one that fixes the login issue?" gets the
   linked issue's assignee instead of the author. None of the seven kinds of question asks this, so the test cannot show
   it. It is reported as a limit.
5. **The brief used the word the rule keys on.** It said "ticket", so the writers are likely to say "ticket". The test
   checks the rule where people say "ticket" or "issue". It does not cover other words, such as "card" or "bug".
6. **The development section** now says that the gains come from one writer's one template.

**A check made before the test:** "tickets" could rightly include Jira tickets, while the test's expected answers count
only Linear issues. In every earlier set, none of the people asked about has a Jira ticket assigned. The test's report
checks this again (`jira_people`).

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
  and "pull request" only.
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

**The groups this test cares about:**
- **The action items that name no tracker:** action-item questions that contain neither "Linear" nor "Jira"
  (`NAMES_TRACKER`). Rules 1 and 3 use them.
- **All other questions,** per question. Rule 2 uses them.

## Rules

1. **The ticket rule answers action items that name no tracker:** v11 − v9 ≥ +0.25 on those questions.
2. **No harm on the other questions:** v11 ≥ v9 − 0.03, per question.
3. **The same with the small model's form:** v12 − v10 ≥ +0.25 on the action items that name no tracker.
4. **No harm on the earlier sets:** v11 ≥ v9 − 0.01 and v12 ≥ v10 − 0.01, on the mean of the seven earlier held-out sets
   as drawn. **Known from development**, so it is a guard rather than a test.
5. **Principles, not memorisation:** v11 and v12 on the test set ≥ their score on the 201 training questions − 0.15. The
   training score is known: 0.993.
6. **It holds when the information changes:** v11 and v12 on the changed copy ≥ the test set − 0.05.
7. **No harm on what was learned:** v11 and v12 ≥ v4 − 0.03 on the first 48 training questions. **Known from
   development:** 0.993 against 0.927.

**What decides:**
- **Rules 1 and 2 decide whether the ticket rule works.** Rule 3 is expected to follow rule 1; it is not a separate
  confirmation.
- **If fewer than 4 action-item questions name no tracker,** rules 1 and 3 are reported as **not measurable**, not as
  met or not met. The same rules are then reported on each writer's wording alone, for information.

**Also reported:**
- every arm on the whole test set and by kind;
- the same questions in each writer's wording;
- how many questions name no tracker;
- whether any person asked about has Jira tickets;
- v12's form use and the model's time.

## Frozen

| what | sha256 / value |
|---|---|
| code | the commit that removes the draft line from this document |
| `plan_lessons_v11.json` (201 questions, glossary, tickets) | `f51b0b1b59ac1921…` |
| `plan_lessons_v9.json`, `plan_lessons_v4.json`, `plan_lessons_v8.json` | as before (`00e63e5f…`, `74715075…`, `ad549716…`) |
| v12's form prompt and model | as v10 (`bf3f84a670bd43be`, `llama3.2:3b` `a80c4f17…`) |
| the run script | `docs/benchmarks/factbank_ticket/run_ticket.sh` |
