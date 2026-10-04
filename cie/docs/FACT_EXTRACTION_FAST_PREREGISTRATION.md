# A faster fact extraction: what is measured and what decides, fixed before the GPU run

I wrote this on 2026-10-04, before any run of the fast setting. It adds to `docs/FACT_EXTRACTION_PREREGISTRATION.md`
(the criteria for Llama 3.1 8B) and does not change it. The notebook `notebooks/fact_extraction_colab.ipynb` runs it
with `SPEED = "fast"` (or `"both"`).

## Why

Run 1 (`docs/FACT_EXTRACTION_RESULTS.md`) took about 49 minutes for 5,000 documents on an A100 80 GB. At that rate,
512,000 documents would take about 84 hours. Its log shows where the time goes:
- About 3,800 output tokens and about 5,300 prompt tokens per second.
- The model wrote about 330 tokens per passage, about 1.6 times the passage itself (median 220 tokens on a 40-document
  sample).
- Writing the output is most of the GPU time.

Three things in run 1's output and input cost time without adding facts:
- **Tag lines.** In the three outputs looked at, the tag line took 18%, 21% and 30% of the output tokens.
- **Repeated subjects.** A list of four items came out as 13 lines, each repeating its subject ("The company's
  predictable performance is due to …", three times).
- **Repeated text.** The builder overlaps a document's passages by up to 120 characters. On the 40-document sample,
  233 of 304 passages start with the end of the previous one: 10.4% of all passage text, often as a cut-off fragment.
  Its facts are extracted twice.

## The fast setting (fixed)

Everything else stays as in run 1: the documents, the passages, temperature 0 and at most 768 output tokens.
1. **Short instructions.** `extract_facts.INSTRUCTIONS_SHORT` at this commit. They are run 1's instructions with
   three changes:
   - one short sentence per fact;
   - several details of one thing go in one sentence, instead of repeating the subject;
   - no tags and no summary.
2. **No repeated text.** Each passage leaves out its start that repeats the end of the previous passage of the same
   document (`extract_facts.without_repeats`). No text is lost, because the previous passage holds it. A passage that
   holds nothing else is not sent. One risk: a fact whose words run across the cut can lose context. F2 below
   measures this.
3. **8-bit weights.** The weights match the GPU:
   - on an A100, INT8 (`RedHatAI/Meta-Llama-3.1-8B-Instruct-quantized.w8a8` at `024e24c`);
   - on an L4 or H100, FP8 (`RedHatAI/Meta-Llama-3.1-8B-Instruct-FP8-dynamic` at `442e7f5`).

   Both are made from Meta's weights, and Red Hat's evaluations put them at about 100% of the bf16 model's scores.
   They use the same tokenizer, chat template and stop tokens as run 1's weights (checked file by file).

**Expected effect.** About twice as fast on an A100. This is an estimate:
- the tag lines and repeated subjects are about a third of the output;
- the repeated text is about 10% of the input;
- 8-bit matrix multiplication is about twice as fast.

The run measures the real effect. The short instructions are the least certain part. On a CPU, Llama 3.2 3B wrote 14%
fewer tokens with them on 6 passages, but it looped until the 768-token cap on 2 passages with each prompt. That is too
few passages, and too different a model, to predict the 8B model's output.

**A quick speed check first** (optional, not a decision): `SPEED = "both"` with `LIMIT_PASSAGES = 2000` runs both
settings on the same 2,000 passages and GPU. It reports output tokens per passage and passages per second for each, in
about 10 minutes. A later full run continues these files.

## Criteria for the fast setting

On the same 5,000 documents, on a full run (every passage):
- **F1. The three criteria of the 8B pre-registration.** Judged "covered" for at least 80% of the sampled answer
  facts, and at least 15 points more than the rule-based records. At most 5% judged wrong or unsupported, with the
  upper 95% bound at most 8%. At most 2% of lines with a number not in their passage. Same judge, samples and seed.
- **F2. Answer facts kept, word check.** The share of answer facts kept, counted without tag lines, is at most 3
  points below the run-1 setting's. The run-1 setting's share also leaves out tag lines, when its full facts are in
  the same results folder. Otherwise the reference is run 1's 87.5% with its tag lines, which is stricter.
- **F3. Speed.** At least 1.5 times the run-1 setting's passages per second on the same type of GPU. The reference is
  the run-1 setting measured in the same folder on the same GPU, or else run 1's 11.36 on an A100 80 GB. On any other
  GPU, with no run-1 measurement on it, F3 is undecided and the speed is reported.

The word check leaves out tag lines for F2 because tag lines add words to it: the short instructions write none, and
they would otherwise lose points for that alone.

## Decisions fixed in advance

- **F1, F2 and F3 all met.** The fast setting is used for the large loads (50,000 and 512,000 documents).
- **Any of them not met.** The run-1 setting stays for the large loads. The report says which failed and by how much.
- A criterion that cannot be decided (no usable judge, or no speed reference) leaves the decision open. It is not
  counted as met.

Every result is reported, including failures. With `SPEED = "both"`, the two settings run one after the other on the
same GPU, and the report shows them side by side.
