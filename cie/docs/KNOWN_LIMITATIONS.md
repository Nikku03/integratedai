# Known limitations

Stated plainly so nobody mistakes a scaffold for a finished capability.

## Not exercised against live services in this build
* **LLM providers.** Anthropic, OpenAI, Gemini and local (OpenAI-compatible)
  adapters are implemented against the public APIs but no API key was
  available, so assisted answers, the LLM planner and the LLM specialist
  strategy were tested only through `FakeProvider`. All shipped numbers use the
  deterministic extractive strategies.
* **Unlimited-OCR.** The adapter follows the published vLLM/SGLang API and its
  `<|det|>` layout markers are parsed by unit tests, but no GPU was available
  to run the model. Tesseract is the OCR engine behind every reported number.
* **S3/MinIO backend and the compose stack.** `S3Backend` is implemented with
  boto3 but tests use the local filesystem backend; the Docker daemon was not
  available in the build environment, so `docker compose up` was not executed
  here. The Dockerfile and compose file are complete but unverified end to end.
* **Connectors.** Only the local-folder connector works. IMAP, Google Drive,
  SharePoint, Slack and Git connectors raise `NotImplementedError`.
* **OpenSearch/Elasticsearch.** Not implemented; PostgreSQL full text is the
  lexical engine. The class exists only to mark the swap point and raises on use.
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

## Security
* API keys only (no OIDC), no rate limiting, TLS delegated to ingress, at-rest
  encryption keyed from an environment variable, scanners are pattern based.

## Dashboard
* Built and type-checked but not exercised against a running API in this
  build (no browser session). Endpoint wiring follows `docs/openapi.json`.
