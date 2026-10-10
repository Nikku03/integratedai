# The company brain (v15): one version for every kind of question, fixed before the test

DRAFT: this line is removed by the commit that freezes the test.

I wrote this on 2026-10-10 and 2026-10-11:
- **after** building and tuning v15 on training and development documents (below);
- **before** drawing the test documents or writing a single test question.

The results go in `docs/FACTBANK_BRAIN_RESULTS.md`. All data is fictional: the benchmark's made-up company.

## Why

The goal is a company brain: one system that answers whatever is asked about the company. Until now each version was good at
one kind of question:
- **v1** (the untrained fact bank) answers questions about one document: owners and other fields, deadlines, lists. It
  scored 0.85 on those at 5,089 documents, but almost nothing on questions that join two documents.
- **v13** (the planner) answers questions that join documents: 0.97 at 5,000 documents. On single-document questions it scored
  0.51 at 5,089 documents (v1: 0.85).
- **Neither answers free-text questions** ("what are the default upload size limits?"): their answers held 0 of 250 answer
  facts in a survey of the benchmark's own questions.
- **Neither says "not found"** when a question names something the company does not have.

**v15 is one version for all of these.** This test asks whether it answers every kind at least as well as the best earlier
answer for that kind, on documents and questions it has never seen.

## What v15 is

`cie/src/cie/factbank/brain.py`, over one bank (the v2 bank file, `factbank_v2.sqlite`). It takes the first route that
applies:

1. **Not found:** the question names a ticket key, a pull request number, a quoted title or a person's full name that the bank
   does not hold. The answer is "not found".
2. **Fact or prose:** a small router, a logistic regression trained on labelled questions, decides whether the question asks
   for a fact or for something written in prose.
3. **Fact:**
   - **plan:** the planner's answer when its plan starts from something the question names (a key, a pull request number, a
     full name, a quoted title) and reads what the question asks for;
   - **fact:** otherwise the single-document engine's answer (v1's), on the same bank.
4. **Prose:** sentences quoted from the passages of document text that best match the question (no language model).

**The planner's fixes** (`plans.py`, behind the `brain` flag; v13 is unchanged without it):
- the question word decides the kind of answer when it contradicts the learned one ("when" asks for a date);
- no count when several things are asked for;
- a one-word name ("Priya", "Redwood"), or a team's name in a person field ("Customer Success"), does not fix the start;
- system words count only as whole words ("CI-driven" does not name Google Drive);
- when the question asks for no link, no extra hop: the thing named is read directly, by the shortest route.

**The evidence fixes** (`engine.py`, behind the `brain` flag): evidence ordered by the largest single vote, keys in list lines,
and passages of document text for prose.

**Training** (`cie/src/cie/eval/brain_train.py`), on the training documents only:
- **single-fact lessons** on 396 single-document questions;
- **plan lessons** on 511 single- and multi-document questions, plus v13's own 201 training questions on their bank, with v13's
  rules;
- **the router** on 622 questions: 396 single-document, 115 multi-document and 111 free-text.

## The documents: zones never seen before

**Every document of every earlier set is excluded:** 229,685 seen documents, including the lexicon's 200,000-document sample
and the review draws. That leaves 282,273 fresh documents.

**The fresh documents are split once into three zones** by a hash (`cie/src/cie/eval/brain_draw.py`, salt `brain-zones-v1`):
- test 56,641 documents;
- development 56,068;
- training 169,564.

The 27 pull requests that can be planted (each linking one Linear issue that no other pull request references) were dealt
10 / 8 / 9, each pair kept in one zone. The zone file is `zones.json.gz` (sha256 `b1afac237c309a82…`).

**Training set:** 5,000 documents of the training zone (seed 601), 9 planted pull requests.

**Development set:** 5,000 documents of the development zone (seed 701), 8 planted pull requests.

**Test set:** 5,000 documents of the test zone, seed 809, with the zone's 10 planted pull requests. It is drawn only after this
document is committed; the draw refuses the test zone without a flag that says so.

## The questions

Every kind of question that can be checked automatically:

**Single-document (family "single"):**
- **deadlines:** Linear due dates and meeting action items;
- **lists:** a person's Linear issues, by status, due in a date window, Jira tickets, pull requests, a customer's tickets;
- **document fields:** 31 kinds, such as a Drive document's owner, a Jira ticket's priority, a HubSpot account's stage, a pull
  request's repository;
- **names:** meeting attendees, pull request reviewers, a project's members (scored by name-list F1);
- **descriptive:** written by blind writers, describing a document by what it is about instead of its title, as the
  benchmark's metadata questions do; the expected answer is the document's field.

**Multi-document (family "multi"):** v13's seven kinds (a pull request's linked issue, an issue's pull request author, a
ticket's linked ticket, a person's count, a person's first issue due, which of two is due first, an action item owner's
issues), and a Linear issue's parent.

**Not found (family "not_found"):** a ticket key, a pull request number, a quoted title or a full name that appears nowhere in
the 5,000 documents. Right only if the answer says "not found".

**Free text (family "prose"):** written by blind writers. Each is a question whose answer is stated in a document's text, with
1 to 3 answer facts copied word for word from it. The score is the share of the facts in the answer.

**Questions with two right answers are set aside,** as in the earlier tests.

**The mix** (seed 810), as in the development set:

| group | questions |
|---|---|
| deadlines | 15 |
| lists | 15 |
| document fields | 30 |
| names | 10 |
| descriptive (writers) | all that pass the checks, up to 40 |
| link | 15 |
| combine | 15 |
| compare | 6 |
| not found | 20 |
| free text (writers) | 50 |

**The writers** (`docs/benchmarks/brain/writers_test.js`): independent agent sessions in ten roles, blind to the method. Each
reads one batch of 10 packets (a document and an instruction) and writes its questions straight to a file.
- **The packets:** 40 descriptive (seed 811) and 60 free-text (seed 812), on different test documents
  (`cie/src/cie/eval/brain_writers.py`). The expected answers are kept out of the packets.
- **Sealed:** the writers return only a count. Their questions are read by code alone (checks, draw, scoring) until the
  scores are written. Nobody reads them before.
- **The checks** (`brain_writers.collect`) reject a question that holds its answer or a long run of the title, a free-text
  fact not found word for word in the document, a fact shorter than 2 words, a yes/no question, and so on.

**The small control:** the same questions on a set holding only their gold documents (`brain_test questions --small`).

## How it runs

`docs/benchmarks/brain/run_brain_1.sh` (draw and packets), then the writers (`writers_test.js`), then
`docs/benchmarks/brain/run_brain_2.sh`:
- the writers' questions are checked and converted, the questions drawn and the small set written;
- the banks are built;
- every arm answers, one at a time, on the small set and then on the 5,000 documents;
- v15 answers again under hash seed 1;
- `brain_test score --preregistered` decides the rules.

**The arms:**
- **v1:** the untrained fact bank;
- **v2:** the fact bank with the single-fact lessons (`fb50/lessons.json`);
- **v13:** the planner (`plan_lessons_v13.json` with `fb50/lessons.json`);
- **quotes:** plain keyword search over the documents' passages, answered with the same quoting code as v15's prose route,
  with no fact bank;
- **v15:** the company brain (the frozen lessons and router below).

## Rules

Each family's score is the mean of its questions' scores. "Mean over families" is the mean of the four family scores.

1. **Single-document questions:** v15 ≥ v1 − 0.03.
2. **Multi-document questions:** v15 ≥ v13 − 0.03.
3. **Free text:** v15 ≥ quotes − 0.05.
4. **Not found:** v15 ≥ 0.80 on the not-found questions, and v15 says "not found" to at most 0.03 of the other questions.
5. **One brain for every kind:** v15's mean over families ≥ every other arm's + 0.20.
6. **It holds at size:** v15 at 5,000 documents ≥ the small set − 0.05, mean over families.
7. **The right route:** v15's route accuracy ≥ 0.90, mean over families (fact routes for single and multi, prose for free
   text, not found for not found).

**What decides:**
- **One brain answers every kind (the claim):** rules 1, 2, 3 and 4 all met.
- **Rule 5** is the headline number; it is expected to be met by a wide margin, since no other arm answers every family.
- **Rules 6 and 7** are reported. A failure is diagnosed question by question.
- **Any decisive rule not met:** v15 does not yet answer that kind as well as the best earlier answer. The questions it loses
  are diagnosed.

**How to read differences:**
- The single family has about 105 questions: one question moves it by about 0.01.
- The multi family has about 35: one question moves it by about 0.03.
- Free text has 50: one question moves it by up to 0.02.
- So rule 1's −0.03 allows about three single-document questions; rule 2's allows about one.

**Also reported:**
- every arm by family, group and kind;
- false "not found" on answerable questions;
- free-text facts within the first 2,000 / 6,000 / 24,000 characters of each arm's evidence;
- time per question;
- route counts and accuracy;
- the small set and its differences;
- the hash-seed check (no answer should change);
- the questions set aside, and the writers' questions rejected, with the checks' reasons.

## Development (on training and development documents)

**Training and development sets.** The training questions were drawn from the training set (seed 621). The writers' questions
for training and development were written by 34 blind sessions in the same ten roles:
- training: 116 descriptive and 111 free-text questions kept;
- development: 36 descriptive and 52 free-text kept.

**The development set: 214 questions** (seed 721), in the mix above. Mean over families, and the four families:

| arm | single | multi | free text | not found | mean |
|---|---|---|---|---|---|
| quotes | 0.107 | 0.056 | 0.654 | 0.000 | 0.204 |
| v1 | **0.800** | 0.056 | 0.000 | 0.250 | 0.277 |
| v2 | 0.635 | 0.083 | 0.006 | 0.250 | 0.243 |
| v13 | 0.255 | **0.944** | 0.000 | 0.000 | 0.300 |
| v15, before training (v13's lessons, rule router) | 0.735 | 0.944 | 0.538 | 1.000 | 0.804 |
| v15, trained, rule router | 0.772 | 1.000 | 0.538 | 1.000 | 0.828 |
| v15, trained, trained router | 0.785 | 1.000 | 0.663 | 1.000 | 0.862 |
| **v15, frozen** (+ two fixes below) | **0.804** | **1.000** | **0.663** | **1.000** | **0.867** |

- **Seen on the development set, so the frozen line is optimistic.** The two last fixes (team names; the fewest hops) and the
  choice of the trained router were made after reading its answers.
- **The trained router** sends 51 of 52 free-text questions to prose and every single- and multi-document question to a fact
  route. The rule router sent 7 free-text questions to a fact route.
- **Where the frozen v15 is still below the best other arm on a development question** (12 of 214):
  - one meeting's attendee list: an extra hop to the meetings the attendees went to;
  - one meeting date and two descriptive questions, which plain search or v13 got;
  - eight free-text questions, where plain search's passages held more of the facts. On seven others v15's held more.

**Earlier sets, all seen** (the full trained brain against saved answers):
- **12 multi-document sets of the earlier tests:** v15 matches or beats v13 on 10. It loses one question on each of the other
  two: "the other ticket linked to ENG-…", where the trained planner reads the named ticket itself.
- **Part B's single-document sets:** the first test's 50 questions at 50 documents 0.910 (v1 0.885); Part B's 50 on their
  small set 0.828 (v1 0.866), where the router sends 4 of the benchmark's long descriptive questions to prose.

**Measured and dropped along the way:**
- retraining the planner on the first test's single-document questions alone (it cost three "other linked ticket" questions);
- the rule router (it sent free-text questions to fact routes).

## Disclosures

- **The development set guided every fix after training.** Its scores are not results.
- **The 5,089-document haystack and Part B's questions were used for the first diagnosis** (why v13 fails on single-document
  questions), and the planner's fixes were first measured there. They are seen.
- **Seeds used so far:**
  - zones salt `brain-zones-v1`, pull-request deal 900;
  - training 601 (questions 621; packets 611, 612);
  - development 701 (questions 721; packets 711, 712);
  - a survey's counting draws on the fresh pool, 53 and 101-130, counts only.
  - The test's seeds 809, 810, 811 and 812 were never used.
- **The writers and the method are the same model family as the author.** The writers saw only their packets. The router and
  the descriptive checks were developed on writer questions from the same ten roles.
- **The glossary** the plan lessons name is `scratchpad/glossary.json`, the same file as
  `docs/benchmarks/factbank_llm/glossary.json` (sha256 `0dd7d0bc2a7788d5…`).

## Known limits

- **No judge:** free-text answers are scored by whether their answer facts appear word for word, not by reading them. An answer
  that paraphrases a fact scores 0 for it, and a long quote can hold a fact by chance. No language model writes or grades
  answers here.
- **Free-text answers are quotes,** not written answers: about 1,000 characters of the best-matching sentences.
- **5,000 documents, one fictional company, about 210 questions.** The families are small, so one or two questions decide a
  close rule.
- **The question kinds are those that code can check.** Questions such as "why did the incident happen?" are covered only as
  far as writers' free-text questions cover them, and abstaining on hard questions is not tested beyond "not found".
- **Not-found questions are templates** (invented keys, numbers, titles and names), easier to spot than a real question about
  something the company never did.
- **Time:** about 3–5 seconds per question at 5,000 documents, mostly the planner.

## The review before freezing

To be filled in from the pre-freeze review (`docs/benchmarks/brain/prefreeze_review.json`).

## Frozen

| what | value |
|---|---|
| code | the commit that removes the draft line from this document |
| single-fact lessons | `docs/benchmarks/brain/lessons/single_lessons.json` (`ee8b9d053405a47f…`) |
| plan lessons | `docs/benchmarks/brain/lessons/plan_lessons.json` (`de756122b9f027be…`) |
| router | `docs/benchmarks/brain/lessons/router.json` (`20e9c05046406f14…`) |
| v2's and v13's lessons | `fb50/lessons.json` (`afa4e7d9fee0a05c…`), `plan_lessons_v13.json` (`64cf5b302a826b2e…`) |
| zones | `zones.json.gz` (`b1afac237c309a82…`) |
| seeds | test draw 809, questions 810, packets 811 and 812, hash seed 0 (and 1 for the check) |
| run | `docs/benchmarks/brain/run_brain_1.sh`, `writers_test.js`, `run_brain_2.sh` |
