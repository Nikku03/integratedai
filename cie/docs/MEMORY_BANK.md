# The full memory bank for exported company systems (`cie.ingest`)

How the Company Intelligence Engine turns exported records from company systems
(Slack threads, e-mail threads, Linear and Jira tickets, GitHub pull requests,
Confluence pages, Drive documents, HubSpot accounts, Fireflies meetings) into an
organised memory, at a bulk speed that handles half a million documents, and how
that memory is measured against plain chunk search on EnterpriseRAG-Bench.

## What is stored per document

| layer | what | where it comes from |
|---|---|---|
| sections | the body cut into ~1,000-character chunks, one run per body field ("Description", "Root cause", "Acceptance criteria"); short fields gathered into one "Details" section; the first section carries a metadata header (source, project, company, people, status, tags) for lexical search | the export's body fields |
| memory card | the document record: an extractive summary (the document's own summary field if it has one, else the two sentences most central to its vocabulary), tags, people with roles, companies, project, identifiers, dates; embedded as title + summary + tags | the export's metadata and body |
| tags | the system's own labels and categorical fields (labels, components, status, priority, stage, channel, space, team, repo, region, ...) plus up to six key phrases | metadata, body |
| typed records | tasks (with owner and due date), decisions, risks and blockers, open questions, requirements and acceptance criteria, root causes, resolutions and workarounds from structured fields; deadlines, decisions, requirements, risks, metrics and open questions from the rule extractor over sentence-aligned prose (code, JSON and tables are skipped). Each record cites the section that holds its text; one from a metadata-only field cites none. A record's date is its event (a due date, a meeting), not the moment it becomes true: only decisions and metrics take effect on their date, and never later than the load | structured list fields and prose |
| numeric sentences | up to 16 sentences with numbers, kept only for contradiction detection | body |

Nothing is generated: every summary sentence, tag and record quotes the document.
Export artefacts that a real system would not have (`original_location`,
`dataset_noise_document`, file paths) are dropped at read time so they can never
steer retrieval; a document's filename is `<source>:<its own identifier>`, never the
export path. E-mail header and quote-attribution lines ("From: ...", "On Tue, ...
wrote:") never become summary sentences or records. NUL characters, which
PostgreSQL cannot store, are removed at read time.

**Sensitivity.** A document is restricted (level 2) when its confidentiality,
visibility, sensitivity or privacy field holds anything other than an open label
(`internal`, `public`, `company`, ...): "restricted", "restricted
(customer-sensitive)", "confidential", "private", "team-only" and any unknown label.
Its sections and records carry the same level.

## What is stored across documents

| structure | how | link kind |
|---|---|---|
| people and companies | one canonical record per normalised name, company-wide ("Priya Nair (Solutions Engineer)", "priya_nair" and "Priya Nair <priya@...>" are one person; "Acme AI Inc." and "Acme AI" one company); every record that names them gets a `mentions` link and their id in `entity_ids`; aggregate detail (documents, roles, sources, aliases) written at the end. The record takes the sensitivity of the least restricted document that names the person, and its aggregate counts only documents at that level, so a company-wide profile never reveals what a restricted document says | `mentions` |
| projects | one record per Linear project, with the same sensitivity rule; documents are `part_of` it and chained in time order to their two nearest siblings | `part_of`, `relates_to` |
| explicit references | ticket keys in dependency and link fields and in the body, repository-qualified pull requests, wiki page paths, CRM account ids. A key held by one document resolves to it. A key held by two or three documents resolves to all of them when they are one object (next row), otherwise to the holder whose memory card is most similar to the citing document's, and to none when no holder leads by a clear margin; a key held by more is ambiguous. An unresolved citation is better than a wrong edge | `depends_on`, `references` |
| same identifier | documents that carry the same identifier are one object only when their titles match or their memory cards are nearly identical (cosine 0.92 within one system, 0.80 across systems); only then are they linked and checked for conflicting facts. Real exports reuse identifiers across unrelated records (in EnterpriseRAG-Bench about 19k same-key pairs are different objects), so a shared key alone links nothing | `references` |
| near-duplicates | mutual nearest neighbours of memory-card embeddings with cosine at least 0.92 (a GPU matrix product on Colab) | `near_duplicate` |
| contradictions | for near-duplicate and same-object pairs, sentences that say the same thing (word Jaccard at least 0.5) with different quantities (identifiers, links, clock times and versions ignored) become a disputed `fact` in each document, in that document's own scope and sensitivity, joined by `contradicts` edges whose text quotes neither side. A reader who may see both documents reaches the other side through the edge; anyone else does not. A `contradiction` record quoting both sides is written only when both documents share a scope, at the stricter sensitivity | `contradicts` |

Retrieval follows the new kinds at graph horizon 1, and the query's seeds stay
active at every horizon, so a retrieved ticket brings the tickets it depends on,
the pages it cites and the near-duplicate that disagrees with it, within the same
log(N) budget. People, companies and projects are hubs (a busy person is named by
thousands of records), so as seeds they are followed at horizon 1 only, and every
frontier node fetches at most a few of its strongest edges, capped in SQL. A
recorded contradiction pulls the other side into the packet next to the side that
was retrieved, when the reader may see it.

## How it runs at scale

`cie.eval.bench_enterprise.load_full`: documents are read and built in worker
processes (about 5 ms per document, pure Python); the main process embeds
(sections, cards, typed records, new entities) through an on-disk cache and writes
everything with binary COPY into session staging tables, from which one
`INSERT ... SELECT` per batch adds the text-search vector, so no pass rewrites the
tables afterwards. At most two batches per worker are in flight, so memory stays
flat. A batch the database rejects is retried document by document; a document that
still fails is skipped, counted and logged, and nothing links to it. Above 20,000
documents the vector and text indexes are dropped before the load and rebuilt
afterwards with memory and workers sized to the machine (`CIE_INDEX_BUILD_MEM`,
`CIE_INDEX_BUILD_WORKERS`; the Colab notebook sets them from the VM's RAM and
cores). They are rebuilt even when the load fails, and any that are missing are
rebuilt when a run starts.

## What it measured (EnterpriseRAG-Bench, 5,000-document haystack, 500 questions)

Same haystack, same questions, same code version, evaluated back to back (tables in
`docs/BENCHMARKS.md`, raw results in `docs/benchmarks/enterprise_rag_bench_5k*.json`).
The full memory bank organises the corpus (5,146 people and companies, 327 projects,
28,722 typed records, 430 cross-document references, 45 near-duplicate pairs, 13
conflicting facts), but **it does not improve document retrieval on this benchmark**:
recall@10 0.848 against 0.857 for chunks only, MRR 0.719 against 0.738. It helps
keyword search (lexical-only recall@10 0.703 against 0.672) and abstains less on
answerable questions (0.011 against 0.032); it loses on multi-document project and
constrained questions.

The cause, traced question by question: records the rule extractor derives from chat
and ticket prose (it was built for contracts) are noisy, metrics above all (6,269, the
largest type). When a question contains a word that hints a type ("budget" hints
metric, "decide" hints decision), those short records compete at full weight and
outrank sections of the relevant documents that cover the question far better. Two
measured fixes are in: typed records the question does not ask for are fused at half
weight (vector-only MRR 0.733 to 0.744), and vector search keeps its recall under
tenant and permission filters (iterative HNSW scans). The next step is a
conversational-text extractor, or a support threshold for typed records in the
reranker; both belong on a held-out question set, not on these 500.

## How to run

```
python -m cie.eval.bench_enterprise --root <EnterpriseRAG-Bench checkout> --docs 5000 --memory full
python -m cie.eval.bench_enterprise --root <checkout> --memory chunks --docs 5000     # the comparison
python -m cie.eval.bench_enterprise --root <checkout> --assisted ...                 # also compose answers (CIE_LLM_PROVIDER, key)
```

or the Colab notebook `notebooks/enterprise_rag_bench_colab.ipynb` for the whole
corpus on a GPU. Results are in `docs/BENCHMARKS.md`.
