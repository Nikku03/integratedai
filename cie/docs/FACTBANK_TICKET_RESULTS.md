# A ticket means Linear or Jira: results

**Run on 2026-10-09**, by the rules in `docs/FACTBANK_TICKET_PREREGISTRATION.md`. The design was frozen at commit
`ffdfe2b`; the test set was drawn after it.
- **Raw results, wordings, forms and review:** `docs/benchmarks/factbank_ticket/`.

## In short

**The rule fixed the failure it was built for, every time that failure came up.** But the test did not reach its
pre-registered bar, so rules 1 and 3 are **not met**.

- **On the 10 action-item questions** (none names Linear or Jira), v11 scored 0.600 against v9's 0.393. That is +0.207,
  short of the +0.25 required.
- **On the other 40 questions** it changed nothing: both score 1.000. No harm.
- **On the whole test set,** v11 0.942 against v9 0.912.

**Why it fell short:**
- **Only 3 of the 10 questions had the targeted problem.**
  - v9 answers from the meeting notes only when the question says "meeting". One writer never did, and the random draw
    gave that writer's wording to 6 of the 10.
  - On all 3 questions that did say "meeting", v11 answered from the tickets. In each writer's wording alone, it fixed
    5 of 5.
- **A different, older mistake capped the gain.**
  - "Which tickets are assigned to them? Ticket keys please" made the bank return only the first ticket due, not all of
    them. v9 and v11 both do this.
  - So two of the three fixed questions got only part marks.
  - Had they been listed in full, the gain would have been about +0.30. That figure is a what-if, not a result.

**The small model's form changed nothing here.** v12 = v11 and v10 = v9 on every answer. The form has no way to say
"list them all".

## Decision

| Rule | Result |
|---|---|
| 1. The ticket rule answers action items that name no tracker (v11 − v9 ≥ +0.25) | **Not met:** 0.600 against 0.393 (+0.207) |
| 2. No harm on the other questions (v11 ≥ v9 − 0.03) | **Met:** 1.000 against 1.000 |
| 3. The same with the small model's form (v12 − v10 ≥ +0.25) | **Not met:** +0.207, the same 3 questions as rule 1 |
| 4. No harm on the earlier sets (guard, known) | **Met:** v11 = v9 (0.962); v12 0.978 against v10 0.976 |
| 5. Principles, not memorisation | **Met:** 0.942 against 0.993 |
| 6. It holds when the information changes | **Met:** the changed copy scores the same |
| 7. No harm on what was learned (known) | **Met:** 0.993 against v4's 0.927 |

## Results

Own answers, three-group mean:

| | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|
| v4 | 0.474 | 0.522 | 0.625 | 0.540 | 0.345 |
| v8 | 0.789 | 0.478 | 0.875 | 0.714 | 0.537 |
| v9 | 1.000 | 0.736 | 1.000 | 0.912 | 0.870 |
| v10 | 1.000 | 0.736 | 1.000 | 0.912 | 0.870 |
| **v11** | 1.000 | **0.826** | 1.000 | **0.942** | 0.884 |
| **v12** | 1.000 | **0.826** | 1.000 | **0.942** | 0.884 |

**Questions naming no tracker:** all 50. The brief named none, and no writer added one.

### The action items, question by question

v11 differs from v9 on 3 of the 50 test answers, all action items:

| question | v9 | v11 | what changed |
|---|---|---|---|
| `action_owner_issues-020` | 0 (answered from the meeting notes) | **1.0** | answered from the owner's tickets |
| `action_owner_issues-029` | 0 (answered from the meeting notes) | 0.4 | from the tickets, but only the first due of 4 |
| `action_owner_issues-035` | 0 (answered from the meeting notes) | 0.667 | from the tickets, but only the first due of 2 |
| the other 7 | the same | the same | 6 of them return only the first due, in both versions |

**Why only 3:**
- **v9's failure needs the word "meeting".** The bank reads it as the system asked about. Writers 1 and 3 used it;
  writer 2's wording ('Whoever picked up the "X" action item in "Y"') did not.
- **The draw.** Each question drew writer 1's or writer 2's wording at random. Writer 1's went to 4 of the 10 action
  items, and 3 of those are where v9 fails.
- **The odds.** Over all 1,024 ways those 10 could have been drawn, the expected gain is +0.173, the most is +0.347, and
  only 16% of draws reach +0.25.

**The same questions in each writer's wording alone** (information only):

| wording | v9, action items | v11, action items | v9, whole set | v11, whole set |
|---|---|---|---|---|
| writer 1 only (a recruiter) | 0.253 | **0.600** | 0.892 | **0.942** |
| writer 2 only (a customer success manager) | 0.600 | 0.600 | 0.942 | 0.942 |
| writer 3 only (an operations intern) | 0.500 | **1.000** | 0.928 | **1.000** |

- In writers 1 and 3, v9 answered the same 5 of 10 from the meeting notes. v11 answered all 5 from the tickets.
- Writer 3 asked "Could you please list the keys…", so there v11 also listed them all: 1.000.

### The other mistake: "the first one due" instead of "all of them"

**What happens:** all 8 action items v11 still misses use the same plan: the owner's tickets, ordered by due date, and
only the first returned. The right list was always among the bank's plans.

**Why it happens** (diagnosed after the test):
- Writers 1 and 2 ask "…which tickets are assigned to them?".
- The glossary (v8) maps "which ticket" to "key".
- In training, "key" comes almost only from the "which of the issues assigned to P is due first? Give the key"
  question. So the bank leans to "the first one due".

**What else that tells us:**
- v9, v10, v11 and v12 all share this mistake. The ticket rule neither causes nor fixes it.
- It is the next thing to fix: "the first one due" should need a word that asks for first, soonest or earliest.

### v12 and the small model

**Same answers:** v12 gives the same answer as v11, with the same plan, on every question. That holds in the test set,
the changed copy and each writer's wording; v10 likewise matches v9.

**How the form was used:**
- It was used for the kind of answer on 4 of 50 test questions.
- Its field was applied where its kind agreed.
- Neither changed an answer.
- On the action items it said "a ticket key, about the owner". That is right, but it cannot say "list them all".

The model took 1.9 seconds per question (median).

### No harm elsewhere

**v11 changed no answer outside these action items:**
- not on the other 40 test questions;
- not on the changed copy (it changed the same 3);
- not on the 48 or 201 training questions;
- not on any of the seven earlier sets.

**How much that shows:** the other 40 test questions were already at 1.000, so rule 2 could only have caught harm to
perfect answers.

## What the review found

Two reviewers checked the numbers and protocol, and the interpretation. A third tried to refute each finding
(`review.json`).
- **The protocol was followed.**
  - The test set was drawn once, at 21:26, after the freeze commit (21:06).
  - Its documents are shared with no earlier set.
  - It used the frozen code, lessons, wordings, prompt and model.
  - Every answer and verdict reproduces.
- **The result rests on 3 questions and on the draw.** The 10 action items cover only 7 owners: three pairs share an
  owner and expected answer.
- **"Or Jira" was not tested.** The test set has no Jira documents (Linear 34, GitHub 8, meeting notes 8). So the Jira
  check is empty by construction, and the test checks only "a ticket is a Linear item".
- **Smaller points:**
  - On one question (`-014`) the rule never acted. The meeting's title contains "GPU Driver", and the bank's older
    substring matching reads "drive" as Google Drive. The answer was the same either way.
  - The development note that an action item fails because it "contains the word date" was a different case. These
    misses come from the glossary's "which ticket" → "key".

## What this shows

- **The rule works where it applies.**
  - When a question says "meeting" and "tickets", v11 answers from the tickets, not the meeting notes: every time, on
    every set.
  - It changed nothing else anywhere.
- **The pre-registered bar was not reached.** The draw left few such questions, and a second, older mistake (the first
  one due instead of the list) took part of the gain. The verdict stays "not met".
- **The bigger remaining problem is now "list them all" against "the first one due".** It costs more than the ticket
  rule gains, and it affects every version.

**Next** (each needs its own pre-registered test):
- "the first one due" should need a word asking for first, soonest or earliest;
- match system names as whole words, so "Driver" is not read as Google Drive;
- test "or Jira" on a set that has Jira tickets.

## Reproduce

```bash
python -m cie.eval.factbank_multi train --work $TRAIN9 --single lessons.json --plans plan_lessons_v11.json --rules v9 --proper --glossary glossary.json --tickets
bash docs/benchmarks/factbank_ticket/run_ticket.sh   # draws the test set, answers with every arm, scores the rules
```
