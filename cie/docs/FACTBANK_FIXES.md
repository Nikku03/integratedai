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
| similar | 16 answers | 4 | 12 |
| grounded | 5 | 1 | 4 |
| absence, named | 0 | | |

- A sixth guard was tried and dropped: it showed a count that differed from the brain's beside it. It would have
  spoken 32 times, each time on a right answer.
- The guards speak rarely. Whether "similar" helps (4 wrong answers to win, 12 right ones to keep) can only be
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
