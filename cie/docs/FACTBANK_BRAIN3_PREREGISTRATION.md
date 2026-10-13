# The company brain, round 3 (v17): fixed before the test

**DRAFT: not frozen.** The freeze is the commit that removes this line.

I wrote this on 2026-10-13:
- **after** building v17 on training documents and checking it on development documents and on round 2's spent test set
  (below);
- **before** drawing the test documents or writing a single test question.

The results go in `docs/FACTBANK_BRAIN3_RESULTS.md`. All data is fictional: the benchmark's made-up company.

## Why

Round 2 (`docs/FACTBANK_BRAIN2_RESULTS.md`) found v16 weakest on questions that describe a document instead of naming it
("the PR that added the latency metric"): 0.500, against 0.750 for the older v2. A check after that run found the cause:
- **v16 rarely found the described document.** Its planner joined on the wrong one, or its coverage check gave up.
- **Plain BM25 search found it almost every time:** 39 of the 40 test questions, and all 20 that v16 missed.

**The claim:** letting BM25 pick the described document, and v16's own engine read the answer from it, answers more of these
questions without harming any other kind.

## What v17 is

v17 is v16 with one more route, **described** (`cie.factbank.brain.Brain.described`, `Brain(..., v17=True)`). With v17 off,
v16 gives the same answers as before.

**When it runs.** It runs only when all of these hold:
- v16's earlier routes (not found, history and messages of a named document, counts and lists) did not answer;
- the router says the question asks for a fact, not free text;
- the question names no document: no ticket key, no pull request number, no quoted title, no unquoted title v16 recognises
  (`Records.named_docs` is empty);
- the question does not ask for several things: a list, a count, keys, "every", "all", or a plural item noun ("tickets",
  "PRs", "pages"…) (`DESCRIBED_SKIP`, and v1's `LIST_RE`);
- it does not ask for an order over several documents ("which one is due first", "the first issue Marco has due", "A vs
  B": `DESCRIBED_ORDER`).

**What it does:**
1. **The document:** the one whose passage BM25 ranks first. It uses the free-text route's index: passages of 600–1,000
   characters, titles weighted 2.5.
2. **The check:** that document's stored text must hold at least **0.68** of the question's words, each weighted by its
   rarity (the free-text route's `coverage`). Below that, the question is left to v16's routes, as before.
   - A question about a document the company does not have usually finds only a near one, which holds less.
   - 0.68 is the training fit: the highest threshold that still keeps 95% of the 110 training descriptive questions whose
     gold document BM25 ranks first (0.687, rounded down).
3. **The answer, from that document,** the first of these that applies:
   - its history or messages, as the derived route answers them about a named document; a date never answers "who";
   - "not found" when the asked field is empty there, as the absent route says it;
   - for a "what" or "which" question (not "when", "who" or "whose"): the field named in the five words from the first
     "what" or "which" on, when one of the document's fields stands out there (`Records.relevance` at least 1.0 and ahead of
     the next). The rest of the question describes the document, and its words name fields too ("the customer's bug
     about…");
   - otherwise v1's engine, seeded with that document alone, reads the answer with the lessons and v16's fixes (a "when"
     reads only dates, a "who" only people).
   - When the engine finds nothing, v16's routes answer.

The route answers with the same row as every other route. Its journal records the document, the coverage and the threshold.

**What was tried and dropped** (on the development data below):
- **v1's engine alone** for every question. It reads the wrong field of the right document for many "what/which"
  questions: the attendees for "which customer was on that call", the priority for "which project is it filed under".
- **A field matcher alone,** or over the whole question. It read the wrong field for "when" questions ("team" for "when was
  the team's doc created") and for descriptions that name fields ("the customer's bug"). On training's 50 "what/which"
  descriptive questions, the five-word head with the engine behind it was right on 45, the whole question on 43, the engine
  alone on 34.
- **Two other coverage measures** (v16's fact-route weights, with and without chat filler). On round 2's set they fired on
  36–37 of 40 descriptive questions, but on 7–9 of 83 held-out ones, against 35 and 2 for the measure kept.
- **Also running when the router says free text,** when the question names the field read. That fired on genuine free-text
  questions ("what did BillMinder's legal team need…" read the "team" field). On development, free text fell from 0.777 to
  0.560.
- **Skipping only questions that name exactly one document.** Questions comparing two keys ("ENG-1 vs PM-2, which is due
  first?") and a person's first-due issue then got one document's date: 7 answers lost on four of the multi-document
  guard sets. With the skips above, none of those sets changes.

## The documents

- **5,000 documents of the test zone** (seed 1009), drawn by `brain2_draw draw` as in round 2. None of them is in round 1's
  test set (`brain/test5k`) or round 2's (`brain2/test5k`).
- Pull request → Linear issue pairs are planted as in round 2.
- **The held-out documents** (seed 1013) are test-zone documents in none of the three test sets.
- **The small control:** the same questions on a set holding only their gold documents.

## The questions

The kinds and checks are round 2's, with more descriptive questions and fewer free-text ones (free text is not what v17
changes):

| family | what | how many |
|---|---|---|
| single | round 1's single-document kinds, 20 embedded field questions, and up to 90 writers' descriptive questions | about 180 |
| multi | round 1's multi-document kinds and round 2's two-document kinds | 56 |
| prose | free text, written by blind writers | up to 50 |
| not_found | invented keys, numbers, titles and names | 20 |
| counts | as round 2 | 40 |
| history | as round 2 | 40 |
| email_chat | as round 2 | 40 |
| unanswerable | writers' questions about held-out documents, and 20 about a field the named document leaves empty | about 100 |

**The writers and rewriters are round 2's sessions, sealed** (`docs/benchmarks/brain2/writers_test2.js`,
`rewriters_test2.js`):
- The writers write descriptive, free-text and held-out questions in a casual style, from packets of the test documents.
- The rewriters reword every generated question the way people type.
- Both write straight to files and return counts. Nobody reads a question until the scores are written.

The packets:
- 100 descriptive (seed 1011), up to 90 kept;
- 60 free text (seed 1012), up to 50 kept;
- about 90 held-out (75 documents, seed 1013).

**Two sets on the same 5,000 documents, as in round 2:**
- **the messy set,** which decides the rules: the writers' questions and the generated questions in the rewriters' words;
- **the tidy set,** reported beside it.

## The arms

- **v17** (`brain2_test ask --arm v17`) and **v16** (`--arm v16`), with round 2's frozen lessons and router.
- **v1, v2 and plain search with quotes,** for reference.
- v13 and v15 are not asked: round 2 showed where they stand, and they take most of the run's time.
- **v17 again under hash seed 1** (`v17_seed1`, messy set).

## How it runs

1. `docs/benchmarks/brain3/run_brain3_1.sh`: the draw and the packets.
2. The writers (`brain2/writers_test2.js`), sealed.
3. `docs/benchmarks/brain3/run_brain3_2.sh`:
   - the writers' questions are checked and converted;
   - the questions are drawn (seed 1010) and the small set written;
   - the banks are built;
   - the rewriters' batches are written.
4. The rewriters (`brain2/rewriters_test2.js`), sealed.
5. `docs/benchmarks/brain3/run_brain3_3.sh`, with `SET=messy` and then `SET=tidy`:
   - the arms answer, three at a time;
   - `brain3_test score` scores the set, with the rules on the messy set.

Every step prints counts, hashes, batch names and scores only. Errors go to a file next to the work folder. A writer or
rewriter batch that is missing or incomplete is written again by a new sealed session, as in round 2.

## Rules

All on the messy set (`cie.eval.brain3_test.preregistered3`). Each compares v17 with v16, asked in the same folder:

| | rule |
|---|---|
| 1 | **Descriptive questions:** v17 ≥ v16 + 0.10 |
| 2 | **Single-document family:** v17 ≥ v16 + 0.03 |
| 3 | **No harm:** on each of the other seven families, v17 ≥ v16 − 0.03 |
| 4 | **No answer in the haystack:** v17 ≥ 0.70 on the unanswerable questions |
| 5 | **False "not found":** v17 says it to at most 0.05 of the answerable questions |
| 6 | **Not worse overall:** v17's mean over the eight families ≥ v16's |
| 7 | **It holds at size:** for single, multi and free text each, v17 at 5,000 documents ≥ the small set − 0.05 |

**The claim is met when rules 1 to 6 are met.** Rule 7 is reported; a failure is diagnosed.

**How to read differences:**
- With 90 descriptive questions, one question moves that score by 0.011.
- One question moves a 40-question family by 0.025, so rule 3 allows one net loss there.
- v17 minus v16 is reported per family with its 95% bootstrap interval, with the questions that got better and worse.

## Development

v16 and v17 in the same process on every question (`docs/benchmarks/brain3/development/`, the script `compare.py`):

| set | questions | descriptive v16 → v17 | single v16 → v17 | all v16 → v17 | better / worse |
|---|---|---|---|---|---|
| training (train5k, built on) | 622 | 0.819 → 0.905 (116) | 0.888 → 0.913 | 0.868 → 0.884 | 12 / 2 |
| development (dev5k_q2) | 443 | 0.750 → 0.861 (36) | 0.878 → 0.910 | 0.913 → 0.922 | 4 / 0 |
| round 2's test, messy (seen) | 579 | 0.500 → 0.700 (40) | 0.736 → 0.797 | 0.782 → 0.801 | 13 / 2 |

- **No other family changes on development.** On round 2's set, history and unanswerable rise by one question each:
  - history: 0.850 → 0.875;
  - unanswerable: 0.825 → 0.854. Two-word account names that v16 did not find get the empty-field "not found".
- **On round 2's set, not found falls by one question** (0.900 → 0.850). An invented Confluence title, unquoted, finds a near
  page that covers 0.69 of the question.
- **The four answers lost:**
  - on training, a project and a forecast month read from the wrong document;
  - on round 2's set, the invented title above, and a "who created" answered by v1's engine with a date.
- **The 14 guard sets** (698 questions):
  - 12 do not change;
  - b5ksmall gains 3;
  - b5kfb50 gains 1 and loses 2: a "which draft document … was last…" read from one document, and an action item's due
    date one day off.
- **Time:** the described route adds the passage index, which v16's free-text route already builds, and one search a
  question.

The development set's casual descriptive questions are round 2's test questions, already seen, so the 0.700 there is
optimistic.

## Disclosures

- **Round 2's test set is development data here.** Its 40 casual descriptive questions and 83 held-out questions guided
  v17's design:
  - which coverage measure;
  - leaving free-text routing alone;
  - skipping lists.
  
  The threshold itself was fitted on training documents only. Round 3's documents are fresh, so its test is not affected.
- **The writers' prompt and checks are round 2's,** unchanged, including the "remind me" fix made before round 2's freeze.
- **v17 changes nothing else in v16.** Every v16 route runs as before when the described route does not answer.

## Known limits

- **One fictional company,** 5,000 documents. The descriptive questions are written by language-model writers, not by
  people.
- **BM25 matches words, not meaning.** A description in words the document does not use is not found. The coverage check
  then leaves it to v16.
- **The described route answers from one document.** A question about a pair of documents, or a person's several, is left
  to v16 (by the plural and list check), and a question that slips past that check gets an answer from one document.

## The review before freezing

⟨TBD⟩

## Frozen

⟨TBD⟩
