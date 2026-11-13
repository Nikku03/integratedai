# The fresh test: plan

Written before any arm answered a question of this test. The rules below decide the result.

## Why a new test

The 50,000-document test (`docs/FACTBANK_50K_RESULTS.md`) met its eight rules. Its stored answers were then read
closely, and eleven things were fixed (`docs/FACTBANK_FIXES.md`). Two of those fixes cannot be judged on the old
questions:

- **The old questions are development data now.** The brain's v19 and the model's new tools and checks were made
  after reading the answers to them. A score on them says little.
- **The old test was easier than it looked.** Its complex questions were built from the fields the model's `find`
  tool filters. Its casual wordings kept every key and title. Its free-text score rewarded copying. Its baseline was a
  single keyword search.

This test answers those points:

| weakness of the old test | what this test does |
|---|---|
| questions written by our own generators | the benchmark's own questions, written by its authors |
| free text scored by overlap with the record's words | a model judges each answer against the reference answer and its facts; people label a sample of the verdicts |
| baseline: one keyword search | a second baseline: the same model with search and read tools, free to search as often as the main arm |
| one run of the model | three seeds of the main arm on a fixed sample |
| no ablations | the model without the brain, and without the tools, on the same sample |
| documents the fixes were developed on | documents no earlier test used |

## The documents

50,000 documents of the benchmark's company (EnterpriseRAG-Bench at commit `d36685e`):

- the **684** documents that the benchmark's own questions rest on;
- **49,316** more, every system in its share of what is left, drawn with seed 6060;
- **no document of the earlier test's haystack**, except 28 of the 684 (a question's own documents cannot be left out).

The draw is `python -m cie.eval.fresh_test draw`. Its fingerprint is in `docs/benchmarks/fresh/plan/expect.json`, and
the notebook stops if its own draw differs.

## The questions

**bench: 463 of the benchmark's own 500 questions.** Each has a reference answer, the facts a right answer states
(4.9 on average) and the documents it rests on.

| type | questions | what it asks |
|---|---|---|
| basic | 158 | a fact in one document, asked plainly |
| semantic | 118 | the same, asked in other words than the document's |
| project_related | 40 | several documents about one project |
| intra_document_reasoning | 30 | something to work out within one document |
| constrained | 29 | an answer that depends on a condition |
| completeness | 20 | every item of a kind, across documents |
| info_not_found | 20 | the documents do not hold the answer; a right answer says so |
| conflicting_info | 19 | two documents disagree |
| miscellaneous | 19 | other |
| high_level | 10 | a summary across many documents |

- **37 questions are left out and never counted.** Every document they rest on was in the earlier haystack, so they
  could be asked there. They were used to try this harness end to end with a scripted stand-in for the model.
- The benchmark's 100 extra metadata questions are not used: an early version of this project was developed on them.
- The benchmark's questions are not copied into this repository. The notebook reads them from the benchmark and checks
  their fingerprint.

**gen: 402 generated questions with exact answers**, drawn from the new documents with new seeds (6061, 6062) by the
generators of the earlier tests.

| family | questions | what it asks |
|---|---|---|
| single | 90 | a field of one record, a deadline, a person's role |
| multi | 56 | lists, and answers that join two records |
| counts | 40 | how many records match one or two filters |
| history | 40 | when a record was created, updated, merged; who commented first |
| email_chat | 40 | senders, recipients, attachments, channels |
| not_found | 20 | a name or key the company does not have |
| unanswerable | 20 | a field the named record does not hold |
| complex | 96 | two to four steps over two or more records (8 kinds, 12 of each) |

The free-text and descriptive questions of the earlier tests were written by hand for other documents; the
benchmark's own questions take their place.

**The samples:** 100 of each set, every kind in its share, drawn with seed 6063.

The counts and fingerprints of all four question files are in `docs/benchmarks/fresh/plan/expect.json`.

## Who answers

One model for every model arm: Qwen3.8-27B, thinking on, effort medium, the settings of the earlier test.

| arm | what answers | asked on |
|---|---|---|
| `v19` | the brain alone (v18 with the four fixes), no model | every question |
| `reasoner` | the model on the brain: it reads the brain's answer, has every tool, and its final answer is checked | every question, seed 0 |
| `agent` | the model with search and read only | every question, seed 0 |
| `rag` | the model reading 12 passages of one keyword search | every question, seed 0 |
| `reasoner` seeds 1, 2 | the main arm again | the samples |
| `nobrain` | the model with every tool but the brain | the samples |
| `notools` | the model with the brain's answer and evidence, no tool | the samples |

- The brain's answer stands without the model on four of its routes (a field of a named record, a count by exact
  filters, a name the company does not have, a field the record lacks). This is part of the `reasoner` arm.
- Every answer file records the model, effort, seed, loop version and brain version. Answers made with other settings
  are refused, not mixed in.

## How answers are scored

- **gen:** by exact check, as in the earlier tests (`brain50k.score_one`). The mean is over the families other than
  complex; complex is reported and ruled on by itself.
- **bench:** by the judge (`cie.eval.judge`). The same model, in a separate conversation, is shown the question, the
  reference answer, its facts and the answer (with the quotes that go with it). It says which facts the answer states
  and whether the answer is right. An answer is right when it agrees with the reference on what was asked and says
  nothing that contradicts it. Completeness is the share of the facts stated.
  - A verdict that cannot be read is asked for once more, then left out. It is never counted as wrong, and the report
    says how many were left out.
  - Also reported, with no rule: how many of the documents an answer rests on appear in what the arm read.
- **The judge is checked by people.** After the run, 60 answers (20 of each core model arm) go to a sheet without
  the judge's verdicts. A person marks each right or wrong. The report gives the agreement and Cohen's kappa.
  - If agreement is below 0.85, rules 4 to 6 are not decided by the judge: they wait for a person's labels on a
    larger sample.

## The rules

Each is met or not met by the numbers of the report. Rules 1 to 7 read seed 0 on every question.

| # | rule |
|---|---|
| 1 | **No harm.** gen: `reasoner` is within 0.01 of `v19` on the mean, and within 0.03 on every family. |
| 2 | **Complex.** gen: `reasoner` scores 0.80 or more on the complex questions. |
| 3 | **The bank helps.** gen: `reasoner` beats `agent` by 0.05 or more on the mean. |
| 4 | **Natural questions.** bench: `reasoner` is judged right at least as often as `agent`. |
| 5 | **Beats plain search.** bench: `reasoner` is judged right more often than `rag`, by 0.05 or more. |
| 6 | **Says when it does not know.** bench: on the info_not_found questions, `reasoner` is judged right on 0.70 or more. |
| 7 | **False "not found".** gen: `reasoner` says "not found" on at most 0.05 of the answerable questions. |
| 8 | **Seeds agree.** On the samples, the three seeds of `reasoner` differ by at most 0.03 (gen mean) and 0.06 (bench, judged right). |

**What each outcome means:**
- Rules 1, 2, 7 failing: the model's new checks or tools hurt on new questions. The fixes of sections 2 to 4 of
  `FACTBANK_FIXES.md` are not proven.
- Rule 3 or 4 failing: a model that only searches does as well. The fact bank is not earning its cost on that kind of
  question, and the report must say so.
- Rule 5 failing: on natural questions the whole system is no better than the usual search-then-model baseline.
- Rule 8 failing: differences smaller than the spread between seeds are noise, and rules decided by less than that
  spread are reported as undecided.

## Reported without a rule

- `v19` against v18's development numbers: by family, and how often `v19` reaches the gold documents of the bench
  questions. The brain alone has no way to write a free-text answer, so its judged score on bench is expected to be low.
- What the brain adds (`reasoner` minus `nobrain`) and what the tools add (`reasoner` minus `notools`), on the samples.
- Cost: prompt and output tokens and time per question, per arm.
- Every arm by question type.

## What has and has not been looked at

- **Looked at:** the documents (to draw them), the questions' text (to write them to files). The 37 left-out
  questions were asked on the earlier bank to try the harness.
- **One dry run of the notebook, deleted unread.** To make sure the notebook does not fail hours into a run, its cells
  were run once here with `LIMIT = 3` and a scripted stand-in for the model (it searches once and answers with the
  first title it sees; as a judge it calls long answers right). The brain answered the first 3 questions of each of
  the four folders. The answers, the report and the log were deleted without being read. They decide nothing.
- **Not looked at:** apart from that, no arm, with or without a model, has answered any of the 463 bench questions or
  any generated question of this test.
- **The brain was not changed after the old answers were last read.** v19's rules are those of commit `b8a61a1`. Later
  commits changed how the brain reads the bank (a profile, fields read on demand), not what it answers: v18's 1,270
  stored answers are reproduced exactly with the final code (`docs/FACTBANK_FIXES.md`, section 1).
- **Not changed after this plan:** the brain, the tools, the loop, the judge's instructions, the scorer, the rules.
  A bug found during the run is fixed only if the fix cannot change a right answer into a wrong one or the reverse;
  otherwise the run is reported as it is, with the bug.

## Cost

About four times the model answers of the earlier test: the notebook expects 8 to 14 hours on an A100 80 GB. It saves
to Google Drive every few minutes and goes on from where it stopped. `RUN_EXTRA = False` skips the samples (rule 8
then stays open).

## Files

| | |
|---|---|
| harness | `src/cie/eval/fresh_test.py`, `src/cie/eval/judge.py` |
| notebook | `notebooks/company_brain_fresh_colab.ipynb` |
| the plan's draw and questions | `docs/benchmarks/fresh/plan/` |
| what was fixed and how each fix was checked | `docs/FACTBANK_FIXES.md` |
