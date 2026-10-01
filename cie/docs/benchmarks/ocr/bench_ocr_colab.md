# OCR benchmark on Colab (A100): report as produced

Run by `notebooks/enterprise_rag_bench_colab.ipynb` Part 3 (`python -m cie.eval.bench_ocr --docs 30 --ingest 5 --engines
tesseract,unlimited_ocr`), code of branch `claude/epic-keller-gevn7j` at c00ed8d. Tesseract 5.3.4 ran on the CPU (one
thread per page). Unlimited-OCR (`baidu/Unlimited-OCR` at revision 07dea83) ran in the process on the A100, in bf16,
through `transformers` 4.57.1. Rules: `docs/OCR_PREREGISTRATION.md`. Results and decision: `docs/OCR_RESULTS.md`.

### OCR benchmark: 30 EnterpriseRAG-Bench documents typeset at 200 dpi, 116 scanned pages (scan, hard levels; seed 11)

| engine | level | pages | median CER | mean CER | median WER | numbers kept | s/page p50 |
|---|---|---|---|---|---|---|---|
| tesseract (5.3.4) | hard | 58 | 0.0065 | 0.0607 | 0.0359 | 0.9712 | 2.203 |
| tesseract (5.3.4) | scan | 58 | 0.0019 | 0.0097 | 0.0127 | 0.999 | 2.352 |
| unlimited_ocr (baidu/Unlimited-OCR@07dea83) | hard | 58 | 0.0025 | 0.012 | 0.0086 | 1.0 | 33.602 |
| unlimited_ocr (baidu/Unlimited-OCR@07dea83) | scan | 58 | 0.0 | 0.002 | 0.0 | 1.0 | 33.995 |

| engine | all pages: median CER | p90 CER | numbers kept | s/page p50 / p95 | load s | failed pages |
|---|---|---|---|---|---|---|
| tesseract | 0.0036 | 0.1308 | 0.9851 of 2,080 | 2.266 / 2.871 | 0.0 | 0 |
| unlimited_ocr | 0.0013 | 0.0137 | 1.0 of 2,080 | 33.645 / 40.183 | 29.8 | 0 |

Memory bank from 5 scanned documents read by tesseract: 13 sections, records {'document': 5, 'metric': 8, 'risk': 4,
'decision': 3, 'requirement': 1}, numbers kept in the sections 1.0, 29.8 s.

Memory bank from 5 scanned documents read by unlimited_ocr: 18 sections, records {'document': 5, 'metric': 8, 'risk': 4,
'decision': 3, 'requirement': 1}, numbers kept in the sections 1.0, 296.2 s.

Pre-registered criteria (docs/OCR_PREREGISTRATION.md):

| Criterion | Met | Value |
|---|---|---|
| 1. hard pages: median CER lower than Tesseract's | yes | 0.0025 vs 0.0065 |
| 2. office scans: median CER at most Tesseract's + 0.005 | yes | 0.0 vs 0.0019 |
| 3. numbers kept at least Tesseract's | yes | 1.0 vs 0.9851 |
| 4. at most 2 pages failed | yes | 0 |

All criteria met.

First page as each engine read it (both correct; Unlimited-OCR joins the wrapped lines of a paragraph, Tesseract keeps
the line breaks of the page): Unlimited-OCR CER 0.0015 in 31.8 s, Tesseract CER 0.0038 in 2.8 s.
