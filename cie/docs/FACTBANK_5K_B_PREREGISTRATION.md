# The fact bank at 5,000 documents, part B: the fact bank against the memory bank, fixed before the test

> **Draft, under review:** the design is frozen only by the commit that removes this line.

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
- It is the only haystack where owner questions with checkable answers exist. All 100 of the benchmark's metadata questions
  have their gold documents there.
- **It is a set I had seen, for both systems.** The memory bank's search was developed on it, and the fact bank's first test
  drew from it. That is disclosed, not hidden: no part of either system changes for this test.

## Questions

**Primary: 50 new questions** (`factbank_5k_b.draw_questions`, seed 61):
- **The first test's mix:**
  - 26 owners;
  - 10 Linear due dates and 8 meeting action items;
  - 6 lists.
- **Each part is a seeded sample of the memory test's checkable questions that no earlier test used.** The fb50, fbtest and
  mt50 questions are left out.
- **Ten list questions are left out as flawed:** their expected list misses a real item, because the item's key is reused on
  another document.
- **The lists cannot match the first test's kinds.** Only 2 unused pull-request lists remain, so the lists will be mostly
  Linear and Jira.

**The control for the primary questions:** the same 50 questions on a small set holding only their gold documents. It has
its own memory bank, plain index and fact banks. The difference between the two is the effect of the other 5,000 or so
documents.

**Secondary: the first test's own 50 questions** (fb50) on the 5,089 documents: literally "the same test". Its control is the
first test's 50-document run, collected again with today's code. The memory bank, retrieval and memory-test code have not
changed since that run.
- **The re-collected control is compared with the original run's evidence,** and every difference is reported.
- **v2 is in-sample here:** it was trained on these exact questions.

## How it runs

The script is `docs/benchmarks/factbank_5k/run_5k_b.sh`. It runs after part A, on an idle machine.
- **A new database at the current schema for each size,** so each size's memory bank is alone in its indexes. That matches
  the first test, whose 50-document bank was alone in its database.
- **The 5,089-document memory bank** is loaded with today's code. It reuses the embedding cache of the earlier 5,000-document
  runs: the same model and the same texts, so only the time changes.
- **Plain search** builds its passages, BM25 index and vectors before any evidence is collected.
- **The evidence is collected twice.** The first pass warms the caches; the second is scored. Any difference in the bank's
  evidence between them is reported.
- **Searches that give up on a time limit are counted.** The bank's search gives up silently, logged only at debug level, so
  the run counts every give-up.
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
  - On today's schema, a design probe puts the fact bank at about 0.58 to 0.64 of the bank's storage at 5,000 documents.
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
- the checks: bank errors, give-ups, missing evidence, the bank's evidence collected twice, and the control against the
  original run;
- for each question, how many other documents carry the answer's text (`chance`).

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
