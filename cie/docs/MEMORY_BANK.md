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
| typed records | tasks (with owner and due date), decisions, risks and blockers, open questions, requirements and acceptance criteria, root causes, resolutions and workarounds from structured fields; deadlines, decisions, requirements, risks, metrics and open questions from the rule extractor over sentence-aligned prose (code, JSON and tables are skipped) | structured list fields and prose |
| numeric sentences | up to 16 sentences with numbers, kept only for contradiction detection | body |

Nothing is generated: every summary sentence, tag and record quotes the document.
Export artefacts that a real system would not have (`original_location`,
`dataset_noise_document`, file paths) are dropped at read time so they can never
steer retrieval.

## What is stored across documents

| structure | how | link kind |
|---|---|---|
| people and companies | one canonical record per normalised name, company-wide ("Priya Nair (Solutions Engineer)", "priya_nair" and "Priya Nair <priya@...>" are one person; "Acme AI Inc." and "Acme AI" one company); every record that names them gets a `mentions` link and their id in `entity_ids`; aggregate detail (documents, roles, sources, aliases) written at the end | `mentions` |
| projects | one record per Linear project; documents are `part_of` it and chained in time order to their two nearest siblings | `part_of`, `relates_to` |
| explicit references | ticket keys in dependency and link fields and in the body, pull-request URLs, wiki page paths, CRM account ids; an identifier carried by one to three documents (the same ticket in two systems, or two versions of it) resolves to all of them, one carried by more is ambiguous and is skipped rather than guessed | `depends_on`, `references` |
| same identifier | documents that carry the same identifier are linked and checked for conflicting facts | `references` |
| near-duplicates | mutual nearest neighbours of memory-card embeddings with cosine at least 0.92 (a GPU matrix product on Colab) | `near_duplicate` |
| contradictions | for near-duplicate and same-identifier pairs, sentences that say the same thing (word Jaccard at least 0.5, numbers ignored) with different numbers become a disputed `fact` in each document, `contradicts` edges between the facts and between the two documents, and a `contradiction` record citing both | `contradicts` |

Retrieval follows the new kinds at graph horizon 1, and the query's seeds stay
active at every horizon, so a retrieved ticket brings the tickets it depends on,
the pages it cites and the near-duplicate that disagrees with it, within the same
log(N) budget. A recorded contradiction pulls the other side into the packet next
to the side that was retrieved.

## How it runs at scale

`cie.eval.bench_enterprise.load_full`: documents are read and built in worker
processes (about 5 ms per document, pure Python); the main process embeds
(sections, cards, typed records, new entities) through an on-disk cache and writes
everything with binary COPY; at most two batches per worker are in flight, so memory
stays flat. Above 20,000 documents the vector and text indexes are dropped before
the load and rebuilt afterwards with memory and workers sized to the machine
(`CIE_INDEX_BUILD_MEM`, `CIE_INDEX_BUILD_WORKERS`; the Colab notebook sets them from
the VM's RAM and cores).

## How to run

```
python -m cie.eval.bench_enterprise --root <EnterpriseRAG-Bench checkout> --docs 5000 --memory full
python -m cie.eval.bench_enterprise --root <checkout> --memory chunks --docs 5000     # the comparison
python -m cie.eval.bench_enterprise --root <checkout> --assisted ...                 # also compose answers (CIE_LLM_PROVIDER, key)
```

or the Colab notebook `notebooks/enterprise_rag_bench_colab.ipynb` for the whole
corpus on a GPU. Results are in `docs/BENCHMARKS.md`.
