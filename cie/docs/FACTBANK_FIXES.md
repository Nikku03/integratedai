# The company brain after the 50,000-document test: what was fixed, and how each fix was checked

The 50,000-document test (`docs/FACTBANK_50K_RESULTS.md`) met its eight rules. A review of the code and of the run's
stored answers then found eleven things to fix. This document lists each fix, what it rests on, and how it was checked.

- **What could be checked here was checked here:** on the same 50,000 documents, with no GPU.
- **What needs the model is not measured yet:** the changes to the model's loop can only be measured on a GPU. They are
  built, unit-tested and simulated on the stored answers. The Colab notebook of the next test measures them.
- **The 635 questions of the first test are now development questions.** The fixes were made after reading their
  answers. The next test needs questions nobody has looked at (`docs/FACTBANK_FRESH_PLAN.md`).

## What the review found

| Finding | Evidence in the first run |
|---|---|
| The model never saw a real field name or record id | 285 of its 1,424 tool calls (20%) failed or came back empty for a reason it could not see |
| All harm came from changing the brain's answer | kept: 391 answers, 0.990 right; changed: 244, 0.869 right; all 19 losses were on questions the brain had right |
| The brain was slow for avoidable reasons | a lookup took 5 to 6 s, a count 12 ms; each process built 1 GB of indexes |
| The free-text score measured wording and length | a reader judged 77 of the model's 80 free-text answers right and 76 of plain search's; the scores were 0.813 and 0.702 |
| The brain's rules are hand-built for this company | about 1,000 words in lists, the company's own name in field lists |
| The test was easier than reported | complex questions built from the fields `find` filters; casual wordings keep every key and title; the baseline had one search |
| A test question's answer was in the model's instructions | the example answer `ENG-4833` is the right answer to `compare_two-175` and appears in four more questions |

## 1. The brain is three to five times faster, with the same answers

**What was wrong** (a profile of the brain on the 50,000-document bank):
- The planner tries hundreds of plans a question. For each it read an entity's links, field values and label again.
- Every question scanned all 1.16 million facts for the list of field names.
- The engine loaded every column of every fact, long claims included.
- A record's text was fetched from the full-text table by an id that table does not index: a scan of every row.
- Each process cut all 50,000 documents into passages and indexed them in memory on its first free-text question:
  about 40 seconds and 1 GB a process.

**What changed:**
- The planner keeps what it reads of an entity between plans (bounded: dropped past 200,000 entities).
- The field names are read once. The engine reads the six short columns it uses.
- The bank file has a table from an entity's id to its row in the full-text table (`text_rows`).
- The passage index is built once into the bank file and read from disk (`cie.factbank.store`). Only the index is
  stored; a passage's text is cut again from its document when it is read.

**Check:** all 1,270 questions of the first test were asked again.

| | before | after |
|---|---|---|
| Rows identical in every field (answer, route, reason, evidence, journal) | | 1,270 of 1,270 |
| A folder of 635 questions, 3 processes | about 980 s | about 295 s |
| Median question | 3.1 s (messy), 2.9 s (tidy) | 0.63 s, 0.56 s |

**A dependency that changed an answer's reason.** The first replay differed on one row in each folder: the same
question, the same answer ("not found"), another coverage figure in its reason (0.399 for 0.424).
- The cause was not this change. The code from before it gives 0.399 here too.
- The sentences the brain quotes are chosen with the stemmer of the `tantivy` library, which was not pinned. Version
  0.27 stems "added" to "add"; version 0.25, which the first test ran, stems it to "ad".
- `tantivy` is now pinned to 0.25.0, and a test fails if its stemmer changes (`tests/test_brain_prose.py`).
- With the pin, the replay is identical on every row.

## 2. Tools that tell the truth and read names as people write them

**What was wrong** (counted on the first run's 1,424 stored tool calls):
- 140 `read` calls were given a ticket key, a pull request number or a title; `read` took only a record id.
- 126 `find` calls came back empty, most on a field name written another way ("due date" for `due_date`, "name" for a
  HubSpot account's title). An unknown field gave 0 records, not an error.
- 121 searches came back empty. With a system named, `search` ranked the 200 best records of all systems first and
  filtered after: 38 of 99 HubSpot searches were empty. Words under three letters were dropped ("AI").
- `values` listed only a system's first 80 field names; HubSpot has 428.
- `find` showed a field it did not know as empty, and a `show` of "title" replaced the title with nothing.
- An exact filter missed a value written another way: "Solstice Health" did not match "SolsticeHealth" (18 for 19).

**What changed** (`cie.factbank.tools`, over indexed tables in the bank file, nothing copied into memory):
- **Names:** a field is found whatever its case, spacing or camel case. "title", "name" and "subject" are a record's
  title; "id" is the record itself. A system goes by its usual names ("gdrive", "emails").
- **Errors:** a field or system that does not exist is an error that names the closest ones, never an empty result.
- **read** takes a record's id, its ticket key, its pull request number or its exact title.
- **Values** are compared without case, spacing or punctuation, and the result lists the spellings it counted. A
  filter that matches nothing says which condition matched nothing and which values come close.
- **find** sorts, limits and groups, and filters by `not`, `contains`, date ranges, number ranges and `exists`.
- **search** filters by system before it ranks, keeps short names, puts a record with exactly that title first, and
  marks the hits that hold every word.
- **schema** lists a system's fields with the kind of value each holds. The kinds are read from the data.
- **The model's instructions** list every system's main fields with their kinds, read from the bank.

**Check:** the first run's 1,424 stored calls were run again with the new tools on the same bank.

| tool | then | now |
|---|---|---|
| `read` | 140 of 451 failed | 53 fail (keys and addresses that do not exist); 87 now return the record |
| `find` | 126 of 277 empty, 1 error | 47 now return records; 15 are errors that name the closest field; 64 are empty and say why |
| `search` | 121 of 629 empty | 79 now return results; 42 are empty (nothing holds the words) |
| `values` | 32 of 53 failed | 21 now return values; 11 are errors that name the closest field |

Cases that failed in the first run and work now:
- `search` for "Acme AI" in HubSpot returns the account first.
- `find` for the Gmail threads of "Solstice Health" counts 19 and lists both spellings.
- `find` on Fireflies with "redwood owner" counts Jordan Park's 13 meetings in one call.
- "The issue due first" is one call (`sort`, `limit`); it took 5.5 calls on average.

## 3. A final answer is checked before it replaces the brain's

**What was wrong:** nothing checked a change. The model answered "not found" after failed calls, answered from a
similar record where the brain had rightly found nothing, and at the call limit was never offered the brain's answer.

**What changed** (`cie.factbank.reasoner`): a final answer passes guards. Each may send the conversation back once, two
in all, and none once the tool calls are used up.

| guard | sends the answer back when |
|---|---|
| absence | the model says "not found" where the brain answered, and no tool call of its has worked |
| similar | the model answers where the brain found nothing: it is asked to check the record is the one named |
| named | a ticket key, pull request number or quoted title of the question is in nothing the tools returned |
| grounded | a figure, date or key of a short answer is in nothing the model was shown |
| quotes | none of the quotes it gives is word for word in a record it was shown |

Also:
- **The brain's answer stands without the model** where the brain is reliable: a field or history line of a named
  record, a count by exact filters, a name the company does not have, a field the named record lacks. On the first run
  the model changed 5 of these 213 answers: 2 for the better, 3 for the worse, at 18% of its prompt tokens.
- **The last turn offers the brain's answer** beside "not found".
- **The brain's row shows the ids of the records it read**, and 6,000 characters of evidence for a free-text answer
  (2,500 before).
- **The example answer in the instructions is a made-up key.** A test fails if any example in the instructions is in a
  question set of the repository.

**Check, by simulation on the first run's stored answers** (the stored calls run again with the new tools; this is not
a measurement, since a guard changes the conversation that follows):

| guard | would speak on | of them wrong | of them right |
|---|---|---|---|
| similar | 17 answers | 4 | 13 |
| grounded | 5 | 1 | 4 |
| absence, named | 0 | | |

- A sixth guard was tried and dropped: it showed a count that differed from the brain's beside it. It would have
  spoken 32 times, each time on a right answer.
- The guards speak rarely. Whether "similar" helps (4 wrong answers to win, 13 right ones to keep) can only be
  measured with the model.

## 4. Free text: a short answer and the record's own sentences

**What was wrong:** the model lost to the brain on 12 free-text questions by shortening a right quote. Its
instructions asked for a bare date or figure when the question asked for one; the scorer wants the record's phrase.

**What changed:**
- A free-text answer is a short direct line plus `quotes`: one to three sentences copied word for word from a record.
- The quotes are checked against what the model was shown. Those that are not word for word are dropped.
- They are kept beside the answer (`support`) and shown under it. A free-text answer is scored with them.
- When the model keeps the brain's document and quotes nothing, the brain's own quote goes with its answer.
- Plain search gets the same format ("Quote:" lines), checked against its passages, so the comparison is even.

**Not checked yet:** the effect on the score needs the model. The scorer still rewards copying; the next test adds a
judge (section 9).

## 5. The missing arms

Every arm is the same model and loop; they differ only in what the model may use (`reasoner.ARMS`).

| arm | what the model has | what it shows |
|---|---|---|
| `reasoner` | the brain's answer and every tool | the whole system |
| `nobrain` | every tool but the brain, no first answer | what the rules add to the model and the exact tools |
| `agent` | search and read only | a model that searches by itself: what the fact bank's structure adds |
| `notools` | the brain's answer and evidence, no tool | what the tools add |
| `rag` | 12 passages of one keyword search | the usual search-then-model baseline |

- A run takes a seed (`--seed`); a seed other than 0 answers into its own file.
- Every answer carries the model, effort, seed and the version of the loop it was made with. Answers of another
  version are never mixed in.

## 6. The brain's own fixes (v19)

v19 is v18 with four fixes, each with a name and each switchable (`Brain(v19=True, fixes=...)`). It is off by default:
with no fix on, every answer is v18's (a test compares them).

**What was wrong** (from the answers that got worse between 5,000 and 50,000 documents, and the review):
- The "not found" check weighed chat words ("hey", "actually") and dropped the words of any field name, asked for or
  not. Its bar for "too little to check" was set at 14,000 entities and did not move with the bank.
- 499 of the bank's 22,846 "people" are companies ("AWS Marketplace", "Lumina Labs"): an email's external participants
  list holds both. The planner started from them as if they were people.
- A name typed in lower case ("authored by mikko rodriguez") was not seen as a name.
- When a look-alike record ranked first, the answer said nothing of the others that fit as well.

| fix | what it does | development questions, casual wording: better / worse |
|---|---|---|
| `cover` | the check weighs the words the question is about: not chat, not the field it asks for; the bar grows with the bank | 4 / 0 |
| `orgs` | a name that the records write in a company field, and never as an assignee, author or attendee, is not a person | 2 / 1 |
| `names` | a lower-case word that is not ordinary English, not a typo of it, and that the bank holds nowhere, is an unknown name | 0 / 0 |
| `candidates` | the row lists the other records that hold as much of the question (`candidates`); the answer is not changed | 0 / 0 |
| all four | | 6 / 1 |

Mean of the eight families, brain alone, on the 635 development questions:

| wording | v18 | v19 |
|---|---|---|
| casual | 0.878 | 0.885 |
| tidy | 0.914 | 0.916 |

- **The one answer that got worse** was right by luck. v18 answered "not found" because it had started from "Acme
  Retail" as a person and found nothing; v19 does not make that mistake, reaches the free-text route, and quotes a
  document that holds half the question's words. The question has no answer in the documents.
- **`names` changed no answer.** The list of ordinary words holds common first names and surnames, so "mikko" and
  "rodriguez" count as ordinary. The fix only catches names outside that list. It is kept because it cost nothing
  here; it is unproven.
- **`candidates` costs time:** the median question takes 0.82 s (0.63 s for v18). About 150 of 635 rows list
  candidates. The model reads them as `also_close`.

**Measured and not adopted:**
- *Choose the record that holds more of the question* (rank the finder's candidates by coverage): wins 3 and loses 2
  on described records, wins 3 and loses 5 on free text. Coverage does not tell a look-alike from the right record.
- *Withhold fewer free-text quotes:* the 6 quotes wrongly withheld have coverage 0.35 to 0.49; the 29 rightly
  withheld have 0.23 to 0.56. No bar separates them.

**Not solved by v19:** the complex questions (0.17 without the model) and free text (0.63) are where the model is
needed. These numbers are on development questions; the fresh test measures v19 on questions it has not seen.

## 7. A bank that is built in batches and updated without a rebuild

**What was wrong:**
- `build` held every fact of the bank in memory at once, and the checker read them all again (1.7 GB at 50,000
  documents). The memory grew with the company.
- Any change to the documents meant building the whole bank again (about 3 minutes at 50,000 documents).

**What changed** (`cie.factbank.bank`, `cie.factbank.store`):
- `build` reads and writes the documents 2,000 at a time. The checker is a set of queries and holds nothing.
- `sync` brings a bank up to date with the documents as they are now. It adds new documents, replaces changed ones
  (by a hash of their content) and removes those that are gone. The derived tables (text by id, passage index, field
  table, schema) are changed with it, a document at a time.
- A count of changes (`store.revision`) tells a process that keeps part of the bank in memory that the bank changed.
- One rule had to be fixed to make this possible: an identifier that several documents carry points to the document
  with the smallest id. Before, it pointed to whichever came last in an unordered set. No reference of the
  50,000-document bank goes through such an identifier (checked: 0 of 54,047).

**Checks at 50,000 documents:**

| check | result |
|---|---|
| The batch-wise build against the bank the old build wrote | every row of every table the same, in the same order (1,162,089 facts) |
| Peak memory of the build | 1.7 GB before; 0.4 GB now, and it no longer grows with the documents |
| 500 documents taken out | 6 s |
| The same 500 put back | 7 s; every table then holds the same rows as the bank built from scratch |
| 500 documents changed in place, then changed back | 12 s each way; again the same rows as the bank built from scratch |
| The checker after the changes | passes; the derived tables need no repair |

- A test makes random additions, changes and removals to a small company and compares the bank with a fresh build
  after each step (`tests/test_bank_sync.py`).
- **One difference remains:** after an update the rows are the same but their order in the tables is not (new rows come
  last). Two passages that match a question equally can then come in another order. A full build restores the order.

**An independent review of this code found five bugs and one hazard, now fixed,** each with a test that failed
before its fix:

| bug | what went wrong | fix |
|---|---|---|
| a citation longer than 300 characters | values are stored cut to 300 characters; an update read the cited key again from the cut copy, and lost it | the key is read from the citation's own record, which holds it whole |
| the same fields in another order | the change check ignored field order, but the builder reads fields in order (which spelling of a name comes first) | the check keeps the order |
| a custom profile without its own name | it was taken for the default and not saved, so an update read documents with the default lists | a profile is compared by its lists, not its name |
| an update on a bank built without its derived tables | it failed, or left stale search rows behind | the update builds the missing tables first |
| sentence facts (the hazard) | an update not told the bank was built with them dropped them | the bank records it, and the update follows |
| the field reader's bulk mode | documents of no known system (added after the bank was opened) were lost after 256 lookups | they are read one at a time |

The review also ran 750 random sequences of updates against fresh builds; apart from these cases, every one
matched.

## 8. What the code knows about the company: the profile

**What was wrong:** the builder and the brain knew this company from lists in the code: 19 fields that name people (two
with the company's own name in them), 19 that cite other records, a rule on field names for dates, the systems of
record, the fields that name companies.

**What changed** (`cie.factbank.profile`):
- A `Profile` holds those lists. The default profile is exactly what the code held: a bank built with it is the same
  bank, row for row (a test compares them).
- A profile is a JSON file. Another company's fields are written there, not in the code.
- `derive` reads a profile from the documents themselves:
  - a field holds dates when 90% of its values are dates;
  - it cites records when half its values hold an identifier by its form (a ticket key, a pull request's address) or
    are an identifier another record carries;
  - it names people when its name-shaped values are names that another field of people also holds. People turn up
    in several roles; a company's web domain or a team's name does not.
- The bank keeps the profile it was built with. `sync` and the brain read it from the bank.
- Two bugs the review found in `derive`, now fixed:
  - an identifier of digits that other records carry (an account number) read as a date (epoch seconds): references
    are now told before dates;
  - a field the documents did not hold at all was dropped from the lists, so documents added later that hold it lost
    their people and references: such a field now keeps the default's lists, and a date by its name.

**How much the documents tell by themselves** (the profile read from the 50,000 documents against the lists written by
hand, counted in field values):

| | fields found | share of the written lists' values | missed |
|---|---|---|---|
| dates | 48 | 99% | one field of months ("2026-04"), which is not a day |
| people | 16 of the 18 the documents hold | 42% | Slack's `participants` (163,000 values, 83% of them handles like "deploy-bot", not names), `stakeholders` |
| references | 11 of 19 | 24% | fields that cite by a web address, a file name or a thread id |

- The references it misses cite documents outside the 50,000 (the haystack is a tenth of the company), by forms only
  the hand-written reader knows. Nothing in the values gives them away.
- It also found fields the lists lack: 8 that cite pull requests and issues, 2 date fields the name rule misses.

**What that costs in answers:** the bank was built again with the derived profile (80,135 entities for 114,341) and
the brain asked the 635 development questions in casual wording.

| | written lists | read from the documents |
|---|---|---|
| mean of the eight families | 0.878 | 0.878 |
| questions that changed | | 1 better, 1 worse |

**What this does and does not show:**
- The field lists are not what holds the brain to this company: reading them from the data loses nothing on these
  questions.
- The questions come from generators that know this company's fields too, and few of them follow a web link from
  one document to another. A second company is the real test, and there is none here.
- **Still written by hand,** and not in the profile:
  - the words of a question that point to a field ("who owns" for `owner`), about 1,000 words;
  - the reader of each system's export (which field is the title, which identifiers a record carries);
  - the fields that name companies and the systems of record: a company's name and a person's look alike, and the
    values do not tell which system is the source of truth;
  - the weights the brain learned from this company's questions.

## 9. A judge for free text, and a test on questions nobody has seen

**What was wrong:**
- Free text was scored by the words of the expected facts that an answer holds. That follows wording and length, not
  correctness (section "What the review found").
- The benchmark's own 500 questions, written by its authors with reference answers, had never been asked.
- Every fix above was made after reading the answers to the old questions. A score on them proves little.

**What changed:**
- **A judge** (`cie.eval.judge`): the loaded model, in a separate conversation, is shown the question, the reference
  answer, its facts and an answer. It says which facts the answer states and whether the answer is right.
  - A verdict it cannot give in the asked form is asked for once more, then left out and counted as "not judged". It
    is never counted as wrong.
  - `judge sample` writes answers to a sheet for a person to label, without the judge's verdicts. `judge agreement`
    compares the two (agreement and Cohen's kappa). Until a person has labelled a sample, the judge's numbers are
    unproven.
- **The fresh test** (`cie.eval.fresh_test`, `docs/FACTBANK_FRESH_PLAN.md`): 463 of the benchmark's own questions and
  newly generated ones, on 50,000 documents of which only the questions' own documents were in the earlier haystack.
  Its rules were written before any arm answered.

**Checked here, without a GPU:**
- The harness was run end to end on the earlier bank with the 37 benchmark questions that are left out of the test
  and a scripted stand-in for the model: every arm, three seeds, the samples, the judge, the report and the rules.
  What the stand-in says is nonsense; the run shows that every step reads what the step before wrote.
- Unit tests cover the judge's reading of a verdict, the sample, the copying of rows to the sample, the bench score
  and each rule (`tests/test_judge.py`, `tests/test_fresh_test.py`).

- An independent review of the harness found four bugs, now fixed with tests:
  - rules 4 to 6 were decided from the judge's verdicts before the judge was checked against people, against the
    plan; they now wait for an agreement of 0.85;
  - a rule decided by less than the spread between seeds was not marked undecided when the seeds disagree, against
    the plan; it now is (the plan says how this is worked out);
  - a sample kept a verdict the judge had failed to give over the full folder's good one, and judged it again;
  - the run stopped when a folder had no sample.
  - Also: a benchmark question the documents cannot answer, with no reference text, was not judged at all; it now is,
    against "not found".

**Not checked:** everything that needs the model. The notebook `notebooks/company_brain_fresh_colab.ipynb` runs it.

## 10. A brain process's memory, and the whole company

**What was wrong:**
- A brain process kept everything it read for later questions, bounded only at 200,000 entities. A person can hold
  thousands of facts, so one process grew past 1 GB at 50,000 documents and kept growing.
- On its first count or filter, the record table loaded every field of every document of the bank (1.3 GB a process
  at 50,000 documents).

**What changed:**
- The planner keeps at most 600,000 facts between questions and drops the ones it read longest ago first.
- The record table reads a document's fields when they are asked for, and a whole system once many of its documents
  are; it keeps at most a million field values of whole systems.
- A bank object can tell that its file was updated under it (`FactBank.stale`).

**Checks at 50,000 documents:**

| | before | after |
|---|---|---|
| The 1,270 old questions | | every answer identical |
| One process, the same 120 questions | 163 s; 1.21 GB at the end, still growing | 165 s; 1.07 GB at most |

**The whole company (512,000 documents) does not fit the brain yet:**
- The bank builds (section 7) and the brain loads it in 40 s, in 1.3 GB.
- One complex question then took 148 s, and the process reached 7.9 GB. Three parts of the brain grow with the
  company:
  - the index of every title's beginnings and ends, used to catch made-up titles (1.2 GB);
  - the planner's candidate plans (1.4 GB);
  - the first version's lookup engine, which the brain runs for evidence: it spreads from a person to every record
    that names them and writes each fact it meets (3 GB, for one question).
- Each of these decides what the brain answers. Bounding them changes answers, so it is a change to the brain, to be
  measured by a test of its own, not a memory fix. It has not been made.

## What is and is not verified

| fix | verified here | needs the GPU run |
|---|---|---|
| 1. speed | 1,270 of 1,270 answers identical, 3 to 5 times faster | |
| 2. tools | the first run's 1,424 calls run again: 234 of 419 failures now succeed, the rest say why | whether the model then answers better |
| 3. checks on the final answer | simulated on stored answers; unit tests | the effect on real conversations |
| 4. free-text quotes | unit tests | the effect on scores |
| 5. arms, seeds | harness tried with a stand-in | the numbers |
| 6. brain v19 | development questions: 6 better, 1 worse | the fresh questions |
| 7. batch build, update without rebuild | row-for-row equality at 50,000 documents; the full company built | |
| 8. profile | default reproduces the bank; derived profile loses nothing on development questions | a second company |
| 9. judge, fresh test | harness tried with a stand-in; four bugs an independent review found, fixed with tests | the judge against a person's labels; the test itself |
| 10. memory | the same 1,270 answers; a process stays under 1.1 GB at 50,000 documents | the whole company needs a change to the brain itself |
