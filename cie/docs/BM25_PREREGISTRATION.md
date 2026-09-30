# BM25 keyword search: what is measured and what decides the default, fixed before the test runs

I wrote this before running either test below. Nothing was tuned on the benchmark questions. During development,
unit tests used synthetic records, and one EnterpriseRAG-Bench question was run once to time a prototype index.

## Question

Keyword search uses PostgreSQL full text. Its ranking scores every row that matches a query before it can return the
best k. In the 50,000-document run, keyword search alone took 0.47 s at p50 and 5.5 s at p95. On the local
5,000-document copy, it was 36% of all search time, and 28 of 500 questions spent over a second in it.

`cie.retrieval.bm25` adds a BM25 index per tenant (Tantivy). It returns the best candidates without scoring every
match, and SQL then applies the same permission and validity filter as before.

**Does BM25 keep retrieval quality while removing the slow keyword tail?**

## Setup

`cie.eval.bench_enterprise`, with the EnterpriseRAG-Bench questions (all 500). The arms differ only in the keyword
engine; exact lookup, vector search, graph expansion, reranking and the packet are unchanged.

| Arm | Keyword engine |
|---|---|
| `hybrid+graph(REM)` | PostgreSQL full text (as in every earlier run) |
| `hybrid+graph(REM) [BM25]` | BM25 |
| `lexical-only` | PostgreSQL full text |
| `lexical-only [BM25]` | BM25 |

Both engines run in the same session, on the same memory bank, one arm after the other.

**Fixed before any run:**
- BM25 parameters are Tantivy's: k1 = 1.2, b = 0.75.
- A title match weighs 2.5 times a body match. That is the ratio of the full-text weights A and B (1.0 and 0.4).
- Query terms are the content words full-text search already used, stemmed with the index's English stemmer.
- Over-fetch starts at 4 × k candidates (at least 100). It grows 4 times per round, up to 5,000, when too few pass the
  SQL filter.

## Test runs

- **A. 5,000 documents, local.** Tenant `erbfull-5000-9688c2`, 4 CPUs, fastembed embeddings. Run once.
- **B. 50,000 documents, Colab A100.** The notebook's Part 1, which builds the BM25 index after the load. Run once,
  as confirmation.

## Criteria

BM25 becomes the default keyword engine (`lexical_engine = "bm25"`) if all of these hold:

1. **Quality.** `hybrid+graph(REM) [BM25]` has doc recall@10 of at least `hybrid+graph(REM)`'s minus 0.01, and MRR of
   at least its MRR minus 0.01. 0.01 is the run-to-run variation measured between two loads of the 50k haystack.
2. **Speed.** `hybrid+graph(REM) [BM25]` has p95 latency of at most 0.6 × `hybrid+graph(REM)`'s p95, and p50 of at
   most its p50 + 10%.
3. **No fallback.** Every keyword search in the BM25 arms was served by BM25.

## Reported, with no threshold

- `lexical-only [BM25]` against `lexical-only`: recall@10, MRR, p50 and p95.
- Every measure by question category.
- The BM25 index's size and build time.

## Decisions fixed in advance

- **A meets 1 to 3.** The default becomes BM25 now. Bulk loads build the index; `cie lexical build` builds it for
  an existing tenant; a tenant without an index keeps full text. B then confirms or reverts.
- **A meets 1 but not 2.** BM25 stays optional (`CIE_LEXICAL_ENGINE=bm25`), and B shows whether it helps at scale.
- **A fails 1.** BM25 stays optional. The loss is reported by category.
- **B fails any criterion.** The default goes back to full text, and BM25 stays optional.

Every result is reported, including failures.
