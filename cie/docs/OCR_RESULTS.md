# Unlimited-OCR against Tesseract: results

The rules were fixed in `docs/OCR_PREREGISTRATION.md` and committed (97f079f) before the test ran. The test ran once,
on Colab (A100), in the notebook's Part 3. 30 EnterpriseRAG-Bench documents were typeset into 58 pages, and each page
was scanned at two levels: 116 pages in all. The raw report is `docs/benchmarks/ocr/bench_ocr_colab.md`.

## Outcome

**Every criterion was met.** Following the decision fixed in advance, `unlimited_ocr_local` now defaults to true:
with `ocr_backend=auto`, scanned pages are read by Unlimited-OCR on any machine with a CUDA GPU (or a configured
server), and by Tesseract elsewhere.

| Criterion | Unlimited-OCR | Tesseract | Met |
|---|---|---|---|
| 1. poor copies: median character error rate | 0.25% | 0.65% | yes |
| 2. office scans: median character error rate (at most Tesseract's + 0.5 points) | 0.00% | 0.19% | yes |
| 3. numbers kept, all pages | 2,080 of 2,080 | 2,049 of 2,080 | yes |
| 4. pages failed (at most 2) | 0 | 0 | yes |

## What the numbers mean

- **Fewer errors, and no bad pages.** The median is close for both engines; the difference is the worst pages. On the
  worst 10% of pages, Tesseract lost 13% or more of the characters. Unlimited-OCR's worst 10% stayed at 1.4% or less.
  On poor copies, Tesseract's mean error rate was 6.1%, against 1.2%.
- **Every figure kept.** Unlimited-OCR read all 2,080 numbers (amounts, dates, identifiers) exactly. Tesseract misread
  or lost 31 of them. The memory bank's figures come from these numbers.
- **The same memory bank.** Five scanned documents went through the vault and extraction pipeline with each engine.
  Both built the same typed records (5 document cards, 8 figures, 4 risks, 3 decisions, 1 requirement), with every
  number found in the sections. Unlimited-OCR's output made 18 sections against 13, because it returns paragraphs as
  separate blocks.

## The cost: speed

| | Unlimited-OCR (A100 GPU) | Tesseract (one CPU core) |
|---|---|---|
| seconds per page (p50 / p95) | 33.6 / 40.2 | 2.3 / 2.9 |
| loading the engine | 29.8 s | none |
| 1,000 pages, one process | about 9.3 hours | about 38 minutes |

Unlimited-OCR was 15 times slower here, on far more expensive hardware. The model ran in the process through
`transformers`, one page at a time, with no batching. A vLLM or SGLang server (`CIE_UNLIMITED_OCR_URL`) batches
pages and is the way to read scans in volume. Its speed was not measured.

## What this does not show

- **Real paper.** These pages are typeset text with simulated scanning. There are no stamps, handwriting, photos taken
  at an angle, forms or complex tables. Those are where a vision-language model should gain more, but this test does
  not show it.
- **Other languages.** The text is English, typeset in ASCII.
- **Server throughput.** Only the in-process path was measured.
- **The EnterpriseRAG-Bench memory bank.** Its documents are exported text, not scans, so OCR does not change it.
