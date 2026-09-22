# Security model

## Tenancy and identity
* Every table carries `tenant_id`; every query filters on it. Cross-tenant
  access is impossible through the API because the principal's tenant is
  resolved from the API key and injected into every filter.
* Principals are users, agents or services. Agents authenticate exactly like
  users; their permissions are ordinary grants, so an agent can never read
  what its grants do not cover (tested: `test_agent_permissions_apply_to_evidence`).
* API keys are stored as SHA-256 hashes. OIDC/SSO is roadmap.

## Authorization (RBAC + ABAC)
* Roles carry a permission level (read/write/admin) and a clearance
  (`max_sensitivity`). Grants bind principal × role × scope and inherit down the
  scope tree (company → department → project → agent → task).
* A resource is visible iff a grant covers its scope or an ancestor, the role's
  clearance ≥ the resource's sensitivity, and the resource ACL does not deny the
  principal (or allows it when an allow-list exists).
* The rule is compiled to one SQL predicate (`Visibility.sql_filter`) used by
  every retrieval query, and re-checked in Python per record (defence in depth).
* Project and department isolation follows from scopes: a Legal reader sees no
  Finance records unless a grant says so. Graph expansion never crosses into
  scopes the principal cannot read (cross-scope horizon uses the
  permission-only filter).

## Data protection
* Vault bytes are content-addressed and optionally AES-256-GCM encrypted at
  rest (`CIE_ENCRYPTION_KEY`). Checksums are verified on every read.
* Transport encryption is delegated to the ingress (TLS terminator/reverse
  proxy) in the compose deployment; the API itself does not terminate TLS.
* Retention policies set `retain_until`; legal holds block deletion; deletion is
  a workflow (request → approval → soft delete of document, sections and derived
  records; blob removed when unreferenced). All steps are audited.

## Untrusted content
* Ingestion scanners flag secrets, PII and prompt-injection phrases per page.
  Flags are advisory and shown in the UI.
* Retrieved text is *always* passed to models inside an `<untrusted_document>`
  envelope with an explicit instruction that it is data. Packet text with
  injection matches is redacted before it reaches a model or an answer; the
  original page stays visible in the source viewer.
* Assisted answers and LLM specialist outputs are post-verified: every claim
  must cite a packet item and be lexically supported by it; unsupported claims
  are dropped in strict mode and reported.

## Audit and provenance
* `audit_log` records ingest, search, answer, source views/downloads,
  permission changes, approvals, deletions and denied attempts (denials are
  committed even though the request fails).
* Every answer stores its evidence packet id; the packet stores the full
  retrieval trace; re-running the extractive answer on the stored packet
  reproduces the answer byte for byte (tested).
* Prompt and model versions are stored on answers and records.

## Human gates
* High-risk agent tasks are verified by a different agent; failed verification
  creates an approval item. Deletions always require approval.

## Known gaps (see KNOWN_LIMITATIONS.md)
* No rate limiting or per-key quotas; no OIDC; TLS delegated to ingress;
  scanners are pattern-based; encryption key management is environment-based.
