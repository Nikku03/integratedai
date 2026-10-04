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
