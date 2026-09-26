# Learned REM explorer: results

An experimental recurrent graph network that learns which company-memory records to explore and return, with a
Blue Brain–informed variant. The rules were fixed in `docs/REMNET_PREREGISTRATION.md` (one amendment, made
before the test run). Raw summaries are in `docs/benchmarks/remnet/`.

## Decisions

| Rule | Result |
|---|---|
| 1. Useful to the engine: beats the best non-learned arm by ≥ 0.02 (CI excluding 0) on **both** datasets | **Not met.** The REM network wins by a wide margin on the controlled dataset (+0.184) but not on ERB (+0.020, CI −0.008 to +0.046). The MLP and GGNN win on ERB (+0.029, +0.034) but lose on the controlled dataset. |
| 2. Message passing earns its place | **Met** by the REM network: +0.240 over the MLP on the controlled dataset, −0.010 on ERB (within tolerance). |
| 3. Bounded activation keeps accuracy with ≤ 50% of the updates | **Mixed.** Controlled: +0.281 over GGNN using 26% of its node updates. ERB: −0.014 (CI −0.028 to 0.000) using 19%. |
| 4. Routing shortcuts help | **Not met** (+0.001 and +0.000). |
| 5. Blue Brain detail helps | **No evidence.** Against same-mechanism controls, the Blue Brain variant is within ±0.0005 on the controlled dataset and +0.004 to +0.009 on ERB, with every CI including 0. The mechanism with random or learned parameters does as well. |

What this means for the engine:
- **Default stays as is.** Nothing replaces typed traversal by default.
- **The bounded REM network is worth developing further**, because of how large its effect is on dependency-structured data.
  - It needs out-of-distribution evaluation first. The controlled training and test data come from one generator.
  - On document retrieval (ERB), a cheap per-record reranker (the MLP) is as good.
- **The Blue Brain variant should not be pursued** as an engine component on this evidence.

## What was built (`cie/src/cie/remnet/`)

- **Candidate pool.** For each question, the permission-filtered typed traversal from the same start hits the baselines use (depth 2, at most 300 records). The network re-ranks inside it, so a gain cannot come from a larger pool.
- **Node state.** The record's embedding plus its type, search rank, hop distance, reliability and degree. The question is embedded the same way.
- **Update.** h_i ← GRU(h_i, Σ_j α_ij(q,t) W_{r_ij} h_j): relation-typed weights with both edge directions, and question-conditioned attention.
- **Arms.**
  - `mlp`: no messages.
  - `ggnn`: every record updated at every step.
  - `rem`: starts at the search hits. Each step it loads the neighbours of active records, and a learned gate activates at most K of them (16 on the controlled dataset, 32 on ERB). Only touched records can be returned. Routing shortcuts form an extra relation.
- **Biological variants** (from the NMC portal pathway factsheets, 1,932 pathways; `data/bluebrain/SOURCE.md`):
  - contradicts/supersedes edges carry inhibitory messages;
  - each edge has Tsodyks–Markram short-term plasticity with U, D, F and a release-failure rate drawn from a Blue Brain pathway of matching sign, at one step = 50 ms.
  - Controls: the same mechanism with random parameters over the Blue Brain ranges, or with learned per-relation parameters.
- **Permissions.** Enforced before the network: pools contain only records the requester may read (tested).

## Data

| Dataset | Train | Validation | Test | Pool (median) | Gold inside the pool |
|---|---|---|---|---|---|
| Controlled (synthetic) | 564 questions (60 seeds) | 36 | 83 (10 new seeds) | 61 records | 93% |
| EnterpriseRAG-Bench | 185 | 49 | 236 (held-out split) | 166 records | 89% |

## Test results

Learned arms are the mean of 3 training seeds; the seed-to-seed standard deviation is at most 0.023. Non-learned arms run through `run_query` on the same start hits and budgets.

**Controlled dataset, 350-token budget** (primary: recall@10):

| Arm | recall@10 | Evidence recall | Evidence precision | MRR | Node updates | Inference p95 |
|---|---|---|---|---|---|---|
| A search | 0.478 | 0.478 | **0.603** | 0.926 | — | — |
| B traversal | 0.743 | 0.908 | 0.287 | 0.948 | — | — |
| C REM priority | 0.745 | 0.914 | 0.280 | 0.948 | — | — |
| mlp | 0.689 | 0.870 | 0.270 | 0.979 | 0 | 0.3 ms |
| ggnn | 0.648 | 0.842 | 0.261 | 1.000 | 184 | 5.7 ms |
| **rem** | **0.929** | **0.933** | 0.322 | 1.000 | 48 | 7.6 ms |
| rem, no routing | 0.928 | 0.932 | 0.325 | 1.000 | 48 | 6.1 ms |
| rem + inhibition | 0.929 | 0.933 | 0.322 | 1.000 | 48 | 6.4 ms |
| rem + inhibition + **Blue Brain** STP + failures | 0.928 | 0.928 | 0.308 | 0.991 | 48 | 7.5 ms |
| rem + inhibition + random STP + failures | 0.928 | 0.931 | 0.297 | 1.000 | 48 | 8.5 ms |
| rem + inhibition + learned STP | 0.929 | 0.931 | 0.321 | 1.000 | 48 | 7.5 ms |

**EnterpriseRAG-Bench, 2,000-token budget** (primary: MRR of the first gold document):

| Arm | MRR | Evidence recall | Evidence precision | Node updates | Inference p95 |
|---|---|---|---|---|---|
| A search | 0.740 | 0.817 | 0.262 | — | — |
| B traversal | 0.740 | 0.818 | 0.251 | — | — |
| C REM priority | 0.607 | 0.794 | 0.173 | — | — |
| mlp | 0.769 | 0.823 | 0.289 | 0 | 0.6 ms |
| ggnn | **0.774** | 0.814 | **0.333** | 495 | 9.1 ms |
| rem | 0.760 | 0.820 | 0.304 | 96 | 10.8 ms |
| rem, no routing | 0.760 | 0.824 | 0.305 | 96 | 11.4 ms |
| rem + inhibition | 0.765 | 0.826 | 0.311 | 96 | 12.1 ms |
| rem + inhibition + **Blue Brain** STP + failures | 0.769 | 0.812 | 0.315 | 96 | 10.8 ms |
| rem + inhibition + random STP + failures | 0.762 | 0.818 | 0.315 | 96 | 11.1 ms |
| rem + inhibition + learned STP | 0.759 | 0.809 | 0.317 | 96 | 11.8 ms |

At 6,000 tokens every arm's evidence recall is between 0.854 and 0.871.

**Paired comparisons on the primary metric** (bootstrap 95% CI over test questions):

| Comparison | Controlled | ERB |
|---|---|---|
| rem vs best non-learned | +0.184 [0.151, 0.219] | +0.020 [−0.008, 0.046] |
| mlp vs best non-learned | −0.056 [−0.100, −0.012] | +0.029 [0.003, 0.056] |
| ggnn vs best non-learned | −0.097 [−0.138, −0.060] | +0.034 [0.008, 0.059] |
| rem vs ggnn | +0.281 [0.252, 0.311] | −0.014 [−0.028, 0.000] |
| rem vs mlp | +0.240 [0.198, 0.280] | −0.010 [−0.025, 0.003] |
| rem vs rem without routing | +0.001 [0.000, 0.003] | +0.000 [−0.010, 0.010] |
| Blue Brain vs inhibition only | −0.001 [−0.002, 0.000] | +0.004 [−0.009, 0.017] |
| Blue Brain vs random parameters | +0.001 [0.000, 0.002] | +0.007 [−0.004, 0.019] |
| Blue Brain vs learned parameters | −0.001 [−0.002, 0.000] | +0.009 [−0.003, 0.022] |

On ERB by question type, the learned models gain most on *completeness* (search 0.722 → 0.85–0.87, n = 9) and
*conflicting-info* (0.900 → 1.000, n = 10). They lose on *intra-document reasoning* (0.879 → 0.81–0.87, n = 20). These groups are small.

## Cost (CPU, one core per training run)

| | mlp | ggnn | rem variants |
|---|---|---|---|
| Parameters (weights) | 64k (250 KB) | 180k (705 KB) | 181k (706 KB) |
| Training time per run: controlled / ERB | 7 s / 2 s | 98 s / 28 s | 63–119 s / 36–47 s |
| Inference p95 per question | < 1 ms | 6–9 ms | 6–12 ms |
| Worker peak memory | 0.5–0.7 GB | 0.5–0.8 GB | 0.5–0.8 GB |

Worker memory is dominated by the Python process and the loaded samples, not the models.

Other costs:
- **Candidate pool extraction** (shared by every learned arm): median 102 ms on the controlled dataset and 342 ms on ERB.
- **Non-learned arms, median latency:**
  - search: 45–48 ms;
  - traversal: 87–158 ms;
  - REM priority: 100–254 ms.
- **Building the training data:** 22 minutes for 74 controlled tenants, and 20 minutes for 470 ERB questions (hybrid search for each).

## Why the results look like this

- **Bounded activation helps on structured data.** The REM network is anchored to the search hits and grows only through records it activates. On dependency-structured data, the gold evidence sits near the hits along specific relationship types, and the gate learns which to follow. The dense GGNN and the MLP rank all 60 pool records, so they are distracted by the many orders, milestones and tasks the traversal pulls in.
- **On ERB, the graph adds little.** There are few business relationships between documents, so the evidence is mostly the search hits' own passages. A per-record reranker captures most of the gain there, which matches the earlier REM finding that traversal adds nothing over search on this corpus.
- **The Blue Brain dynamics add nothing measurable.** Their main effect over three steps is a fixed decay or growth of message strength per edge, which the trained attention and GRU can represent on their own. The random- and learned-parameter controls perform the same, so the biological values carry no information that helps this task.

## Limitations

- **The controlled dataset is synthetic and templated.** Training and test come from one generator, so the REM network's large gain there is in-distribution. It may partly reflect learned templates, not general skill. The real-data test (ERB) shows a small, non-significant gain.
- **Small training sets.** 564 synthetic and 185 ERB training questions; one hyperparameter setting, not tuned; three training seeds per arm.
- **No compute saving on the database.** The pool is extracted by traversal before the network runs. The REM network's lower node-update count is a model-compute saving, not yet a database one; driving extraction from the gate is the next step if it is pursued.
- **No stop criterion.** The network ranks and the packer fills the token budget; "stop when enough is known" was not trained or evaluated.
- **Limited use of Blue Brain data.** Only short-term plasticity, release failures and sign (from juvenile rat somatosensory cortex pathways) were used. Mapping one message step to 50 ms is an assumption. Connectivity statistics were not used. Other biological mechanisms were not tested.
- **One CPU machine.** Nothing here says anything about energy use or spiking hardware.

## Reproduce

```bash
python -m cie.remnet.bluebrain --fetch                 # Blue Brain factsheets, sha256-checked
python -m cie.remnet.data controlled                   # 74 seeded tenants (about 22 minutes)
CIE_DATABASE_URL=…/cie_erb python -m cie.remnet.data erb --erb-root <EnterpriseRAG-Bench checkout>
python -m cie.eval.bench_remnet --dataset all --eval val    # development
python -m cie.eval.bench_remnet --dataset all --eval test   # the pre-registered single test run
PYTHONPATH=. pytest tests/test_remnet.py
```
