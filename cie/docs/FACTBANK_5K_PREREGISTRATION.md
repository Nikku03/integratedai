# The fact bank at 5,000 documents, part A: what decides, fixed before the test

I wrote this on 2026-10-10:
- **after** probing the frozen system on a 5,000-document set I had seen (below);
- **before** drawing the test set's 5,000 documents.

The results go in `docs/FACTBANK_5K_RESULTS.md`. Part B, the fact bank against the memory bank on finding evidence, has its
own pre-registration (`docs/FACTBANK_5K_B_PREREGISTRATION.md`).

## Why

Every test of the fact bank so far used 50 documents. Two earlier write-ups said the same check was still owed: does it
hold up on 5,000 documents (`docs/FACTBANK_PREREGISTRATION.md`, `docs/FACTBANK_RESULTS.md`)?

**Part A asks this of the current system.** The fact bank with the planner, v4 to v14, answers the same kinds of
multi-document questions as before, with the bank built from 5,000 documents instead of 50.

## Nothing changes but the size of the bank

**Frozen:**
- **The code:** `cie/src/cie/factbank` and every existing function in `cie/src/cie/eval`, at the commit that removes the draft
  line. The test's own code is new and changes nothing else: `cie/src/cie/eval/factbank_5k.py`.
- **The lessons:**

  | file | sha256 |
  |---|---|
  | `plan_lessons_v4.json` | `747150754ce6ad27…` |
  | `plan_lessons_v8.json` | `ad54971605f3864b…` |
  | `plan_lessons_v9.json` | `00e63e5fbca8cee8…` |
  | `plan_lessons_v11.json` | `f51b0b1b59ac1921…` |
  | `plan_lessons_v13.json` | `64cf5b302a826b2e…` |
  | single-fact lessons `fb50/lessons.json` | `afa4e7d9fee0a05c…` |
  | the glossary | `0dd7d0bc2a7788d5…` |

- **The small model's form** (v12, v14): prompt `bf3f84a670bd43be`, model `llama3.2:3b` (`a80c4f17…`).
- **The wordings:** the order test's wording pairs, `docs/benchmarks/factbank_order/wordings.json` (`3ec6d777750f80a5…`). Each
  question takes one of its pair at random, as before. The replication reused its test's wordings in the same way, so only the
  documents changed.

## The test set

**Documents** (`factbank_5k.draw`, seed 53):
- **5,000 documents from the whole benchmark,** every source in its share of what earlier sets left: Slack, Gmail, Linear,
  Google Drive, HubSpot, Fireflies, GitHub, Jira and Confluence. Most are unrelated to any question, as in a real company.
- **Excluded:** every document of every earlier set (`mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`, `mdwords`,
  `mdblind`, `mdllm`, `mdplan`, `mdrep`, `mdtick`, `mdord`) and the lexicon's 200,000-document sample.
- **One document per name.** The benchmark reuses some ticket keys and pull request numbers on unrelated documents. A key or
  number already drawn is not drawn again, so a question naming one has one right answer. A real company does not reuse
  ticket keys.
- **Ten planted pull requests.** A plain sample holds almost no pull request together with the ticket it links. So ten are
  drawn first, each linking one Linear issue that no other pull request left after the exclusions references. The other
  tickets a planted pull request links stay out of the set.
  - **Only 56 pairs qualify** in what is left.
- **Odd keys stay out.** A ticket whose key is not a plain key (such as `ENG-642317-decision-mesh-schema-refactor`) is not
  drawn.

**Questions** (`factbank_5k.build_sets`, seed 54):
- **Drawn over all 5,000 documents** by the same generator as every earlier test (`factbank_multi.questions`). Expected answers
  are computed over all 5,000.
- **Set aside when they have more than one right answer** (`why_unclear`):
  - **named:** a key, pull request number or meeting title they name is on more than one document, or the action item they
    name was taken by more than one person in that meeting. The draw makes this rare.
  - **answer:** a ticket key their answer rests on is on more than one document.
  - **linked:** the bank follows links both ways, so a ticket that links *to* the named ticket, or another ticket the named
    pull request links, is a second reading. When that ticket's asked field differs from the expected answer, the question
    has two right answers. This happens far more often at 5,000 documents than at 50.
  - **tickets:** the wordings say "tickets", but the expected answers count Linear issues only. That never mattered at 50
    documents: no person asked about had a Jira ticket. At 5,000 it can. When reading "tickets" as Linear and Jira items gives
    another answer, the question has two right answers and is set aside.
    - **"Which is due first" is not set aside.** Jira tickets have no `due_date` field, and their SLA and first-response
      deadlines are not counted as due dates.
    - **The planner agrees:** every plan for these questions reads `due_date`, which a review checked.
- **50 questions picked:** the kinds take turns in name order. Within a kind the order is seeded. At each turn the pick
  prefers a question about documents no question of any kind is about yet, so one person or pull request does not carry
  many questions.

**The control: the same questions, a small bank.**
- **The small set** holds only the documents those 50 questions need: the union of their gold documents.
- **The same expected answers:** the draw checks that every picked question has the same expected answer within the small
  set. A question that fails is asked of neither bank, and the count is reported.
- So the difference between the two banks is the effect of the other documents on identical questions.

**The set-aside questions** (up to 50, picked the same way) are also answered on the 5,000-document bank, for information.
They are scored two ways:
- **strict:** against the Linear-only answer;
- **lenient:** right under either reading of "tickets".

The draw saves only counts. It prints nothing of the questions.

## How it runs

The script is `docs/benchmarks/factbank_5k/run_5k.sh`.
- **It checks first that the small model is running.**
- **It makes the forms before any timed run.**
- **It waits for an idle machine** before the arms run.

## Arms

On both banks: v1 (the fact bank alone), v4, v8, v9, v11, v12, v13 and v14, as in the order test.
- **Every run fixes Python's hash seed** (`PYTHONHASHSEED=0`). Which entity a colliding name resolves to can depend on it.
- **The same check under seed 1:** v13 is run again on the 5,000-document bank with seed 1, and every changed answer is
  reported.

## Measure

As before:
- own answers;
- the three-group mean (link, combine, compare);
- right for the right reason.

## Rules

1. **Nothing lost to size:** v13 on the 5,000-document bank ≥ v13 on the small bank − 0.05.
2. **The level holds:** v13 on the 5,000-document bank ≥ 0.92. That is within 0.05 of v13's mean on the eight earlier sets
   (known from development), 0.969.
   - **Why that reference:** this test's questions are drawn over a new set with another mix of people and kinds, so the
     reference is v13 across every earlier set.
   - **For information,** it is also compared with the order test, the same wordings at 50 documents (1.000).
3. **The planner's lead holds at 5,000:** v9 − v4 ≥ +0.10 and v9 − v8 ≥ +0.05, as in the planner test.
4. **The same with the small model's form:** v14 on the 5,000-document bank ≥ v14 on the small bank − 0.05. It is expected to
   follow rule 1; it is not a separate confirmation.
5. **Right for the right reason:** v13's share on the 5,000-document bank ≥ its share on the small bank − 0.05.

**What decides:**
- **It holds at 5,000** if rules 1 and 2 are both met.
- **Rule 3 not met:** the planner's lead over the old planner does not hold at 5,000. It is reported and does not change
  "holds".
- **Rule 5 not met:** it holds, but more right answers come from the wrong plan at 5,000. Each one is diagnosed.
- **Rule 1 met, rule 2 not met:** size costs nothing, but this set is harder for another reason. Diagnosed question by
  question.
- **Rule 1 not met:** size costs accuracy. Every question that got worse is diagnosed.

**How to read differences:** one link or combine question moves the mean by about 0.015–0.02, and one compare question by
about 0.04.
- **Questions about one person or one pull request fail together.** A person asked about in three combine questions is worth
  about 0.05 of the mean, and a planted pair asked about twice about 0.03.
- **So the changed questions are reported grouped by the documents they are about.**

**Also reported:**
- every arm on both banks, by group and by kind;
- every question whose score differs between the banks;
- time per question for each arm on both banks (median, 90th percentile, maximum), the build times, storage and peak memory;
  - the small model's forms are made once before any timed run, so v12's and v14's times on both banks come from the cache;
- the draw's counts: documents by source, duplicates skipped, planted pull requests, questions drawn, set aside (by reason and
  kind), kept and picked;
- the set-aside questions, strict and lenient;
- the hash-seed check;
- each arm against the 50-document tests (order test, and the eight-set mean). The kind mix differs, so only the control
  isolates size.

## What a pass means, and what it does not

**What a pass shows:** 4,950 unrelated documents do not break the bank's lookups and planning.

**What it does not show:** that search holds up when it is hard. Every kind of question here names its starting point
exactly, by a ticket key, a pull request number, a quoted title or a full name. Finding that start does not get harder with
size. Part B tests search.

**What size can still break:**
- names that match several people (first names, near names);
- people with many more documents;
- system words in passing ("for the status email" names Gmail as a system, and at 5,000 there are Gmail documents about the
  ticket);
- many more paths for the planner to choose from.

## Development (on a set I had seen, and review probes)

**The reviews drew from what is left, with other seeds** (997, 7, 101, 202, 303). They used those draws to count questions and
to check the filters, and ran v13 and v4 on a few of their questions. So about 4 or 5 of the 10 planted pairs the test draws may
already have been looked at in review, though not by me.

**The probes** (`docs/benchmarks/factbank_5k/understand.json`) used `mt5k`, the 5,089-document haystack the training documents
came from. So their scores are optimistic and are not results.
- **v13 scored 0.859 on 50 questions drawn there,** against 1.000 at 50 documents.
  - 12 of its 15 errors were questions about people who also hold Jira tickets: the "tickets" ambiguity.
  - 2 came from reused ticket keys, and 1 from "the status email".
- **On the questions with neither ambiguity,** v13 scored 0.983 on 118 questions.
- **Cost:** about 5 seconds per question at 5,000 documents, against 0.2 at 50. Most of the time goes on looking up names in
  the question: one regular expression for each of about 8,000 aliases. The code stays frozen; the time is reported.
- **The bank:** about 110 MB for each of the two banks, built in about 15 seconds with a warm disk.

**The changed copy and the single-writer reruns are left out.**
- The changed copy cannot be made at 5,000 documents: it must rename about 4,000 people and has 560 new names.
- The single-writer reruns would re-ask the same questions in other wordings, which says nothing about size.

**A dry run of the whole pipeline on `mt5k`** checked every step: the draw's filters, the small set, both banks, every arm and
the score. Its numbers are in `docs/benchmarks/factbank_5k/dry_run.json`. They come from a seen set and are not results.
- **Every step ran,** and every picked question reproduced its expected answer on the small set.
- **The hash-seed check changed no answer.**
- **v13 scored 1.000 on the small bank and 0.937 on the 5,089-document bank,** so rule 1 would not have been met there.
- **The whole difference was three questions in one wording:** "When is the ticket linked to pull request #N due? I need the
  deadline date for the status email."
  - The bank reads "email" as asking for an answer from Gmail.
  - At 5,089 documents there are Gmail messages about the ticket, so the plan ends there. At 50 documents there are none, and
    the check that would act is skipped.
- **This is a real way size can cost accuracy, and it stays in the test.** The wordings and code are not changed to avoid it.
  The test set may or may not draw that wording.
- **Timing:** the arms ran up to seven at a time on four cores. v13 took a median of 11.8 seconds per question at 5,089
  documents, against 0.45 on the small bank.

## Known limits

- **One draw, one fictional company, 50 questions.** The questions share documents, so they are fewer than 50 independent
  checks.
- **The small bank has no unrelated documents at all.** The 50-document banks of earlier tests were similar.
- **Setting questions aside removes some real hazards** from the decisive score, such as people with Jira tickets. They are
  reported, strict and lenient.
- **The 2 to 4 window:** a person is asked about only if they have 2 to 4 Linear issues in the set, as before. The busiest
  people are never asked about.
- **The time per question** was measured on a shared 4-core machine, with several arms running at once.

## The review before freezing

Three reviewers checked the code, the run and the protocol, and a fourth tried to refute each finding
(`docs/benchmarks/factbank_5k/prefreeze_review_a.json`). What held up, and what was done:

1. **Second readings through links were missed.** The bank follows links both ways, so a ticket linking *to* the named ticket
   is a second answer. The review found 0 or 1 such picked question per draw. **Fixed:** the "linked" reason.
2. **Odd keys** could make an expected answer unscoreable, or stop the draw. **Fixed:** they are not drawn, and the compare check
   is guarded.
3. **v12's time on the 5,000-document bank included the small model's calls,** and peak memory was not reported. **Fixed:** the
   forms are made before any timed run, and peak memory is reported.
4. **One person could carry several questions across kinds.** **Fixed:** the pick prefers new documents across kinds, and the
   changes are reported grouped by document.
5. **Rules 3 and 5 had no stated consequence.** **Fixed** above.
6. **The script did not check that the small model was running,** and would stop if no question was set aside. **Fixed.**
7. **Wording:**
   - Jira due dates;
   - the planted pairs' pool;
   - "held-out" for sets known from development;
   - the reference for rule 2.

   **Fixed.**

## Frozen

| what | value |
|---|---|
| code | the commit that removes the draft line from this document |
| the run script | `docs/benchmarks/factbank_5k/run_5k.sh` |
| seeds | documents 53, questions 54, hash seed 0 (check: 1) |
| lessons, glossary, form, wordings | as listed above |
