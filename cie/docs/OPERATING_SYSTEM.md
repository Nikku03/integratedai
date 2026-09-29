# Company operating system: live state, identity, work and verification

This document covers the parts of the engine that turn memory into coordinated work: the live model of the
business, identity resolution, the workflow engine, event routing, the context builder and verification. The
evidence vault, knowledge memory and search are described in `docs/ARCHITECTURE.md`; REM (an optional analysis)
in `docs/REM.md`.

| Layer | Package | Owns |
|---|---|---|
| Evidence vault | `cie.vault`, `cie.extraction` | original files, page and character pointers |
| Knowledge memory | `cie.memory`, `cie.retrieval` | typed records, scopes, search |
| **Live state** | `cie.state` | the current, versioned business records; field sources and authority; conflicts; lifecycles; events in commit order |
| Analysis (optional) | `cie.rem` | candidate impacts and suggested checks after a change; never identity, permissions, transaction order or task status |

## 1. Live state (`cie.state`)

**Records.** Each business record (order, invoice, milestone, task, contract, person, …) has a stable id, a type
and business key, and a version history: every change writes a new version with the change's sequence number, so
the state at any earlier moment can be read back. Tables: `rem_nodes`, `rem_node_versions`, `rem_edges`,
`rem_stock` (they keep their original names).

**Events.** `cie.state.events` stores each event once per idempotency key and applies it in one transaction under
the tenant lock, taking the next sequence number. Order of work for one event:

1. **Authorize**, under the lock, against the state it will change. A refused event is `rejected` and uses no
   sequence number.
2. **Check versions.** An operation may name the version it was based on (`expected_version`). If the record has
   moved on, the whole event is refused as `conflict` and nothing is applied.
3. **Apply** the operations.
4. **Keep generated content consistent.** Content derived from a restricted record gets that record's access, and
   content derived from a changed, deleted or restricted record is marked `invalidated`.
5. **Run the analysis, if any.** REM's change rules are optional (`analysis="rules"`).
6. **Mark stale** the cached results that used a changed record, and **audit** the event.

**Field-level sources.** `observe` records one statement of one field: its value, source (`system`, `kind`,
`record`, `method`), evidence pointers, event time (`effective_at`) and recorded time (sequence number and
timestamp). Statements are kept in `state_fields`. Exactly one per field is `current`, and its value is also the
record's attribute. The others are kept as `history`, `corroboration`, `conflict`, `superseded`, `rejected` or
`overwritten`.

**Authority. Newest does not always mean correct.** Rules in `state_authority` rank sources per entity type,
field and system (lower wins; `*` matches anything). Without a rule, the rank comes from the kind of source:

| Source kind | Rank |
|---|---|
| system of record | 10 |
| human | 30 |
| document | 50 |
| email | 70 |
| chat | 80 |
| agent | 90 |
| unknown | 100 |

A new statement is decided as follows:

| Situation | Outcome |
|---|---|
| no current value | becomes current |
| same value | corroborates; becomes the backing statement if its source ranks higher |
| more authoritative source | replaces the current value, unless it describes an earlier moment: then a conflict is opened |
| less authoritative source, different value | conflict; the current value stays |
| equally authoritative, later event time | replaces |
| equally authoritative, earlier event time | kept as history (a late report) |
| the same source updating its own statement | replaces |
| equally authoritative, no time to order them | conflict |

A value written directly on a record (by import or ingestion) becomes the baseline statement the first time the
field is observed. Its source is the record's `source_system` (a system of record for `erp`, `inventory`,
`contract_repository` and `project_tracker`); otherwise it is `unknown`. A later direct write that changes an
observed field marks the statement it replaced as `overwritten`, so no source is shown for a value it did not
give.

**Conflicts.** A conflict (`state_conflicts`) stays open, and the current value stays in place, until an authorized
principal resolves it (`resolve_conflict`, accepting the current or the challenging value) or a more authoritative
statement settles the field.

**Lifecycles.** `cie.state.lifecycle` lists the allowed status transitions for orders, invoices, milestones, tasks,
projects and contracts. A status change outside them (for example an order going from `shipped` back to `open`, or
an unknown status) is not applied; it opens a conflict.

**Other operations**, all with optional `expected_version`:
- `set_status`: a status statement, checked against the lifecycle.
- `set_owner`: an owner statement; it also moves the `owned_by` relationship.
- `verify_entity`: sets `last_verified_at`, the method and who verified, and marks the field statements verified.
  Only an administrator, a principal with `can_verify`, or the system itself may do this.

**Entity view.** `GET /api/state/entities/{type}/{key}` returns what the caller may see: id, status, owner,
version, dependencies (both directions, with provenance), facts with their current statement (source, method,
rank, event and recorded time, verification, evidence), other statements (`?history=true`), evidence, unresolved
conflicts, and `last_verified_at`.

```json
{"entity_id": "order:o184", "status": "open", "owner": "ana", "version": 4,
 "facts": {"promised_date": {"value": "2026-10-01",
           "statement": {"source": {"system": "erp", "kind": "system_of_record"}, "rank": 10, "recorded_seq": 1}}},
 "dependencies": [{"relation": "depends_on", "direction": "out", "type": "supplier", "key": "s1"}],
 "unresolved": [{"field": "promised_date", "reason": "mail (email, rank 70 …) disagrees with the current value …",
                 "challenger": {"value": "2026-10-20", "evidence": [{"document": "email-1"}]}}],
 "last_verified_at": null}
```

**API.**
- `POST /api/state/events`: `analysis` is `none` (the default), `rules` or `reachability`; `wait=false` queues the
  event as a `state_event` job.
- `GET /api/state/events/{id}`: for the submitter or an administrator.
- `GET /api/state/conflicts` and `POST /api/state/conflicts/{id}/resolve`.
- `GET` and `PUT /api/state/authority`: `PUT` is for administrators only.

**What REM may still write.** Only derived, labelled content: `rule` or `inferred` relationships with their
derivation, and review marks on generated records. `AnalysisWriter` enforces this. Giving generated content its
source's access used to be rule R8's write; it is now a state step.
