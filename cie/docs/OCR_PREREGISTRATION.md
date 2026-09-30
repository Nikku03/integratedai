# Unlimited-OCR against Tesseract on scanned company documents: fixed before the test run

I wrote this before running the test. The development check used seed 1 and three documents with Tesseract only,
to make sure the pipeline runs; the test uses seed 11.

Two things the development check found are already fixed:
- **Tesseract stalls on this container's CPU.** Its OpenMP threads took 578 s on one page, against 2 s with one thread.
  The adapter now runs it with one thread (`OMP_THREAD_LIMIT=1`).
- **The office-scan level is easy for Tesseract.** It read the development pages at about 0.1% CER, so a second,
  harder level was added before any test. On six development pages at the hard level, Tesseract's median CER was 0.003
  and its mean 0.035. It sometimes fails a page outright: on one extra test page, which a person reads easily, its CER
  was 0.92.

## Question

The memory bank reads scanned PDFs and images through OCR. Tesseract 5 runs on the CPU. `baidu/Unlimited-OCR` is a
3.3B-parameter vision-language OCR model that needs a GPU. It is now wired in two ways: a server
(`CIE_UNLIMITED_OCR_URL`), or the model loaded in the process on a CUDA GPU (`UnlimitedOCRLocal`, revision 07dea83).

1. How accurately does each engine read scanned company documents, and how fast?
2. Built from each engine's output, does the memory bank keep the documents' figures?

The EnterpriseRAG-Bench corpus is exported text (JSON), not scans. Its 50,000-document memory bank does not use OCR
and is not changed by this test. The test typesets some of that text as scanned pages, so that the true text of
every page is known.

## Setup (`cie.eval.bench_ocr`)

- **Pages.** 30 EnterpriseRAG-Bench documents (seed 11, at least 600 characters each), at most 2 letter-size pages
  per document, typeset at 200 dpi in an 11-point sans-serif font.
- **Degradation.** Every page is scanned at two levels (`bench_ocr.LEVELS`):
  - `scan`, an office scan: rotation up to 1 degree, Gaussian blur of radius 0.6, grain with sigma 8, JPEG at quality 60;
  - `hard`, a poor copy: rotation up to 3 degrees, scanned at 75% resolution and scaled back, blur of radius 1.0, grain
    with sigma 16, JPEG at quality 35.
- **Engines.**
  - `tesseract`: the version Colab installs, on the CPU, through the extraction pipeline's adapter.
  - `unlimited_ocr`: the model in the process on the Colab A100, in bf16. It uses the model card's single-image
    settings: base 1024, tiles 640, cropping on, no repeated 35-token n-grams within 128 tokens, at most 8,192
    tokens.
- **Measures.** Per page:
  - character error rate (CER) and word error rate (WER), on text normalised the same way for both engines;
  - numbers kept verbatim;
  - seconds per page, and the time to load the engine.
- **Memory bank.** `--ingest 5`: the first 5 documents, at the `scan` level, go through the vault and extraction pipeline
  with each engine, in a new tenant. For each engine it reports:
  - the sections and typed records built;
  - the share of the documents' numbers found in the sections.

## Test run

Once, on Colab, in the notebook's Part 3.

## Criteria

Unlimited-OCR becomes the preferred engine on machines with a CUDA GPU if all of these hold:

1. **Accuracy on poor copies.** On `hard` pages, its median CER is lower than Tesseract's.
2. **No loss on office scans.** On `scan` pages, its median CER is at most Tesseract's + 0.005.
3. **Figures.** Over all pages, it keeps at least as large a share of the numbers as Tesseract.
4. **Reliability.** At most 2 of its pages fail, whether by error or timeout.

Speed is reported without a threshold, because a GPU and a CPU do not cost the same.

## Decisions fixed in advance

- **All met.** `unlimited_ocr_local` defaults to true. `ocr_backend=auto` then reads scanned pages with Unlimited-OCR
  on any machine with a CUDA GPU (or a configured server), and with Tesseract elsewhere.
- **Any not met.** Unlimited-OCR stays opt-in (`CIE_OCR_BACKEND=unlimited_ocr`, or `CIE_UNLIMITED_OCR_LOCAL=true`),
  and Tesseract stays the default.

Every result is reported, including failures.

## What this does not show

- **Real paper.** There are no stamps, handwriting, photos taken at an angle, forms or complex tables.
- **Other languages.** The text is English, typeset in ASCII.
- **Its long, multi-page mode.** The model can read many pages in one pass ("unlimited" context). The pipeline sends
  one page at a time, so that every block keeps its page number for citations.
