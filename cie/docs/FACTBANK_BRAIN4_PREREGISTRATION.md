# The company brain, round 4 (v18): fixed before the test

**Draft: not frozen.** The freeze is the commit that removes this line.

I wrote this on 2026-10-15:
- **after** building v18 and checking it on development data: earlier rounds' training, development and spent test sets
  (below);
- **before** drawing the test documents or writing a single test question.

The results go in `docs/FACTBANK_BRAIN4_RESULTS.md`. All data is fictional: the benchmark's made-up company.

## Why

Round 3 (`docs/FACTBANK_BRAIN3_RESULTS.md`) left four kinds of question short of right, on its messy set:

| family | v17 | what went wrong |
|---|---|---|
| not found (names a document the company does not have) | 0.800 | 4 made-up titles, written without quotes, answered from a similar real document |
| counts | 0.825 | casual wordings ("# of…", "for the board deck, how many…") slipped past the counting step; a name was given instead |
| unanswerable (the answer is in no document) | 0.880 | the free-text route quoted a document about something else; two answers read another field |
| free text | 0.750 | the right document, the wrong part quoted; two-part questions got one part |

On the tidy wordings, not found and counts were both 1.000: the casual wording caused the misses.

**The claim:** v18's fixes raise all four families, without harming the other four, without more false "not found" and
without longer free-text answers.

## What v18 is

v18 is v17 with the fixes below (`Brain(..., v18=True)`; `cie.factbank.brain`, `records`, `prose`). With v18 off, v17 gives
the same answers as before.

**1. Not found: a title made of two real ones** (`Brain.spliced`). A question that writes, quoted or not:
- the start of one real document title (at least 0.4 of its words, `SPLICE_SHARE`),
- followed at once by the end of another (at least 0.4 of its words),
- where no one title has both (that is a real title with words left out),
- each part holding a word of three letters or more that is not a word of asking,
- and the bank writes the two together nowhere,

is "not found" (route not_found). The benchmark invents titles this way (the first half of one title and the second half of
another); a made-up title of new words is still caught only by the older checks (unknown names, quoted titles).

**2. Counts asked the way people type** (`Records.v18`):
- "# of…", "num of…", "no. of…" and "count the pages…" (a "count" before an item noun) ask for a count;
- a lead-in clause, set off by a comma, a semicolon, a colon, a spaced dash or brackets, before the clause that asks, that
  holds no field value, no item or system noun, no "not", no "open" and no number, is an aside whose words need not be
  explained ("for the board deck, how many…", "fyi prepping for a review - how many…"); a clause after the ask is still read
  as a condition;
- "by" before a person names the author, creator or owner when the person fills several fields ("pages by Aisha Patel");
- "both", "his", "her", "him", "he", "she" are filler.

**3. No answer in the haystack:**
- the empty-field check (`Records.absent`, route absent) also runs when the router says free text, when the question names
  one document ("what's the crm deal id for the meeting X?");
- "can someone remind me…", "does anyone know…" are not links to another document (`records.ASK_SOMEONE`);
- a plan that starts from a person the question names and reads one value is checked on the documents it reaches, as other
  plans are (`Brain.cover_step`, `COVER_BELOW` 0.57 unchanged), without the person's name, the words of chat and "on someone's
  plate"; "when did the xactly ai demo with samir patel get scheduled?" is "not found" when none of the documents the plan
  reaches is about it. A count, a list or an order over the person's documents is not checked;
- a free-text answer whose document does not write the question's own terms is "not found" (`Brain.unheld_terms`). The own
  terms: each word of a run of two or more capitalised words inside the sentence ("Argentum Health"), and each word or part
  of a hyphenated or slashed term, of letters only, that is not ordinary English (round 1's general lexicon, a word or its
  stem; nor one slip of a letter from one; nor chat shorthand). Words with digits are left out ("p95", "sev2", "6wk": documents
  write them in too many ways). "tmrw", "tmr", "tho", "cuz", "lmk", "wrt" are read as chat shorthand.

**4. Free text: the quote** (`cie.factbank.prose.quote_v18`). The route still quotes one document, the one v16 picks, and
still decides whether to answer as v16 does (v16's quote, `quote_cov` below 0.47 is "not found"). When it answers, v18
quotes:
- **the parts of the question:** the question is cut at clause breaks before a question word ("…, and how much…", "— what…");
  a question word opens a part when only words of asking and chat come before it in its clause, or a verb of knowing or
  telling just before it ("can someone remind me what…"); the other words describe the document;
- **each part's best sentence first,** then the best sentences overall, each with the sentence after it, as v16 did;
- **weights:** a word's rarity among the document's sentences; the words that describe the document, and the words of the
  document's title, weigh 0.3 (`DESC_WEIGHT`); words of asking and chat weigh nothing;
- **the asked kind:** a sentence holding a value of the kind a part asks for (a date for "when", a number for "how much",
  a person for "who", a ticket key, a flag or setting), one the question does not write, gains 0.3 (`KIND_BONUS`);
- **the same length:** at most 1,100 characters with labels (`QUOTE_CAP`, v16's cap), in v16's form.

**What was tried and dropped** (development, below):
- **Quoting with v18's quote and deciding on it too.** The tighter quote held fewer of the question's describing words, so
  the coverage check said "not found" to right answers: free text fell on development (0.797 → 0.773).
- **Own terms with digits** ("p95", "geo-steer-v3"): they cost right answers whose documents wrote them otherwise.
- **Capitalised names checked as one phrase** ("NorthPoint MSA"): documents write the words apart.
- **A lowercase person-name check** for not found: no development question needed it.
- **Asides after the ask:** "how many tickets are P1, created after March?" would have counted all P1 tickets.
- **Checking every plan from a named person,** counts and orders too: "which of Marcus Chen's tickets has the soonest
  deadline?" was refused, since "soonest" and "deadline" are in none of his tickets. On round 2's and 3's sets that cost 7
  right answers for 1 right refusal.

## The documents

- **5,000 documents of the test zone** (seed 1019), drawn by `brain2_draw draw` as in rounds 2 and 3. None of them is in the
  test sets of rounds 1, 2 or 3.
- Pull request → Linear issue pairs are planted as before.
- **The held-out documents of rounds 2 and 3** (their writers' questions guided v17 and v18) are left out of the draw and of
  the held-out pool.
- **The held-out documents** (seed 1023): test-zone documents in none of the four test sets nor among the earlier held-out
  documents.
- **The small control:** the same questions on a set holding only their gold documents.

## The questions

The kinds and checks are rounds 2's and 3's, with more of the four families v18 changes:

| family | what | how many |
|---|---|---|
| single | round 1's single-document kinds, 20 embedded field questions, up to 50 writers' descriptive questions | about 140 |
| multi | round 1's multi-document kinds and round 2's two-document kinds | 56 |
| prose | free text, written by blind writers | up to 80 |
| not_found | invented keys, pull request numbers, titles and names: 10 of each | 40 |
| counts | counts and filtered lists, as round 2 | 60 |
| history | as round 2 | 40 |
| email_chat | as round 2 | 40 |
| unanswerable | writers' questions about held-out documents, and 40 about a field the named document leaves empty | about 120 |

**The writers and rewriters are round 2's sessions, sealed** (`docs/benchmarks/brain2/writers_test2.js`,
`rewriters_test2.js`), as in round 3:
- The writers write descriptive, free-text and held-out questions in a casual style, from packets of the test documents.
- The rewriters reword every generated question the way people type.
- Both write straight to files and return counts. Nobody reads a question until the scores are written.

The packets: 60 descriptive (seed 1021, up to 50 kept); 100 free text (seed 1022, up to 80 kept); about 100 held-out
(`--n 100`, seed 1023).

**Two sets on the same 5,000 documents:** the messy set, which decides the rules, and the tidy set, reported beside it.

## The arms

- **v18** (`brain2_test ask --arm v18`) and **v17** (`--arm v17`), with round 2's frozen lessons and router.
- **v1, v2 and plain search with quotes,** for reference. v16 is not asked: round 3 showed where it stands.
- **v18 again under hash seed 1** (`v18_seed1`, messy set).

## How it runs

1. `docs/benchmarks/brain4/run_brain4_1.sh`: the draw and the packets.
2. The writers (`brain2/writers_test2.js`), sealed.
3. `docs/benchmarks/brain4/run_brain4_2.sh`: the writers' questions checked and converted; the questions drawn (seed 1020)
   and the small set written; the banks built; the rewriters' batches written.
4. The rewriters (`brain2/rewriters_test2.js`), sealed.
5. `docs/benchmarks/brain4/run_brain4_3.sh`, with `SET=messy` and then `SET=tidy`: the arms answer; `brain4_test score`
   scores the set, with the rules on the messy set.

Every step prints counts, hashes, batch names and scores only. Errors go to a file next to the work folder. A writer or
rewriter batch that is missing or incomplete is written again by a new sealed session.

## Rules

All on the messy set (`cie.eval.brain4_test.preregistered4`). Each compares v18 with v17, asked in the same folder:

| | rule |
|---|---|
| 1 | **Not found:** v18 ≥ 0.95 |
| 2 | **Counts:** v18 ≥ 0.95 |
| 3 | **Unanswerable:** v18 ≥ v17 + 0.03 |
| 4 | **Free text:** v18 ≥ v17 + 0.04 |
| 5 | **No harm:** on each of single, multi, history and email and chat, v18 ≥ v17 − 0.03 |
| 6 | **False "not found":** v18 says it to at most 0.05 of the answerable questions |
| 7 | **Better overall:** v18's mean over the eight families ≥ v17's + 0.02 |
| 8 | **No longer free-text answers:** v18's mean free-text answer length ≤ 1.05 × v17's |
| 9 | **It holds at size** (reported): for single, multi and free text each, v18 at 5,000 documents ≥ the small set − 0.05 |

**The claim is met when rules 1 to 8 are met.** Rule 9 is reported; a failure is diagnosed.

**How to read differences:**
- One question moves the 40-question not-found family by 0.025: rule 1 allows two misses.
- One question moves the 60-question counts family by 0.017: rule 2 allows three misses.
- v18 minus v17 is reported per family with its 95% bootstrap interval, with the questions that got better and worse.

## Development

(To be filled from `docs/benchmarks/brain4/development/`.)

## Disclosures

- **Round 3's test set is development data here,** and so are round 2's. Their questions guided every fix above; the fixes
  were built on round 3's misses. Round 4's documents are fresh, so its test is not affected.
- **The splice check follows the benchmark's own way of inventing titles.** It catches a title made of two real ones; a
  made-up title of new words is left to the older checks.
- **v18 changes nothing else in v17.** Every v17 route runs as before when a v18 fix does not apply.

## Known limits

- **One fictional company,** 5,000 documents. The writers and rewriters are language models, not people.
- **No language model answers:** free text is still a quote of sentences, not a written answer.
- **The own-terms check is a word check.** A question about something the company has, in words its document does not use,
  can be refused; a question about something it lacks, in words a near document uses, can still be answered.
