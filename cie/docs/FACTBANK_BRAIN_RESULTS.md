# The company brain (v15): results

**Run on 2026-10-10 and 11,** by the rules in `docs/FACTBANK_BRAIN_PREREGISTRATION.md`, frozen at commit `723a70b`
(23:49:24 UTC). The test documents were drawn after it, at 23:50.
- **Raw results, run log and reviews:** `docs/benchmarks/brain/` (`test/`, `prefreeze_review.json`, `postrun_review.json`).
- **All data is fictional:** the benchmark's made-up company.

## In short

**The claim is not met.** v15 was to answer every kind of question at least as well as the best earlier answer for that kind.
- It did on three of the four families.
- **On free text it did not.** Its quoted answers held 0.583 of the answer facts, against 0.707 for plain keyword search with
  the same quoting code. That is −0.12, more than the −0.05 allowed.

**On the other three families, v15 did better than every earlier version.**
- **Single-document questions:** 0.821 against v1's 0.794.
- **Multi-document questions:** 0.972 against v13's 0.889.
- **Questions about something the company does not have:** it said "not found" to all 20 and never said it to an answerable
  question.
- **It is the only version that answers every kind:** 0.844 on the mean over the four families, against at most 0.291 for any
  other.

**The free-text shortfall is real but not large in a way we can pin down.**
- 50 questions are too few: the 95% interval runs from −0.24 to −0.00.
- **Routing is not the cause:** every free-text question went to the free-text route.
- **Finding the document is not the cause either:** both arms quoted the right document in 50 of 50 answers.
- **The cause is which passages v15 cuts from it, and how it ranks them.** A check after the run (not a result) found that v15
  would have tied plain search if its free-text route had used plain search's passages.

**What it shows:** one system answers lookups of fields, lists, deadlines and links across one to six records, finds the passage
in a document that holds a free-text answer, and recognises questions about tickets, pull requests, titles or people that do not
exist.

**What it does not show:** that it answers whatever is asked. The test did not cover:
- combining several documents into one answer in prose;
- counts and filters ("how many tickets are P2?");
- history ("who had it before?");
- knowing when not to answer a natural question;
- most of the company's chat and email.

A few untested probes of these after the run mostly failed.

## Decision

| Rule | Result |
|---|---|
| 1. Single-document questions: v15 ≥ v1 − 0.03 | **Met:** 0.821 against 0.794 (+0.028) |
| 2. Multi-document questions: v15 ≥ v13 − 0.03 | **Met:** 0.972 against 0.889 (+0.083) |
| 3. Free text: v15 ≥ plain search with quotes − 0.05 | **Not met:** 0.583 against 0.707 (−0.123) |
| 4. Not found: ≥ 0.80, and false "not found" ≤ 0.03 | **Met:** 1.000, and 0.000 |
| 5. One brain for every kind: mean ≥ every other arm's + 0.20 | **Met:** 0.844 against 0.291 |
| 6. It holds at size (single, multi, free text) | **Met:** −0.021 against the small set |
| 7. The right route ≥ 0.90 | **Met:** 0.998 |

**The claim (rules 1 to 4) is not met,** because of rule 3.

**The hash-seed check:** v15 asked again under hash seed 1 changed no answer.

## Results

215 questions on 5,000 documents of the test zone: 109 single-document, 36 multi-document, 20 not found, 50 free text.

| arm | single | multi | free text | not found | mean over families |
|---|---|---|---|---|---|
| plain search with quotes | 0.086 | 0.000 | **0.707** | 0.000 | 0.198 |
| v1 | 0.794 | 0.028 | 0.000 | 0.250 | 0.268 |
| v2 | 0.617 | 0.111 | 0.000 | 0.250 | 0.244 |
| v13 | 0.275 | 0.889 | 0.000 | 0.000 | 0.291 |
| **v15** | **0.821** | **0.972** | 0.583 | **1.000** | **0.844** |

**By group:**

| | deadlines | lists | fields | names | descriptive | link | combine | compare |
|---|---|---|---|---|---|---|---|---|
| v1 | 0.933 | 0.800 | 0.800 | 0.553 | **0.795** | 0.067 | 0.000 | 0.000 |
| v13 | 0.467 | 0.467 | 0.300 | 0.000 | 0.179 | 0.733 | 1.000 | 1.000 |
| **v15** | **1.000** | 0.800 | **0.933** | 0.553 | 0.744 | **0.933** | **1.000** | **1.000** |

**The paired differences behind rules 1 to 3** (v15 minus the arm, 95% bootstrap interval):

| | difference | interval |
|---|---|---|
| single: v15 − v1 (109) | +0.028 | −0.018 to +0.073 |
| multi: v15 − v13 (36) | +0.083 | 0.000 to +0.194 |
| free text: v15 − quotes (50) | −0.123 | −0.243 to −0.003 |

**Routes:** single 108 of 109 to a fact route, multi 36 of 36, free text 50 of 50 to prose, not found 20 of 20.

**Time per question at 5,000 documents** (median): v15 4.6 s, v13 4.2 s, v2 1.7 s, v1 0.7 s, plain search 0.02 s.

**The small set** (259 documents, the questions' gold documents only): v15 is 0.029 lower at 5,000 documents on single, 0.034
lower on free text and the same on multi.

## Free text: why v15 fell short

**How close the rule was.**
- v15 won 6 free-text questions, plain search 15, and 29 were ties.
- The interval only just excludes zero (a sign test gives p = 0.08).
- **Counting a fact only inside a quote from the right document,** the gap is −0.10 (−0.22 to +0.02).
- **Pooled with the development set,** where v15 led by +0.01, it is −0.06 over 102 questions.
- **So "v15 is clearly worse at free text" is not shown either.** The rule failed on the point estimate, as written.

**Where the facts were lost.**
- **Not routing:** all 50 free-text questions went to the prose route.
- **Not finding the document:** the right document was v15's first document for 49 of 50 questions, and both arms quoted it in
  every answer.
- **Not the length:** both arms quote up to the same 1,100 characters.
- **The loss is inside the right document.** v15 ranks the passage holding a fact lower. Its first such passage averages rank
  2.7, against 0.6 in plain search. Its quotes then fill the 1,100 characters with other sentences, often from other
  documents' passages.
- **Two differences in how v15 cuts and ranks its passages** (`FactBank.passages`):
  - It ranks passages by which question words they hold, with no weight for how often or in how short a passage. So
    passages tie.
  - It cuts the text into windows that do not overlap. A fact that opens the next window after a quoted sentence is lost.

**A check after the run, not a result** (17 variants were tried with the answers known, so the best is optimistic):
- **Plain search's passages in v15's free-text route** would give exactly plain search's answers: 0.707, and rule 3 met. The mean
  over families would be 0.875.
- **Keeping v15's own documents and changing only the ranking** (BM25) gives 0.670.
- **Changing only the cutting** (overlapping chunks) gives 0.663.
- Each of these is a fix to test on new questions; these test answers cannot judge it.

**The free-text score is not a share of questions answered.** Neither arm writes an answer: each returns about 1,060 characters of
quoted sentences, and the score counts the answer facts' words found in them. Some credit is by chance: one of plain search's
full marks came from another customer's document with the same discount. There is no judge.

## The other families

**Single-document questions (rule 1 met).**
- **v15 and v1 differ on 7 of 109 questions.** v15 wins 5, all through the planner (an SLA date, a status, an assignee, a
  repository, a due date).
- **It loses 2, both descriptive:**
  - one was sent to free text (it asked for an SLA date and how to handle loaner laptops);
  - in the other, a product name stored as a person ("Okta SSO") became the plan's start.
- **Four more questions trail the best arm, repeating v1's own engine errors:**
  - a meeting's ID read as its date;
  - "filed under" read as the reporter;
  - the wrong account found by content;
  - half of an attendee list (only the company's attendees).
- **Names (0.553) are v1's answers exactly:** project members score 0 of 3 and attendee lists about 0.6.

**Multi-document questions (rule 2 met).** 3 wins and no losses against v13.

**Not found (rule 4 met), and what it measures.**
- **All 20 not-found questions are templates:** an invented ticket key, pull request number, quoted title or full name. v15's
  not-found route checks exactly those.
- **It is a check that something named exists,** not whether the brain knows when it does not know.
- **On answerable questions v15 never said "not found",** including the 23 it got wrong.
- **Without this family** the mean over families is 0.792.

## What the test did not cover

- **Combining documents in prose:** every free-text question has one gold document.
- **Counts and filters:** only "how many issues does this person have" (5 questions).
- **History and change:** no question asks about a value that changed.
- **Chat and email:** Slack and Gmail are 80% of the 5,000 documents. No single- or multi-document question has its answer there,
  and 13 of the 50 free-text questions do.
- **Size:** 5,000 documents, about 1% of the company's 512,000. The time per question grows faster than the number of
  documents' square root (7.8 times the time for 19 times the documents).

**An exploratory probe after the run** (10 hand-written questions on the test bank; not pre-registered, not a result):
- **Unanswerable questions without a named key or person:** 0 of 3 got "not found" (a gym reimbursement policy, a Tokyo office, a
  payroll vendor). Each got quotes from unrelated passages.
- **Counts and filters:** 1 of 4 right. "How many Jira tickets have priority P2?" got "P2".
- **History:** "Who was ENG-… assigned to before?" got the current assignee.
- **Cross-document questions** ("which customers asked about SOC 2?") got loosely related quotes.

## Checks

- **Every number recomputes** from the saved answers with the repository's own code.
- **The order of steps holds by file times:** the freeze came before the draw, and the code that ran is the frozen code.
- **The lessons, zones and glossary** match their pre-registered hashes.
- **The writers' files were all complete** (10 batches, 100 questions written). The checks kept 39 of 40 descriptive and 54 of 60
  free-text questions, and the mix was filled as pre-registered.
- **No test-zone document is in any training or development material.**
- **The hash-seed check** changed no answer.
- **Record-keeping to improve:** step 1's printed output was not saved, and the answers files record the lessons' paths, not their
  hashes or the hash seed. Both were confirmed from the files and the script.

The post-run review is `docs/benchmarks/brain/postrun_review.json`: three lenses, each finding checked by a refuter.

## What it means, and what is next

- **One system answers every kind of question tested:** the fact families as well as or better than the best earlier version,
  with near-perfect routing (0.998).
- **For free text it is a passage finder,** and on this test a weaker one than plain keyword search.
- **The next steps, each to be tested on new questions:**
  1. **Free text:** give v15's prose route plain search's passage ranking and overlapping chunks, or the plain search index itself.
  2. **The fact routes:** fix the faults found here: a "when" asked mid-sentence, product names stored as people, the meeting-ID
     tie, and attendee lists that read only one field.
  3. **What was not tested:** add counts and filters, history, questions answered from several documents, natural
     unanswerable questions, and questions drawn in proportion to where the company's text is (chat and email).
  4. **Written answers:** a language model writing answers from v15's evidence, graded by a judge, once keys are available.
     Today v15 returns facts and quotes, not written answers.
