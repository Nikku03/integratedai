# Facts extracted by Llama 3.1 8B at load time: results

The plan and the criteria are in `docs/FACT_EXTRACTION_PREREGISTRATION.md`. The notebook is
`notebooks/fact_extraction_colab.ipynb`, and the code is in `cie.eval.extract_facts`. The documents are the benchmark's
generated (fictional) company data.

## Run 1: 2026-10-04, A100 80 GB

**Set-up**
- Code at commit `ab9fe64`.
- Weights: `RedHatAI/Llama-3.1-8B-Instruct` at `83c9274` (meta-llama's repo is gated), in bf16.
- vLLM 0.30.0, temperature 0, at most 768 output tokens per passage.
- Up to 512 passages in flight and 16,384 tokens per step; results saved every 4,096 passages.
- 5,000 documents and 33,363 passages; 470 questions and 2,207 answer facts. Of those, 1,388 are found word for word
  in a gold passage, which is the ceiling.

**Answer facts kept** (the evidence audit's word check, not the judge)

| | kept, of 1,388 | share | in one line |
|---|---|---|---|
| rule-based records (today) | 707 | 51% | 453 |
| Llama 3.1 8B | 1,215 | 88% | 391 |

| question type | checkable | rule-based records | Llama 3.1 8B |
|---|---|---|---|
| basic | 359 | 181 | 321 |
| completeness | 222 | 137 | 197 |
| conflicting_info | 32 | 8 | 23 |
| constrained | 128 | 64 | 104 |
| intra_document_reasoning | 81 | 41 | 69 |
| miscellaneous | 34 | 23 | 31 |
| project_related | 261 | 110 | 231 |
| semantic | 271 | 143 | 239 |

**What Llama wrote**
- 587,032 fact lines, 17.6 per passage.
- 7,660 lines (1.3%) carry a number that is not in their passage.
- 17,315 lines (2.9%) have weak word support in their passage.
- 20,662 repeated lines were dropped.
- 1,602 passages (4.8%) reached the 768-token cap, so their lists are cut short.

**Speed**
- 3,792 output tokens and 11.36 passages per second: the 33,363 passages took about 49 minutes.
- Loading the model took about 2.5 minutes.
- Projected time on this GPU: 0.82 hours for 5,000 documents, 8.2 hours for 50,000 and 84 hours for 512,000. The
  passages per document come from this set, which holds every gold document. Gold documents run longer than average,
  so the two larger figures may be high.

**Criteria**
1. Answer facts covered (judged): **not decided.** The runtime was disconnected before the judge ran, and the facts,
   kept on the runtime's own disk, were lost.
2. Wrong or unsupported lines (judged): **not decided**, for the same reason.
3. Lines with a number not in their passage: 1.3%, against at most 2%: **met.**

**How to read the word check**
- It is a word-overlap check, not a judgment. The judge decides criteria 1 and 2.
- The rule-based records' 51% includes the document card, which copies the first passages word for word. Without that
  copy, their share would be lower. Run 1 did not measure it; the score step now reports it, for information.
- "In one line" is lower for Llama (391 against 453) because Llama splits a passage into many short lines. The card's
  copied passage is one long line holding many facts.

## Changes before run 2

- Results are written to Google Drive as they come, so a disconnect loses nothing, and Run all continues the run.
- The amendments in the pre-registration, made before any judged result.
- The size of the facts against the passages counts only the passages done, so a partial run reads correctly.
- Results are saved every 8,192 passages, not 4,096. Each save waits for the batch to empty, so fewer saves waste less
  GPU time.
- The notebook stops at once on a GPU that cannot run bf16 (a T4 or V100). On a driver older than 580 it installs
  vLLM's CUDA 12.9 build.
