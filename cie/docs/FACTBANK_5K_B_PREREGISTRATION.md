# The fact bank at 5,000 documents, part B: the fact bank against the memory bank, fixed before the test

I wrote this on 2026-10-10, before collecting any evidence on the 5,089-document haystack. The results go in
`docs/FACTBANK_5K_RESULTS.md`, with part A's (`docs/FACTBANK_5K_PREREGISTRATION.md`).

## Why

The first fact-bank test asked whether the fact bank's evidence holds the answer better than the memory bank's
(`docs/FACTBANK_PREREGISTRATION.md`, `docs/FACTBANK_RESULTS.md`). It did, at 50 documents. The write-up then said two things
must come first before replacing the memory bank. The first was "the same test on the 5,000-document haystack, where search
is hard", because 50 documents make finding the right one easy. **Part B is that test.**

## What is tested

**The same arms as the first test:**
- plain keyword search (`plain-words`);
- keyword plus vector search (`plain`);
- **the memory bank** (`bank`), the present system with its default search;
- **the fact bank** (v1, untrained), which the first test's rules were written for;
- for information, **the trained fact bank** (v2, the single-fact lessons `fb50/lessons.json`, `afa4e7d9fee0a05c…`).

**The same measure:** whether the expected answer is in each arm's evidence within the first 2,000, 6,000 and 24,000
characters, for owners (a document's field), deadlines and lists; and the fact bank's own answers.

**The haystack:** the memory test's 5,089 documents (`mt5k`), the haystack the first test's 50 documents came from.
- **Why this haystack:** it is the one the first test promised, it holds owner questions with checkable answers, and the
  earlier 5,000-document runs' embedding cache makes loading it cheap.
- **The unseen alternative was rejected for cost and disk.** That alternative was part A's new sample plus the gold documents
  of new owner questions. It would need about 1.5 hours of embedding and more disk than this machine has.
- **It is a set I had seen, for both systems:**
  - The memory bank's search was developed on it.
  - The fact bank's first test drew its 50 documents from it.
  - The multi-document training and test sets (v2 to v14) lie inside it.
  - Part A's dry run already ran the fact bank v1 on it, on other questions.
  - The trained fact bank (v2) learned from questions in the same wording as the primary questions.

  No part of either system changes for this test.

## Questions

**Primary: 50 new questions** (`factbank_5k_b.draw_questions`, seed 61):
- **The first test's mix:**
  - 26 owners;
  - 10 Linear due dates and 8 meeting action items;
  - 6 lists.
- **Each part is a seeded sample of the memory test's checkable questions that no earlier test used.** The fb50, fbtest and
  mt50 questions are left out, matched by what they ask (kind, expected answer and gold documents), not by id: mt50 numbers its
  questions anew.
- **The unused pools:** 47 owners, 20 Linear due dates, 12 action items and 33 lists.
- **Ten list questions are left out as flawed:** their expected list misses a real item, because the item's key is reused on
  another document.
- **The lists cannot match the first test's kinds.** Only 2 unused pull-request lists remain, so the lists will be mostly
  Linear and Jira.

**The control for the primary questions:** the same 50 questions on a small set holding only their gold documents. It has
its own memory bank, plain index and fact banks. The difference between the two is the effect of the other 5,000 or so
documents.

**Secondary: the first test's own 50 questions** (fb50) on the 5,089 documents: literally "the same test".
- **Its control is the first test's 50 documents, loaded again with today's code into a database of their own.** The
  original database now holds five other banks, which share its indexes and change the bank's graph budget.
- **The memory bank, retrieval and memory-test code have not changed since the first test.** The control's plain-search
  index is the original one.
- **The control is compared with the original run's evidence,** and every difference is reported. A difference in the bank's
  evidence would come from the new load, the database or the hash seed, not from the code.
- **v2 is in-sample here:** it was trained on these exact questions.

## How it runs

The script is `docs/benchmarks/factbank_5k/run_5k_b.sh`. It runs after part A, on an idle machine, from fresh folders and
databases.
- **A new database at the current schema for each bank:** the control, the 5,089 and the small set. Each memory bank is
  alone in its indexes, as the first test's 50-document bank was.
- **The 5,089-document memory bank** is loaded with today's code. It reuses a copy of the earlier 5,000-document runs'
  embedding cache: the same model and the same texts, so only the time changes.
- **Plain search** builds its passages, BM25 index and vectors before any evidence is collected.
- **Each load is checked.** The run stops if a memory bank is missing documents, or if its BM25 index failed to build. Without
  that index, the bank's search falls back to full text without a word. Whether the index is ready is also recorded when the
  evidence is collected.
- **The evidence is collected twice, on an idle machine.** The first pass warms the caches; the second is scored. Any
  difference in the bank's evidence between them is reported.
- **Questions cut short are collected again once.** The bank's search gives up silently on a time limit, logged only at debug
  level, so the run counts every give-up, per question.
  - Every question where the scored pass gave up or hit an error is collected once more.
  - The questions still cut short after that are reported.
  - Rules 1 and 2 are then also given without them. That only ever helps the bank, which has the time limits.
- **Python's hash seed is fixed** (`PYTHONHASHSEED=0`).

## Rules

These are the first test's rules, unchanged, on the fact bank v1, for the primary questions at 5,089 documents:

1. **Not worse at the evidence budget:** fact bank − bank ≥ −0.03 in every group, within 24,000 characters.
2. **Better near the top:** fact bank − bank ≥ +0.10 on the mean, within the first 2,000 characters.
3. **Answers without a model:** the fact bank's own answers ≥ 0.70 on the mean.
4. **Smaller:** the fact bank takes at most a third of the bank's storage. The bank is measured on today's schema, as in the
   first test: its rows plus its BM25 index.

Plus one new rule, as in part A:

5. **Its own answers hold at size:** the fact bank's own answers at 5,089 documents ≥ on the small set − 0.05.

**What decides:**
- **Replace,** as originally written: rules 1, 2 and 4 all met.
- **Stated now: rule 4 is expected not to be met.**
  - A projection, not a measurement, puts the fact bank v1 at about 0.58 to 0.59 of the bank's storage at 5,000 documents
    (v2 at 0.63 to 0.64). It is projected from the old-schema 5,000-document bank, without its stored text index and with
    16-bit vectors.
  - At 50 documents it was 0.60, also not met.
  - So "replace" is expected not to be met, whatever rules 1 and 2 show. Storage is not re-judged against a new bar here.
- **The headline is whether the evidence lead holds at size: rules 1 and 2.**
  - **Both met:** the fact bank's evidence still beats the memory bank's when search is hard.
  - **Rule 1 met, rule 2 not met:** its lead near the top does not survive size. Diagnosed question by question.
  - **Rule 1 not met:** at the full budget, the memory bank's evidence is better at 5,000 documents.
- **Rules 3 and 5** say whether its own answers hold.

**How to read differences:** one owner question moves its group by about 0.038, one deadline question by 0.056, and one list
question by up to 0.167. So rule 1's −0.03 means "no question lost" in the owners and deadlines groups.

**Also reported:**
- every arm at every budget, by group and mean, for all four folders: primary at 5,089, primary small, fb50 at 5,089, and
  fb50 at 50;
- each arm's change from its control;
- the fact bank minus plain keyword search at each budget;
- the trained fact bank (v2) on the same rules;
- time per question for each arm (median, 90th percentile, maximum), the load and build times, and storage by part;
- the checks:
  - bank errors, give-ups and the retry;
  - whether BM25 was ready;
  - missing evidence;
  - documents loaded;
  - the bank's evidence collected twice;
  - the control against the original run;
- for each question, how many other documents hold the answer by the measure's own check (`chance`), for all three 5,089 and
  small folders.

## The review before freezing

Three reviewers checked the run, the measure and the protocol, and a fourth tried to refute each finding
(`docs/benchmarks/factbank_5k/prefreeze_review_b.json`). What held up, and what was done:

1. **A failed BM25 build would have gone unseen,** and the bank would have been measured on full-text search. **Fixed:** each
   load is checked, and readiness is recorded.
2. **Give-ups and errors were only counted.** They only ever hurt the bank, and one can decide rule 1. **Fixed:** the questions
   cut short are collected again once, on an idle machine, and the rules are also given without the ones still cut short.
3. **The control's database is no longer the original's alone.** **Fixed:** the control is loaded again into its own database,
   and the difference from the original run is reported.
4. **The earlier embedding cache would have been written to through a link.** **Fixed:** it is copied.
5. **Used questions were matched by id,** which dropped 4 questions no test used. **Fixed:** they are matched by content.
6. **The `chance` count did not match the measure** (pull request numbers over-counted, written-out dates missed). **Fixed:** it
   uses the measure's own check on the text plain search indexes.
7. **Promised reports were missing:** load and build times, and the `chance` counts of two folders. **Fixed.**
8. **Rule 1 treated a missing bank group differently from the first test.** **Fixed:** it is now literally the first test's
   rule.
9. **The disclosure of what was seen was incomplete,** and rule 4's figure mixed v1 and v2. **Fixed** above.
10. **A rerun after a failure would have overwritten the first pass.** **Fixed:** the run stops if a folder already has
    evidence.

## Disclosures

- **Seen haystack.** See above.
- **A design probe already ran the untrained fact bank on the fb50 questions against all 5,089 documents.** It reported the
  answer within 2,000 / 6,000 / 24,000 characters at about 0.23 / 0.40 / 0.75, against 0.77 / 0.96 / 0.99 at 50 documents.
  - Its files were not kept, so those numbers are recalled, not results.
  - The secondary set reproduces them in this run.
  - The primary questions have not been looked at by any arm.
- **Seeds 7 and 55 were drawn during the design** to inspect the mix. The primary draw uses seed 61, never drawn before.

## Known limits

- **"Within N characters" checks that the answer's text is present, not where it came from.**
  - At 5,089 documents, many dates and names also appear in unrelated documents, so chance hits grow with size.
  - The `chance` counts show how much. Owner answers that are very common names, and deadlines, are most exposed.
- **The storage comparison leaves out the bank's indexes but counts the fact bank's,** as in the first test.
- **Timing is from a shared 4-core machine.**
- **Not covered:**
  - near-duplicate documents, which may make some owner questions ambiguous;
  - list kinds the first test never used.

## Frozen

| what | value |
|---|---|
| code | the commit that removes the draft line from this document (memory bank, retrieval and memory test code unchanged since the first test) |
| the run script | `docs/benchmarks/factbank_5k/run_5k_b.sh` |
| seeds | questions 61, hash seed 0 |
| the trained fact bank's lessons | `fb50/lessons.json` (`afa4e7d9fee0a05c…`) |
| embedding model | `BAAI/bge-small-en-v1.5` through fastembed, as in the first test |
