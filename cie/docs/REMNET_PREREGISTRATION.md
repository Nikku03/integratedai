# Learned REM explorer: decision rules fixed before the test runs

Written before any model was trained or evaluated on test data. Test data is evaluated once with these settings.

## Question

Can a recurrent graph network learn which company-memory records to explore and return, better than the
non-learned arms (A search order, B typed traversal, C REM priority policy)? Does bounded, REM-style activation
keep the accuracy of an ordinary graph network with less computation? And does biological detail from Blue Brain
data help, beyond the same mechanism with non-biological parameters?

## Data (company data only; Blue Brain data sets parameters of one variant, nothing else)

| Dataset | Train | Validation | Test |
|---|---|---|---|
| Controlled dependency dataset | seeds 1000–1059 | seeds 1–4 | seeds 201–210 (new; never used before) |
| EnterpriseRAG-Bench (5k tenant) | dev split, 80% by hash | dev split, 20% | held-out split (236 questions) |

The candidate pool for every question is the permission-filtered typed traversal (depth 2, at most 300 records)
from the same start hits the baselines use. Every arm packs evidence under the same token budgets:
- Controlled dataset: 350 and 1,000 tokens.
- ERB: 2,000 and 6,000 tokens.

## Arms

- **Non-learned:** A search order, B typed traversal, C REM priority policy, all via `run_query` on the same hits.
- **Learned** (3 training seeds each; d = 64, 3 steps, K = 16 active records per step on the controlled dataset
  and 32 on ERB, Adam lr 2e-3, at most 20 epochs, early stopping on validation):
  - `mlp`: no message passing;
  - `ggnn`: every record updated at every step;
  - `rem`: bounded activation with a learned gate and routing shortcuts;
  - `rem+norouting`: `rem` without routing shortcuts;
  - `rem+inh`: contradicts/supersedes edges inhibitory;
  - `rem+inh+stp-bluebrain+fail`: short-term plasticity and release failures from Blue Brain pathways;
  - `rem+inh+stp-random+fail`: the same mechanism with random parameters over the Blue Brain ranges;
  - `rem+inh+stp-learned`: the same mechanism with learned per-relation parameters.

## Metrics

- **Primary:**
  - Controlled dataset: evidence recall at 350 tokens.
  - ERB: MRR of the first gold document at 2,000 tokens.
- **Guards:** evidence precision at the same budget; inference time per question.
- **Also reported:**
  - recall@10 and evidence recall and precision at every budget;
  - records touched and node updates (compute);
  - parameters, training time, and baseline latency and database calls.

Learned arms are averaged over three training seeds. Paired bootstrap 95% confidence intervals are computed over
test questions (1,000 resamples) for each comparison below.

## Decision rules

1. **Useful to the engine.** A learned arm is proposed for the engine only if, on both datasets:
   - it beats the best non-learned arm on the primary metric by at least 0.02, with a CI excluding 0;
   - its evidence precision is not more than 0.02 lower;
   - its p95 inference time is at most 50 ms per question on CPU, excluding the shared pool extraction.
2. **Message passing earns its place** only if `ggnn` or `rem` beats `mlp` by at least 0.01, with a CI excluding 0,
   on at least one dataset and loses by no more than 0.01 on the other.
3. **Bounded activation is kept** if `rem` is within 0.01 of `ggnn` on the primary metric while doing at most half of
   `ggnn`'s node updates.
4. **Routing shortcuts are kept** only if `rem` beats `rem+norouting` by at least 0.01 with a CI excluding 0.
5. **Blue Brain detail helps** only if `rem+inh+stp-bluebrain+fail` beats both `rem+inh` and
   `rem+inh+stp-random+fail` by at least 0.01, with CIs excluding 0, on both datasets. It must also be no more than
   0.01 below `rem+inh+stp-learned`. Otherwise the result is "no evidence that the Blue Brain values help", even if
   the mechanism itself helps.
6. Every test result is reported, including regressions. Nothing is called a brain simulation, and no energy or
   speed benefit is claimed for biological dynamics on this hardware.

## Amendment 1 (before any test run; after the validation run)

**Change.** On the controlled dataset the primary metric becomes **recall@10 at 350 tokens**: the share of gold
evidence among the first ten evidence items returned. Evidence recall at 350 tokens stays reported.

**Why.** On validation, evidence recall at 350 tokens reached the pool's coverage ceiling (0.980) for every REM
variant and at 1,000 tokens for every arm. It could not separate the variants that rules 3–5 compare, and every
paired difference was exactly 0.

**What did not change.** The ERB primary metric (MRR at 2,000 tokens), the arms, hyperparameters, splits, budgets
and decision thresholds. No model setting was tuned on validation results.

Validation results that informed only this amendment:

| Arm | Controlled: recall@10 at 350 tokens | Controlled: evidence recall at 350 tokens | ERB: MRR at 2,000 tokens |
|---|---|---|---|
| B | 0.811 | 0.952 | 0.768 |
| C | 0.780 | 0.957 | 0.616 |
| mlp | 0.684 | 0.940 | 0.814 |
| ggnn | 0.631 | 0.913 | 0.790 |
| rem | 0.957 | 0.980 | 0.799 |
| rem+inh+stp-bluebrain+fail | 0.949 | 0.980 | 0.803 |

## Outcome (added after the single test run)

| Rule | Result |
|---|---|
| 1. Useful to the engine | **Not met.** rem: controlled +0.184 [0.151, 0.219], ERB +0.020 [−0.008, 0.046]. mlp and ggnn pass on ERB and fail on the controlled dataset. |
| 2. Message passing earns its place | **Met** by rem: controlled +0.240 over mlp, ERB −0.010. |
| 3. Bounded activation | **Mixed.** Controlled: +0.281 over ggnn with 26% of its updates. ERB: −0.014 with 19%. |
| 4. Routing shortcuts | **Not met.** |
| 5. Blue Brain detail helps | **Not met: no evidence.** Every paired difference with the controls is within ±0.01, and every CI includes 0. |

Details are in `docs/REMNET_RESULTS.md`.
