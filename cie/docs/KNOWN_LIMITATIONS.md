# Known limitations

Stated plainly so nobody mistakes a scaffold for a finished capability.

## Not exercised against live services in this build
* **LLM providers.** Anthropic, OpenAI, Gemini and local (OpenAI-compatible)
  adapters are implemented against the public APIs but no API key was
  available, so assisted answers, the LLM planner and the LLM specialist
  strategy were tested only through `FakeProvider`. All shipped numbers use the
  deterministic extractive strategies.
* **Unlimited-OCR.** It is the OCR engine on machines with a GPU since its
  pre-registered test (`docs/OCR_RESULTS.md`): fewer errors than Tesseract and
  every number kept, on typeset pages with simulated scanning. Real paper (stamps,
  handwriting, photos, forms) was not tested. In the process it took 33.6 s per
  page on an A100, against 2.3 s for Tesseract on one CPU core; a vLLM/SGLang
  server batches pages, but its speed was not measured. The pipeline sends one
  page at a time, so the model's multi-page mode is not used.
* **S3/MinIO backend and the compose stack.** `S3Backend` is implemented with
  boto3 but tests use the local filesystem backend; the Docker daemon was not
  available in the build environment, so `docker compose up` was not executed
  here. The Dockerfile and compose file are complete but unverified end to end.
* **Connectors.** Only the local-folder connector works. IMAP, Google Drive,
  SharePoint, Slack and Git connectors raise `NotImplementedError`.
* **OpenSearch/Elasticsearch.** Not implemented. The keyword engines are PostgreSQL
  full text and a BM25 index per tenant (Tantivy, `cie.retrieval.bm25`). The
  OpenSearch class only marks a swap point and raises on use.
* **With BM25, search no longer abstains when the answer is not in the corpus.** Without a model, the extractive
  answer abstained on 3 of the 20 such questions at 50,000 documents with full text, and on none with BM25. BM25
  finds partly matching text for almost any question, so the evidence threshold is passed more often. False
  abstentions on answerable questions halved. A model composing answers still abstains (0.9 of those questions).
* **The BM25 index lives on one machine's disk** (`CIE_LEXICAL_INDEX_DIR`). Processes
  on the same host share it. Several API or worker hosts each need the directory
  on shared storage, or their own build. Rows written since the index last synced
  are scored from the database with the index's statistics (document frequencies
  and average lengths), so their scores approximate what the index would give.
  A tenant with more than `lexical_tail_max` rows waiting falls back to full text
  until the worker syncs. Deleted rows stay in the index until the next build;
  the SQL filter removes them from results.
* **Temporal.** Not integrated; the durable queue is a PostgreSQL table with
  leases and checkpoints.

## Quality limits of the deterministic layer
* Fact extraction is rule based (dates, money, percentages, modal
  requirements, decisions, risks, parties, defined terms, clause numbers). It
  misses anything a pattern does not name, and its type assignment is coarse
  (a sentence with "shall" and "$" becomes both a requirement and a metric).
* Extractive answers quote records; they do not paraphrase, aggregate or
  reason. Multi-hop questions get the top evidence, not a synthesized answer.
* Evidence support is lexical (IDF-weighted term coverage). Purely semantic
  paraphrases with no shared content words are ranked by the vector index but
  do not count as support, so they can be reported as insufficient evidence.
* Cross-document contradiction detection is conservative (same type, same
  value kind, shared entity, ≥3 shared topic words). Most contradictions still
  have to be declared by agents or people through the API.
* Entity resolution is fuzzy-string based; ambiguous names become open
  questions rather than being resolved.
* Language detection is a stopword heuristic; OCR corrections are narrow
  regex rules; sectioning of OCR output depends on recovering headings from
  text shape.
* The reranker is heuristic, not a trained cross-encoder.

## Acceptance numbers are in-sample (see BENCHMARKS.md)
* All §13 targets are met on the 18-question synthetic set, but that set was
  used to find and fix retrieval defects during development. Treat the
  numbers as evidence the mechanisms work, not as generalisation. There is
  no out-of-sample evaluation yet.
* Cross-document contradiction detection at ingest is deliberately narrow:
  same record type and value kind, a shared discriminative organisation,
  two shared topic words, and at most one of the two documents a governing
  instrument (a contract-versus-email disagreement is flagged; two different
  contracts with the same counterparty are not). Everything else must be
  declared by an agent or a person.

## Scale
* Quality was measured on a 15-document synthetic corpus. Latency, storage
  and hit@20 were measured on synthetic tenants of 10k, 100k and 1M typed
  records (`python -m cie.eval.bench_scale`, tables in BENCHMARKS.md); the
  1M row was re-measured after the fixes it forced, the 10k and 100k rows
  were not. The scale corpus is templated: every record names its supplier,
  which favours entity-anchored lexical search over what real documents
  offer, and its questions are templated too.
* At 1M records a name that is a prefix of other names ("Alpine Cloud" among
  "Alpine Cloud 1…124") is ambiguous: the exact-name document ties with its
  namesakes in the document-name search and in full-text rank, and can fall
  outside the top 20.
* The partial-match full-text tier drops lexemes that planner statistics
  expect in more than 5,000 rows and is bounded by a 1.5 s statement
  timeout; the trigram entity fallback is bounded by 400 ms. A bounded tier
  that times out contributes nothing for that question, and this is counted,
  not hidden. Statistics come from `ANALYZE`; a table that was never
  analysed has none, and the tier then runs over every term.
* Single client, one tenant per run, one machine (4 vCPU, no GPU):
  throughput under concurrent load and multi-tenant interference were not
  measured.
* Token counts are estimates unless a provider reports usage.
* Half-precision (halfvec) HNSW indexes need pgvector 0.7+; on older servers the
  migration keeps float32 indexes, which are twice the size. The scale
  benchmark's recall with halfvec is measured on normalised 384-d embeddings;
  other models were not measured.
* Organisation views aggregate records as they are: a supplier known under two
  unresolved spellings has two profiles until the aliases are merged, and the
  scope digest's "most mentioned" ranking counts `mentions` edges, so records
  that reference an entity only through `entity_ids` (bulk-loaded data) do not
  raise it.

## Security
* API keys only (no OIDC), no rate limiting, TLS delegated to ingress, at-rest
  encryption keyed from an environment variable, scanners are pattern based.

## Dashboard
* Built and type-checked but not exercised against a running API in this
  build (no browser session). Endpoint wiring follows `docs/openapi.json`.

## Topological memory bank (docs/TOPOLOGY.md)
* Cliques and cavities are computed on the tissue a query activates (its seeds and
  their bounded one-hop neighbourhood), never on the whole bank; a cavity is a
  per-query statistic, not a stored memory trace.
* The record graph's link direction (detail to context) is the reverse of a
  circuit's, so simplex sinks are documents, clauses and entities; the cascade
  recruits along them, the rerank bonus ignores direction.
* Plasticity changes link weights in place from what packets used; it is run only
  by the benchmark, which restores the weights. Enabling it in production needs a
  policy for who may teach the bank and an audit of every weight change.
* The clique network is a rate-coded feed-forward model with sparse fixed fan-in
  and a reward-modulated Hebbian rule; it is not a spiking simulation and has no
  cavities.

## Dynamic memory bank
* Off by default (`CIE_DYNAMIC_MEMORY`). Wiring follows answers, so whoever asks
  shapes the bank; a wrong answer wires wrong records together until decay and
  pruning remove the link. Every wiring event is audited and `POST
  /memory/shapes/reset` undoes all of it, but there is no per-principal policy
  yet for who may teach the bank.
* Links form inside the answer's document (two for conflicts, three for
  comparisons); cross-document shapes therefore only come from answers that
  legitimately span documents.
* The synthetic scale generator wrote two copies of each record template into
  two-thirds of the documents (records wrapped around the document list). The
  10k/100k/1M rows in BENCHMARKS.md were measured on that corpus: hit@20 counts
  either copy, so retrieval numbers stand, but each such document carries two
  conflicting fee, penalty and notice values. The generator now writes exactly
  twelve records per document; the next run (the Colab notebook included) uses
  the clean corpus.

## EnterpriseRAG-Bench (out-of-sample company corpus)
* Measured locally on a 5,000-document haystack (every gold document plus a
  stratified sample of the 512k), so recall numbers are optimistic relative to
  the full corpus; the Colab notebook runs the full corpus on a GPU.
* Correctness and completeness need the benchmark's LLM judge; only document
  recall, MRR, extra documents and abstention are computed here. Extra documents
  are counted against the gold set without the judge's "valid" relabelling.
* Extractive answers quote sections; the judge expects composed answers, so
  judged correctness will lag document recall until an assisted-mode model is
  in the loop.
* The corpus exposed three biases tuned on contracts and now corrected:
  keyword-array overlap rode on the exact-match weight, sections were discounted
  against records in fusion, and capitalised topic words were treated as document
  names. The "semantic" category (paraphrased questions with little word
  overlap) remains the weakest: that is an embedding-model limit (384-d
  bge-small) more than a pipeline one.
* Full memory bank (docs/MEMORY_BANK.md): references between documents are
  resolved only when unambiguous. The corpus reuses identifiers across unrelated
  records, so a citation of a shared key goes to the most similar holder or to
  none; some true references therefore stay unlinked. Contradictions are found
  only between near-duplicate or same-object documents, and only for sentences
  that differ in a quantity; a disagreement stated in words ("approved" vs
  "rejected") is not detected. People, companies and projects are recognised
  from metadata fields and task owners, not from free text.
* The full memory bank does not yet improve document retrieval over chunks on this
  benchmark (recall@10 0.848 vs 0.857, MRR 0.719 vs 0.738 on the 5k haystack): the
  rule extractor, built for contracts, turns chat and ticket prose into noisy metric
  and decision records that outrank better-matching sections when a question hints
  their type. See docs/MEMORY_BANK.md, "What it measured".
* Across department scopes a contradiction is kept as two disputed facts with no
  combined record, so a reader who may see only one side is told nothing about
  the other document; one who may see both gets both through the link.

## REM

* The change rules encode explicit business definitions (supply exposure, dependents, penalty clauses, derived
  content, unblocking, contract change, deletion, revocation). Consequences outside those rules are not detected,
  and missing or wrong relationships in the source data are invisible to them.
* R1 does not allocate stock between milestones of one project that need the same product.
* The REM priority policy is off by default: on EnterpriseRAG-Bench it lowered precision and MRR relative to
  search order. Routing shortcuts showed no benefit.
* REM record search has no vector index (sequential cosine scan). Passages copy section text and embeddings
  instead of referencing them; at 5k documents the node-version table is 445 MB.
* Open suggested tasks are updated in place (their wording at an old snapshot is not reproducible). Historical
  stock rows are checked with the snapshot's permissions only. Stored aggregate counts are not re-filtered after
  a revocation.


## Live state, identity, workflow, context and verification (docs/OPERATING_SYSTEM.md)

**Measured only on generated projects so far.** `cie.eval.bench_loop` measures the one-project loop
(retrieval completeness, citation accuracy, stale-state errors, missed dependencies, duplicate actions, task
completion, latency, cost) on generated worlds. Both pre-registered test runs met every criterion
(`docs/LOOP_RESULTS.md`). It is not measured on a real project.

**A small model cannot do the project analysis.** In study 2, none of Llama 3.1 8B's answers was right. It never got
the cost of the open orders right (it wrote out the arithmetic instead of the result), and it judged the milestones
at risk correctly in 20% of answers. Verification caught every wrong figure. It cannot catch a wrong at-risk
judgment, which has no recalculation. No stronger model has been measured.

**A blocked answer still completes its task.** The publication gate keeps a finding that fails verification, and an
answer resting on it, out of shared memory. It does not send the task back: the task completes holding that
answer as its result, and anything reading the result gets it. In study 2, 735 checks found a completed task
holding a wrong model answer.

**Over-invalidation.** By default every live-state record in a task's context becomes an input, so changes to
records a task read but did not rely on still reopen it. Workers that declare their inputs avoid this with
`inputs="explicit"`, and workers whose findings cite state avoid it with `inputs="relied"`.

**Results released early are measured in simulation only.** `cie.eval.bench_schedule` runs the real engine on
generated projects with simulated durations. Real specialists may not split their work into early results this
neatly, and the schedule order depends on duration estimates.

**Agents, decisions and actions are tested with scripted models and simulated connectors.**
- Agents take turns on their own, ask each other for work, get one more evidence round, and have their questions
  answered by a person, with blocking questions pausing the task. All of this is tested with scripted models, not
  measured with real ones.
- Requests are decided by fixed rules (merge equivalent ones, decline work no agent does), not by judging whether
  the work is worth it.
- Decision authority is a limit per decision kind that the agent itself reports. A model that under-reports its
  decisions, or leaves one out, is not caught; the action gateway checks amounts again for actions.
- Re-planning relaxes constraints only within an approver's authority, or asks a person. It does not propose new
  tasks.
- The action gateway has an outbox file and a signed webhook connector. No ERP, email or payment system is
  connected. Confirmation reads back what the other side holds; it cannot see whether a person acted on it.
- A task's period is shown to the worker but does not filter search.

**Relied inputs trust the citations.** With `inputs="relied"`, a task's inputs are the records its result cites,
so a worker that relies on a record without citing it is not refreshed when that record changes. A result with no
state references gets no inputs at all. In study 2 the model's answers cited 99.4% of the records they needed, and
no change hit a record they left out, so nothing was missed. With a model that cites less, a change to an uncited
record would not reach the task.

**Authority.**
- Ranks come from rules or the kind of source. A value written directly by an import becomes a system-of-record
  statement only when the record's `source_system` is a known system of record; otherwise it has rank `unknown`,
  so any named source can replace it.
- Conflicts are resolved by a person, or by a more authoritative statement. Nothing escalates an old open
  conflict automatically.

**Identity.**
- Name candidates come from trigram similarity over current record names, and there is no trigram index on
  `rem_node_versions.name` yet, so large tenants scan.
- Merges cannot be undone (there is no split operation).
- Records with different access are never merged.
- Project and department records cannot be merged.

**Workflow.**
- The head agent runs tasks in-process with its own lease owner. External workers use the task API, but there
  is no built-in pool of remote agent workers.
- Overdue tasks are reported, not escalated.
- Addressing requested changes means dropping unsupported findings; it does not re-plan the work.

**Context.**
- Exhaustive mode scans live-state collections (a record type, optionally one project), not knowledge-memory
  documents.
- Paging through a large match list re-runs the scan at the same snapshot.
- Budgets are estimated tokens, not a model's tokenizer.

**Verification.**
- The built-in extractive strategy produces cited findings, but not calculations or state references, so for the
  default agents verification is citation-based. Recalculation and state checks apply to findings that declare
  them, for example from external agents through the task API.
- The synthesis is written to the project scope, labelled, and is not itself gated.

**Missing.** The action gateway.
