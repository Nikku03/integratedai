# The first one due only when the question asks for it: what decides, fixed before the test

> **Draft, under review:** the design is frozen only by the commit that removes this line.

I wrote this on 2026-10-09:
- **after** building the check and trying it on every earlier set, all of which I had seen;
- **before** drawing the test set's documents;
- **before** reading its wordings.

Three new writers wrote those wordings and saved them to files that I have not opened. The results go in
`docs/FACTBANK_ORDER_RESULTS.md`.

## Why

The ticket test (`docs/FACTBANK_TICKET_RESULTS.md`) found the mistake that now costs the most:
- **The question:** "Whoever picked up the action item X in the Y meeting, which tickets are assigned to them? Ticket
  keys please."
- **What goes wrong:** the bank answers with only the owner's first ticket due, instead of all of them. 8 of the 10
  action items there got part marks for this, in v9, v11 and v12 alike.
- **Why:** the glossary turns "which ticket" into "key". In training, "key" comes almost only with "which of the issues
  assigned to P is due first? Give the key". So the bank leans to "the first one due".

## What changes

### v13: v11, plus "an order needs a word of order"

**The check** (`ORDER_WORDS`, `Planner.asks_order`, check 5 in `Planner.check`, in `cie/src/cie/factbank/plans.py`):
- A plan that picks the first or the last thing by a date is kept only if the question asks for an order.
- A question asks for an order when it uses one of these words, outside quoted titles: first, earliest, earlier, soonest,
  sooner, next, nearest, closest, urgent, last, latest, later, final, before, after (stemmed).
- **These are English words of time order, a closed class.** The list was fixed after looking at the earlier sets'
  wordings.
- **Like every check,** it is skipped if no plan passes it.

**What is unchanged:**
- **The weights are v11's.** The check acts only when a question is asked, so `plan_lessons_v13.json` is v11's lessons
  with the switch on.
- **The switch is off by default** (`PlanLessons.orders`). Every earlier version gives the same answers as before.

### v14: v12 with the same check

It is v13's lessons plus the 3B model's form, used only where the bank's lessons are unsure.

### The others, as before

v4, v8, v9, v11 and v12 are frozen and unchanged.

## Development (all on sets I had seen)

**Is a word of order always there when an order is asked?** I checked every wording of every earlier set:
- **Every** "which of two is due first" and "a person's first issue due" question uses a word of order. So the check
  never removes the right plan from them.
- A few other questions use one in passing ("before my call", "After the meeting…"). There the check simply does
  nothing.

Three-group mean of own answers:

| set | v11 | v13 | v12 | v14 |
|---|---|---|---|---|
| first 48 training questions | 0.993 | 1.000 | 0.993 | 1.000 |
| 201 training questions | 0.993 | 1.000 | 0.993 | 1.000 |
| first held-out | 0.980 | 0.980 | 0.980 | 0.980 |
| retest | 0.984 | 0.984 | 0.968 | 0.968 |
| new words | 0.877 | 0.877 | 0.965 | 0.965 |
| general-English blind | 0.958 | 0.963 | 0.977 | 0.981 |
| language-model test | 0.983 | 0.983 | 0.983 | 0.983 |
| planner test | 0.975 | 0.982 | 0.975 | 0.982 |
| replication | 0.979 | 0.979 | 1.000 | 1.000 |
| **ticket test** | 0.942 | **1.000** | 0.942 | **1.000** |
| ticket test, writers 1 / 2 / 3 alone | 0.942 / 0.942 / 1.000 | **1.000 / 1.000 / 1.000** | 0.942 / 0.942 / 1.000 | 1.000 / 1.000 / 1.000 |

**Question by question:**
- Every change is a gain, on an action item. No question anywhere got worse.
- **Most of the gains are the ticket test's own failing questions:** 8 on the test set, and 8 in each of writers 1 and 2
  alone.
- **The rest are on earlier sets:**
  - the planner test's one action-item miss, where the action item contained the word "date";
  - one on the blind set;
  - 3 in training.

## The test set (frozen)

**Documents:**
- A new sample: `fresh --seed 47`, questions seed 48.
- **Excluded:** every earlier set's documents (`mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`,
  `mdwords`, `mdblind`, `mdllm`, `mdplan`, `mdrep`, `mdtick`) and the lexicon's 200,000-document sample.
- The changed copy is made by the same fixed transform.

**Wordings:**
- Three new independent agent sessions wrote them, in roles not used before:
  - a project manager writing a weekly status email;
  - a support engineer on call;
  - a VP of engineering on a phone between meetings.
- The brief is the ticket test's: it names no tracker.
- Each writer saved its wordings to a file itself. I have not read them.
- The same selection rule applies: writers 1 and 2 give the pair, and writer 3 stands in for an invalid wording. A
  script applied it and printed only that one wording was replaced.

| file | sha256 |
|---|---|
| `writer1.json` | `aa94fbebbcaf7c58…` |
| `writer2.json` | `241d892ce56b9dae…` |
| `writer3.json` | `e55ee4cfa16f2bb8…` |
| `wordings.json` (the pairs used) | `3ec6d777750f80a5…` |

## Measure

As before:
- own answers;
- the three-group mean;
- right for the right reason.

**The groups this test cares about:**
- **the action-item questions**, where the mistake happens;
- **all other questions**, per question;
- **the questions that do ask for an order** ("which of two is due first", "a person's first issue due"), where the
  check must do no harm.

## Rules

1. **The first one due only when an order is asked:** v13 − v11 ≥ +0.15 on the test set's action-item questions.
2. **No harm on the other questions:** v13 ≥ v11 − 0.03, per question.
3. **The same with the small model's form:** v14 − v12 ≥ +0.15 on the action items. It is expected to follow rule 1; it
   is not a separate confirmation.
4. **No harm on the earlier sets:** v13 ≥ v11 − 0.01 and v14 ≥ v12 − 0.01, on the mean of the eight earlier held-out sets
   as drawn, the ticket test's included. **Known from development**, so it is a guard rather than a test.
5. **Principles, not memorisation:** v13 and v14 on the test set ≥ their score on the 201 training questions − 0.15. The
   training score is known: 1.000.
6. **It holds when the information changes:** v13 and v14 on the changed copy ≥ the test set − 0.05.
7. **No harm on what was learned:** v13 and v14 ≥ v4 − 0.03 on the first 48 training questions. **Known:** 1.000 against
   0.927.

**What decides:**
- **Rules 1 and 2 decide whether the check works.**
- **If v11 already scores 0.9 or more on the action items,** there is no room for it to help. Rules 1 and 3 are then
  reported as **not measurable**.

**Also reported:**
- every arm on the whole test set and by kind;
- the questions that ask for an order, and how many of them use no word of order;
- how many action items use a word of order;
- the same questions in each writer's wording;
- v14's form use and the model's time.

## Frozen

| what | sha256 / value |
|---|---|
| code | the commit that removes the draft line from this document |
| `plan_lessons_v13.json` (v11's lessons with the order check on) | `64cf5b302a826b2e…` |
| `plan_lessons_v11.json`, `plan_lessons_v9.json`, `plan_lessons_v4.json`, `plan_lessons_v8.json` | as before (`f51b0b1b…`, `00e63e5f…`, `74715075…`, `ad549716…`) |
| v14's form prompt and model | as v10 (`bf3f84a670bd43be`, `llama3.2:3b` `a80c4f17…`) |
| the run script | `docs/benchmarks/factbank_order/run_order.sh` |
