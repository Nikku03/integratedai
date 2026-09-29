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

## 2. Identity resolution (`cie.state.identity`)

Business entities (customers, suppliers, people, products, teams, companies) keep stable ids. Whether a new
description is a known entity is decided by identifiers, not names:

| Evidence | Outcome |
|---|---|
| a known **strong identifier** (VAT or tax number, registration number, customer or supplier number, IBAN, DUNS, LEI, SKU, GTIN, employee id, a person's email) | the same entity |
| a strong identifier that conflicts on a single-valued scheme (two different VAT numbers) | different entities, however alike the names |
| identifiers held by two different records | not decided: a new record, and a proposal with each holder |
| a similar name (score ≥ 90 after normalising case, punctuation and legal suffixes), or a shared weak identifier (phone, domain, address) | a **match proposal** only; the records stay separate |

Tables: `state_identifiers` (a partial unique index keeps each strong identifier on one record per type),
`state_match_proposals` and `state_aliases`.

**Operations:**
- `upsert_entity`: resolves, then creates or updates. Attributes go through the field authority rules.
- `add_identifier`: a strong identifier already held by another record creates a proposal; it is not merged.
- `confirm_match`, `reject_match`.

References can name a record by identifier: `{"type": "supplier", "scheme": "vat", "value": "GB123456"}`.

**Proposals.** A rejected pair is never proposed again, and a proposal is never acted on until it is confirmed.
Confirming needs write access to both records.

**Merging.**
- **Which record stays.** The older record stays canonical, unless the confirmation names the other one. For two
  records created by the same event, the one with more strong identifiers stays, then the lower key.
- **What moves.** The alias's identifiers, relationships, stock rows and project memberships move to the canonical
  record. Its field statements are replayed through the canonical record's authority rules, so a disagreement
  becomes an open conflict, never a silent overwrite.
- **The alias afterwards.** The alias is closed as a version, so its history stays readable. Its id and business
  key keep resolving to the canonical record: in references, in entity views (`resolved_from`) and in imports
  that still send the old key, whose values become statements about the canonical record.
- **When a merge is refused:**
  - the records have different access (scope, clearance or access list); align it first;
  - they carry different single-valued identifiers;
  - they are not of the same mergeable type.

**API:**
- `POST /api/state/identity/resolve`: a dry run. A match on a record the caller may not see is reported without
  details.
- `GET /api/state/identity/proposals`: lists only proposals where the caller can see both records.
- `POST /api/state/identity/proposals/{id}/confirm` and `/reject`.
- The entity view lists identifiers, aliases and open possible matches.

**Knowledge memory.** Mention linking in knowledge memory (`cie.memory.entities`) is a retrieval aid:
- The same normalised name links to the existing entity record.
- A similar name is only `probable`. It gets an unconfirmed `relates_to` link carrying its score, and no alias is
  recorded.
- Before this change, a fuzzy match at score ≥ 90 was linked as the same entity and its spelling recorded as an
  alias.

## 3. Workflow engine (`cie.workflow.engine`)

Every task status change goes through the engine, which checks it against the transition table, increments the
task's `revision` and logs it in `task_transitions` with actor, reason and details. Nothing else sets a status.

```
proposed ─accept─▶ ready ─claim─▶ running ─submit─▶ review ─passed─▶ completed
    │               ▲  │            │  │              │  │               │
    │               │  ▼            │  │   changes    │  │ failed        │ an input changed
    └─▶ cancelled   blocked         │  └──requested◀──┘  ▼               ▼
                                    │                  failed ─retry (authorised)─▶ ready
                                    └─ lease expired / released ─▶ ready (progress kept)
```

**What a task stores:**

| Field | Contents |
|---|---|
| `brief` | inputs as instructions |
| `task_inputs` | versioned inputs: live-state records with the version used, and other tasks' results with their revision |
| `acceptance` | the acceptance criteria |
| `owner_principal_id`, `deadline_at` | owner and deadline |
| `task_dependencies` | `requires` (the dependency must be completed) or `after` (it must be settled or waiting on a person; used by the synthesis) |
| `limits` | `max_tokens`, `max_cost_usd`, `max_seconds`, allowed `tools` |
| `progress` | checkpoints |
| `result` | the result |
| `verification` | every review with its reviewer, verdict, notes and round |
| `attempts`, `max_attempts`, `review_rounds` | counters |

**Claims and leases.** A worker claims a ready task with a lease (`FOR UPDATE SKIP LOCKED`, so no task is claimed
twice). It extends the lease with heartbeats and records progress with checkpoints. When a lease expires, the task
goes back to `ready` with its progress, and the next worker resumes from the last checkpoint. Once `max_attempts`
is used up, it fails instead. A worker that lost its lease cannot submit.

**Review.** On submission the engine checks, in order:
1. the limits: exceeded means `failed`;
2. the inputs: if a record or task result moved on since the task used it, changes are requested;
3. the acceptance criteria (`min_findings`, `citations_required`, `max_unsupported`, `required_fields`,
   `min_confidence`): unmet means changes are requested.

After that, the `review` mode decides:
- `auto` completes the task.
- `agent` (the default for high-risk work, and for work that disagrees with another agent's findings) waits for an
  independent agent: the head creates a verification task and assigns it to a different agent.
- `human` waits for a person, through an approval request.

A reviewer can pass the task, request changes (it goes back to the same worker for a bounded number of rounds) or
fail it. When the rounds run out, a person decides. A task never completes on inputs that moved on.

**Failures and reopening.**
- A failed task is retried only with a named authorisation (`retry`), which allows one more attempt.
- A completed task is reopened only when an input changed (`reopen`). Completed dependants that required it are
  reopened too, and waiting ones are blocked.
- When a task is decided after a dependant used an earlier revision of it, that dependant is reopened. For
  example, a synthesis that reported the task as waiting on a person.

**Head agent.** The head proposes its plan as tasks and accepts them. It claims each ready task for the chosen
agent, records the dependency results it hands over as inputs, and submits results to the engine. It addresses
requested changes by dropping findings the verifier could not support, then resubmits. The synthesis reports
every task's outcome: verified, not independently verified, failed, or waiting on a person.

**API.** Status changes go through these routes, never through direct edits:
- `POST /api/tasks`: propose and accept a task.
- `POST /api/tasks/claim` (next ready task) and `POST /api/tasks/{id}/claim`.
- `POST /api/tasks/{id}/heartbeat`, `/checkpoint`, `/submit` and `/release`.
- `POST /api/tasks/{id}/review`: the worker that produced a result cannot review it.
- `POST /api/tasks/{id}/retry` and `/cancel`.
- `GET /api/tasks/{id}/transitions` and `GET /api/tasks-overdue`.
- Approving or rejecting a `task_result` approval is a person's review verdict.

**Migration.** Old statuses map to new ones:

| Old | New |
|---|---|
| `pending` | `ready` |
| `assigned` | `running` |
| `needs_verification`, `awaiting_approval` | `review` |
| `verified`, `done` | `completed` |
