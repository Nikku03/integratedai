# The company brain, round 4 (v18): fixed before the test

I wrote this on 2026-10-15 and froze it on 2026-10-16:
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

**The claim:** v18's fixes bring not found and counts to at least 0.95 (and not below v17) and raise unanswerable and free
text, without harming the other four families, with false "not found" on at most 0.05 of the answerable questions (and at
most 0.01 more than v17), and without longer free-text answers.

## What v18 is

v18 is v17 with the fixes below (`Brain(..., v18=True)`; `cie.factbank.brain`, `records`, `prose`). With v18 off, v17 gives
the same answers as before.

**1. Not found: a title made of two real ones** (`Brain.spliced`). A question that writes, quoted or not:
- the start of one real document title: at least 0.4 of its words (`SPLICE_SHARE`), holding at least two of its content words
  (one for a title of two content words or fewer; a content word has three letters or more and is not a word of asking or a
  stop word, so "replace the" is not the start of "Replace the badge printer"),
- followed at once by the end of another, by the same measure,
- where no one title has both (that is a real title with words left out),
- and the bank writes the two together nowhere,

is "not found" (route not_found). The benchmark invents titles this way (the first half of one title and the second half of
another); a made-up title of new words is still caught only by the older checks (unknown names, quoted titles).

**2. Counts asked the way people type** (`Records.v18`):
- "# of…", "num of…", "nums of…" and "no. of…" are read as "number of" (`records.COUNT_SAYS`); "count the pages…" (a "count"
  opening the question or a clause, or after "pls", "can you" and the like, before an item noun) asks for a count, while
  "which tickets count as open?" still asks for keys;
- a lead-in clause, set off by a comma, a semicolon, a colon, a dash (a hyphen with spaces around it, or an en or em dash) or
  brackets, before the clause that asks, that
  holds no field value, no item or system noun, no "not", no "open" and no number, is an aside whose words need not be
  explained ("for the board deck, how many…", "fyi prepping for a review - how many…"); a clause after the ask is still read
  as a condition;
- "by" before a person names the author, creator, owner or reporter (`records.BY_ROLES`, which also holds redwood_owner) when
  the person fills several fields ("pages by Aisha Patel");
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
  stem; nor one slip of a letter from one; nor chat shorthand). A term counts as written when the document writes it as a word,
  by its stem, without a plural "s", or as two or three of its words written together ("KVCache" for "KV cache"). Words with
  digits are left out ("p95", "sev2", "6wk": documents write them in too many ways). "tmrw", "tmr", "tho", "cuz", "lmk", "wrt" are read as chat shorthand.

**4. Free text: the quote** (`cie.factbank.prose.quote_v18`). The route still quotes one document, the one v16 picks, and
still decides whether to answer as v16 does (v16's quote, `quote_cov` below 0.47 is "not found"). When it answers, v18
quotes:
- **the parts of the question:** the question is cut at clause breaks before a question word ("…, and how much…", "— what…");
  a question word opens a part when only words of asking and chat come before it in its clause, or a verb of knowing or
  telling is among the three words before it ("can someone remind me what…"); the other words describe the document;
- **each part's best sentence first,** then the best sentences overall, each with the sentence after it, as v16 did;
- **weights:** a word's rarity among the document's sentences; the words that describe the document, and the words of the
  document's title, weigh 0.3 (`DESC_WEIGHT`); words of asking and chat weigh nothing;
- **the asked kind:** a sentence holding a value of the kind a part asks for (a date for "when", a number for "how much",
  a person for "who", a ticket key, a flag or setting), a whole value the question does not write, gains 0.3 (`KIND_BONUS`);
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
| unanswerable | writers' questions about held-out documents, and 40 about a field the named document leaves empty | about 135 |

**The writers and rewriters are round 2's sessions, sealed** (`docs/benchmarks/brain2/writers_test2.js`,
`rewriters_test2.js`), as in round 3:
- The writers write descriptive, free-text and held-out questions in a casual style, from packets of the test documents.
- The rewriters reword every generated question the way people type.
- Both write straight to files and return counts. Nobody reads a question until the scores are written.

The packets: 60 descriptive (seed 1021, up to 50 kept); 100 free text (seed 1022, up to 80 kept); about 120-130 held-out
(`--n 100` is a target: 1.4 × 100 = 140 documents are examined, and those that pass the checks become packets; the dry run on
the development zone gave 119), seed 1023.

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

All on the messy set (`cie.eval.brain4_test.preregistered4`), with v17 asked in the same folder. Rules 1 and 2 set a level and
forbid a fall; rule 6 sets a ceiling and a rise; rules 3, 4, 5, 7 and 8 compare with v17:

| | rule |
|---|---|
| 1 | **Not found:** v18 ≥ 0.95 and ≥ v17 |
| 2 | **Counts:** v18 ≥ 0.95 and ≥ v17 |
| 3 | **Unanswerable:** v18 ≥ v17 + 0.03 |
| 4 | **Free text:** v18 ≥ v17 + 0.04 |
| 5 | **No harm:** on each of single, multi, history and email and chat, v18 ≥ v17 − 0.03 |
| 6 | **False "not found":** v18 says it to at most 0.05 of the answerable questions, and at most v17's + 0.01 |
| 7 | **Better overall:** v18's mean over the eight families ≥ v17's + 0.02 |
| 8 | **No longer free-text answers:** v18's mean free-text answer length ≤ 1.05 × v17's |
| 9 | **It holds at size** (reported): for single, multi and free text each, v18 at 5,000 documents ≥ the small set − 0.05 |

**The claim is met when rules 1 to 8 are met.** Rule 9 is reported; a failure is diagnosed.

**How to read differences:**
- One question moves the 40-question not-found family by 0.025: rule 1 allows two questions' worth of score lost.
- One question moves the 60-question counts family by 0.017: rule 2 allows three. A filtered list scores its key F1, so a
  partly right list counts in part.
- One question moves single (about 140) by 0.007, multi (56) by 0.018, history and email and chat (40) by 0.025, and
  unanswerable (about 135) by 0.007: rule 5 allows about four net losses on single and one on each of the others; rule 3 needs
  about four net gains; rule 6's rise of 0.01 is about four questions of about 416 answerable ones.
- **The leads are demanding.** On the sets v18 was not built on, the gains were: unanswerable +0.028 (dev5k_q2, tidy wording);
  free text +0.050 (dev5k_q2) and +0.043 (train5k); the mean over the families +0.010 (dev5k_q2). On the messy sets it was
  built on they were about twice as large. Rules 3, 4 and 7 can therefore fail even if v18 is as good as its unseen
  development sets show; with about 80 free-text questions the paired standard error is about 0.03.
- v18 minus v17 is reported per family with its 95% bootstrap interval, with the questions that got better and worse.

## Development

v17 and v18 in the same process on every question (`docs/benchmarks/brain4/development/`, the script `compare.py`), with the
code frozen below. The last change (the splice check's content words, after the review) touched only the splice check; it was
checked on every set's questions by `probe_nf.py` (`probe_splice.log`), where it fired on no answerable question and on one more
not-found question of round 2's set, whose row was asked again.

| set | questions | not found | counts | unanswerable | free text | mean of 8 families (rule 7) | false "not found" | better / worse |
|---|---|---|---|---|---|---|---|---|
| round 3's test, messy (seen) | 517 | 0.800 → 1.000 | 0.825 → 1.000 | 0.880 → 0.946 | 0.750 → 0.830 | 0.859 → 0.924 | 10 → 12 of 405 | 25 / 1 |
| round 3's test, tidy (seen) | 518 | 1.000 → 1.000 | 1.000 → 1.000 | 0.913 → 0.946 | 0.750 → 0.830 | 0.937 → 0.951 | 5 → 5 of 406 | 11 / 1 |
| round 2's test, messy (seen) | 579 | 0.850 → 1.000 | 0.775 → 1.000 | 0.854 → 0.913 | 0.666 → 0.771 | 0.837 → 0.905 | 17 → 17 of 456 | 46 / 5 |
| development (dev5k_q2) | 443 | 1.000 → 1.000 | 1.000 → 1.000 | 0.887 → 0.915 | 0.777 → 0.827 | 0.938 → 0.948 | 1 → 1 of 352 | 7 / 1 |
| training (train5k) | 622 | – | – | – | 0.697 → 0.740 | – | 10 → 10 of 622 | 15 / 6 |
| messy samples (dev 80, train 116) | 196 | 0.800 → 1.000 (5) | 1.000 → 1.000 (35) | 0.778 → 0.889 (9) | – | – | 3 → 3 of 182 | 2 / 0 |

- **No other family changes on any set,** except one more single-document question right on round 2's set.
- **Every answer that got worse is a free-text quote** (14 in all): v18 picked another sentence, and an answer fact moved
  out. On the same sets 63 free-text answers got better.
- **False "not found":** two more on round 3's messy set, both a "single" question v17 also got wrong (an action item's due
  date), now refused by the check of plans from a named person.
- **The 14 guard sets** (698 questions): none changes.
- **The free-text answers are as long as v17's** (round 3's set: 1,054 characters on average both; `prose_quote.log`).
- **Time:** v18 answers in the time v17 does (the same median, question by question in the same process); the splice check
  takes 0.2 seconds for 517 questions.

**How the quote's weights were chosen.** On training's 111 free-text questions alone (`prose_grid_train5k.log`), the settings
tried (description weight 0.15–1.0, kind bonus 0–0.5, title words weighed down or not) were within 0.03 of each other (0.730–
0.757) once the description weighed less than 1.0; training's best had title words not weighed down (0.757 against 0.740).
Pooled over the four development sets (`prose_grid_pooled.log`, 361 questions), weighing them down was better (0.805 against
0.792), and it was kept, with 0.3 and 0.3.

**Most of the development questions are seen.** Round 3's set is the one whose misses v18 was built on, so its numbers are
optimistic; round 2's guided the free-text work too.

## Disclosures

- **Round 3's test set is development data here,** and so are round 2's. Their questions guided every fix above; the fixes
  were built on round 3's misses. Round 4's documents are fresh, so its test is not affected.
- **The splice check follows the benchmark's own way of inventing titles** (`brain_questions.missing_titles`: the first half
  of one title and the second half of another). It catches a title made of two real ones; a made-up title of new words is left
  to the older checks. Ten of the test's 40 not-found questions are such titles.
- **The quote's weights were chosen on pooled development sets that include rounds 2's and 3's test sets,** against
  training's own best (`prose_grid_pooled.log`).
- **The word lists were fitted to the same sealed writers and rewriters** that write the test's questions (round 2's
  sessions): the chat shorthand, the asides, "can someone", "on someone's plate". A test written by other people could word
  things otherwise.
- **v18 changes nothing else in v17.** Every v17 route runs as before when a v18 fix does not apply.

## Known limits

- **One fictional company,** 5,000 documents. The writers and rewriters are language models, not people.
- **No language model answers:** free text is still a quote of sentences, not a written answer.
- **The own-terms check is a word check.** A question about something the company has, in words its document does not use,
  can be refused; a question about something it lacks, in words a near document uses, can still be answered.

## The review before freezing

Three reviewers read this document, the v18 code (the diff since round 3's results, `511f5a5`), the round-4 scoring and the run
scripts; a skeptic then tried to refute each finding. They were not allowed to open any data. They ran the unit tests, `bash -n`
and their own checks on the unit tests' tiny made-up bank.

**Confirmed:**
- with v18 off, v16 and v17 give byte-identical rows to `511f5a5` on 153 questions of the tiny bank, alone and with a v18 brain
  asked first in the same process (as `compare.py` runs them);
- nothing crashes on empty, punctuation-only, quoted, unicode or very long questions; the splice check is bounded;
- "What v18 is" matches the code item by item, except for the findings below;
- the harness wiring (arm v18, its answers file, `--v18`) is consistent.

**Found and fixed** (in the code before the freeze, then the development runs above were done again):
1. **"num of…" and "no. of…" were read as counts but never answered:** the counting step found "num" and "no" unexplained.
   **Fixed:** they are read as "number of" (`COUNT_SAYS`), with tests.
2. **"count" as a verb turned a list question into a number** ("which tickets with priority P1 count as open tickets?").
   **Fixed:** "count" asks for a count only when it opens the question or a clause, or follows "pls", "can you" and the like.
3. **The splice check refused "when do we need to replace the wifi keys?"**: "replace the" counted as half the start of
   "Replace the badge printer". **Fixed:** each part must also hold two of its title's content words (one for a short title).
   A first fix, the shares over content words only, missed a made-up title on round 2's set ("cycle surge & rebalance —
   dynamic staffing sizing for weights, KV, and activations"), whose first half held few content words; it was replaced.
4. **The asked-kind bonus compared single digits** with the question ("20%" was not new to a question about 2026). **Fixed:**
   whole values are compared.
5. **A term written joined ("KVCache") was refused against a document writing "KV cache".** **Fixed:** two or three of the
   document's words written together count.
6. **Rules 1, 2 and 6 did not test the claim as first written** ("raise all four families", "without more false 'not
   found'"): they set levels only. **Fixed:** rules 1 and 2 also forbid a fall below v17, rule 6 also limits the rise to 0.01,
   and the claim says so.
7. **The document's wording and numbers:** the roles "by" names (the reporter too), "among the three words before", the
   dashes, the held-out and unanswerable sizes (about 135, not 120), the quote grid's spread (0.730–0.757, within 0.03), the
   development table's "all" column (a mean over questions, not rule 7's mean of the families: both are now shown), the
   missing false "not found" counts, the reading of the leads (they can fail even if v18 is as good as its unseen sets show),
   and the missing frozen table. **Fixed** in the text.
8. **The "by a person" rule had no real test.** **Fixed:** a test bank where one person fills two role fields.

**Disclosed, not changed:** the word lists were fitted to the same sealed writers and rewriters the test uses; the splice check
follows the benchmark's own title generator; the quote's title weighting was chosen on pooled sets that include rounds 2's
and 3's test sets.

**The rehearsals:**
- step 5 (`run_brain4_3.sh`, both sets) on a copy of round 3's rehearsal folders (241 questions): every arm answered, both sets
  were scored, the rules were applied, the hash-seed check found no difference, and the error file stayed empty. The size rule
  gave no result there, because that small folder holds other questions; the test's small folder holds the same ones;
- step 1 (`run_brain4_1.sh`) on the development zone, then the question draw with the round-4 mix: 60 descriptive and 100
  free-text packets, 119 held-out packets; 40 not-found questions (10 of each invented kind), 60 counts, 40 empty-field
  questions, 40 history and 40 email and chat questions were all filled.

## Frozen

| what | value |
|---|---|
| code | the commit that removes the draft line from this document |
| v18's constants | `SPLICE_SHARE` 0.4; `DESC_WEIGHT` 0.3, `KIND_BONUS` 0.3, `TITLE_DOWN` on, `QUOTE_CAP` 1,100; `CHAT_WORDS_V18`; `PLATE_WORDS`; v16's `COVER_BELOW` 0.57 and `ABSTAIN_BELOW` 0.47 and v17's `DESCRIBED_BELOW` 0.68 kept |
| the rules' thresholds | `cie.eval.brain4_test`: 0.95, 0.95, +0.03, +0.04, −0.03, 0.05 and +0.01, +0.02, 1.05; size −0.05 |
| v17's and v18's lessons | `docs/benchmarks/brain2/lessons/`: `single_lessons.json` (`ee8b9d053405a47f…`), `plan_lessons.json` (`4c2c8c6201be08ec…`), `router.json` (`20e9c05046406f14…`) |
| v2's lessons | `fb50/lessons.json` (`afa4e7d9fee0a05c…`) |
| ordinary English words | `src/cie/factbank/data/general_words.txt.gz` (`f36d409bb74a8a4b…`) |
| zones | `zones.json.gz` (`b1afac237c309a82…`) |
| seeds | test draw 1019, questions 1020, packets 1021 and 1022, held-out 1023, none used before; hash seed 0 (and 1 for the check) |
| run | `docs/benchmarks/brain4/run_brain4_1.sh`, `brain2/writers_test2.js`, `run_brain4_2.sh`, `brain2/rewriters_test2.js`, `run_brain4_3.sh` (`SET=messy`, then `SET=tidy`) |
