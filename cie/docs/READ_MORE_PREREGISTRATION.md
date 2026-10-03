# Read more: what is measured and what decides the default, fixed before the test run

I wrote this before any answer from the read-more arm was graded. The setting was chosen on the development half of
the questions only.

## Question

The evidence audit found that most answer facts still missing from what the model reads sit in documents that are
already in the evidence packet:
- in documents ranked 4th or lower, which document expansion does not look inside;
- or past the 24,000 characters a small model (Llama) is given.

**If the model reads more evidence, are more of its answers correct?**

## Development (odd question numbers, 5,000 documents, no model)

These numbers count answer facts that reach the model (the evidence audit's lexical check). They are not answer
correctness.

| What the model reads | Every answer fact reaches the model |
|---|---|
| today: packet of 12,000 tokens, first 24,000 characters | 74% |
| packet of 24,000 tokens, 10 documents expanded, first 40,000 characters | 77% |
| the same packet, first 60,000 characters | 82% |
| the same packet, first 80,000 characters | 84% |
| the same packet, all of it (about 103,000 characters) | 86% |

Tried and rejected on the same half:
- cutting passages down to the sentences that share words with the question: 31–69%;
- reordering with a small reranker (MiniLM) to fit more into 24,000 characters: 71–72%;
- removing duplicate text: no change.

**Fixed for the test:** the packet holds up to 24,000 tokens and 200 items, document expansion covers 10 documents,
and a small-context model reads its first 60,000 characters. A long-context model (Claude) reads the whole packet,
as it does today. Llama's context is raised from 12,288 to 24,576 tokens so the 60,000 characters fit.

## Test run

The Colab notebook, with `LLM_ANSWERS` and `READ_MORE` on. Run once.
- `cie.eval.bench_enterprise --assisted --read-more` asks all 500 questions twice with the same model:
  - `hybrid+graph(REM), composed answers` (today's settings);
  - `hybrid+graph(REM), composed answers, read more`.
- Part 1c grades both answers files with the benchmark's own judge (`metrics_based_eval --no-correction`), through
  `cie.eval.grade_answers`. The judge model is the benchmark's default, `claude-sonnet-4-6`, unless the notebook's
  `JUDGE_MODEL` says otherwise; the report names it.
- The haystack is what the run loads: the full corpus (about 512,000 documents) with `FULL_CORPUS`, else 50,000. The
  report names it.

The criteria use the **even half** of the questions, which was not used to choose the setting.

## Criteria

Read more becomes the default for composed answers if all of these hold:

0. **The grading is usable.** In each graded file, at most 5% of the answered questions have a judge call that
   returned nothing. The benchmark's code scores such a failure as a wrong answer, so a larger share means the
   grading failed, not the model.
1. **More correct answers.** Correct (the judge's `answer_correct`) is at least 3 percentage points higher with read
   more, on the even half.
2. **No loss of facts.** Average completeness (the share of gold facts an answer states) is at least as high, on the
   even half.
3. **Affordable time.** Read more's p50 time per question is at most 3 times today's.

## Reported, with no threshold

- Correct and completeness on all questions, and by question type.
- How many even-half questions became correct with read more, and how many became wrong.
- Declined answers (the model said the evidence was insufficient), and how often they were correct.
- Correct by evidence-audit stage, for today's settings: among questions where every answer fact reached the model,
  the share of correct answers is the model's own share of the loss.
- Tokens read and p50/p95 time per question for both arms.

## Decisions fixed in advance

- **All criteria met.** Composed answers use the read-more settings by default. Extractive answers (no model) keep
  today's packet.
- **Criterion 0 fails.** No decision: the grading is repeated after the judge is fixed.
- **Criterion 1, 2 or 3 fails.** Read more stays an option (`--read-more`), and the result is reported.

Every result is reported, including failures.
