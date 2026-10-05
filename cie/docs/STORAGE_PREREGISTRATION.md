# A smaller memory bank: what decides, fixed before the measurements

I wrote this on 2026-10-05. It was before any measurement of Step 1 on the memory bank, and before any end-to-end
measurement of Step 2. The numbers that motivated the two steps came from copies of the 5,000-document bank's rows,
summarised below. The results go in `docs/STORAGE.md`.

## The two steps

- **Step 1** (migration `a9b0c1d2e3f4`):
  - stored vectors become 16-bit floats, the precision their HNSW indexes already compared at;
  - the stored tsvector columns are dropped. Keyword search uses GIN indexes on expressions that compute the tsvector
    from the row's text (`cie.memory.text`).
- **Step 2** (`python -m cie.memory.compact vector-index binary`):
  - the HNSW vector indexes become binary: one bit per dimension;
  - each query takes the 800 nearest by Hamming distance and re-sorts them by the exact cosine distance of their
    stored 16-bit vectors.

## What motivated them (copies of the 5,000-document bank's rows, tables without indexes)

- **Sections table.** 149.5 MB today. With 16-bit vectors, 122.3 MB. Without the stored tsvector as well, 72.4 MB.
  The keyword GIN index built from the text was the same size as the one on the stored column, 17.9 MB both.
- **Section vector index** (33,200 vectors). On the 500 benchmark questions, against exact search:

  | index | bytes per vector | recall@10 |
  |---|---|---|
  | 16-bit HNSW | 1,170 | 98.2% |
  | binary HNSW, re-sorting 800 | 349 | 95.9% |

## Set-up (fixed)

- **Bank and questions.** The 5,000-document memory bank (tenant `erbfull-5000-9688c2`), the benchmark's 500
  questions, `cie.eval.bench_enterprise --reuse-tenant`.
- **Four arms:**
  - `hybrid+graph(REM) [BM25]`, the primary arm. Its keyword engine is the default one. Document expansion is also on
    by default, but it changes the packet, not the documents found;
  - `hybrid+graph(REM)` and `lexical-only`, which use PostgreSQL full text and so test Step 1's keyword indexes;
  - `vector-only`, which tests Step 2.
- **Same everything else.** The same code for each run apart from the change measured, on the same machine (4 CPUs,
  15 GB of RAM).

## Criteria

**Step 1 changes nothing measurable but size.** It is kept if all three hold:
1. On every arm, document recall@10 and MRR are within 0.5 point of the run before the migration.
2. On every arm, the p95 latency is at most 25% higher.
3. The bank takes less disk: tables and indexes, measured.

**Step 2 is adopted** as the recommended layout for large memory banks if, on the bank after Step 1, all four hold:
1. Document recall@10 of the primary arm is at most 1.0 point below the 16-bit index.
2. MRR of the primary arm is at most 1.0 point below.
3. The p95 latency of the primary arm is at most 25% higher.
4. The vector indexes take at most 40% of the 16-bit indexes' bytes.

If Step 2 fails any of these, it stays available but is not recommended, and the report says by how much. If Step 1
fails, it is reverted (the migration has a downgrade).

Every result is reported, including failures.
