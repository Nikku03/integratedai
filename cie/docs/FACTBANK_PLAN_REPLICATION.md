# Fixing the planning step: the same test on another 50 documents

**Section 1 was written on 2026-10-09, before the new documents were drawn.** The results are added below it after the
run, in a separate commit.

## 1. What decides (fixed before the run)

### Why

The planner test (`docs/FACTBANK_PLAN_RESULTS.md`) scored:
- v9: 0.975
- v4: 0.510
- v8: 0.722

Its review warned that the 0.975 was partly a lucky draw of wordings. This run asks whether the same results come out on
50 different documents.

### Nothing changes but the documents

**The system, unchanged since the freeze:**
- The same code. `cie/src` has not changed since commit `7017046`.
- The same lessons: `plan_lessons_v9.json` (`00e63e5fbca8cee8…`), `plan_lessons_v9n.json` (`1b68d133783a7958…`), and
  v4's and v8's as before.
- The same glossary, v10 prompt (`bf3f84a670bd43be`) and model (`llama3.2:3b`, manifest `a80c4f17acd55265…`).

**The questions:**
- The same blind wordings: `docs/benchmarks/factbank_plan/wordings.json`, the pairs from writers 1 and 2.
- Each question's wording is drawn from its pair at random, as before.
- The same seven rules, applied to the new set.

**The documents:**
- A new sample of the whole benchmark: `fresh --seed 41`, questions seed 42.
- **Excluded:** every document of every earlier set, now including the first planner test's (`mdplan`). The full list is
  `mt5k`, `mt50`, `fb50`, `fbtest`, `mdtrain`, `mdtest`, `mdfresh`, `mdwords`, `mdblind`, `mdllm`, `mdplan` and the
  lexicon's 200,000-document sample (`lexsample`).
- The changed-information copy is made by the same fixed transform.

**The script:** `docs/benchmarks/factbank_plan/run_replication.sh`. It is the frozen run script with the seed, the output
folder and the exclusion list changed, plus the single-writer runs below.

### What counts as "the same results"

1. **The same verdicts:** rules 1, 2, 3, 5, 6 and 7 are all met again on the new set. Rule 4 (v10 − v9 ≥ +0.05) is
   reported but not required: on the first test it could not be met.
2. **The level holds:** v9 on the drawn wordings scores at least 0.925, within 0.05 of the first test's 0.975.

### Also reported (information only)

- Every arm's score next to its first-test score, by group and by kind.
- **The same questions in a single writer's wording**, as run after the first test:
  - writer 1 only;
  - writer 2 only;
  - writer 3 (the stand-in, plain words) only.
- How often v10's form was used, and the model's time.

**How to read differences:** one link or combine question moves the mean by about 0.015–0.02, and one compare question
by 0.042. So differences of 0.04 or less are within noise.
