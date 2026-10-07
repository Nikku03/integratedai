# Questions that need several documents: training, then a fair retest. What decides, fixed before the run

I wrote this on 2026-10-07, after the question sets were frozen and before the plan learner was trained. The results go
in `docs/FACTBANK_MULTI_RESULTS.md`.

## What is tested

Whether the fact bank can learn to put **fragments from several documents** together to answer one question.

**The method** (`cie/src/cie/factbank/plans.py`):
- the bank enumerates every plan it allows: a start, up to two hops along links between documents, a field, and a way
  to combine (one value, a list, a count, the earliest or the latest);
- it carries each plan out one hop at a time, writing down every entity reached;
- learned weights pick the plan.

The weights cover how well relation and field names match the question, word associations learned from the training
answers, whether the answer's kind fits the question, which way of combining the question's words suggest, and the
clue rule. No value from the training documents is learned.

## Data (frozen)

`python -m cie.eval.factbank_multi build` (seed 11), from the 5,089-document haystack of the memory test. Two sets share
no document. Every expected answer is computed within its own set.

| | documents | questions | sha256 of questions.jsonl |
|---|---|---|---|
| training | 50 | 48 | `bd8b55addbc581ea…` |
| held-out | 49 | 50 | `37ab096a8c0073a3…` |
| held-out, changed information | 49 | 50 | `02399dd329e071aa…` |

**Kinds of question.** Each needs 2–5 documents.
- **link:** a pull request → its Linear issue → assignee, due date or status; a Linear issue → the pull request that
  references it → its author; a ticket → the ticket it links → status or assignee.
- **combine:** how many Linear issues a person has; which of them is due first; the Linear issues of whoever took a
  given meeting action item (meeting → action item → person → issues).
- **compare:** which of two Linear issues is due first.

| | link | combine | compare |
|---|---|---|---|
| training | 17 | 23 | 8 |
| held-out | 17 | 25 | 8 |

**Wording.** Training uses three wordings per kind, and the held-out set two others, written before training. For
example, "How many Linear issues are assigned to P?" in training, and "How many Linear tickets does P have on their
plate?" in the held-out set.

**Changed information:** 110 people renamed and every ISO date moved 23 days later. This applies to the documents, the
questions and the expected answers alike.

## Arms

| arm | |
|---|---|
| v1 | the fact bank's engine, untrained |
| v2 | the fact bank with the single-document lessons learned before (`docs/FACTBANK_LEARNING_RESULTS.md`) |
| **v3** | v2's document finding, plus the plan weights learned from the 48 training questions |
| memory bank | the present one, its own search |
| plain keyword search, plain keyword + vector search | references |

## Measures

1. **Own answers, no model:** the memory test's code check. Values and dates must match exactly; lists score F1; a
   count must be the right number.
2. **All fragments within the evidence:** the share of the question's pieces found in the first 2,000 and 24,000
   characters of each arm's evidence. The pieces are the keys, dates, names and values the answer is built from.

The groups are link, combine and compare. The mean is the mean of the three.

## Rules

1. **Learned plans answer multi-document questions:** v3 − v1 ≥ +0.20 on the mean, own answers, held-out set.
2. **Principles, not memorisation:** v3 on the held-out set ≥ v3 on its training questions − 0.15.
3. **It holds when the information changes:** v3 on the changed set ≥ v3 on the held-out set − 0.05.
4. **It brings the fragments together:** v3 − memory bank ≥ +0.10 on the mean, all pieces within 24,000 characters,
   held-out set.

## Known limits

- **Template questions.** The questions follow templates; real multi-document questions are messier.
- **Few examples per kind.** The rarest kind, issue → PR author, has 2 training questions and none held out.
- **No language model.** A word the training questions never used can only be understood through field names.
