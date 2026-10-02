# Document expansion: results

Pre-registration: `docs/EXPANSION_PREREGISTRATION.md` (committed in f320d4e before any test-half run).

## In short

Often the memory bank found the right document but not the passage that held the answer ("right document, wrong
part": 24% of judged questions). Document expansion takes the first 3 documents of the ranked list and runs a keyword
search inside each one. Each document's 5 best passages are placed right after the document's first item.

On the test half, every pre-registered criterion was met. **Expansion is now on by default** (3 documents × 5
passages). The 50,000-document run on Colab (test B) confirms or reverts it.

## Test A: 5,000 documents, local (BM25, extractive answers, model view of 24,000 characters)

**Evidence audit, test half (even question numbers, 190 judged questions):**

| Stage | Expansion off | Expansion on |
|---|---|---|
| search missed the document | 9 | 9 |
| right document, wrong part | 44 | 35 |
| cut before the model | 11 | 10 |
| **everything reached the model** | **126 (66.3%)** | **136 (71.6%)** |
| answer facts in the packet (of 652) | 517 | 545 |
| answer facts in the model view | 464 | 487 |

**Retrieval benchmark, all 500 questions:**

| Measure | `[BM25]` (expansion off) | `[BM25+expansion]` |
|---|---|---|
| doc recall@10 | 0.878 | 0.872 |
| MRR | 0.761 | 0.756 |
| p50 latency | 419 ms | 401 ms |
| p95 latency | 879 ms | 861 ms |
| keyword searches served by BM25 | 1,000 of 1,000 | 1,000 of 1,000 |

The expansion arm ran first, as pre-registered. Its lower latency is run-to-run variation, not a speed-up. On
development questions, expansion added about 45 ms at p50 (the three keyword searches take about 24 ms).

**Criteria:**

| Criterion | Result | Met |
|---|---|---|
| 1. everything reached the model: at least +4 points (even half) | 71.6% vs 66.3% (+5.3) | yes |
| 2. facts in the model view: at least as many (even half) | 487 vs 464 | yes |
| 2. search missed the document: at most +2 (even half) | 9 vs 9 | yes |
| 3. recall@10 at least `[BM25]`'s − 0.01 | 0.872 vs 0.878 | yes |
| 3. MRR at least `[BM25]`'s − 0.01 | 0.756 vs 0.761 | yes |
| 4. p50 at most `[BM25]`'s + 100 ms | 401 vs 419 ms | yes |
| 4. p95 at most `[BM25]`'s + 200 ms | 861 vs 879 ms | yes |

**Decision (as fixed in advance):** every criterion was met, so the default is now 3 documents × 5 passages
(`packet_expand_documents = 3`). `CIE_PACKET_EXPAND_DOCUMENTS=0` turns it off.

## Reported, with no threshold

**All 379 judged questions (both halves; the odd half was used to choose the setting):**

| Stage | Expansion off | Expansion on |
|---|---|---|
| search missed the document | 15 (4%) | 15 (4%) |
| right document, wrong part | 91 (24%) | 69 (18%) |
| cut before the model | 27 (7%) | 21 (6%) |
| **everything reached the model** | **246 (65%)** | **274 (72%)** |
| answer facts in the packet (of 1,325) | 1,033 | 1,082 |
| answer facts in the model view | 911 | 964 |

On the development half alone: 120 → 138.

**Questions that changed stage:**
- 34 got better: 24 went from "wrong part" to "everything reached", and 10 from "cut" to "everything reached".
- 8 got worse: 6 went from "everything reached" to "cut", and 2 from "cut" to "wrong part". The added passages
  take room, so other evidence falls past the 24,000 characters a small model reads.
- 337 stayed the same.

**By question type (everything reached the model):**

| type | judged | off | on | wrong part, off → on |
|---|---|---|---|---|
| basic | 136 | 118 | 123 | 14 → 9 |
| semantic | 91 | 33 | **50** | 37 → 24 |
| project_related | 40 | 12 | 12 | 22 → 22 |
| intra_document_reasoning | 39 | 34 | 37 | 4 → 2 |
| constrained | 29 | 18 | 20 | 6 → 4 |
| completeness | 17 | 7 | 8 | 8 → 8 |
| miscellaneous | 15 | 14 | 14 | 0 → 0 |
| conflicting_info | 12 | 10 | 10 | 0 → 0 |

Semantic questions gain the most. Project questions gain nothing: their answers span several documents, and
expansion only looks deeper inside the first three. That is the largest loss left.

**Other retrieval measures (all 500 questions):** recall@5 0.817 → 0.810, hit@10 0.911 → 0.902, every gold document
found 0.834 → 0.830, hit@1 unchanged at 0.677. The added passages use packet room, so a few lower-ranked documents no
longer fit.

## A side effect found in the test run, and fixed

Two measures with no threshold got worse:
- **Facts in the extractive answer:** 161 → 148.
- **False abstentions** (declining a question that has an answer): 1.3% → 2.1%. On the 20 questions with no answer,
  1 more was declined (0 → 5%).

**Cause.** The extractive answer (strict mode, no model) reads only the packet's leading items:
- it checks evidence strength on the first 5 items;
- it quotes the first section.

Expansion puts up to 5 passages right after the first item. Those passages pushed the strongest items out of the
first 5, and the quote became one document's passage instead of the best-ranked one.

**Fix.** Packet items placed by expansion are marked (`expanded`). The extractive answer reads the packet without
them, in search's own order. The model-written answer still gets every item. The packet itself does not change.

**Re-measured after the fix.** This was not pre-registered: the fix was made after seeing the test results.

| Measure | Expansion off | On (test run) | On (after the fix) |
|---|---|---|---|
| everything reached the model (all 379) | 246 | 274 | 274 |
| facts in the extractive answer | 161 | 148 | **164** |
| false abstentions | 1.3% | 2.1% | **1.5%** |
| declined on questions with no answer | 0% | 5% | 0% |
| doc recall@10 | 0.878 | 0.872 | 0.876 |
| MRR | 0.761 | 0.756 | 0.761 |
| p50 / p95 latency | 419 / 879 ms | 401 / 861 ms | 437 / 881 ms |

"After the fix" is a separate run of the expansion arm alone. Its latency comes from a different run than the others.

## What this does not show

- **Whether a model's answers improve.** More questions now have every fact in what the model reads. Whether Llama
  then answers them correctly is measured on Colab (Part 1b with `LLM_ANSWERS`).
- **50,000 documents.** Test B on Colab: Part 1 runs both benchmark arms, and Part 1b runs the audit with expansion
  off and on. The notebook prints each criterion.
- **Other benchmarks.** Runs made before this change (the operating loop, OCR) had no expansion. Later runs have it by
  default.

## Files

All in `docs/benchmarks/expansion/`:
- `audit_5k_expansion_off.json`, `audit_5k_expansion_on_test.json` and `audit_5k_expansion_on_after_fix.json`: the
  evidence audits, with per-half and per-category summaries.
- `bench_expansion_5k.json` and `.md`: the two benchmark arms (test A).
- `bench_expansion_5k_after_fix.json`: the expansion arm after the fix.
- `dev_sweep_odd_half.json`: the settings tried on the development half.
