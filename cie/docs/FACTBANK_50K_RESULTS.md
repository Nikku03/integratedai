# The company brain at 50,000 documents, with a language model as its reasoning engine: results

**Run on 2026-10-21** on Colab: an A100 80 GB, Qwen3.8-27B in bf16 (`Qwen/Qwen3.8-27B` at `1d4bf0f`), vLLM 0.30.0,
thinking on with effort "medium". The rules are those of `docs/FACTBANK_50K_PLAN.md`.
- **Order of events** (commit times from the git log; the run's times from its files' creation times on Google Drive,
  listed in the raw results' README; the answer rows themselves carry no times):
  - **2026-10-17:** the plan was written (`c468f67`).
  - **2026-10-19 and 2026-10-21:** it was changed in commits `a215da6` (2026-10-19, 21:38 UTC), `c27b0a9` (2026-10-21,
    15:12 UTC) and `61c794a` (16:14 UTC).
  - **16:19 to 16:43 UTC:** the draw was saved, then v18's answers and run records.
  - **17:03 UTC:** plain search's first answers reached Drive. The reasoner's followed at 18:35 (messy) and 19:00 (tidy),
    and the report at 19:24.

  So every change came before Qwen3.8-27B's first answer. Before that, only local plumbing runs of a small model (Qwen3
  0.6B) answered test questions: 4 a folder before the plan was written, and 6 messy ones on 2026-10-19 (21:42 to 21:51
  UTC, after `a215da6`). As the plan says of runs with `LIMIT`, they decide nothing.
- **The code each arm ran:**
  - Plain search's messy answers and its first 512 tidy ones were made with a checkout from before `61c794a`: they carry
    no settings stamp, and they have `a215da6`'s `passages` field. By the timeline, that checkout is most likely
    `c27b0a9`. Its answer reader and `a215da6`'s read every one of these replies the same.
  - The reasoner and the last 123 tidy plain-search answers ran on `61c794a`.
  - Between `c27b0a9` and `61c794a` only `brain50k.py` changed (the settings stamp, the resume check, row splitting). So
    each arm's prompt, plain search's passages and the reading of answers are the same for both.
  - The plan's amendment header gives only 2026-10-19; two of its edits are from 2026-10-21, both before any model answer.
- **Raw results:** `docs/benchmarks/brain50k/test/` holds both model arms' answers, both folders' run records, the score
  step's report and v18's answers made again locally (see its README).
- **All data is fictional:** the benchmark's made-up company.

## In short

**The claim is met.** All eight rules of the plan were met on the messy set (the casual wordings, which decide). Rules 3
and 5 are met on their point estimates only: their 95% intervals cross the line. Rules 2 to 8 say a bigger reasoning
engine makes the brain better; rule 1 says the brain holds at 50,000 documents.

**What the reasoning engine adds** (635 questions on 50,000 documents):
- **Complex questions** (three or four steps over several records; 62 of the 126 cross from one system to another):
  **0.929**, against 0.167 for the brain alone and 0.190 for plain search with the same model.
- **The mean over round 4's eight families:** **0.958**, against 0.878 and 0.668.
- **Free text:** 0.813, against 0.625 and 0.702.
- **False "not found" on answerable questions:** **0.016** (8 of 498), against 0.032 and 0.277.
- **Change against the brain alone:** better on 168 questions, worse on 19.

**What the logs show** (the model's thinking is not stored, and no arm tests the tools without the model or the model
without the brain's answer):
- **Complex questions:** in 80 of its 96 wins over the brain, the model made the brain's missing steps with its tools
  (`find`, `read`, `search`, `values`). In the other 16 it needed no tool: the brain's own evidence held the answer.
- **Keeping the brain's answer:** it kept it word for word on about 62% of the questions.
  - Where the brain was not fully right (188 questions), it raised 168.
  - Where the brain was right (447 questions), it lowered 19 (4%).
- **Its losses:** in 17 of the 19, it changed a right brain answer. It overruled 6, and it shortened 11 right free-text
  quotes with no tool call, against its prompt.

**Why plain search does badly:**
- In 211 of its 219 wrong answers in single, multi, counts, history, email and chat, and complex, the 12 passages did not
  hold the answer.
- It cannot count over 50,000 documents from 12 passages (counts 0.073).
- It cannot follow a link in one search (multi 0.323).
- In this setup it sees only the first part of a long record, because only a record's first chunk carries its key
  (history 0.500).

**The brain at 50,000 documents** lost a little:
- **Rule 1's measure:** −0.019 (95% interval −0.034 to −0.005), against a bar of −0.05.
- **Where:** single −0.073, free text −0.056 and not found −0.027.
- **Why:** the 20 questions that got worse in those three families were traced one by one.
  - In half, a new document now ranks above the right one.
  - The rest come from a name with more records, a company stored as a person and new field names.
  - These causes are read from the brain's steps; none was tested by taking the new documents out.
  - Six unanswerable questions also got worse, and six got better.

**What it shows:**
- On one fictional company's records, a language model working through exact tools answered 0.929 of templated
  multi-step questions. The rule-based brain answered 0.167 of them, and search with the same model 0.190.
- Its scores on counts (0.982 against 0.947) and not found (0.973 against 0.973) are no lower than the brain's. But the
  not-found interval runs down to −0.081, and it overruled the brain's right answer on one count and on four questions
  whose answer was "not found".

**What it does not show:**
- **Real company data:** the documents are generated.
- **Fresh questions:** round 4's questions were scored before.
- **More than one sampled run:** a rerun moves the scores. On the same question text, the reasoner scored 0.929 on the
  complex questions in one folder and 0.952 in the other.
- **Questions people would write:** the complex questions are templated from the same record fields the reasoner's
  `find` filters on.
- **Free text, beyond the scorer:** answers are judged by word-matching code. About two thirds of the reasoner's
  free-text lead over plain search is wording the scorer misses. With wording forgiven, the rest (+0.038) cannot be told
  from zero.
- **Stronger plain search:** plain search had one BM25 search and no tools. No vector search, reranker or model allowed to
  search again was tried.

## Decision (the messy set)

| Rule | Result |
|---|---|
| 1. The brain holds at size: v18 at 50,000 − v18 at 5,000 ≥ −0.05 (mean over the eight families, paired, on round 4's questions whose answers did not change) | **Met:** −0.019 (95% interval −0.034 to −0.005) |
| 2. Better overall: the reasoner's mean of the eight families ≥ v18's + 0.03 | **Met:** 0.958 against 0.878 (+0.080; interval +0.050 to +0.112) |
| 3. Free text: reasoner ≥ v18 + 0.10 | **Met:** 0.813 against 0.625 (+0.188; interval +0.067 to +0.312) |
| 4. Complex questions: reasoner ≥ v18 + 0.20 | **Met:** 0.929 against 0.167 (+0.762; interval +0.683 to +0.833) |
| 5. No harm where the brain is exact: not found, counts and unanswerable, each ≥ v18 − 0.05 | **Met:** not found 0.973 against 0.973; counts 0.982 against 0.947; unanswerable 0.960 against 0.870 |
| 6. Few false "not found": ≤ 0.05 of answerable questions | **Met:** 0.016 (8 of 498) |
| 7. Better than plain search with the same model: mean of the eight families ≥ rag's + 0.05 | **Met:** 0.958 against 0.668 (+0.290; interval +0.254 to +0.326) |
| 8. … and on complex questions: ≥ rag + 0.10 | **Met:** 0.929 against 0.190 (+0.738; interval +0.651 to +0.817) |

**The claim (rules 2 to 8) is met, and so is rule 1.**

The intervals for rules 1, 2 and 7 are stratified over the eight families (`memory_test.stratified_ci`, 2,000 resamples).
The others are the report's paired bootstrap intervals.

Two of the rules pass on their point estimate while their interval crosses the line:
- **Rule 3:** the free-text interval goes down to +0.067.
- **Rule 5:** the not-found interval runs from −0.081 to +0.081.

Exact ties are rounded up here (0.8125 is 0.813, 0.0625 is 0.063). The report itself rounds them to even.

## Results

**The messy set** (635 questions):
- round 4's questions that still hold: single 124, multi 31, free text 80, not found 37, counts 57, history 40, email and
  chat 40, unanswerable 100;
- complex 126.

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | complex | mean of 8 | false not found |
|---|---|---|---|---|---|---|---|---|---|---|---|
| plain search (rag) | 0.858 | 0.323 | 0.702 | **1.000** | 0.073 | 0.500 | 0.937 | 0.950 | 0.190 | 0.668 | 0.277 |
| v18 | 0.803 | 0.903 | 0.625 | 0.973 | 0.947 | 0.950 | 0.950 | 0.870 | 0.167 | 0.878 | 0.032 |
| **reasoner** | **0.960** | **1.000** | **0.813** | 0.973 | **0.982** | **0.975** | **1.000** | **0.960** | **0.929** | **0.958** | **0.016** |
| v18 at 5,000 (round 4's answers), on the 454 questions | 0.876 | 0.903 | 0.681 | 1.000 | 1.000 | 0.950 | 0.950 | 0.870 | | 0.904 | 0.035 |
| v18 at 50,000, on the same 454 questions | 0.803 | 0.903 | 0.625 | 0.973 | 1.000 | 0.950 | 0.950 | 0.870 | | 0.884 | 0.050 |

- **The 454 questions** are round 4's questions whose answers are the same at 50,000 documents. Rule 1 compares the last
  two rows.
- **Counts there rest on 2 questions:** 55 of the 57 were counted again over the 50,000 documents, so they have new
  answers and are left out of rule 1.
- **False "not found" on the 454:** 11 of their 317 answerable questions at 5,000 documents, and 16 of the same 317 at
  50,000. All 16 of v18's false "not found" answers (16 of 498 in the row above) are among them.

**The tidy set** (the same questions in the generators' wordings; reported, not decided on):

| arm | single | multi | free text | not found | counts | history | email, chat | unanswerable | complex | mean of 8 | false not found |
|---|---|---|---|---|---|---|---|---|---|---|---|
| plain search (rag) | 0.863 | 0.323 | 0.702 | 1.000 | 0.091 | 0.475 | 0.962 | 0.950 | 0.190 | 0.671 | 0.263 |
| v18 | 0.855 | 0.935 | 0.625 | 1.000 | 0.982 | 1.000 | 1.000 | 0.910 | 0.167 | 0.913 | 0.030 |
| **reasoner** | **0.952** | **0.968** | **0.804** | 1.000 | 0.982 | 1.000 | 1.000 | **0.970** | **0.952** | **0.959** | **0.018** |

Rules 2 to 8 also hold on the tidy set by their point estimates. Rule 2 has the thinnest margin there: the reasoner is
+0.046 above v18, with interval +0.022 to +0.070, so the interval crosses the +0.03 line. (The report gives the
reasoner's tidy mean as 0.960, an average of family means already rounded; unrounded it is 0.9595.)

**The complex questions by kind** (messy):

| kind | steps | questions | reasoner | rag | v18 |
|---|---|---|---|---|---|
| assignee_open_p: an issue's assignee, then their open issues of one priority, counted | 4 | 16 | **1.000** | 0.000 | 0.063 |
| compare_due_assignee: two issues, the one due first, its assignee | 3 | 16 | **1.000** | 0.875 | 0.000 |
| creator_jira_load: an issue's creator, then their Jira tickets, counted | 3 | 16 | **1.000** | 0.000 | 0.938 |
| email_account_owner: a thread's account, then its HubSpot owner | 4 | 16 | **0.750** | 0.000 | 0.125 |
| meeting_account_owner: a meeting's customer, its account, the owner | 4 | 7 | **1.000** | 0.000 | 0.000 |
| meeting_account_stage: … the account's stage | 4 | 7 | **1.000** | 0.000 | 0.429 |
| owner_meetings: a meeting's owner, then their meetings, counted | 3 | 16 | **1.000** | 0.000 | 0.000 |
| pr_assignee_load: a pull request's issue, its assignee, their issues, counted | 4 | 16 | **0.875** | 0.000 | 0.000 |
| project_first_due: a project's issues, the one due first, its assignee | 3 | 16 | **0.813** | 0.625 | 0.000 |

By steps: the reasoner scored 0.953 on the 64 three-step questions and 0.903 on the 62 four-step ones; plain search 0.375
and 0.000; v18 0.234 and 0.097.

**Paired differences** (messy; mean, 95% interval, questions better and worse):

| | single | multi | free text | not found | counts | history | email, chat | unanswerable | complex | all |
|---|---|---|---|---|---|---|---|---|---|---|
| reasoner − v18 | +0.156 [0.089, 0.221] 21/1 | +0.097 [0.0, 0.194] 3/0 | +0.188 [0.067, 0.312] 28/12 | 0.000 [−0.081, 0.081] 1/1 | +0.035 [−0.035, 0.105] 3/1 | +0.025 [−0.05, 0.125] 2/1 | +0.050 [0.0, 0.125] 2/0 | +0.090 [0.02, 0.17] 12/3 | +0.762 [0.683, 0.833] 96/0 | +0.232 [0.197, 0.269] 168/19 |
| reasoner − rag | +0.102 [0.041, 0.165] 16/2 | +0.677 [0.484, 0.839] 21/0 | +0.110 [0.056, 0.171] 14/0 | −0.027 [−0.081, 0.0] 0/1 | +0.909 [0.825, 0.976] 52/0 | +0.475 [0.3, 0.625] 20/1 | +0.063 [0.005, 0.138] 4/0 | +0.010 [−0.04, 0.06] 4/3 | +0.738 [0.651, 0.817] 94/1 | +0.329 [0.291, 0.368] 225/8 |
| rag − v18 | +0.055 [−0.032, 0.14] 18/11 | −0.581 [−0.742, −0.419] 0/18 | +0.077 [−0.048, 0.215] 26/19 | +0.027 [0.0, 0.081] 1/0 | −0.874 [−0.962, −0.769] 1/51 | −0.450 [−0.6, −0.3] 0/18 | −0.013 [−0.113, 0.095] 2/4 | +0.080 [0.01, 0.15] 11/3 | +0.024 [−0.079, 0.127] 24/21 | −0.097 [−0.141, −0.053] 83/145 |
| v18 at 50k − at 5k | −0.073 [−0.137, −0.008] 5/14 | 0.000 0/0 | −0.056 [−0.106, −0.013] 0/5 | −0.027 [−0.081, 0.0] 0/1 | 0.000 0/0 | 0.000 0/0 | 0.000 0/0 | 0.000 [−0.07, 0.07] 6/6 | | −0.032 [−0.058, −0.007] 11/26 |

"all" pools every question (the complex ones too, for the first three rows), so it is not the rules' mean of the eight
families. On that mean, rule 1's difference is −0.019 [−0.034, −0.005], rule 2's +0.080 and rule 7's +0.290.

**How the arms ran** (messy):

| arm | time | output tokens a question | prompt tokens a question | tool calls | cut off at the token limit | out of room in the window |
|---|---|---|---|---|---|---|
| v18 | 632 s, in 10 processes | | | | | |
| rag | 1,376 s | 456 | 3,540 | | 0 | |
| reasoner | 1,556 s | 532 | 9,245 | 1,424 (2.24 a question) | 0 | 0 |

- **Every model conversation ended with an answer of its own.** None was cut off, ran out of room or fell back on the
  brain's answer.
- **The model arms were faster than planned.**
  - The reasoner took about 26 minutes a folder (1,556 s messy, 1,596 s tidy), against the plan's 2 to 3.5 hours.
  - Plain search took 23 minutes on the messy folder, against 30 to 45. (Its tidy run was cut off and resumed, so its
    time there is not recorded whole.)
  - Two things may explain it, and the rows cannot show how much each does. The model thought briefly: on average about
    140 tokens of thinking a turn or less. And the notebook lets the GPU hold up to 256 conversations at once, where the
    estimate assumed 10 to 50.

## Checks of the result

Six analyses read the answers themselves. Each was checked again by a second reader, who recomputed its key numbers and
listed what they could not check. Their corrections are applied below. The answer files, scripts and outputs were in the
session's scratch space; the answers are in `docs/benchmarks/brain50k/test/`.

### 1. The answers are the ones scored, and one model made them

- **The scores reproduce.** Scored here again with `brain50k.score_one`, both model arms match the report on all 635
  questions in both folders.
- **v18's answers reproduce.** Colab's v18 answer files are larger than the Drive connector could fetch, so v18 was
  asked all 1,270 questions again here.
  - The bank was built here from the same 50,000 documents: the draw's document list is the same as Colab's
    `haystack.json`, in the same order.
  - Every answer gave Colab's score and answer length: 635 of 635 in each folder.
  - These answers are in the raw results.
- **The answers read the same with the final code.** Every model row keeps the model's visible reply. Read again with the
  final code, 1 answer of 2,540 differs (prose-1022-066, whose stored reply is cut at 1,500 characters), and no score.
- **One model and one setting.**
  - Every reasoner row carries its settings: Qwen3.8-27B in bf16, effort medium, thinking on, 6,144 tokens.
  - Plain search's first 1,147 answers (635 messy, 512 tidy) were made with code from before rows carried settings. The
    messy run record gives the same settings.
  - The tidy folder's plain search was cut off after 512 answers, made right after the messy folder's in the same
    session. It was resumed for the last 123, which carry the same settings. 118 of those 123 answers are word for word
    the messy run's answers to the same questions.
  - The score step found no mismatch.

### 2. Is any of the lead a scoring artifact? No verdict changes.

The scorer is lenient by design. A person or value counts when it appears on the answer line, and a count by its first
number. So we looked for answers that win by hedging.
- **The reasoner never hedges.**
  - Of its 178 credited person and value answers, 175 are exactly the expected value. The other 3 are one-person
    sentences ("ENG-781901 is due first (2026-03-20) and is assigned to Liam Chen.").
  - None of its 130 count answers gives a range or a second number.
  - Each of its 132 "not found" credits is a literal "not found" from the model. The reader that maps other refusals to
    "not found" made none.
- **Plain search hedged once** (desc-1021-014: "In Review (moved from In Progress …)" for "In Progress").
- **A strict rescore changes no verdict.** In it, a person or value answer scores only if the first candidate it names is
  the expected one, and a hedged count scores 0:
  - rule 2: +0.080 becomes +0.081;
  - rule 7: +0.290 becomes +0.291;
  - rules 3, 4 and 8 do not change.
- **Free text against v18** is not won by length: v18's answers are the long ones (890 characters on average, against
  169).
- **Free text against plain search** is mostly wording. The reasoner leads by +0.110 (95% interval +0.056 to +0.171).
  - Plain search often gives a fact in its own words ("1% for 2 hours → 10% …" for "start at 1% for 2 hours"). The scorer
    then misses it.
  - Count a fact as present when all its figures are there (or, for a fact with no figures, half its words), and the lead
    falls to +0.038 (interval −0.019 to +0.094). Its interval then includes zero.
  - This does not move rule 7: even with plain search's free-text score, the reasoner leads by +0.276.

### 3. Where the reasoner goes wrong

It scored below 1 on 42 of the 635 messy questions. All 19 questions where it did worse than v18 are among them.

| cause | questions | of them worse than v18 |
|---|---|---|
| A right free-text answer in fewer of the record's words than the scorer needs | 18 | 12 |
| Wrong tool use, where the brain was wrong too | 11 | 0 |
| It overruled a right brain answer | 6 | 6 |
| Search could not reach one account ("Acme AI"), or it answered from a similar record | 5 | 0 |
| The question itself | 1 | 1 |
| It trusted a wrong brain answer | 1 | 0 |

In 17 of the 19 losses to v18 the reasoner changed a right brain answer: 6 by overruling it, and 11 by shortening the
brain's right free-text quote with no tool call.

- **Shortened quotes.**
  - In 11 of the 12 free-text losses to v18, the reasoner made no tool call. It shortened the brain's right quote, for
    example to "2025-02-22" for the fact "Usability test scheduled 2025-02-22".
  - Its prompt asked it to keep the record's words, so this is the model not following its instruction as much as the
    scorer.
  - Matching v18 on those 12 would give free text 0.925 and the mean of the eight 0.972.
- **Tools that fail silently or mislead.** These cost the model calls:
  - `find` on a field that does not exist returns 0 records with no error: 75 calls, mostly HubSpot "name".
  - `values` names a missing field, but lists only a system's first 80 field names, so HubSpot's 427 leave out "owner"
    and "stage".
  - `read` refuses anything but a record id: 140 of 451 reads failed, most given a ticket key.
  - `search` applies its system filter after the 200 best hits overall, so "Acme AI" in HubSpot is never reached.
- **Look-alike records.** Of the 24 failures not caused by the scorer, 8 hinge on a look-alike of the right record that
  is among the 45,000 documents added for this test (9 counting desc-1021-036). The reasoner was not run at 5,000
  documents, so this is not a measured effect of size.
- **Sampling.** 5 of the 9 complex failures were right in the tidy run of the same question, and 2 complex successes were
  wrong there.

### 4. How the reasoner worked

- **Calls a question:** median 1, mean 2.24.
  - 40% of the questions took no tool call.
  - 9% used all 8 calls; they still scored 0.805, against v18's 0.576 on the same questions.
- **Calls by tool:** search 629, read 451, find 277, values 53, brain 14.
- **Where the calls went:**
  - It trusted the brain on counts, history and email and chat: over 90% of those answers are the brain's.
  - It worked hardest on unanswerable questions: 36% of all calls. It turned 12 of v18's wrong answers there into a right
    "not found", and 3 of v18's right "not found" answers into an answer from a similar record.
- **The usual complex chain:**
  - find the record, by search or by a `find` on its key;
  - read its fields;
  - count or list with `find`, calling `values` when a field name was wrong.

Two chains:
- **complex-owner_meetings-001** asks how many meetings the owner of "API Bootcamp — Credits & Deployment Fit" owned
  (expected 13).
  - The brain said 18: it counted the meetings that person attended.
  - The reasoner searched, read "redwood owner: Jordan Park", and tried `find` on "redwood owner", which matched nothing.
  - It then called `values`, learned the field is `redwood_owner`, and found 13.
- **complex-pr_assignee_load-001** asks how many Linear issues the assignee of PR #984321's issue has (expected 3).
  - The brain said 1.
  - The reasoner found ENG-4833 among the linked keys, assigned to Felix Schneider. `find` then gave his 3 issues.

### 5. Why plain search fails

The run's passages were rebuilt here, and for all 635 questions they are the ones the run showed (12 each, 11 for
nf_pr-022). Each wrong answer was then checked against what the passages held.
- **Counts:** 12 passages cannot show 25 records, the median count. 43 of its 53 wrong counts equal the number of matching
  records it was shown, so it counted what it saw correctly.
- **Multi:** in all 20 questions that follow a link, the linked record was never retrieved. Its key is not in the
  question.
- **History:** in all 18 comment questions, the record was found but only its first chunk was shown. The comments sit in
  later chunks, which never rank.
- **Complex:** the HubSpot account at the end of a chain was never shown (0 of 30).
- **Not because of parsing.** Its stored answers are what the reader gives (634 of 635), every reply finished, and its
  270 "not found" answers are its own.
- **The prompt was not varied.** No other prompt was tried. Its rule to say "not found" rather than guess cost it some
  answers: in 14 of the 18 comment questions, the chunk it saw held the expected value in another field.
- **How much a better design could gain.** Two weaknesses are this design's, not plain search's as such: only a record's
  first chunk holds its key, and one record's chunks crowd the 12 slots.
  - Fixing the 27 right-record-wrong-part answers would help most. So would fixing the 8 wrong answers whose passages
    held the answer: 4 misreads, and 4 format or gold-label penalties. Together they would raise plain search's mean of
    the eight to 0.744. That is the gain from fixing these failures, not a ceiling for a better design.
  - Rule 7 would still hold. Complex, and so rule 8, would not change.

### 6. Why the brain lost a little at 50,000 documents

The 20 questions that got worse in single, free text and not found were asked again here and traced through the brain's
steps on both banks. (6 unanswerable questions also got worse, cancelled out by 6 that got better; those were not
traced.)

| cause | questions |
|---|---|
| A new document now ranks above the right one, which is still there | 10 |
| The name in the question now has many more records (one owner's action items, 1 → 5) | 4 |
| A company is now stored as a person, from a new email's external participants | 3 |
| New field names (502 → 1,851) make topic words count as asked-for fields in the not-found check | 2 |
| The same right document, quoted from other passages (cause not found; perhaps the same shift in word weights) | 1 |

- The causes are read from the brain's steps. None was tested by taking the new document, alias or field out again.
- Two of the 20 (desc-1021-030 and -033) found the right answer, then withheld it as "not found".
- The reasoner got 18 of the 20 right; plain search got 13.5.

### 7. Wording and noise

- **v18 does not vary between runs.** It changed only on reworded questions: 19 were worse in casual wording. The
  reasoner got all 19 right in both folders. So its lead over v18 is larger on the messy set (+0.080) than on the tidy
  one (+0.046).
- **The model arms vary even on the same text.** 316 questions have the same text in both folders. There, the reasoner's
  score changed on 19 and plain search's on 3.
  - The reasoner scored 0.929 on the 126 complex questions in one run and 0.952 in the other.
  - Both runs used seed 0, and many same-text replies are word for word the same. So this likely understates the noise
    between independent runs.

## What it does not show

- **One company, generated documents:**
  - the benchmark's fictional company, not real records;
  - the complex questions are templated, tidier than people write.
- **Seen questions:** round 4's questions were scored before. This is a test at size, not a fresh test.
- **One sampled run:** at temperature 1.0, a rerun gives somewhat different answers, as section 7 shows.
- **The scorer is code:** a free-text answer is scored by the record's words it holds, which favours copying.
- **Stronger plain search:** BM25 over 12 passages of about 1,000 characters, as in round 4. Vector search, reranking or
  a model allowed to search again were not tried.
- **The tools read the brain's own fact bank:** `find` and `values` filter its fields exactly, and those fields come
  straight from the generated records' structured fields. Real records would be messier. Even here the bank stores three
  companies as people and files one thread under a second spelling ("SolsticeHealth"), which cost the reasoner
  count_gmail-262.

## What next

- **Fix the tools that fail silently or mislead.** These are cheap fixes, and each failure cost calls:
  - `find` should name a field that does not exist, and `find` and `values` should list every field or the closest ones;
  - `read` should take a ticket key;
  - `search` should filter by system before it ranks.
- **Free text:** pass the brain's quote on verbatim when the reasoner keeps it, or check that the facts survive a
  rewrite.
- **The brain at size:** treat external email participants as companies, not people. Keep field names out of the
  not-found check's topic words. Let the finder see past a near tie.
- **A fresh test:** new questions at 50,000 documents, and real records if any can be had.
