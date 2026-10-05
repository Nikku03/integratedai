# A smaller memory bank

Two changes make the memory bank take less space. The rules for keeping them were fixed beforehand in
`docs/STORAGE_PREREGISTRATION.md`.

**Status (2026-10-05): built and tested, not yet measured end to end.** The before-and-after retrieval run on the
5,000-document bank (500 questions, four setups, about two hours) was stopped at 100 questions of the first setup
and has no results. So the criteria have not been applied yet. The numbers below come from copies of the bank's
rows, measured before the change.

## Step 1: 16-bit stored vectors, no stored keyword vectors (migration `a9b0c1d2e3f4`)

- **Stored vectors** are `halfvec(384)`, 16-bit floats. The HNSW indexes already compared vectors at that precision.
  A 32-bit vector took 1,540 bytes, too much to stay in the row, so it went to TOAST at 2.8-3.2 KB a row.
- **No stored tsvector columns.** Keyword search uses GIN indexes on expressions that compute the tsvector from the
  row's text: `cie_section_tsv(title, text)`, `cie_record_tsv(summary, keywords, detail)` and `cie_facts_tsv(text)`
  (`cie.memory.text`). These are the formulas the bulk loader stored, which built the 5,000-document bank. There are
  two differences:
  - section text past 200,000 characters is no longer indexed;
  - records saved one at a time (`cie.memory.records`) used to be indexed on summary and detail only. They now get
    the bulk formula as well: their keywords are added, and only the first 20,000 characters of the detail count.

| measured on copies of the 5,000-document bank's rows (tables without indexes) | before | after |
|---|---|---|
| passages table, 16-bit vectors | 149.5 MB | 122.3 MB |
| passages table, 16-bit vectors and no stored tsvector | 149.5 MB | **72.4 MB** |
| records table, 16-bit vectors | 153.2 MB | 125.6 MB |
| keyword GIN index on the passages: stored column vs expression | 17.9 MB | 17.9 MB |

The records table also loses its stored tsvector (642 bytes a record on average). That was not measured on its own.

**Expected effect on search, not yet measured:**
- Vector results should not change, since the comparison precision is the same.
- PostgreSQL keyword results on the bulk-loaded bank should not change, since the formula is the same.
- PostgreSQL keyword ranking (`ts_rank_cd`) now rebuilds the tsvector of each matching row from its text. This could
  make that path slower. The default keyword engine, BM25 (`cie.retrieval.bm25`), keeps its own index and does not
  use it.

## Step 2: binary vector index (`python -m cie.memory.compact vector-index binary`), off by default

- The HNSW indexes are built on `binary_quantize(embedding)::bit(384)`, one bit per dimension.
- Each search takes the 800 nearest by Hamming distance and re-sorts them by the exact cosine distance of their stored
  16-bit vectors (`cie.retrieval.vector`).
- `vector-index halfvec` switches back, and `status` reports sizes.

| measured on 33,200 passage vectors of the 5,000-document bank, 500 questions, vector search alone | 16-bit HNSW | binary HNSW, re-sorting 800 |
|---|---|---|
| index bytes per vector | 1,170 | 349 |
| share of the exact top 10 found | 98.2% | 95.9% |
| time per search | 2.2 ms | 6.8 ms |

It helps only when the vector index no longer fits in memory. Then about 3.4 times as many vectors fit in the same
memory, by the bytes per vector above. On the 5,000-document bank the two 16-bit indexes take about 120 MB, so there
it gains nothing and costs some accuracy and time. The re-sort reads 800 stored vectors per search; the 6.8 ms was
measured with them in memory.

## Checked

- The migration runs up, down and up again on an empty database.
- The test suite passes, file by file. `tests/test_acceptance.py` was left out because it already stalled before this
  change.
- `tests/test_compact.py`: with the binary index, search returns the same top 5 with the same scores as the 16-bit
  index. On a few rows the re-sort window holds them all. The test then switches back.

## Not yet

- The pre-registered end-to-end run: the four setups before the migration, after Step 1, and after Step 2.
- The 5,000-document bank itself is not migrated yet.
