# Does the memory bank beat plain search? Results

**Status (2026-10-05): set up, not yet run with a real model.** What decides is fixed in
`docs/MEMORY_TEST_PREREGISTRATION.md`. The test runs on Colab: `notebooks/memory_test_colab.ipynb`.

## How to run it

On Colab, open the notebook with an A100 or H100 runtime and choose **Run all**. It takes about an hour, less when the
fact-extraction notebook's facts are already on Google Drive. Results are saved to `MyDrive/cie_memory_test` as they are
made, so Run all after a disconnect continues where it stopped. The Score cell prints `report.md`.

Elsewhere, with PostgreSQL and the benchmark checkout:

```bash
W=eval_out/memory_test
python -m cie.eval.memory_test questions --root <EnterpriseRAG-Bench> --work $W --docs 5000
python -m cie.eval.memory_test load --work $W
python -m cie.eval.memory_test plain --work $W
python -m cie.eval.memory_test facts-passages --work $W
python -m cie.eval.extract_facts run --work $W/facts --model llama-3.1-8b-int8 --name llama-3.1-8b-fast-int8 --prompt short --strip-overlap
python -m cie.memory.facts --tenant <load.json's tenant_name> import --work $W/facts --facts $W/facts/facts_llama-3.1-8b-fast-int8.jsonl
python -m cie.eval.memory_test evidence --work $W
python -m cie.eval.memory_test answer --work $W --backend vllm --model llama-3.1-8b
python -m cie.eval.memory_test judge --work $W          # OPENAI_API_KEY
python -m cie.eval.memory_test score --work $W
```

## Checks of the set-up

These checks used no real model, so their scores mean nothing:

- **The question set**, built from the benchmark checkout over the 5,089-document haystack, has 243 questions:

  | group | questions | kinds |
  |---|---|---|
  | owners | 100 | 96 with a field value to check |
  | deadlines | 70 | 40 Linear due dates, 30 action items |
  | lists | 53 | 15 by assignee, 10 by assignee and status, 8 by due window, 10 Jira, 10 pull requests |
  | conflicts | 20 | |

- **Every step ran on 50 documents** with a stand-in model that copies the first key or date it sees. The notebook ran
  from start to end in about 2 minutes.
- **After a simulated disconnect**, with the database and local disk wiped, Run all reused the saved evidence and
  answers. It gave the same report.
- **The Llama facts route:**
  - a fact-extraction file was reused for all 401 passages, and none was asked again;
  - its import matched every passage to a section of the bank, with identical text.
- `tests/test_memory_test.py`: action items in three layouts, the expected values, the code checks, the lookups' field
  checks, the decision rules, and the whole pipeline on a tiny fictional company.

## Results

To be filled in from the Colab run's `report.md`.
