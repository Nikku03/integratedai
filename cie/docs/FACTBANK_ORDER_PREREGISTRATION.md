# All of them when the question asks for several: what decides, fixed before the test

> **Draft, under review:** the design is frozen only by the commit that removes this line.

I wrote this on 2026-10-09:
- **after** building the check and trying it on every earlier set, all of which I had seen;
- **after** an independent review, which found that my first design did harm. The check was redesigned (below);
- **before** drawing the test set's documents;
- **before** reading its wordings.

Three new writers wrote those wordings and saved them to files that I have not opened. The results go in
`docs/FACTBANK_ORDER_RESULTS.md`.

## Why

The ticket test (`docs/FACTBANK_TICKET_RESULTS.md`) found the mistake that now costs the most:
- **The question:** "Whoever picked up the action item X in the Y meeting, which tickets are assigned to them? Ticket
  keys please."
- **What goes wrong:** the bank answers with only the owner's first ticket due, not all of them.
  - v11 and v12 got part marks for this on 8 of the 10 action items.
  - v9 chose the same "first one due" plan on 8: 6 got part marks, and 2 scored 0 because it read the meeting notes.
- **Why:** the glossary turns "which ticket" into "key". In training, "key" comes almost only with "which of the issues
  assigned to P is due first? Give the key". So the bank leans to "the first one due".

## What changes

### v13: v11, plus "several, not the first"

**The check** (`MANY_WORDS`, `MANY_ITEMS`, `RANK_WORDS`, `raw_words`, `Planner.asks_several`, `Planner.asks_rank` and check
5 in `Planner.check`, in `cie/src/cie/factbank/plans.py`):
- **When it acts:** the question asks for several things and asks for no rank by time.
- **What it does:** it drops the plans that pick the first or the last thing by a date.
- **"Asks for several"** means one of these:
  - it says "list", "lists", "listing", "enumerate" or "itemize";
  - it asks for "keys", "IDs", "identifiers" or "numbers";
  - it asks "which" or "what" followed by a plural: "which tickets", "what Linear issues", "which ones", "what are".
    "Which of the tickets…" asks for one of them, so it does not count.
- **"Asks for a rank by time"** means it uses one of: first, 1st, earliest, soonest, nearest, closest, last, latest,
  final, oldest, newest.
- **How words are read:** as written and in lower case, outside quoted titles (straight or curly double quotes). There is
  no stemming, so "keys" stays plural and "soon" is not "soonest".
- **Like every check,** it is skipped if no plan passes it.

**Why this way round:** the check acts only on positive evidence that several things are wanted.
- **When it is wrong, the cost is small:**
  - If it misses a way of asking for several, the question is answered as v11 answers it.
  - If a rank word appears in passing ("last thing for today"), the same happens.
- **When it could do harm:** only a question that asks for one thing first by date, phrased in the plural with no rank
  word. That is rare.

**What is unchanged:**
- **The weights are v11's.** The check acts only when a question is asked, so `plan_lessons_v13.json` is v11's lessons
  with the switch on. The file is the same as in the draft; only the code it switches on changed.
- **The switch is off by default** (`PlanLessons.orders`). Every earlier version gives the same answers as before.

### v14: v12 with the same check

It is v13's lessons plus the 3B model's form, used only where the bank's lessons are unsure.

### The others, as before

v4, v8, v9, v11 and v12 are frozen and unchanged.

## The first design, and why it changed

**The draft's check was "an order needs a word of order":** a "first one due" plan was kept only if the question used a
word such as first, soonest, earlier or before.

**The review showed that it did harm** (`docs/benchmarks/factbank_order/prefreeze_review.json`):
- **The words were not a closed class.** A question asking for the first one due without one of the 15 words lost its
  right answer. Examples: "tightest deadline", "most overdue", "most pressing", "closer", "due 1st".
- **The reviewers' rewordings showed it:** 41 of 42 such rewordings of earlier sets' questions went from right in v11 to
  wrong in v13.
- **On the earlier sets it looked harmless only by construction.** The list was built from those sets' wordings, and three
  of its words each covered exactly one wording.

**The new check acts the other way round.** It needs evidence that several things are wanted, not evidence that an order
is wanted.

## Development (all on sets I had seen)

**On every earlier wording** (`docs/benchmarks/factbank_order/earlier_wordings.py`):
- The check acts on **all 25** action-item wordings.
- It acts on **none** of the 50 wordings that ask for an order ("which of two is due first", "a person's first issue
  due").

**On the reviewers' rewordings** (`docs/benchmarks/factbank_order/review_probes/`):
- **154 rewordings of questions that ask for an order:** none gets worse in v13. With the first design, 41 did.
- **18 action items with words in passing** ("as soon as you can", "before my 1:1", "after standup"): 12 are now right.
  - The other 6 use a rank word in passing ("last thing for today", "not just the first one"). They are answered as v11
    answers them.

**Three-group mean of own answers:**

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
- **v13 against v11:** 33 questions changed. All are gains on action items, and no question anywhere got worse. v14 against
  v12 is the same.
- **Most of the gains are the ticket test's own failing questions:** 8 on the test set, and 8 in each of writers 1 and 2
  alone.
- **The rest are on earlier sets:**
  - the planner test's one action-item miss;
  - one on the blind set;
  - 3 in training.
- **The new check gives exactly the same answers as the first design** on every one of these sets. They differ only on
  wordings outside the earlier sets.

## The review before freezing

Three reviewers checked the check, the scoring and the protocol, and a fourth tried to refute each finding
(`docs/benchmarks/factbank_order/prefreeze_review.json`). What held up, and what was done:

1. **The first design did harm** to questions asking for the first one due without a listed word. **Fixed:** the check
   was redesigned (above).
2. **No rule protected the questions that ask for an order.** Rule 2's −0.03 allowed one of them to be lost outright.
   - **Fixed:** rule 2 now also requires that no such question scores lower in v13 than in v11, or in v14 than in v12.
3. **Rules 1 and 3 could only fail when v11 scored between 0.85 and 0.9.** In that band a gain of +0.15 is impossible.
   - **Fixed:** they are judged only when v11 scores 0.85 or less on the action items.
4. **Rule 3's "not measurable" condition used v12's score, while this document said v11's.** **Fixed:** both rules now use
   v11's.
5. **The single-writer runs would have used the one wording the selection rule rejected.** **Fixed:** a rejected wording is
   replaced by writer 3's, as in the drawn set. Only the number replaced is printed.
6. **"Quoted titles" meant straight double quotes only.** The new check also ignores curly double quotes.
7. **The motivation overstated v9's part marks.** It is corrected above.

**Known limits, not fixed:**
- A rank word in passing turns the check off, and the question is answered as v11 answers it.
- "All" and "every" are not read as asking for several, because "due before all the others" asks for one.
- Earlier versions read titles only in straight quotes. A writer using curly quotes affects every version alike.

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
- **the questions that ask for an order** ("which of two is due first", "a person's first issue due"), where the check
  must do no harm.

## Rules

1. **All of them when several are asked for:** v13 − v11 ≥ +0.15 on the test set's action-item questions.
2. **No harm on the other questions**, both of these:
   - v13 ≥ v11 − 0.03 on the other questions, per question;
   - no question that asks for an order scores lower in v13 than in v11, or in v14 than in v12.
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
- **If v11 scores more than 0.85 on the action items,** a gain of +0.15 is impossible. Rules 1 and 3 are then reported as
  **not measurable**:
  - the test then gives no evidence that the check helps;
  - only the no-harm rules are judged.

**Also reported:**
- every arm on the whole test set and by kind;
- every question whose score changed;
- how many action items the check reads as asking for several, and how many of them also use a rank word;
- how many questions that ask for an order the check reads as asking for several with no rank word (where harm could
  happen);
- the same questions in each writer's wording;
- v14's form use and the model's time.

## Frozen

| what | sha256 / value |
|---|---|
| code | the commit that removes the draft line from this document |
| `plan_lessons_v13.json` (v11's lessons with the check on) | `64cf5b302a826b2e…` |
| `plan_lessons_v11.json`, `plan_lessons_v9.json`, `plan_lessons_v4.json`, `plan_lessons_v8.json` | as before (`f51b0b1b…`, `00e63e5f…`, `74715075…`, `ad549716…`) |
| v14's form prompt and model | as v10 (`bf3f84a670bd43be`, `llama3.2:3b` `a80c4f17…`) |
| the run script | `docs/benchmarks/factbank_order/run_order.sh` |
