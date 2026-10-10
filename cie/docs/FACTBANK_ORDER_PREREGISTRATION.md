# All of them when the question asks for several: what decides, fixed before the test

I wrote this on 2026-10-09 and 2026-10-10:
- **after** building the check and trying it on every earlier set, all of which I had seen;
- **after** two independent reviews. Each found that the check, as it then stood, harmed questions it should not touch, so
  it was redesigned twice (below);
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

**The check** (`Planner.wants_several` and check 5 in `Planner.check`, in `cie/src/cie/factbank/plans.py`):
- **What it does:** it drops the plans that pick the first or the last thing by a date.
- **When it acts:** all three of these hold:
  1. the question asks for several things;
  2. it does not ask for one thing;
  3. it uses no word of order.
- **Like every check,** it is skipped if no plan passes it.

**1. Asks for several** (`asks_several`), any one of:
- it says "list", "lists", "listing", "enumerate", "itemize", "all", "every" or "each";
- it asks for "keys", "IDs", "identifiers" or "numbers";
- it asks "which" or "what" followed by a plural: "which tickets", "what Linear issues", "which ones", "what are".

**2. Asks for one thing** (`asks_one`), any one of:
- "which of…", "which one";
- "which" followed by a singular: "which ticket", "which Linear issue". This does not count when a plural follows, as in
  "which ticket keys";
- "just one", "only one", "top one", "single".

**3. Uses a word of order** (`asks_order`), any one of:
- one of: first, 1st, next, earliest, earlier, soonest, sooner, nearest, nearer, closest, closer, last, latest, later,
  final, oldest, newest, recent, urgent, overdue, tightest, pressing, top, asap, upcoming, prior, priority;
- "before" or "ahead" followed within three words by others, other, rest, else, anything or everything ("before all the
  others").
- "Next" does not count when a meeting, call, week, sprint, review or similar comes right after it ("before my next
  meeting").

**How words are read** (`raw_words`):
- as written and in lower case, outside quoted titles (straight or curly double quotes);
- "ticket(s)" reads as "tickets", and "key's" or "ID's" as "keys" or "IDs";
- there is no stemming, so "keys" stays plural and "soon" is not "soonest".

**Why it is built this way:** each part of the condition guards against harm.
- **Where it can only help or do nothing:** the check acts only when the question asks for several things. A missed way of
  asking for several leaves the question answered as v11 answers it.
- **Where the harm was:** a question asking for the first one due often carries a generic plural ("Keys only", "IDs
  please"). Parts 2 and 3 keep the check off for such questions, because they nearly always say "which of", "which one"
  or a word of order.
- **The cost:** an action item with a word of order in passing ("last thing for today") is answered as v11 answers it.

**What is unchanged:**
- **The weights are v11's.** The check acts only when a question is asked, so `plan_lessons_v13.json` is v11's lessons
  with the switch on. The file is the same as in the draft; only the code it switches on changed.
- **The switch is off by default** (`PlanLessons.orders`). Every earlier version gives the same answers as before.

### v14: v12 with the same check

It is v13's lessons plus the 3B model's form, used only where the bank's lessons are unsure.

### The others, as before

v4, v8, v9, v11 and v12 are frozen and unchanged.

## How the check got here

**First design: "an order needs a word of order."** A "first one due" plan was kept only if the question used one of 15
words such as first, soonest, earlier or before.
- **The first review showed that it did harm** (`docs/benchmarks/factbank_order/prefreeze_review.json`). A question asking
  for the first one due without one of the 15 words lost its right answer: "tightest deadline", "most overdue", "due 1st".
- On the reviewers' rewordings of earlier questions, 48 of 154 went from right in v11 to wrong.

**Second design: "several, unless a superlative".** The check acted when the question asked for several things and used
none of first, soonest, latest and the like.
- **The second review showed that it still did harm** (`docs/benchmarks/factbank_order/prefreeze_review2.json`). A
  question asking for the first one due often adds a generic plural: "Which of P's issues is due next? IDs please." With
  "next", "most urgent" or "before the others", which are not superlatives, the check acted.
- On the reviewers' new rewordings, 286 of 308 such questions went from right in v11 to wrong.

**Third design, frozen here:** "asks for one thing" and the wider set of order words also keep the check off.

**On every earlier set, all three designs give exactly the same answers.** They differ only on wordings outside those sets.
So the earlier sets cannot tell them apart; only the reviewers' rewordings can.

## Development (all on sets I had seen, and on the reviewers' rewordings)

**On every earlier wording** (`docs/benchmarks/factbank_order/earlier_wordings.py`):
- The check acts on **all 25** action-item wordings.
- It acts on **none** of the 50 wordings that ask for an order.
- **Both are true by construction:** the word lists were written while looking at these wordings. They show that the check
  fits the seen wordings, not that it is safe on others.

**On the reviewers' rewordings, the real test of harm** (`docs/benchmarks/factbank_order/review_battery/`):
- **What they are:** the second review wrote new wordings in a project manager's, an on-call engineer's and a VP's style,
  including generic plurals, typos and one-letter edits of earlier writers' wordings. Expected answers come from the
  documents of eight earlier sets.
- **1,072 questions that ask for an order:** none changed in v13.
- **441 questions of other kinds:** none changed.
- **1,358 action items:** 577 better, 779 the same, 2 worse. The 2 worse are one question asked twice, below.
- Of the action items the check acted on but did not get right, all but that one already failed in v11 with the same plan,
  for reasons the check does not touch ("what tickets do they have?" read as asking for a status).

**On the first review's probes** (`docs/benchmarks/factbank_order/review_probes/`):
- **154 rewordings that ask for an order:** the check acts on none, so none changes.
- **18 action items with words in passing:** 12 are now right.
  - The other 6 use a word of order in passing ("last thing for today", "not just the first one"). They are answered as
    v11 answers them.

**Three-group mean of own answers on the earlier sets:**

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

**Question by question:** 33 answers changed across the 19 sets and wordings, v13 against v11. All are gains on action
items, and none got worse; v14 against v12 is the same. They are:
- 8 on the ticket test set, and 8 in each of writers 1 and 2 alone;
- the planner test's one action-item miss, in the set and in each of its three writers' wordings (4);
- one on the blind set;
- one training question, which counts once in the first 48 and three times in the 201, since the 201 hold three wordings of it
  (4).

## The reviews before freezing

Each review had three reviewers (two in the second), and a further one tried to refute each finding. What held up, and
what was done:

**First review** (`prefreeze_review.json`):
1. **The first design did harm.** **Fixed:** redesigned (above).
2. **No rule protected the questions that ask for an order.** Rule 2's −0.03 allowed one of them to be lost outright.
   - **Fixed:** rule 2 now also requires that no such question scores lower in v13 than in v11, or in v14 than in v12.
3. **When v11 scored between 0.85 and 0.9 on the action items, rules 1 and 3 were judged but could not be met:** a gain of
   +0.15 is impossible there.
   - **Fixed:** they are judged only when v11 scores 0.85 or less.
4. **Rule 3's "not measurable" condition used v12's score, while this document said v11's.** **Fixed:** both rules now use
   v11's.
   - Rule 3 keeps v11's condition on purpose. In every earlier set, v11 and v12 score the same on every action item.
5. **The single-writer runs would have used the one wording the selection rule rejected.** **Fixed:** a rejected wording is
   replaced by writer 3's, as in the drawn set. Only the number replaced is printed.
6. **"Quoted titles" meant straight double quotes only.** The check also ignores curly double quotes.
7. **The motivation overstated v9's part marks.** Corrected above.

**Second review** (`prefreeze_review2.json`):
1. **The second design still did harm,** through generic plurals. **Fixed:** redesigned (above).
2. **The scoring would have crashed** while writing the report. **Fixed:** a name clash in `order_test`.
   - It was then run end to end on copies of the ticket test, with development answers.
3. **The development evidence never exercised the check** on questions that ask for an order. **Fixed:** the reviewers'
   rewordings, which do, are now the main evidence (above), and the by-construction results are marked as such.
4. **Ways of asking for all that the check missed:** "ticket(s)", "key's", "ID's", "JIRAs", "key for each one". **Fixed:**
   they are now read.
5. **Number and wording errors in this document.** Corrected.

**Known limits, not fixed:**
- **A word of order in passing turns the check off,** and the question is answered as v11 answers it.
- **Dropping the "first one due" plan can let an unrelated plan win.** In the battery this happened on one question:
  "…which tickets do they have? Send me the ID's." Its "ID's" left the kind of answer unknown, so the owner's name won.
  It went from 0.5 to 0.
- **Earlier versions read titles only in straight quotes.** A writer using curly quotes affects every version alike.

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
- **The second review's rewordings imitate these roles.** The reviewers knew the roles from this document, but they never
  saw the sealed wordings.
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
- how many action items ask for several, and how many of them the check acts on;
- how many questions that ask for an order the check acts on (where harm could happen);
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
