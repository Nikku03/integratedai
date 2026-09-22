# API

Base path `/api`. Auth: header `X-API-Key` (query `api_key` accepted for image
URLs). Interactive docs at `/docs`; the machine-readable contract is
`docs/openapi.json`.

| Area | Endpoints |
|---|---|
| Health | `GET /health` |
| Scopes | `POST /scopes`, `GET /scopes` |
| Ingestion | `POST /ingest` (multipart: file, scope_id, title?, doc_type?, sensitivity?, source?, original_location?, family_id?, retention_policy?, file_created_at?) → document + job |
| Documents | `GET /documents`, `GET /documents/{id}`, `GET /documents/{id}/versions`, `GET /documents/{id}/extraction` (OCR status), `GET /documents/{id}/flags` |
| Jobs | `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/run` (dev helper) |
| Memory | `POST /memory/records`, `GET /memory/records`, `GET /memory/records/{id}`, `/history`, `/links`, `POST .../supersede`, `/contradict`, `/confirm`, `/extend`, `/link?kind=` |
| Organisation views | `GET /memory/entities?q=&type=`, `GET /memory/entities/{id}/profile?at=&include_history=`, `GET /documents/{id}/card`, `GET /scopes/{id}/digest?at=` — what the bank holds about an entity, a document, a scope; permission-filtered |
| Search | `POST /search` → evidence packet; `GET /evidence/{packet_id}` |
| Answers | `POST /answer` (mode strict/assisted) → cited answer; `GET /answers/{id}` |
| Sources | `GET /sources/{doc}/pages/{n}` (text + blocks + corrections), `GET /sources/{doc}/pages/{n}/image`, `GET /sources/{doc}/download` |
| Projects | `POST /projects`, `GET /projects`, `GET /projects/{id}`, `POST /projects/{id}/run` (objective; `background` to enqueue), `POST /projects/{id}/step`, `GET/POST /projects/{id}/ledger`, `GET /projects/{id}/final-answer` |
| Tasks | `POST /tasks`, `GET /tasks`, `GET /tasks/{id}`, `POST /tasks/{id}/route` (explain routing), `POST /tasks/{id}/verify` |
| Agents | `POST /agents`, `GET /agents`, `GET /agents/{id}/scorecards`, `POST /agents/{id}/outcome` (human grading) |
| Messages | `POST /messages`, `GET /messages?project_id=` |
| Governance | `GET /approvals`, `POST /approvals/{id}/decide`, `POST /documents/{id}/legal-hold`, `POST /documents/{id}/retention`, `POST/GET /deletion-requests`, `GET /retention/expired` |
| Audit | `GET /audit?resource_id=&action=` |
| Permissions | `POST /permissions/principals` (returns API key), `POST /permissions/roles`, `POST /permissions/grant`, `GET /permissions/me` |
| Metrics | `GET /metrics/summary` (tokens, latency p95, cost, storage, counts, job stats) |

## Evidence packet item

```json
{"id": "...", "kind": "record|section", "type": "metric", "summary": "...", "detail": "...",
 "document_id": "...", "citations": [{"page_no": 4, "bbox": [72, 300, 540, 330], "block_id": "...", "quote": "..."}],
 "confidence": 0.75, "verification": "unverified", "superseded": false, "conflicts_with": [],
 "valid_from": "...", "valid_to": null, "score": 1.21, "support": 0.83, "reasons": {"fused": 0.6, "type_match": 0.2},
 "horizon": 0, "via": null, "glyph": {...}}
```

## Answer

```json
{"answer": "USD 125,000 [1]. Source: \"3.1 The Supplier shall be paid...\" [1].", "status": "answered|insufficient_evidence|conflict",
 "citations": [{"n": 1, "item_id": "...", "document_id": "...", "page_no": 4, "bbox": [...], "quote": "..."}],
 "confidence": 0.71, "mode": "strict", "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.1, "cost_usd": 0.0,
 "usage_is_estimate": true, "unsupported_claims": []}
```

Click-through: a citation's `document_id` + `page_no` + `bbox` map to
`GET /sources/{document_id}/pages/{page_no}` and `/image`; the dashboard's
evidence viewer highlights the box.
