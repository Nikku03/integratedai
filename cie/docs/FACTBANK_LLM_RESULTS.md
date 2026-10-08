# A language model for the English, the fact bank for the facts: results

**Run on 2026-10-08**, by the rules in `docs/FACTBANK_LLM_PREREGISTRATION.md`. Those rules were written, and everything
frozen, before any run.
- **Raw results, the 3B model's rewrites, the glossary, the writers' wordings and the review:**
  `docs/benchmarks/factbank_llm/`.
- **Code:** `cie/src/cie/factbank/reader.py`.

## In short

**Neither way passed.** On 50 new questions over 50 new documents:

| arm | right answers |
|---|---|
| v4, the plan learner alone | 0.586 |
| **v7**, Llama 3.2 3B rewrites the question, then the bank answers | 0.573 |
| **v8**, a glossary written once by a large model, no model at question time | 0.601 |

Differences this small are within one question.

**The 3B model was not good enough at the rewrite:**
- 31 of its 50 rewrites kept every key, number, title and name, so they were used.
- 13 were exactly the standard question; 15 if a leading menu number is ignored.
- Some chose the wrong question. For example, "which ticket is due first?" became a question about status.

**The glossary read the words well, but the planner's mistakes hid it:**
- It fixed questions about "what state", "deadline" and "how many".
- It lost four action-item questions. The review traced the loss to the plan weights learned again with the glossary,
  not to its English.

**Much of this set is out of reach of the plan learner, whatever the wording:**
- Even with every question re-asked in the standard wording of v7's menu, v4 scores 0.635.
- 4 questions ask for a pull request's issue's due date, a kind of question the 48 training questions never include.
  Every version, under every wording, scores 0 on them.
- The "who opened the pull request" questions score 0 under all three training wordings.
- So on these documents, much of the limit is what the plan learner was taught, not the English.

**On the earlier sets, the glossary helps a lot:** retest 0.800 against 0.596, general-English set 0.898 against 0.727,
new-words set 0.669 against 0.611. The glossary writer never saw those questions. But these are not the decision. Their
questions were also written by the same kind of model as the glossary, which can share its phrasing.

## Decision

| Rule | Result |
|---|---|
| 1. A small model reading the question helps (v7 − v4 ≥ +0.10) | **Not met:** 0.573 against 0.586 (−0.013) |
| 2. A glossary written once helps (v8 − v4 ≥ +0.10) | **Not met:** 0.601 against 0.586 (+0.015) |
| 3. Principles, not memorisation (test set ≥ training − 0.15, each) | **Not met:** v7 0.573 against 0.966; v8 0.601 against 0.986 |
| 4. It holds when the information changes (changed ≥ test set − 0.05, each) | **Met:** v7 0.558 against 0.573; v8 0.601 against 0.601 |
| 5. No harm on what was learned (≥ v4 − 0.03 on training, each) | **Met:** v7 0.966, v8 0.986, against 0.927 |

## Results

Own answers, no model judging (the mean is the mean of the three groups):

| | link | combine | compare | mean |
|---|---|---|---|---|
| test set, v1 (untrained) | 0.150 | 0.000 | 0.000 | 0.050 |
| test set, v4 (plan learner alone) | 0.350 | 0.909 | 0.500 | 0.586 |
| test set, v6 (counted word meanings) | 0.350 | 0.909 | 0.500 | 0.586 |
| test set, **v7 (3B model rewrites)** | 0.400 | 0.818 | 0.500 | **0.573** |
| test set, **v8 (glossary)** | 0.450 | 0.727 | 0.625 | **0.601** |
| changed copy, v7 / v8 | | | | 0.558 / 0.601 |
| training, v4 / v7 / v8 | | | | 0.927 / 0.966 / 0.986 |
| retest set (seen), v4 / v7 / v8 | | | | 0.596 / 0.564 / 0.800 |
| new-words set (seen), v4 / v7 / v8 | | | | 0.611 / 0.655 / 0.669 |
| general-English set (seen), v4 / v7 / v8 | | | | 0.727 / 0.690 / 0.898 |

Without the one action item owned by a customer attendee: v4 0.585, v7 0.570, v8 0.596.

### The 3B model's rewrites

| | test set |
|---|---|
| rewrites used (they kept every key, number, title and name) | 31 of 50 |
| exactly a standard question | 13 (15 ignoring a leading menu number) |
| the right kind of standard question | 25 of the 31 used |
| fell back to the original question | 19: all 8 "which is due first", 6 action items, 4 counts, 1 first-due |

- **A wrong rewrite:** "Of everything assigned to Priya Patel in Linear, which ticket is due first? Send me the ticket
  key." became "What is the status of the ticket that Priya Patel is assigned to?"
- **Speed:** on this machine (4 CPU cores, no GPU) a rewrite took 5–20 seconds. Loading the model the first time took
  3 minutes.

### The glossary

The glossary's phrases changed 9 answers against v4: 5 better, 4 worse.
- **Better:**
  - "what state" → status, in two linked-ticket questions;
  - "deadline" → due date, in a compare question;
  - "how many" → count;
  - one more.
- **Worse:** four "whoever picked up the action item" questions. They lost because v8's plan weights were learned again
  with the glossary in place and came out different. With the glossary's "picked up" → assignee, the winning plan read
  a field instead of listing the person's issues. One of the four questions matched no glossary phrase at all.

## What the review found

After the run, two reviewers checked the new code and the numbers, and a refuting reviewer checked each finding
(`review.json`). Every published number reproduces, and no rule outcome changes. Their findings change how to read the
results:

1. **My "ceiling" claim was too strong.**
   - What I first claimed: re-asking the questions in the standard wording gives 0.635, so "no English reader in front
     of v4 could reach rule 1's 0.686".
   - What holds: that is true only for v7's menu, the first training wording of each kind. Other wordings that already
     exist reach 0.692 (the second training wording for two kinds), 0.718 (a whole earlier blind wording set) and 0.783
     (the best of 13 wording lists per kind).
   - These margins rest on 1–3 questions, partly right by luck. So whether any reader could pass cannot be shown either
     way.
2. **The training set has gaps.** Its 48 questions include no "when is the issue linked from PR #N due?" and only two
   "who opened the pull request". The test has 4 and 5. With v4's weights, the due-date ones score 0 under every
   wording. That is a gap in what was learned, not a failure to read English.
3. **The compare answers are luck.** None of v4's or v7's correct "which is due first" answers reads both issues' due
   dates; they read creation dates or wander to other issues. So one compare question (0.042 of the mean) can swing
   any comparison between versions.
4. **One cluster of tickets gives the link gains.** ENG-4821, ENG-4822 and ENG-4832 link to each other and are all
   "Done". v7's two link gains over v4 come from reading the wrong one of them, which happens to share the answer.
   v8's link gain rests on two questions about one document.
5. **Smaller points:**
   - The rewrite cache is keyed on the question alone, so a changed prompt would silently reuse old rewrites.
   - The glossary's "creator" target adds "created", which matches the creation-date field.
   - For v4 and v8, rule 4 cannot fail by construction: renaming does not change what they read.

## What this shows

- **A small model on a CPU is not yet a reliable reader for this.** It got the standard question exactly right a
  quarter of the time.
- **A glossary written once, with no model when questions are asked, reads the words well.** It is the clearest gain on
  the earlier sets. Here it was masked by the planner's other weaknesses.
- **The plan learner is now the bottleneck.** It learned from 48 questions, misses kinds the training set lacks, and
  answers some questions right for the wrong reason. Better English alone cannot fix that.

**Next** (not tested; each needs its own pre-registered test):
- teach the plan learner the missing kinds (a pull request's issue's due date, who opened a pull request);
- make it check that the answer's kind matches the question (a date for "when", a person for "who"), and that a
  "which is due first" plan really compares due dates;
- or let a model name the plan's parts directly, and have the bank run exactly that plan and check it.

## Reproduce

```bash
python -m cie.eval.factbank_multi fresh --index index.json --root <benchmark> --exclude <every earlier set> <lexicon sample> --out $T --seed 31 --wordings blind2
python -m cie.eval.factbank_split changed --work $T --out $TC
python -m cie.eval.factbank_multi train --work $TRAIN --single lessons.json --plans plan_lessons_v8.json --rules v4 --glossary glossary.json
python -m cie.eval.factbank_multi ask --work $T --single lessons.json --plans plan_lessons_v8.json --name factbank_v8
# v7: Ollama serving llama3.2:3b; the rewrites in docs/benchmarks/factbank_llm/rewrites/ replay without the model
python -m cie.eval.factbank_multi ask --work $T --single lessons.json --plans plan_lessons_v4.json --name factbank_v7 --reader rewrites/mdllm.jsonl
python -m cie.eval.factbank_multi llm --work $T --changed $TC --train $TRAIN
```
