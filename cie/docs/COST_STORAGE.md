# Cost and storage report

Measured on the synthetic evaluation corpus in this build; projections are arithmetic on the measured per-unit numbers and say so.

## Measured storage

| quantity | value |
|---|---|
| documents / pages / sections / records | 15 / 72 / 73 / 289 |
| raw vault bytes (deduplicated blobs) | 12,756,178 (12.8 MB) |
| raw bytes per page | 177,169 |
| `pages` table incl. indexes, bytes per row (database-wide) | 853.3 |
| `blocks` table incl. indexes, bytes per row (database-wide) | 411.3 |
| `sections` table incl. indexes, bytes per row (database-wide) | 4404.6 |
| `memory_records` table incl. indexes, bytes per row (database-wide) | 7618.0 |
| `record_links` table incl. indexes, bytes per row (database-wide) | 328.7 |
| `evidence_packets` table incl. indexes, bytes per row (database-wide) | 32193.1 |

A memory record costs about 7,618 bytes on disk and a section about 4,405 bytes, indexes included (384-d float32 embedding = 1,536 bytes each, HNSW and GIN index entries, tsvector, JSONB glyph and provenance). Evidence packets are the largest growing table because every search stores its full packet for reproducibility; they can be expired by retention policy.

## Projection to a 200-million-token project memory

Assuming ~350 tokens per section and ~120 tokens per record (measured averages on this corpus are of that order), 200M addressable tokens ≈ 450k sections + 350k records:

| component | estimate |
|---|---|
| sections (450k × 4,405 B) | 2.0 GB |
| records (350k × 7,618 B) | 2.7 GB |
| raw vault (450k sections ≈ 60k pages × 177,169 B/page measured on PDFs with embedded fonts) | 10.6 GB |

This fits one PostgreSQL instance with room; HNSW build time and index memory, not disk, are the first limits (see ROADMAP.md).

## Measured at 1,000,000 synthetic records

| quantity | value |
|---|---|
| records / sections / documents | 1,000,000 / 250,000 / 50,000 |
| `memory_records` table incl. indexes | 5.85 GB (5,854 B per record) |
| of which HNSW index (halfvec) / GIN tsvector index | 1.17 GB / 28 MB |
| `sections` table incl. indexes | 1.26 GB (5,039 B per section) |
| `record_links` table incl. indexes | 669 MB |
| load (binary COPY) / tsvectors / HNSW on records / all indexes | 296.5 s / 141.8 s / 301.8 s / 391.6 s |

Synthetic records are shorter than extracted ones (no page-level provenance, small glyphs), so the per-row figure is a floor; the per-row figure from the extracted corpus above is the better estimate for real documents. Retrieval latency at this size is in BENCHMARKS.md.

## Tokens and model cost per question

| approach | tokens sent to the model per question | est. cost at claude-sonnet-5 list price |
|---|---|---|
| full context (everything the admin can read) | ~4,546 | $0.0181 |
| hybrid evidence packet (this system, assisted mode) | ~4,199 | $0.0171 |
| strict extractive mode (this system, default) | 0 | $0 |

The corpus is small, so full context is still cheap in absolute terms; the ratio is what scales. At 200M tokens the full-context approach is impossible (no model holds it) while the packet stays at a few thousand tokens.

## Latency and compute

Retrieval + rerank p50/p95: 104.82 / 181.64 ms on CPU with the embedding model warm; warm metadata lookup p95 0.59 ms. Ingestion of the corpus took 221.0 s including OCR of the scanned document (Tesseract ≈ 0.5 s per page at 110–150 dpi on one core).

## Multi-agent run

| agent | tasks | tokens in | tokens out | cost USD |
|---|---|---|---|---|
| research | 1 | 3,531 | 77 | 0.0000 |
| finance | 1 | 3,213 | 131 | 0.0000 |
| legal | 1 | 3,278 | 85 | 0.0000 |
| operations | 1 | 3,109 | 158 | 0.0000 |
| engineering | 1 | 2,835 | 23 | 0.0000 |
| head | 1 | 0 | 0 | 0.0000 |

Strategy `extractive` (no model calls, so cost is 0); token figures are the estimated size of each agent's brief + evidence packet, i.e. what an LLM strategy would have been sent. Messages carried 2,443 tokens in total across 23 structured messages.

## Price table used for estimates

| model | $/M input | $/M output |
|---|---|---|
| claude-sonnet-5 | 3.0 | 15.0 |
| claude-opus-5 | 15.0 | 75.0 |
| claude-haiku-4-5-20251001 | 1.0 | 5.0 |
| gpt-4o | 2.5 | 10.0 |
| gpt-4o-mini | 0.15 | 0.6 |
| gemini-2.5-pro | 1.25 | 10.0 |
| gemini-2.5-flash | 0.3 | 2.5 |

Prices are list prices typed into `cie.agents.providers.PRICES`; real spend comes from provider usage reports, which this build could not collect.