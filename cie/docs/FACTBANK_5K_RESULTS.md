# The fact bank at 5,000 documents: results

**Run on 2026-10-10**, by the rules in `docs/FACTBANK_5K_PREREGISTRATION.md` (part A) and
`docs/FACTBANK_5K_B_PREREGISTRATION.md` (part B). Both were frozen at commit `7dae3b8` (08:30:08 UTC). Part A's test set was
drawn after it, at 08:30:41; part B's primary questions were drawn at 08:54.
- **Raw results, run scripts and reviews:** `docs/benchmarks/factbank_5k/` (`part_a/`, `part_b/`).
- **All data is fictional:** the benchmark's made-up company.

## Both parts in short

**Part A: the planner's own answers hold at 5,000 documents.** All five rules were met: v13 scored 0.968 at 5,000 documents
against 0.984 on a small bank holding only the documents the questions need. Size cost one question, through a system named
in passing ("for the status email").

**Part B: the fact bank's evidence does not beat the memory bank's at 5,089 documents.** Rules 1 and 2 were not met for the
untrained fact bank, so "replace" is not met. (Rule 4, storage, was stated in advance to fail, and did.)
- **Its answers still hold:** 0.849 at 5,089 documents against 0.866 on the small set.
- **Its evidence text is what broke:** blocks about people who post often in one Slack channel are printed first and push the
  answer down.
- **Plain keyword search beats both banks' evidence at this size.**
- **The trained fact bank's evidence holds the answer near the top almost every time,** but because it prints its own
  candidate answers first, not because of what it learned.

# Part A: the planner's answers at 5,000 documents

## In short

**It holds at 5,000 documents: all five pre-registered rules were met.**
- **v13 scored 0.968 at 5,000 documents, against 0.984 on the small bank** holding only the documents the questions need. That
  is −0.016, inside the −0.05 allowed, and above the 0.92 level.
- **v14** (v13 with the small model's form) scored the same on both banks.
- **The planner's lead over the old planner holds:** v9 − v4 = +0.307 and v9 − v8 = +0.167 at 5,000.
- **Every right answer came from the right plan** on both banks.

**One question was lost to size, and the way it was lost is systematic.**
- "When is the ticket linked to pull request #193 due? I need the deadline date for the status email."
- The bank reads "email" as naming Gmail and prefers a plan that ends in Gmail whenever one exists. At 5,000 documents one
  almost always exists, through the people on the pull request.
- **The same wording was asked about one other pull request** and answered right, only because that pull request's people have
  no path to Gmail.
- **A review probe asked this wording about all 11 pull requests in the questions.** With only the small set, v13 got 11 right.
  With the small set plus the 274 Gmail documents those pull requests' people reach, it got 1 right.
- **So the margin is about three link questions.** Had the second question also failed, v13 would be at 0.952, still inside the
  rules.

**What the result rests on, read plainly:**
- **50 questions, but about 42 independent checks.** Questions that share documents form 42 groups.
- **The pull request questions are the easy form.** 13 of the 14 sit on the 10 planted pairs, where the pull request links one
  ticket in the bank. No pull request in this draw links more than one ticket in the bank.
- **The extra documents crowd the people, not the tickets.** Of the 4,895 extra documents, 681 name a person the questions ask
  about, 21 refer to a ticket they ask about, and none mention a pull request they ask about.
- **About 4 seconds per question** at 5,000 documents with the machine to itself, against about a quarter of a second on the
  small bank. The cost is in looking up names, and it grows with the number of names in the bank.

## Decision

| Rule | Result |
|---|---|
| 1. Nothing lost to size (v13 at 5,000 ≥ v13 small − 0.05) | **Met:** 0.968 against 0.984 (−0.016) |
| 2. The level holds (v13 at 5,000 ≥ 0.92) | **Met:** 0.968 |
| 3. The planner's lead holds (v9 − v4 ≥ +0.10 and v9 − v8 ≥ +0.05, at 5,000) | **Met:** +0.307 and +0.167 |
| 4. The same with the small model's form (v14 at 5,000 ≥ v14 small − 0.05) | **Met:** 0.968 against 0.984 |
| 5. Right for the right reason (v13 at 5,000 ≥ small − 0.05) | **Met:** 0.968 against 0.984 |

**Rules 1 and 2 decide: it holds at 5,000.**

**Counted by group of questions sharing documents** (the post-run review's count), the rules give the same answers. v13 goes
from 0.976 to 0.952, and v14 the same. At 5,000, v9 is 0.874, v4 0.548 and v8 0.706.

## Results

Own answers, three-group mean. 50 questions: link 21, combine 22, compare 7.

| arm | bank | link | combine | compare | mean | right for the right reason |
|---|---|---|---|---|---|---|
| v1 | small | 0.143 | 0.000 | 0.000 | 0.048 | – |
| v1 | 5,000 | 0.381 | 0.000 | 0.000 | 0.127 | – |
| v4 | small | 0.524 | 0.682 | 0.714 | 0.640 | 0.450 |
| v4 | 5,000 | 0.429 | 0.455 | 0.857 | 0.580 | 0.390 |
| v8 | small | 0.762 | 0.682 | 0.714 | 0.719 | 0.513 |
| v8 | 5,000 | 0.667 | 0.636 | 0.857 | 0.720 | 0.530 |
| v9 | small | 0.952 | 0.761 | 1.000 | 0.904 | 0.863 |
| v9 | 5,000 | 0.905 | 0.756 | 1.000 | 0.887 | 0.847 |
| v11 | small | 0.952 | 0.815 | 1.000 | 0.922 | 0.863 |
| v11 | 5,000 | 0.905 | 0.815 | 1.000 | 0.907 | 0.847 |
| v12 | small | 0.952 | 0.815 | 1.000 | 0.922 | 0.863 |
| v12 | 5,000 | 0.905 | 0.815 | 1.000 | 0.907 | 0.847 |
| **v13** | small | 0.952 | 1.000 | 1.000 | **0.984** | **0.984** |
| **v13** | 5,000 | 0.905 | 1.000 | 1.000 | **0.968** | **0.968** |
| **v14** | small | 0.952 | 1.000 | 1.000 | **0.984** | **0.984** |
| **v14** | 5,000 | 0.905 | 1.000 | 1.000 | **0.968** | **0.968** |

**v13 misses two questions.**
- `pr_issue-due_date-127`, at 5,000 only: the loss to size, below.
- `ticket_link-assignee-067`, on both banks: not about size, below.

### What changed between the banks, by group

The pre-registration promised the changed questions grouped by the documents they are about. `scale_report.json` lists them
flat. Here they are grouped. Each line is one group of questions sharing documents; "lost" means right on the small bank and
wrong at 5,000.

| arm | lost at 5,000 | gained at 5,000 |
|---|---|---|
| v13, v14, v11, v12 | 1 group: `pr_issue-due_date-127` (PR #193) | – |
| v9 | the same, plus `action_owner_issues-089` (0.5 → 0) | `action_owner_issues-092` (0 → 0.4) |
| v8 | 4 groups: `-158`, `compare_two-159`, `pr_issue-status-072`, `pr_issue-status-125` | 2: `compare_two-160`, `-165` |
| v4 | 8 groups: `action_owner_issues-158`, `-110`, `-122`, `compare_two-159`, `pr_issue-assignee-113`, `ticket_link-assignee-130`, `person_first-008`, `-060` | 2: `compare_two-160`, `-165` |
| v1 | – | 5: `pr_issue-due_date-127`, `-085`, `-070`, `issue_pr_author-author-146`, `-106` |

### The loss to size: a system word in passing

**What happened to `pr_issue-due_date-127`:**
- The question: "When is the ticket linked to pull request #193 due? I need the deadline date for the status email."
- On the small bank, v13 planned "pull request → linked ticket → due date" and answered right.
- At 5,000 it planned "pull request → reviewers → their Gmail mailboxes → first email date → earliest". It answered with an
  email's subject from a reviewer's mailbox.
- v9, v11 and v13 made the same plan. v12 and v14 went the same way, then ended at a mailbox label.

**Why:**
- The bank maps "email" to Gmail. When a question names a system its starting point does not belong to, the planner keeps only
  plans that end in that system, if any exists.
- On the small bank, no plan from the pull request reaches Gmail: the small set holds only Linear, GitHub and Fireflies
  documents. So that check never acts there.
- At 5,000 documents, the pull request's four reviewers are named in 135, 63, 18 and 2 Gmail documents. That is enough for a
  plan to reach Gmail.

**A correction to the pre-registration.** It said the plan ends in Gmail because "at 5,000 there are Gmail documents about the
ticket". That is wrong for this run.
- No Gmail document in the 5,000 mentions the ticket (ENG-4821) or the pull request.
- **The real route is the pull request's people:** their mailboxes, the threads they took part in, and outside contacts who share
  their names.
- The pre-freeze review had flagged the wording, but it stayed in the frozen text.

**How general it is** (the post-run review's probe, on copies, with the frozen v13):
- 72 of the 77 pull requests in the 5,000 reach Gmail within two steps. So do 10 of the 11 asked about.
- **The other question with the same wording, `pr_issue-due_date-070`, was right** only because its pull request (#43678) is the
  one with no path to Gmail.
- **The probe asked the wording about all 11 pull requests:**
  - on the small set, 11 of 11 right;
  - on the small set plus the 274 Gmail documents those pull requests' people reach, 1 of 11 right: #43678.
- The pre-registration's dry run on a seen set had lost all three questions in this wording.

**What it means:**
- **This is the main thing size broke.** A system named in passing ("for the status email") pulls the answer into that system
  whenever a path exists. At 5,000 documents a path almost always exists.
- **The draw asked this wording twice and lost once.** Losing both would have given 0.952, −0.032, still inside rules 1 and 2.
  About three more such losses would break rule 1.
- **The small set can never show it,** because it has no Gmail documents.

### The miss on both banks

`ticket_link-assignee-067`: "who is on the other ticket ENG-96111 is linked to?"
- **v13 answered the ticket's own assignee** (Riley Kapoor) on both banks, not the assignee of its parent issue (Miguel Rivera).
- **This is not about size:** the plan was identical on both banks.
- **A side issue the review found:** the ticket's `links` field holds a branch URL named after the ticket itself. The bank turns
  that into a link from the ticket to itself. 19 of the 400 tickets in the set have one.
- **Removing that self-link does not fix this answer.** The review re-asked the question on a copy of the bank without it. v13
  still read the ticket's own assignee, by another plan. The miss comes from the planner ranking "this ticket's own assignee"
  above "parent issue → assignee" for "the other ticket".
- The self-link itself is a real inconsistency: the ingest code drops a document's own key from its references, the fact bank
  does not. It is noted for later, not fixed here.

### The old planner shows the other size hazard

v4 lost 0.06 at 5,000, over 8 separate groups. At 5,000 the people asked about have relations they lack on the small bank, and
v4 used them:
- Sofia Patel is also the creator of 2 tickets, and v4 answered through "creator of".
- Jordan Lee attends 9 meetings at 5,000 and none on the small bank, and v4 went through the meetings' action items.
- For Maya Chen, Ethan Cole and Luca Moretti it went through meeting attendees; for two pull request questions, through
  reviewers.

v13 chose "assignee of" or "linked ticket" on all of these. So "many more paths for the planner" is a real hazard at size, and
v13's lessons handle it on these questions. The small control removes the questioned people's own other relations, not only
unrelated documents.

**v1's gain (+0.079) does not mean size helps.** v1 matches the question's words against the bank's content. On the small bank
it gives the same wrong answer to many questions (one date 5 times, one Confluence title 5 times). At 5,000 it finds the right
documents for 4 link questions. The small control isolates size for the planner arms, not for a content-matching arm.

### The questions set aside

23 questions had more than one right answer and were set aside, as pre-registered: 21 about "tickets" (Linear only, or Linear
and Jira) and 2 about linked tickets (a second ticket linking to the named one).

| | v4 | v8 | v9 | v11 | v13 | v14 |
|---|---|---|---|---|---|---|
| strict (Linear only) | 0.049 | 0.087 | 0.087 | 0.267 | 0.443 | 0.443 |
| lenient (either reading) | 0.399 | 0.261 | 0.478 | 0.673 | 0.957 | 0.957 |

- **v13 answers Linear and Jira on all 21 "tickets" questions,** as it was taught. The strict score measures disagreement with
  the generator's Linear-only key, not errors.
- **Its one lenient miss is the other reading of a linked question.** For `ticket_link-assignee-156` it named the assignee of the
  ticket that links to the named one. So it is right under one reading on all 23.
- **Few people:** several are asked about more than once (Diego Ramos four times).

## Time, size and the checks

**Time per question** (v13, median):

| | 5,000 documents | small bank |
|---|---|---|
| seven arms at once on 4 cores (reported) | 6.6 s (90th percentile 10.4 s) | 0.36 s |
| alone (the hash-seed rerun, and the review's rerun) | **4.1 s** (90th percentile 6.5 s) | **0.24 s** |

- **Why it is slow:** looking up the names in a question runs one regular expression per name in the bank, several times per
  question. Python caches 512 compiled expressions. The small bank has about 300 names; the 5,000-document bank has thousands,
  so every expression is compiled again on each call.
- **As frozen, the time grows with the number of names.** It would reach tens of seconds at 50,000 documents.
- **It looks like a cost of the code, not the method.** One compiled matcher, or remembering the lookup within a question,
  would remove most of it. In the review's probe, a precompiled matcher gave the same output at about 0.5 ms per call, against 1.35 ms.
- **v14 is not faster than v13.** Its 4.3 s median came mostly from running alone, after the other arms.

**Size:** the two 5,000-document banks take 95 and 103 MB, built in 9 and 14 seconds. Peak memory was 468 MB while building and
about 190 MB while asking. The small banks take 3.4 and 3.8 MB.

**Checks:**
- **The hash-seed check:** asking under another hash seed changed no answer and no plan.
- **The post-run review recomputed every number** in the report from the saved answers, and found no difference.
- **The draw reproduces byte for byte.** Every source got its share. No ticket key or pull request number is drawn twice. The 10
  planted pairs follow their rule.
- **No overlap:** the 5,000 share no document with any earlier set or the lexicon's sample.
- **The expected answers** were recomputed independently, on both banks: no difference.
- **The frozen system was the one tested:** the lessons, glossary, wordings and the small model's form match their pre-registered
  hashes, and the code is unchanged since the freeze.
- **The order of steps** (freeze, draw, banks, forms, then timed arms) is borne out by the file times.
- **The 5,000-document banks were deleted for disk space** after being hashed, so their hashes cannot be checked again now. The
  small banks were kept, and the stored answers reproduce on them. `part_a/bank_sha256.txt` now names each hash's file.

## What a pass means, and what it does not

**What it shows:** a much busier neighbourhood around the same people does not derail v13's lookups and plans, for people with
2 to 4 tickets. The pre-registration called the extra documents "4,950 unrelated documents". They are 4,895, and they are not
unrelated:
- 681 of them (14%) name a person the questions ask about;
- 21 refer to a ticket the questions ask about;
- none mention a pull request the questions ask about.

**What it does not show:**
- **Search.** Every question names its starting point exactly. Part B tests search.
- **The busiest people.** The 13 people with 5 or more Linear issues hold 38% of them, and are never asked about. Busy people
  with many other documents were asked about (Maya Chen is named in about 150 other documents) and answered right.
- **Partial names.** Every question uses a full name.
- **A pull request linking several tickets in the bank.** None exists in this draw.
- **Names shared by staff and outside contacts.** The bank joins people by name, so an engineer and an outside contact with the
  same name become one person (Maya Chen at a customer, for example). That creates new routes, and it fed the Gmail routes in
  the review's probe. No decisive question failed because of it.

## Corrections and disclosures found after the run

1. **The Gmail route** (above): through the pull request's people, not Gmail documents about the ticket.
2. **Exposure in review was slightly larger than disclosed.** The pre-registration said about 4 or 5 of the 10 planted pairs may
   have been looked at in review draws.
   - In fact 6 of the 10 were in review draws, and questions were answered on 2 of them.
   - One test question, `issue_pr_author-author-071`, was answered in review in the same form (same documents and answer). v13
     answers it right on both banks.
   - `issue_pr_author-author-097` was drawn in review but never answered.
   - `person_first-048` matches a review question in wording only, on other documents with another answer.
   - No code or lesson changed after the reviews, so this does not bias the frozen system's scores.
3. **The changed questions were not grouped by documents** in the report, as promised. They are grouped above.
4. **"4,950 unrelated documents"** is 4,895 related ones, as above.
5. **The bank hash file did not name its files,** and the 5,000-document banks could not be re-checked. It now names them.

The post-run review is `docs/benchmarks/factbank_5k/postrun_review_a.json`: three lenses, each finding checked by a refuter.
None changes a rule or the verdict.

# Part B: the fact bank against the memory bank on finding evidence

## In short

**The untrained fact bank's evidence lead does not hold at 5,089 documents.** Rules 1 and 2 were not met, so "replace" is
not met.
- **Near the top** (the first 2,000 characters), its evidence held the answer for 0.208 of the questions, against the memory
  bank's 0.252. On the small set it was 0.723 against 0.361.
- **At the full budget** (24,000 characters), rule 1 failed on lists by one key in one question. The fact bank was ahead on
  document fields and deadlines.
- **That lead comes from fields the memory bank does not show.** Linear due dates are an example: they are stored only as a
  document field, which the memory bank's evidence never prints. On the questions whose answer both can show, the memory
  bank's evidence is ahead at every budget at 5,089 documents.

**What broke is the order of the fact bank's evidence, not its search or its answers.**
- It still finds the document that holds the answer: among its top five starting points for 41 of the 44 single-answer
  questions, against 42 on the small set.
- Its own answers hold: 0.849 at 5,089 documents against 0.866 on the small set (rules 3 and 5 met).
- **But it orders its evidence by adding up votes.** Slack messages carry their channel's name as their title, so a person in
  six messages of one channel gets six votes. Such people are printed first.
  - 36 of the 50 evidence texts start with a block about a person, against 12 on the small set.
  - One person's 5,100-character block leads 12 of them.
  - The small set has no Slack messages, so it could not show this.

**The trained fact bank (v2) held the answer within 2,000 characters for 0.974,** and met rules 1, 2, 3 and 5.
- That comes from its layout: it prints its own top 8 candidate answers first.
- The untrained bank with the same layout would score 0.942 (a check after the run, not a result).
- Counting only v2's first candidate, it scores 0.816.

**Plain keyword search beats both banks' evidence at 5,089 documents:** 0.603 / 0.628 / 0.697 at the three budgets, against
the fact bank's 0.208 / 0.434 / 0.632 and the memory bank's 0.252 / 0.347 / 0.439.

**Storage:** the fact bank takes 0.577 of the memory bank's storage, not a third, as stated in advance.

## Decision

Rules on the untrained fact bank (v1), primary questions, 5,089 documents:

| Rule | Result |
|---|---|
| 1. Not worse at the evidence budget (fact bank − bank ≥ −0.03 in every group, 24,000 characters) | **Not met:** lists 0.083 against 0.125 (one key in one question); document fields 0.923 against 0.692; deadlines 0.889 against 0.500 |
| 2. Better near the top (fact bank − bank ≥ +0.10 on the mean, 2,000 characters) | **Not met:** 0.208 against 0.252 (−0.044) |
| 3. Answers without a model (own answers ≥ 0.70) | **Met:** 0.849 |
| 4. Smaller (at most a third of the bank's storage) | **Not met:** 106.0 MB against 183.7 MB, 0.577 (projected 0.58–0.59) |
| 5. Own answers hold at size (5,089 ≥ small − 0.05) | **Met:** 0.849 against 0.866 (−0.017) |

**Replace (rules 1, 2 and 4): not met.**

**The pre-registered reading of "rule 1 not met"** was "at the full budget, the memory bank's evidence is better at 5,000
documents".
- **Taken literally, the rule fails on one key.** On lists, both arms hold almost none of the keys: 0.125 against 0.083. The
  gap is one key of one question (`linear_status-009`).
- **On the other groups the fact bank looks far ahead,** but only through answers the memory bank cannot show.
- **Like for like, the pre-registered reading holds.** On the 28 document-field and deadline questions whose answer the
  memory bank's evidence can show, the memory bank is ahead at every budget (below).

**Questions cut short.** The memory bank's search gave up on 4 questions in the first pass, and on 2 in the scored pass and
the retry (`metadata-qst_0047` and `-0063`).
- All of them were the same name lookup, which has a 400 ms limit.
- Run with no limit, it finds nothing for those 2 questions, so nothing was lost.
- The rules without them read the same.

## Results

Answer within the evidence, mean of the three groups:

| arm | 5,089 documents: 2,000 / 6,000 / 24,000 | small set: 2,000 / 6,000 / 24,000 |
|---|---|---|
| plain keyword search | 0.603 / 0.628 / 0.697 | 0.697 / 0.908 / 1.000 |
| plain keyword + vector search | 0.559 / 0.644 / 0.692 | 0.752 / 0.857 / 0.970 |
| memory bank | 0.252 / 0.347 / 0.439 | 0.361 / 0.462 / 0.662 |
| **fact bank (v1)** | **0.208 / 0.434 / 0.632** | 0.723 / 0.891 / 0.957 |
| trained fact bank (v2) | 0.974 / 0.987 / 1.000 | 0.987 / 1.000 / 1.000 |

By group, at 24,000 characters, 5,089 documents (26 document-field questions, 18 deadlines, 6 lists):

| arm | document fields | deadlines | lists |
|---|---|---|---|
| plain keyword search | 0.962 | 1.000 | 0.128 |
| plain keyword + vector search | 0.962 | 1.000 | 0.113 |
| memory bank | 0.692 | 0.500 | 0.125 |
| fact bank (v1) | 0.923 | 0.889 | 0.083 |
| trained fact bank (v2) | 1.000 | 1.000 | 1.000 |

The "owners" group of the first test is really document fields: owner and assignee, but also status, release, forecast close
month and others.

**The fact banks' own answers:**

| | document fields | deadlines | lists | mean | small set |
|---|---|---|---|---|---|
| v1 | 0.615 | 0.944 | 0.989 | **0.849** | 0.866 |
| v2 | 0.577 | 0.833 | 1.000 | 0.803 | 0.772 |

**The first test's own questions** (secondary):

| arm | at 50 documents (the control) | at 5,089 documents |
|---|---|---|
| plain keyword search | 0.823 / 0.972 / 1.000 | 0.564 / 0.628 / 0.710 |
| memory bank | 0.375 / 0.414 / 0.630 | 0.296 / 0.368 / 0.419 |
| fact bank (v1) | 0.767 / 0.962 / 0.987 | 0.226 / 0.402 / 0.745 |
| trained fact bank (v2, trained on these questions) | 1.000 / 1.000 / 1.000 | 0.987 / 0.987 / 0.987 |

- **The control reproduces the first test exactly:** every arm, every budget, and v1's own answers (0.885).
- **At 5,089 documents:** rule 1 is met here (lists 0.500 against 0.083) and rule 2 is not (0.226 against 0.296).
- **It reproduces the design probe** recalled in the pre-registration: about 0.23 / 0.40 / 0.75.

## Why the fact bank's evidence fell behind

**It still finds the document and answers right.**
- For the 44 single-answer questions, the document holding the answer is among its top five starting points for 41 at 5,089
  documents, against 42 on the small set. It is the top one for 26, against 30.
- It answers 33 of the 44 right, against 34.

**Its evidence is ordered by adding up votes, and Slack messages repeat their titles.**
- **The bank adds up a fact's votes** over every document that states it, and prints the entities with the highest scores
  first.
- **Slack titles repeat.** 2,472 of the 5,089 documents are Slack messages, with only 126 distinct titles: their channels'
  names. So "participant of customer-success" collects one vote per message.
- **Example:** a person reached from the top document with 6 messages in one channel scores 1.54. The top document itself
  scores 0.86.
- **How much it crowds out:**
  - 36 of the 50 evidence texts start with a person block, against 12 on the small set.
  - Person blocks fill 72% of the first 2,000 characters, against 22%.
  - In 32 of the 36, the leading block's top fact is "participant of" a Slack channel.
  - Maya Chen's 5,100-character block leads 12 of them.
- **The person shown is reached through the right document in about half the cases.** Even then, the block lists their
  channels and other work, never the answer.
- **The small set has no Slack messages,** and the first test's 50 documents had one. So the effect appears only at size.

**Lists fail for another reason too: the evidence never prints the fact bank's own list answer.**
- Its list answers are right (0.989).
- But its evidence shows a person's tickets by title, not by key.
- The keys appear only in each ticket's own block, which the person blocks push past 24,000 characters.
- The date-window list cannot be shown at all, because the evidence does not run the date-range query the answer uses.

**Checks after the run.** These change the code, so they are not results. A fix would need a new pre-registered test on new
questions.
- **Ordering by the largest single vote instead of the sum** would give v1 0.541 / 0.692 / 0.806 at 5,089 documents. It changes
  nothing on the small set or the control.
- **Printing keys instead of titles** in a person's lines would raise lists at 24,000 characters from 0.083 to 0.830.
- **Printing v1's own top 8 answers first,** as v2 does, would give 0.942 / 0.967 / 0.967.

## Like for like, the memory bank's evidence is ahead

**Most of the memory bank's misses are answers it cannot show.**
- **16 of its 17 misses** in document fields and deadlines at 24,000 characters are answers stored only as a document field:
  - Linear due date, forecast close month, release, transcription quality, merge method.
  - None of these is in the sections or records its evidence prints.
  - This is the field gap the first test already warned of.
- **On Linear due dates, it scores 1 of 10 at both sizes.** Its first block is the right issue in every case, but no block shows
  the date.
- **On meeting action items at 5,089 documents, it is ahead:** 8 of 8 against the fact bank's 6 of 8.

**On the 28 questions whose answer the memory bank can show** (answer found in the document that holds it):

| | memory bank, 2,000 / 6,000 / 24,000 | fact bank (v1) |
|---|---|---|
| document fields (19), 5,089 documents | 0.58 / 0.68 / 0.95 | 0.32 / 0.53 / 0.84 |
| deadlines (9), 5,089 documents | 0.67 / 1.00 / 1.00 | 0.22 / 0.56 / 0.78 |
| document fields, small set | 0.84 / 0.95 / 1.00 | 0.95 / 1.00 / 1.00 |

- **On the small set the fact bank led; at 5,089 documents the memory bank does.**
- **The same holds on the first test's questions at 5,089.** Like for like, the fact bank would fail rule 1 there too.
- **So the fact bank's real advantage is that it stores every field,** which is what it was built for. On finding and ordering
  evidence at size, as laid out now, it is behind.

## The trained fact bank's lead is its layout

v2 starts its evidence with "Most likely answers, best first": its top 8 candidates, or the whole list for a list question.
Then it prints the same kind of evidence as v1.

| v2 at 5,089 documents, 2,000 characters | document fields | deadlines | lists | mean |
|---|---|---|---|---|
| as scored | 0.923 | 1.000 | 1.000 | 0.974 |
| first candidate only | 0.615 | 0.833 | 1.000 | 0.816 |
| first candidate, then the rest of its evidence | 0.769 | 0.889 | 1.000 | 0.886 |
| the rest of its evidence alone | 0.269 | 0.167 | 0.000 | 0.145 |

- **v2 meets rules 1 and 2 even counting only its first candidate:** 0.816 against the memory bank's 0.252.
- **11 of the 44 single-answer questions are credited only through candidates 2 to 8.** A reader would still have to choose
  among those. For one question, seven candidates name different accounts with the same month.
- **The untrained bank with the same layout gets 0.942.** So about 0.73 of v2's 0.77 lead over v1 is the layout, not the
  lessons.
- **Its own answers are below v1's:** 0.803 against 0.849.
- **Its deadline questions use the training questions' two wordings.** On new wordings, an earlier test found its deadline
  answers fell to 0.200. On the first test's questions it is in-sample.

## How much is chance

The measure checks only that the answer's text is present. At 5,089 documents a median of 20 other documents hold each
answer (`chance`). The review traced every piece of evidence to its document and rescored with only the pieces from the
document that holds the answer:

| arm | as scored | from the right document only |
|---|---|---|
| plain keyword search | 0.603 / 0.628 / 0.697 | 0.577 / 0.603 / 0.677 |
| plain keyword + vector search | 0.559 / 0.644 / 0.692 | 0.559 / 0.631 / 0.679 |
| memory bank | 0.252 / 0.347 / 0.439 | 0.252 / 0.347 / 0.439 |
| fact bank (v1) | 0.208 / 0.434 / 0.632 | 0.208 / 0.396 / 0.593 |
| trained fact bank (v2) | 0.974 / 0.987 / 1.000 | 0.956 / 0.956 / 0.987 |

- **Chance credit is small and falls mostly on v1:** 3 of its document-field hits come only from other documents.
- **No rule changes** under the stricter count.
- **Two of the fact banks' right answers at 5,089 come from another account.** One shares the month by coincidence. The other
  fits an ambiguous question as well as the expected account does: the near-duplicate case the pre-registration did not cover.
  Without both, rule 5's margin is −0.042 against the −0.05 allowed.
- **The deadline questions do not make search hard.** Each quotes the exact title, and plain search puts the right document
  first for 16 or 17 of the 18.

## Time, size and the checks

**Time per question at 5,089 documents** (median): plain keyword search 2 ms, plus vectors 23 ms, memory bank 0.46 s, fact
bank 0.78 s, trained fact bank 1.9 s. On the small set: 1 ms, 17 ms, 0.23 s, 10 ms and 0.11 s.

**Loading 5,089 documents:**
- The memory bank took 386 s, reusing earlier embeddings.
- Plain search's vectors took 55 minutes, not cached.
- The fact banks took 8 s (v1) and 14 s (v2).

**Storage:**

| | bytes |
|---|---|
| memory bank | 183.7 MB: records 87.3, sections 69.0, BM25 15.8, links 6.1, documents 5.4 |
| fact bank v1 | 106.0 MB (0.577 of the memory bank) |
| fact bank v2 | 115.1 MB (0.626) |
| plain search | 68.0 MB |

**Checks:**
- **The review recomputed every number** with the repository's own measure, and found no difference.
- **The primary questions** were drawn after the freeze and reproduce from seed 61. No earlier test used them, matched by
  content. No flawed question is among them, and the mix is as pre-registered.
- **The setup:** the code is unchanged since the freeze. Every memory bank held all its documents, alone in its database, with
  its BM25 index ready.
- **The memory bank's evidence was identical across the two passes,** in all four folders.
- **The budgets bind every arm alike:** each arm's evidence is 22,955 to 24,050 characters long.
- **Time limits explain no verdict.** Only the memory bank has them.

## Corrections and disclosures found after the run

1. **"Still cut short" overstates it.** The 2 questions' name lookup finds nothing even without its time limit.
2. **The first pass's evidence was not saved at first,** so the two-pass check could not be redone from the repository. It is
   now saved (`evidence_pass1.jsonl.gz` in each folder).
3. **The "owners" group is document fields,** as above.
4. **A suspicion that the small set flatters lists was refuted.** On the small set, every list key the arms found came from a
   block naming the person asked about, so the drop on lists at size is real. Only the date-window question was partly
   flattered.

The post-run review is `docs/benchmarks/factbank_5k/postrun_review_b.json`: three lenses, each finding checked by a refuter.
None changes a rule outcome. One changes the diagnosis of the lists, and is used above.

## What it means

- **The memory bank should not be replaced by the fact bank as it stands.** Neither bank's evidence beats plain keyword search
  at 5,089 documents.
- **The fact bank's lookups and answers hold at size** (part A, and rules 3 and 5 here). Its evidence text does not.
- **The checks after the run point to three changes:**
  - print the answer first;
  - stop adding up votes from same-titled messages;
  - print keys in list lines.

  Each needs its own pre-registered test on new questions.
- **The memory bank's own gap is unchanged at size:** fields stored only on the document, such as Linear due dates, never reach
  its evidence.
