# Teaching the fact bank, then a fair retest: what decides, fixed before the run

I wrote this on 2026-10-07, after the held-out set was frozen and before the learning component was built. The
results go in `docs/FACTBANK_LEARNING_RESULTS.md`.

## Why

On its first 50 questions (`docs/FACTBANK_RESULTS.md`), the fact bank's reasoning steps were exact (deadlines 18/18,
lists 6/6). Its misses came from what surrounds them:
- **understanding what a question asks for** (8 of 9 wrong answers);
- **facts that live only in sentences** (1);
- **where the answer sits in its evidence.**

## What is learned, and from what

**Training data:** the 50 documents and 50 questions of the first test, with their answers. Nothing from the held-out
set is used.

The learned parts must work from principles, never from the training values (names, dates, keys):
1. **Which document the question means:**
   - its keyword rank;
   - whether the question names it by an identifier or a person;
   - how many of the document's own field values appear in the question;
   - how much of its title the question repeats.
2. **What the question asks for** (which fact is the answer):
   - the overlap of the question with the field's name;
   - an association between question words and field-name words, learned from the training answers;
   - for a value found in a sentence, the overlap of that sentence with the question;
   - whether the kind of value fits the question (a date for "when", a person for "who", a title for "which page");
   - whether the value already appears in the question, which marks it as a clue rather than the answer.
3. **Whether the question wants a list, and which relation it means:** "authored by" or "assigned to", and the
   source system named.
4. **Reading sentences:** dates and identifiers found in the documents' text become facts (confidence "inferred"),
   with their sentence as context.

The weights come from logistic regression on the training questions. They are saved, and shown in the results, as
the lessons learned.

## The held-out set (frozen)

`python -m cie.eval.factbank_split testset` (seed 8):
- **50 documents**, none of them among the training documents.
- **46 questions:** metadata 22, Linear due dates 10, meeting action items 10, pull requests by author 3, Jira tickets
  by assignee 1. These are the training set's kinds; 46 is as many as fit in 50 new documents.
  - questions.jsonl sha256 `763c1ada5d09ae87…`
- **Other wording and tone:**
  - every generated question uses one of a fixed set of other wordings, e.g. "What PRs has P opened on GitHub? Just the
    numbers.";
  - every benchmark-written question gets a casual opener and/or its context clause moved to the end.

  These wordings were written before anything was learned.
- **Changed information** (`factbank_split changed`): the same documents and questions, with every person renamed to a
  name the corpus does not contain (128 people) and every ISO date moved 23 days later. This applies to the documents,
  the questions and the expected answers alike.
  - questions.jsonl sha256 `691da4d72baf0a3a…`

## Arms

| arm | |
|---|---|
| fact bank v1 | as tested before, not trained |
| fact bank v2 | trained as above |
| memory bank | the present one, its own search |
| plain keyword search, plain keyword + vector search | references |

## Measures

The same as in the first test:
- the fact bank's own answers, with no model (owners and deadlines: share correct; lists: mean F1);
- whether the expected answer is in the first 2,000 and 24,000 characters of each arm's evidence.

Groups: owners (22), deadlines (20), lists (4). The mean is the mean of the three groups.

## Rules

1. **Learning helps on unseen documents and wording:** v2 − v1 ≥ +0.10 on the mean, for the fact bank's own answers
   (held-out set).
2. **It holds when the information changes:** v2 on the changed set ≥ v2 on the held-out set − 0.05.
3. **Better evidence near the top:** v2 − v1 ≥ +0.05 on the mean, answer within the first 2,000 characters (held-out
   set).
4. **Still not worse than the memory bank:** v2 − bank ≥ −0.03 in every group, answer within 24,000 characters
   (held-out set).

Also reported, with no threshold: v2 on its own training questions against v2 on the held-out ones (how much it
memorised).

## Known limits

- **Few lists.** There are only 4 list questions, so the lists group is rough.
- **Small training set.** Training saw 50 questions; some kinds of wording in the held-out set never appear there.
  That is the point of the test, but the lessons are only as broad as their examples.
- **Shared company.** The documents differ, but the company is the same, so people and projects can recur. Only the
  changed set removes all of that.
