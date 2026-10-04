# Facts extracted by Llama at load time: what is measured and what decides, fixed before the GPU run

I wrote this before any run of Llama 3.1 8B on the 5,000-document set. The notebook
`notebooks/fact_extraction_colab.ipynb` runs it, and `cie.eval.extract_facts` holds the code.

## Question

Today the memory bank's typed records come from a rule-based extractor. It is noisy, and on a small set it kept only
about a third of the benchmark's answer facts. Can an open model do better? The test gives Llama 3.1 8B Instruct
(run on one GPU, at load time, with no question) one passage at a time and asks for every fact it states. Two things
decide it:

- does it keep the answer facts the benchmark asks about;
- are the facts it writes correct?

## Pilot on a CPU, before this plan

Llama 3.2 3B on one 6,000-character document (`docs/benchmarks/llama_small/`):
- it kept 10 of 15 answer facts fully and 4 partly;
- 14 of 153 fact lines were wrong (9%).

## Set-up (fixed)

- **Documents.** The 5,000-document memory bank's documents: every gold document plus a sample stratified by source,
  `bench_enterprise.select_docs`, seed 5.
- **Passages.** As the memory bank's builder cuts them.
- **Model.** `meta-llama/Llama-3.1-8B-Instruct`, or the byte-identical `unsloth/Meta-Llama-3.1-8B-Instruct` when the
  token has no access. bf16, vLLM, temperature 0, at most 768 output tokens per passage.
- **Prompt.** One passage per request, with the instructions in `extract_facts.INSTRUCTIONS` at this commit.
- **Comparison.**
  - The rule-based records the builder extracts today, from the same passages.
  - Llama 3.2 3B, the same way, reported for information.
- **Judge.** `gpt-5.4-mini`, on the same samples for every method:
  - 300 answer facts, drawn at random (seed 7) from those the word check finds in a gold passage;
  - 300 extracted fact lines per model, drawn at random (seed 7).

## Measured

- **Answer facts kept, word check.** Every checkable answer fact: is it in the facts extracted from its gold documents?
  This uses the evidence audit's check (numbers and 70% of content words), one passage's fact list at a time.
- **Answer facts kept, judged.** On the 300-fact sample: is the fact stated in the facts extracted from the passage that
  holds it? The judge answers covered, partly, missed or contradicted.
- **Correctness, judged.** On the 300-line sample: is the line correct, wrong or unsupported, according to its passage?
- **Numbers not in the passage.** The share of fact lines with a number that their passage does not contain.
- **Speed.** Output tokens per second and passages per second on the GPU used. Also the hours this projects to for
  5,000, 50,000 and 512,000 documents.

## Criteria for Llama 3.1 8B

1. **Keeps the answer facts.** Judged "covered" for at least 80% of the 300 sampled answer facts, and at least 15 points
   more than the rule-based records on the same sample.
2. **Writes correct facts.** Judged "wrong" or "unsupported" for at most 5% of the 300 sampled lines, with the upper 95%
   (Wilson) bound at most 8%.
3. **Does not invent numbers.** At most 2% of all fact lines carry a number that is not in their passage.

Speed is reported, with no threshold. It decides the cost of a full load, not whether the facts are good.

## Decisions fixed in advance

- **All three criteria met.** The next step loads the extracted facts as memory records in a 5,000-document memory bank,
  and runs the evidence audit and the benchmark. That step gets its own pre-registration. Each fact keeps its passage,
  so answers quote the passage, not the extracted line.
- **Any criterion fails.** The rule-based records stay. The report says which criterion failed and by how much.

Every result is reported, including failures. A judge with more than 5% failed calls makes its two criteria
undecided, not met.

## Amendments (2026-10-04, after run 1's word-check table, before any judged result)

Run 1 (`docs/FACT_EXTRACTION_RESULTS.md`) finished the extraction and the word check. Its runtime was then
disconnected before the judge ran, and its facts were lost. The word-check table had been seen; no judged result had.
These changes were made before the second run.

1. **Judged retention.** The judge sees the facts of up to three passages that hold the answer fact, not only the
   first. This applies to every method. A fact often sits in several passages, and the first is not always the one
   with all its words.
2. **Judge failures.** The failure share counts the calls actually sent. An answer fact whose passages have nothing
   extracted is "missed" without a call, and it is not counted as a call.
3. **Decision.** If any criterion is not met, the result is "not met", even when another criterion is undecided.
4. **Rounding.** Criterion 1's "+15 points" is compared after rounding the difference to six decimals, so exactly
   15 points passes.
5. **Weights.** Without access to `meta-llama/Llama-3.1-8B-Instruct`, the code uses
   `RedHatAI/Llama-3.1-8B-Instruct` at revision `83c9274` (the same weight files). Next is
   `unsloth/Llama-3.1-8B-Instruct` at `4699cc7` (the same weights; its config adds a pad token). This replaces the name
   `unsloth/Meta-Llama-3.1-8B-Instruct` above. Run 1 used RedHatAI.
6. **Comparison model.** Llama 3.2 3B is optional and not in the default run, since the test is of the 8B model.
7. **For information only.** No criterion uses these:
   - the rule-based records without the document card's copied passages;
   - numbers checked one at a time against all the text the model was shown, including the document title;
   - the size of the facts against the passages they came from.
8. **Resuming.** A resumed run refuses to mix settings (model, output cap, weights, prompt) into an earlier facts file.

**Unchanged.**
- The three criteria and their thresholds.
- The comparison for criterion 1: the rule-based records as the builder makes them today. Their document card copies
  the first passages word for word, which makes criterion 1 harder for Llama, not easier.
- Criterion 3's number check.
- The judge model, the samples (300 answer facts, 300 lines per model) and seed 7.
