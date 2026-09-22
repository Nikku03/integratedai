# Database schema

PostgreSQL 16 + `pgvector` + `pg_trgm`. Source of truth:
`src/cie/core/models.py`; migrations in `alembic/versions`.

Every table carries `tenant_id`; every query filters on it.

## Tenancy and access

| table | purpose | key columns |
|---|---|---|
| `tenants` | isolation boundary | `name` |
| `principals` | users, agents, services | `kind`, `attributes` (ABAC), `api_key_hash` |
| `scopes` | memory hierarchy tree | `kind` company/department/project/agent/task, `parent_id`, `path` |
| `roles` | permission level + clearance | `permission` read/write/admin, `max_sensitivity` |
| `grants` | principal × role × scope (inherits to descendants) | unique (principal, role, scope) |

Access rule: principal P may read resource R (scope S, sensitivity σ, acl A) iff
∃ grant (P, role, S') with S' an ancestor-or-self of S and role.max_sensitivity ≥ σ,
and P ∉ A.deny, and (A.allow empty or P ∈ A.allow). Evaluated in SQL as a
scope-id set plus a sensitivity ceiling.

## Vault

| table | purpose |
|---|---|
| `blobs` | sha256-addressed immutable bytes; unique (tenant, sha256); `storage_uri`, `encrypted` |
| `documents` | metadata per file version: `family_id`, `version`, `previous_version_id`, `original_location`, `source`, `owner_id`, `scope_id`, `department_id`, `project_id`, `sensitivity`, `acl`, `retention_policy`, `retain_until`, `legal_hold`, `file_created_at`, `ingested_at`, `status`, `injection_flags`, `pii_flags` |

## Processing

| table | purpose |
|---|---|
| `jobs` | durable queue: `kind`, `status`, `payload`, `checkpoint`, `progress`, `attempts`, `locked_by`, `run_after` |
| `extractions` | one extractor run per document: `extractor`, `page_count`, `pages_done`, `language`, `mean_confidence`, `completeness` |
| `pages` | per page text, size, method (text/ocr), confidence, `text_sha256` |
| `blocks` | layout blocks with `bbox [x0,y0,x1,y1]`, `kind`, `text`, `content` (table cells) |
| `corrections` | OCR corrections; originals untouched |
| `sections` | semantic sections: `title`, `page_start/end`, `text`, `spans`, `tsv`, `embedding(384)`, `text_sha256` for dedup |

## Structured memory

| table | purpose |
|---|---|
| `memory_records` | typed records (22 types). Fields: `summary`, `content` (typed JSON), `detail`, `source_document_id`, `source_locations [{page_no,bbox,section_id,block_id,quote}]`, `event_time`, `valid_from`, `valid_to`, `recorded_at`, `author_id`, `producing_agent`, `confidence`, `verification`, `sensitivity`, `acl`, `version`, `family_id`, `superseded_by_id`, `supersedes_id`, `entity_ids`, `keywords[]`, `glyph`, `tsv`, `embedding`, `content_sha256`, `prompt_version`, `model_version` |
| `record_links` | sparse graph edges: `kind` (13 kinds incl. `contradicts`, `supersedes`, `shortcut`), `weight`, `justification` |

Indexes: GIN on `tsv` and `keywords`, trigram GIN on `summary`, HNSW cosine on
`embedding`, btree on (scope, type) and (valid_from, valid_to).

## Agents and projects

| table | purpose |
|---|---|
| `agents` | registry: `role`, `skills[]`, `task_types[]`, `strategy`, `model`, `cost_per_1k_tokens`, `max_concurrency`, `memory_scope_id` |
| `agent_scorecards` | per (agent, task_type): accuracy, citation_quality, completion_rate, latency, tokens, cost, human_corrections, hallucination_rate, verification_score, n_tasks, last_task_at |
| `projects` | objective, head agent, `token_budget` (default 200M) |
| `tasks` | `task_type`, `brief`, `status`, `risk_level`, `assigned_agent_id`, `assignment_reason`, `evidence_packet_id`, `result`, `verification`, `verifies_task_id`, `metrics` |
| `task_dependencies` | DAG edges |
| `agent_messages` | eight structured kinds, point-to-point, `token_estimate` |
| `ledger_entries` | append-only, `seq` per project, `prev_hash`/`hash` chain, `kind`, `label` (e.g. H17), `content`, `refs` |
| `evidence_packets` | query, intent, scopes, filters, items, trace, token estimate, latency |
| `answers` | answer text, citations, confidence, mode, status, model, prompt_version, tokens, latency, cost, unsupported_claims |

## Governance

| table | purpose |
|---|---|
| `audit_log` | who did what to which resource, outcome |
| `approvals` | human approval gates |
| `deletion_requests` | deletion workflow (blocked by legal hold) |
| `prompt_versions` | prompt text + hash by name/version |
| `metrics` | tokens, latency, compute, storage measurements |

## Entity relationship sketch

```
tenants ─┬─ principals ─── grants ─── roles
         ├─ scopes (tree) ◄────────── grants
         ├─ blobs ◄── documents ──► scopes
         │              │
         │              ├─ extractions ─ pages ─ blocks ─ corrections
         │              └─ sections (tsv, embedding)
         ├─ memory_records ──► documents (source), scopes
         │        └─ record_links (sparse graph)
         ├─ agents ─ agent_scorecards
         ├─ projects ─ tasks ─ task_dependencies
         │        ├─ agent_messages
         │        └─ ledger_entries (hash chain)
         ├─ evidence_packets ─ answers
         └─ audit_log · approvals · deletion_requests · metrics
```
