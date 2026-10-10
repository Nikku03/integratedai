# The fact bank at 5,000 documents: results

**Run on 2026-10-10**, by the rules in `docs/FACTBANK_5K_PREREGISTRATION.md` (part A) and
`docs/FACTBANK_5K_B_PREREGISTRATION.md` (part B). Both were frozen at commit `7dae3b8` (08:30:08 UTC). Part A's test set was
drawn after it, at 08:30:41; part B's primary questions were drawn at 08:54.
- **Raw results, run scripts and reviews:** `docs/benchmarks/factbank_5k/` (`part_a/`, `part_b/`).
- **All data is fictional:** the benchmark's made-up company.

**Part B** (the fact bank against the memory bank on finding evidence) is still running; its results follow in this file.

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
