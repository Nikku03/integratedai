# REM benchmark: decision rules fixed before the held-out runs

Written after development on the dev split and before any held-out run. The held-out splits are run once,
with the settings below, and the results are reported whatever they show.

## Frozen settings

* Query policy "v3" (commit that adds this file):
  * query relevance is the cosine similarity of the record's own text to the question, for every record;
  * dependency relevance = normalised search score of the start record × edge-kind and provenance weights
    × 0.8 per hop × 0.5 per change of direction (sibling paths);
  * redundancy and information gain are counted within one evidence role (text or structured record);
  * `max_visited` is strict; under the REM policy, neighbours are admitted in priority order;
  * default weights in `cie.rem.priority.Weights`; nothing is tuned per dataset.
* Controlled dataset: budgets tight / medium / loose as in `cie.eval.bench_rem.BUDGETS`, `start_k = 10`,
  questions asked by the `ops` principal (clearance 2, cannot read Legal), embedding model BAAI/bge-small-en-v1.5.
* ERB: tenant `erbfull-5000-9688c2` (5,000 documents with every gold document), 20 start hits from the engine's
  hybrid search (its own graph expansion off), token budgets 2k and 6k (`cie.eval.rem_erb.BUDGETS`); questions
  split into dev / held-out by the parity of sha1(question_id).
* Change mode: rules R0–R8 as committed; baseline B is typed reverse reachability (3 hops); baseline A is search
  for the changed records' names.

## Development history (dev split only)

| Version | What changed | Tight-budget evidence recall, C vs B |
|---|---|---|
| v1 | first implementation | 0.717 vs 0.850 |
| v2 | dependency relevance decays with hops and sibling paths; qrel = cosine for all; redundancy by role | 0.816 vs 0.857 |
| v3 | `max_visited` enforced strictly (it was checked only between batches); REM admits neighbours by priority | 0.796 vs 0.772 |

v3 also changed baseline B (the strict limit applies to every arm), which is why B's number moved.

## Decision rules

1. **REM priority policy (arm C) becomes the default query policy** only if, on the held-out splits, at the tightest
   budget, its evidence recall is at least B's + 0.02, its evidence precision is at least B's − 0.02, it has no
   unauthorized disclosures and its p95 latency is at most 1.5 × B's; and at every other budget its evidence recall
   is at least B's − 0.01. Otherwise typed traversal (B) stays the default and C stays behind `CIE_REM_POLICY_ENABLED`.
   Both the controlled dataset and ERB must pass.
2. **Routing shortcuts (arm D)** are kept enabled only if D beats C by the same margins at some budget without
   regressing past the same tolerances at the others, on both datasets. Otherwise `CIE_REM_ROUTING_ENABLED` stays off
   (the code stays, so the test can be repeated on other data).
3. **Change-mode rules (C)** are kept if, on held-out, their impact precision and recall are each at least those of
   typed reachability (B) and their incorrect propagation is lower. The comparison with B shows what ignoring the
   business definitions costs; agreement with the oracle is a correctness check of the rules against an
   independent implementation of the same definitions, not evidence that the definitions are the right ones for a
   given company.
4. **Numerical REM inference**: no such engine exists in the inspected repositories, so there is nothing to retain.
5. Any metric that regresses on held-out is reported as a regression, not explained away.

## Outcome (added after the held-out runs)

| Rule | Result |
|---|---|
| 1. REM priority policy as default | **Not met.** Controlled dataset, tight budget: +0.021 evidence recall (+0.033 on the frozen code), +0.015 precision, p95 within bounds; medium and loose within tolerance: passed. ERB, 2k budget: +0.003 evidence recall, −0.074 precision: failed. Typed traversal stays the default; the policy stays behind its flag. |
| 2. Routing shortcuts | **Not met** on either dataset. Flag stays off. |
| 3. Change-mode rules | **Met.** Held-out precision 0.991 vs 0.258 and recall 1.000 vs 0.934 for typed reachability; incorrect propagations 0.06 vs 16.35 per event. |
| 5. Regressions | ERB: the REM policy lowers MRR (0.639 vs 0.738 at 2k) and evidence precision. Reported in `docs/REM_RESULTS.md`. |

Held-out ERB numbers come from the frozen commit (a0d4662). Security fixes made after the review did not change
the ranking path; a 40-question re-run on the final code gave the same aggregates. The controlled dataset was
re-run on the final code. The only ranking change there is a search bug fix, and it did not change any decision.
