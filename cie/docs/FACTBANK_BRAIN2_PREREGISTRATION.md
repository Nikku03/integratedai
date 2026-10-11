# The company brain, round 2 (v16): fixed before the test

**DRAFT: not frozen.** The freeze is the commit that removes this line.

I wrote this on 2026-10-11:
- **after** building and tuning v16 on training and development documents (below);
- **before** drawing the test documents or writing a single test question.

The results go in `docs/FACTBANK_BRAIN2_RESULTS.md`. All data is fictional: the benchmark's made-up company.

## Why

Round 1 (`docs/FACTBANK_BRAIN_RESULTS.md`) built v15, one brain for every kind of question tested. It did better than every
earlier version on single-document questions, multi-document questions and questions about things the company does not have.
It missed its claim on one family:
- **Free text:** its quoted answers held 0.583 of the answer facts, against 0.707 for plain keyword search with the same quoting
  code. The loss was in which passages it cut from the right document and how it ranked them.

The review after the run found five small faults on the fact routes, and the test left whole kinds of question out:
- **The faults:** a "when" or "who" after "do you know" or "can you remind me"; a product name stored as a person ("Okta SSO");
  a meeting's ID read as its date; attendee lists read from only one field; "filed under" read as the reporter.
- **Not tested:** counts and filters ("how many Jira tickets have priority P2?"); history and change ("when was it last
  updated?", "who left the first comment?"); chat and email (80% of the documents); answers that join two documents beyond a
  pull request's issue; and knowing when not to answer a natural question.

**v16 fixes the free text and the faults, and adds the missing kinds.** This test asks whether one brain now answers all of
them, on fresh documents and questions it has never seen, at least as well as the best earlier answer for each kind, and
whether it says "not found" when the company does not have the answer.

## What v16 is

`cie/src/cie/factbank/brain.py` with `v16=True`, over the same bank as v15 (`factbank_v2.sqlite`). With `v16=False` every
answer is v15's, byte for byte (checked on the 214 development questions). It takes the first route that applies:

1. **Not found:** the question names a ticket key, a pull request number, a quoted title or a person's full name that the bank
   does not hold (as v15).
2. **Derived** (`cie/src/cie/factbank/records.py`, `Records.derived`): history and messages of one document the question
   names (by key, number, quoted title or subject, or a quote of a Slack thread's first words). This covers:
   - when it was created and last updated;
   - how many days a pull request took to merge;
   - who left the first comment, and when the latest one was posted;
   - a HubSpot account's first recorded activity;
   - when a ticket moved to a status;
   - an email thread's first sender, its recipients and copies, how many messages and attachments, its account and start
     date;
   - a Slack thread's channel and who started it.
3. **Table** (`Records.table`): counts and filters over one system's documents, with conditions read from the field values the
   question names ("How many Linear issues in release R have status S?", "Which Jira tickets have priority P1? Give the
   keys."), or the people on the filtered documents (a project's assignees).
4. **Fact or prose:** v15's router.
5. **Prose** (`cie/src/cie/factbank/prose.py`): a passage index over the bank's document text. Text is cut into windows of 600
   to 1,000 characters and ranked by BM25, with the title weighted 2.5. The route quotes only from the document of the best
   passage. **It answers "not found" when the quote covers less than 0.47 of the question's words**, each word weighted by how
   rare it is (`quote_cov`). The threshold was fixed on the training questions.
6. **Absent** (`Records.absent`): on a fact question about one named document, "not found" when the field it asks for is one
   that at least 30% of the system's documents hold, but this document leaves it empty (no CSM assigned, no due date).
7. **Plan or fact:** the planner or the single-document engine, as v15, with the five fault fixes (behind the flag):
   - a question word after a verb of knowing or telling still asks;
   - a "person" that no first name, person field or repetition supports is not a start;
   - when "when" or "who" is asked, only dates or people compete;
   - attendee lists join the company's and the customer's attendees;
   - "filed under" asks for the project or space.

⟨TBD: fact-route abstention, router and plan lessons, from phase 2⟩

**Speed:** v15 spent most of its time on repeated name lookups; v16 remembers them per question. On the development set v16
takes about 1.1 s a question against v15's 4.6 s.

## The documents

**The zones are round 1's** (`zones.json.gz`, sha256 `b1afac237c309a82…`): test 56,641, development 56,068, training 169,564
fresh documents.

**Training and development sets:** round 1's (seeds 601 and 701), 5,000 documents each.

**Test set:** 5,000 documents of the test zone that round 1's test set did not use (`cie/src/cie/eval/brain2_draw.py`,
seed 909). Pull request → Linear issue pairs are planted from the zone's remaining documents by the same rule as round 1, up to
10. It is drawn only after this document is committed; the draw refuses the test zone without a flag that says so.

**Held-out documents** (seed 913): test-zone documents in neither test set. A document is kept only when all three hold:
- none of its titles, keys, numbers or customer names is written in the test haystack;
- no test document of the same system has a title sharing half its words;
- it shares under 10% of its five-word runs with any test document.

Writers ask about these documents, so the right answer is "not found".

## The questions

Eight families, every question checked by code.

| family | what | how many |
|---|---|---|
| single | round 1's single-document kinds (deadlines, lists, fields, names, descriptive) and 20 of the same fields asked after "do you know", "can you remind me" | about 130 |
| multi | round 1's multi-document kinds and six new two-document kinds | about 70 |
| prose | free text, written by blind writers | 150 |
| not_found | invented keys, numbers, titles and names, as round 1 | 20 |
| counts | counts with one or two conditions, Gmail counts, key lists | 40 |
| history | created, last updated, days to merge, moved to a status, first commenter, latest comment, first activity | 40 |
| email_chat | Gmail sender, date, recipients, copies, messages, attachments, account; Slack channel and starter | 40 |
| unanswerable | about 50 writers' questions about held-out documents, and 20 about a field the named document leaves empty | about 70 |

**The new kinds** (`cie/src/cie/eval/brain2_questions.py`): expected answers come from the raw documents' fields. A question
with two right answers in the haystack is set aside, and so is one whose answer is written in the question. The two-document
kinds are:
- a planted pull request's issue's project, creator and team;
- joins on a person's full name: the Linear issues assigned to a pull request's author, those reported by a Jira reporter,
  and the HubSpot accounts owned by a meeting's owner.

These joins are on the same name string, not a confirmed same person. A new question that asks the same field of the same
document as a round-1 question, with the same answer, is set aside.

**Scoring:**
- **Counts:** the first number in the answer line must equal the count (`count_hit`).
- **Dates:** exact.
- **Lists and names:** F1.
- **Values:** in the answer.
- **Unanswerable and not found:** 1 when the answer says "not found".
- **Free text:** as round 1 (the share of the answer facts present), plus a strict score that counts a fact only inside text
  quoted from the right document.

**The mix** (questions seed 910): round 1's mix with 150 free-text questions; `brain2_test.MIX16` for the new kinds; every
held-out question that passes the checks.

**The writers** (`docs/benchmarks/brain2/writers_test2.js`): independent agent sessions in ten roles, blind to the method,
sealed. Each reads one batch of 10 packets and writes its questions straight to a file. They return only a count, and nobody
reads their questions until the scores are written.

The packets:
- 45 descriptive (seed 911), up to 40 kept;
- 180 free-text (seed 912), up to 150 kept;
- about 75 held-out (seed 913).

The checks are round 1's, and for held-out questions one more: a question is rejected when a test document holds a rare word
of the held-out document's names together with half its answer facts (every fact when no name word is rare).

**The small control:** the same questions on a set holding only their gold documents.

## How it runs

1. `docs/benchmarks/brain2/run_brain2_1.sh`: the draw and the packets.
2. The writers (`writers_test2.js`).
3. `docs/benchmarks/brain2/run_brain2_2.sh`:
   - the writers' questions are checked and converted, the questions drawn and the small set written;
   - the banks are built;
   - every arm answers, one at a time, on the small set and then on the 5,000 documents;
   - v16 answers again under hash seed 1;
   - `brain2_test score --preregistered` decides the rules.

**The arms:** plain search with quotes, v1, v2, v13 and v15 (round 1's frozen files), and v16 (the frozen files below).

## Rules

Each family's score is the mean of its questions' scores. "The best other arm" is the best of the five other arms on that
family.

⟨TBD: thresholds from the development numbers⟩

## Development

⟨TBD⟩

## Disclosures

⟨TBD⟩

## Known limits

⟨TBD⟩

## The review before freezing

⟨TBD⟩

## Frozen

⟨TBD⟩
