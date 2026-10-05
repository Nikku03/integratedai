# Facts in the memory bank

The memory bank keeps every document's passages in `sections`: the text, a hash of the text, a text-search vector and
an embedding. The rule-based extractor's typed records are in `memory_records`. The facts a language model extracts
(see `docs/FACT_EXTRACTION_PREREGISTRATION.md`) are stored in `section_facts`, beside the passage they came from.
The code is `cie.memory.facts`.

## One row per passage and extractor

| column | what it holds |
|---|---|
| `section_id`, `document_id` | the passage and its document |
| `scope_id`, `sensitivity` | copied from the passage, so reads use the same permission filter as everything else |
| `extractor`, `signature`, `settings` | the model (repository and revision) and a hash of everything that shapes the facts: the model, instructions, output cap, and whether repeated text was left out |
| `facts` | the lines, each with the checks made when it was stored (below) |
| `text`, `embedding` | the lines joined, for keyword search (a GIN index on `cie_facts_tsv(text)`) and vector search |
| `status` | `done`, `empty` (the passage states no fact), `capped` (the output cap cut the list) or `skipped` (the passage only repeats the previous one) |
| `section_sha256` | the passage text the model read |
| `input_sha256` | the passage's own part of the prompt: document title, source, section title and text |
| `n_facts`, `prompt_tokens`, `output_tokens` | sizes |

Each line in `facts` looks like this:

```json
{"text": "The engineering patch is targeted for 2026-03-20.", "numbers_in_section": true, "support": 0.86, "tag": false}
```

- `numbers_in_section`: every number in the line is in the passage. `null` means the line has no number.
- `support`: the share of the line's content words found in the passage.
- `tag`: a tag line, not a fact.

## Filled in parts

- **A run can stop at any point.** A row is written only for a passage the model answered, and each chunk is
  committed. A passage that failed, or that no run has reached, has no row and stays pending. The next run (or
  import) does only those.
- **Nothing is stored twice.** There is one row per passage and signature. Importing the same file again, or a file
  that overlaps an earlier one, adds only what is missing.
- **Nothing is checked twice.** The checks are stored with each line when it is written. Reading uses them as they
  are.
- **Nothing is asked twice.** Under one signature, a passage whose input matches one already extracted takes those
  facts without calling the model. An example is a new version of a document whose other parts changed. Only current
  document versions are pending.
- **Nothing is stored against the wrong text.** An imported passage whose text differs from the memory bank's passage
  is counted as stale and left out.

An imported run and a later run from the database share a signature when they use the same model repository, settings
and instructions. The database run then continues where the import stopped.

## Commands

The database is `CIE_DATABASE_URL`, or `--db`. The tenant is given by id or name.

```bash
# the schema (adds the table)
alembic upgrade head

# a facts file from the Colab notebook (results folder on Drive: passages.jsonl, facts_*.jsonl and .run.json)
python -m cie.memory.facts --tenant erbfull-5000-9688c2 import --work /path/to/extract_facts_5000 \
    --facts /path/to/extract_facts_5000/facts_llama-3.1-8b-fast-int8.jsonl [--embed]

# what is stored and what is pending, per extractor
python -m cie.memory.facts --tenant erbfull-5000-9688c2 status

# facts for the passages that have none yet (new documents, new versions), on a GPU with vLLM
python -m cie.memory.facts --tenant erbfull-5000-9688c2 extract --model llama-3.1-8b-int8 --prompt short --strip-overlap
```

`--embed` also embeds each passage's facts with the configured embedding provider. Without it, the facts are
searchable by keyword only.

## Checked

On 2026-10-04:
- `tests/test_memory_facts.py` covers:
  - a second import adds nothing;
  - a failed passage stays pending, and a database run asks only for it;
  - an imported run and a database run share a signature;
  - a new document version takes the stored facts without calling the model;
  - stale text is refused;
  - facts follow their passage's permissions.
- The migration runs up, down and up again on an empty database.
- On the local 5,000-document memory bank, an import of 3 passages from documents in the bank matched their
  sections with no stale text, and a second import added nothing. A database run of the same extractor added 2 more.
  These used a small local model, and the rows were deleted afterwards.

## Not yet

- Search does not use the facts yet. The next step adds them as a retrieval channel: keyword search on `cie_facts_tsv(text)`, vectors
  on `embedding` for large loads, and each hit leading to its passage.
- The BM25 index (`cie.retrieval.bm25`) does not include them yet.
