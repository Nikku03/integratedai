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

## Acceptance targets not met (measured, see BENCHMARKS.md)
* Exact structured-field accuracy and citation correctness are below the
  99% / 100% targets on the hard synthetic set; the per-question failures are
  listed with causes.
* Conflict detection in the benchmark depends on contradictions having been
  recorded; the corpus's planted cross-document conflict is now detected at
  ingest only when the two records share an entity and topic words.

## Scale
* Everything was measured on a 15-document synthetic corpus. HNSW build,
  full-text index size and graph expansion at millions of records are
  projected in COST_STORAGE.md, not measured.
* Token counts are estimates unless a provider reports usage.

## Security
* API keys only (no OIDC), no rate limiting, TLS delegated to ingress, at-rest
  encryption keyed from an environment variable, scanners are pattern based.

## Dashboard
* Built and type-checked but not exercised against a running API in this
  build (no browser session). Endpoint wiring follows `docs/openapi.json`.
