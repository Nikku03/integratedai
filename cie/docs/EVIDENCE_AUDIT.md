# Where answers get lost: search, packaging or the model

When an answer is wrong, there are two possible causes. Either the memory bank never put the answer in front of the
model, or the model had it and still got it wrong. `cie.eval.evidence_audit` tells them apart. EnterpriseRAG-Bench
gives every question its answer as short facts (`answer_facts`, for example "The default per-file limit is 10 MiB").
The audit follows those facts through the answer path and records the first stage that loses any of them:

| Stage | What happened | Whose fault |
|---|---|---|
| 1. search missed the document | no gold document in the evidence packet | the memory bank (search) |
| 2. right document, wrong part | a gold document is in the packet, but the passage holding a fact is not | the memory bank (selection) |
| 3. cut before the model | every fact is in the packet, but not in the part a small model reads (24,000 characters) | the memory bank (packaging) |
| 4. everything reached the model | every fact is in what the model reads | a wrong answer here is the model's |

## How a fact is checked

A fact counts as present in a passage when:
- every number in it appears as a whole number;
- at least 70% of its content words appear after English stemming.

One passage (a section, or a record) must hold the fact; words scattered over the packet do not count. Each fact is
first checked against the gold documents' own sections. A fact the check cannot find there, because it is
paraphrased, is left out. 91 of the 470 questions had no checkable fact and are not judged.

**Control.** Facts were checked against another question's packet. 3 of 187 matched (1.6%), so the check rarely
finds a fact that is not there.

## Results: 5,000 documents, the 470 questions with gold documents (local, extractive answers)

| Stage | BM25 + document expansion (the default) | BM25 | Full text |
|---|---|---|---|
| 1. search missed the document | 15 (4%) | 15 (4%) | 22 (6%) |
| 2. right document, wrong part | 69 (18%) | 91 (24%) | 100 (26%) |
| 3. cut before the model | 21 (6%) | 27 (7%) | 29 (8%) |
| 4. everything reached the model | **274 (72%)** | 246 (65%) | 228 (60%) |
| answer facts in the packet | 1,082 of 1,325 (82%) | 1,033 (78%) | 963 (73%) |
| answer facts in what a small model reads | 964 (73%) | 911 (69%) | 832 (63%) |

Document expansion came after the first two columns. It searches inside the first 3 documents for their best passages
(`docs/EXPANSION_RESULTS.md`). The odd half of these questions was used to choose its setting. On the even half
alone, everything reached the model in 71.6% of questions, against 66.3% without expansion.

The findings below describe BM25 without expansion, where the audit started.

- **Search finds the document.** It missed the answer document in only 4% of questions. 14 of those 15 misses were
  "semantic" questions, worded unlike the document.
- **Selection is the biggest loss: 24%.** The right document is found, but not every passage the answer needs. This
  is worst where an answer spans several passages or documents:
  - project questions: 22 of 40;
  - completeness questions: 8 of 17;
  - semantic questions: 37 of 91.

  Document expansion brings it to 18% (semantic questions 24 of 91). Project and completeness questions do not
  improve: their answers span several documents.
- **Packaging loses 7%.** Every fact was in the packet, but Llama reads only the first 24,000 characters. A model with
  a larger context, such as Claude, gets the whole packet, so these questions would reach stage 4.
- **For 65% of questions, everything needed reached the model.** A wrong answer there is the model's fault.

By question type (BM25):

| type | judged | missed document | wrong part | cut | everything reached |
|---|---|---|---|---|---|
| basic | 136 | 0 | 14 | 4 | 118 |
| semantic | 91 | 14 | 37 | 7 | 33 |
| project_related | 40 | 0 | 22 | 6 | 12 |
| intra_document_reasoning | 39 | 0 | 4 | 1 | 34 |
| constrained | 29 | 0 | 6 | 5 | 18 |
| completeness | 17 | 1 | 8 | 1 | 7 |
| miscellaneous | 15 | 0 | 0 | 1 | 14 |
| conflicting_info | 12 | 0 | 0 | 2 | 10 |

**The model's share is not measured yet.** These runs used the extractive answer, which quotes the top evidence
rather than answering, so its fact coverage says nothing about a model. With `--assisted`, the audit has the
configured model compose each answer. Stage 4 then splits into:
- answers that hold every fact;
- answers that miss one;
- answers the model declined.

The Colab notebook runs this (Part 1b) with Llama 3.1 8B at 50,000 documents.

## What this does not show

- **Paraphrased facts.** A fact worded differently from every passage is not judged: 19% of questions.
- **Answer correctness.** Having the facts is necessary for a right answer, not sufficient. The benchmark's LLM judge
  grades answers; it was not run.
- **50,000 documents.** These numbers are from the 5,000-document memory bank. The notebook measures them at 50k.

Raw results: `docs/benchmarks/audit/evidence_audit_5k_bm25.json` and `evidence_audit_5k_fts.json`; with document
expansion, `docs/benchmarks/expansion/`.

Tried and not adopted: BM25 over the sentences of the first 5 documents, with the extracts placed first (`docs/benchmarks/inside_bm25/`). On
the development half it moved at most 2 of 189 questions. Most missed facts sit in documents outside the first 5.
