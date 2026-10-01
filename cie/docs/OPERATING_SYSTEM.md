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
| `task_inputs` | versioned inputs: live-state records with the version used, other tasks' results with their revision, and other tasks' released outputs with their version |
| `task_outputs` | the named results it has released, each with a version that goes up only when the value changes |
| `acceptance` | the acceptance criteria |
| `owner_principal_id`, `deadline_at` | owner and deadline |
| `task_dependencies` | `requires` (the dependency must be completed, or only the named `outputs` of it released) or `after` (it must be settled or waiting on a person; used by the synthesis) |
| `limits` | `max_tokens`, `max_cost_usd`, `max_seconds`, allowed `tools` |
| `progress` | checkpoints |
| `result` | the result |
| `verification` | every review with its reviewer, verdict, notes and round |
| `attempts`, `max_attempts`, `review_rounds` | counters |

**Results released early.** A task does not have to finish before others can use its work:
- While it runs, a task releases each named result as soon as it has it (`publish_output`). For example,
  logistics releases `expedite_cost` long before its full delivery plan is done.
- A dependency can name only the results it needs (`depends_on=[(task_id, "requires", ["expedite_cost"])]`). The
  dependant becomes ready as soon as they are released, while the other task is still running. The results it
  reads are recorded as its inputs.
- Releasing the same value again disturbs nobody. A changed value reopens or flags only the tasks that used the
  earlier version, like a changed record (section 4).
- When a task is reopened, its results are marked as being revised:
  - dependants that have not started wait for them;
  - dependants that already used them are disturbed only if a changed value is released.
  A reopened task must re-release every result, even unchanged, before it can complete, and so must a task that
  declares results in `acceptance.outputs`.
- A task's context shows what its dependencies handed over (`upstream`) and what it should release, most awaited
  first (`deliver`).

**Scheduling.** `schedule` puts the ready tasks in the order to run them, each with its reason:
1. priority, lower first;
2. deadline slack: the time until the latest start that still meets every deadline downstream, from the tasks'
   estimates (`metrics.estimate_seconds`);
3. the longest chain of estimated work behind the task;
4. how many unfinished tasks wait on it;
5. age.

`claim` takes the first task in this order that no other worker holds, and the head runs ready tasks in it.
`order="fifo"` keeps priority, then age. `GET /api/projects/{id}/schedule` shows the order.

**Claims and leases.** A worker claims a ready task with a lease (`FOR UPDATE SKIP LOCKED`, so no task is claimed
twice). It extends the lease with heartbeats and records progress with checkpoints. When a lease expires, the task
goes back to `ready` with its progress, and the next worker resumes from the last checkpoint. Once `max_attempts`
is used up, it fails instead. A worker that lost its lease cannot submit.

**Review.** On submission the engine checks, in order:
1. the limits: exceeded means `failed`;
2. the inputs: if a record, a task result or a released output moved on since the task used it, changes are
   requested;
3. the acceptance criteria (`min_findings`, `citations_required`, `max_unsupported`, `required_fields`,
   `min_confidence`, `outputs` released), and every result re-released after a reopening: unmet means changes are
   requested.

After that, the `review` mode decides:
- `auto` completes the task.
- `agent` (the default for high-risk work, and for work that disagrees with another agent's findings) waits for an
  independent agent: the head creates a verification task and assigns it to a different agent.
- `human` waits for a person, through an approval request.

A reviewer can pass the task, request changes (it goes back to the same worker for a bounded number of rounds) or
fail it. When the rounds run out, a person decides. A task never completes on inputs that moved on.

**Failures and reopening.**
- A failed task is retried only with a named authorisation (`retry`), which allows one more attempt.
- A completed task is reopened only when an input changed (`reopen`). Completed dependants that required the
  whole task are reopened too, and waiting ones are blocked. Dependants that need only its results are handled as
  above.
- When a task is decided after a dependant used an earlier revision of it, that dependant is reopened. For
  example, a synthesis that reported the task as waiting on a person.

**Head agent.** The head proposes its plan as tasks and accepts them. A plan can declare the results a task
will hand over, and depend on `"task.result"` instead of a whole task. The head runs ready tasks in schedule order.
It claims each for the chosen agent, records the dependency results it hands over as inputs, and submits results
to the engine. Results named in a result's `outputs` are released on submission. It addresses
requested changes by dropping findings the verifier could not support, then resubmits. The synthesis reports
every task's outcome: verified, not independently verified, failed, or waiting on a person.

**Agents ask each other for work** (`request_work`, `decide_request`). A running task can ask another role for
work it cannot do itself. For example, operations asks finance: "check the budget for $2,000 of expedited
freight".
- The request becomes a proposed task on the requester's behalf. It is answered by releasing an `answer` output;
  the head packages a specialist's result as that answer.
- The head decides each request at its next step:
  - it merges it into an equivalent open request of the same role;
  - it declines it when no agent does that work;
  - otherwise it accepts it.
  A person can decide instead (`POST /api/tasks/{id}/request-decision`).
- With `wait` (the default), the requester steps aside (`blocked`) with its progress kept, and depends on the
  answer. When the answer is released it becomes ready. The same agent then resumes it, with the answer handed over
  in its context.
- A declined, failed or cancelled request releases the requester, and its agent is told why (`work_decision`).
- Requests are bounded: at most 5 per task, and 3 requests deep.
- `POST /api/tasks/{id}/requests` files a request for an outside agent, and queues a head run to decide it.

**More evidence, and questions.**
- A specialist that asks for more evidence gets one more context round per run, with its own permissions, and runs
  again with the new items. Requests it makes after that round are recorded as not served.
- A question only the head can decide goes to a person, as an approval of kind `question`. The person's reply is
  sent to the agent's inbox as an `answer`.
  - A question the agent marks as blocking pauses the task (`blocked`, progress kept) until the answer arrives. The
    answer releases it (`engine.answered`) and queues a run of the project's head.
  - A question that does not block reaches the task the next time it runs.
  - An answer that arrives after the task completed reopens it at the agent's next turn, so the agent
    reconsiders.

**Agents work on their own** (`cie.agents.runtime`). The head is not the only way work gets done. An agent's turn
(job `agent_turn`, or `python -m cie.cli agents --tenant <name>`):
1. reopens its completed tasks that received an answer since;
2. claims the next ready task it can do, in schedule order, across the tenant's projects. It never takes the head's
   planning, verification or synthesis.
3. runs the task exactly as the head would, under its own lease.

What it asks of other agents is decided at once, so they can start. `run_agents` lets every agent take turns until
none has anything left to do.

**Decisions and authority.** A result can carry decisions, such as `{"kind": "spend_usd", "amount": 8000}`. The
engine checks them against the assigned agent's authority (`Agent.config["authority"]`: a limit per kind, or
`true` for any amount).
- The defaults are finance `spend_usd` 5,000 and operations `spend_usd` 1,000; the other agents have none.
  `PUT /api/agents/{id}/authority` changes them (administrators only, audited).
- A decision within authority is recorded as authorised by that agent.
- A decision above it, or by a worker with no authority, sends the task to a person. Its outputs are held until
  the person approves, so a requested answer carrying an unapproved decision never reaches the task waiting for
  it. If the person rejects it, the task fails and its requester is released.

**Constraints and re-planning.** `acceptance.constraints` are checks on a task's outputs, for example
`{"output": "option", "field": "cost_usd", "op": "le", "value": 12000}`.
- An output that breaks a constraint cannot be released, and a result that breaks one is sent back.
- A worker that finds no option meeting them returns `infeasible`, with its reason and the best option it found.
  The task then waits for the head.
- The head re-plans (`replan`). A constraint may flex: `"flex": {"up_to": 15000, "approver": "finance",
  "authority": "spend_usd"}`. When every broken constraint may flex far enough for the best option, and each
  approver's authority covers it, the head relaxes the constraints to that option and accepts it. The decision
  names whose authority it used.
- Otherwise a person decides through a `replan` approval: approve to accept the best option, reject to drop the
  task. `POST /api/tasks/{id}/replan` also lets them relax the constraints and send the task back.

**API.** Status changes go through these routes, never through direct edits:
- `POST /api/tasks`: propose and accept a task.
- `POST /api/tasks/claim` (next ready task) and `POST /api/tasks/{id}/claim`.
- `POST /api/tasks/{id}/heartbeat`, `/checkpoint`, `/submit` and `/release`.
- `POST /api/tasks/{id}/requests`: ask another role for work, and `POST /api/tasks/{id}/request-decision`.
- `POST /api/tasks/{id}/outputs`: release a named result now. `GET /api/tasks/{id}/outputs` lists what the task
  released, what it should deliver, and what its dependencies handed over.
- `GET /api/projects/{id}/schedule`: the ready tasks in order, with the reasons.
- `POST /api/tasks/{id}/replan`: relax the constraints, accept the best option, or drop a task that found no option.
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

## 4. Events and routing to tasks (`cie.state.domain_events`, `cie.workflow.routing`)

**Domain events.** Other systems report what happened as typed events:
- `payment.confirmed` and `invoice.paid`
- `delivery.date_changed`
- `order.status_changed`
- `supplier.delay`
- `task.completed`
- `entity.updated`

Each event carries:
- the record it is about: an id, `[type, key]` or a strong identifier;
- the `version` the sender saw;
- its `source` (system, record, kind);
- `occurred_at`;
- its `data`.

It is translated into field statements, so the authority rules decide what becomes current: a payment from the
bank moves an invoice from `issued` to `paid` or `partially_paid`, while a supplier's email about a delivery date
opens a conflict with the ERP instead of overwriting it.

With `version`, the event is a conditional write. If the record has moved on, the whole event is refused as a
`conflict` (HTTP 409); the sender re-reads and resends. `POST /api/state/domain-events` derives the idempotency
key from the source system and record, so a notification delivered twice is applied once.

**Status ordering without times.** When two equally authoritative sources give a status and neither statement has
an event time, the lifecycle orders them: a status that follows the current one wins, and one that precedes it is
a late report. This applies only to types that have a lifecycle.

**Routing.** After every event (unless `route_tasks=False`), each task that used a changed, deleted or restricted
record (`task_inputs`) is handled according to its status:

| Task status | What happens |
|---|---|
| completed | reopened, with its dependants (see section 3) |
| running or in review | flagged (`progress.stale_inputs`); the engine will not complete it on the old version |
| ready or blocked | noted |

A record also counts as changed when a record joins or leaves it: an order created in, deleted from or moved to a
project changes the project. So a task that relied on "the project's open orders" is refreshed when that set
changes, even though no field of the project did.

Its agent receives an `input_changed` message carrying the record id and versions, never values. Reopened tasks
are recorded in the project ledger. `task_invalidations` is unique per (task, record, new version), so a replayed
or re-delivered event never reopens a task twice. The event summary lists the tasks reopened, flagged and noted.

When a result is first released or revised, the agents of the tasks that need it receive a
`dependency_notification` (`route_output`). The project's head is told of every task reopened in its project.

**Only the fields a task watches.** A task's profile can name trigger fields per record type:
`"triggers": {"order": ["promised_date", "status"]}`.
- A change to other fields of that record neither reopens nor flags the task.
- The engine does not count such a change as stale when the task submits.
- A record appearing, disappearing or being hidden always counts.
- Relationship and stock changes count only if the task watches `edge:*` or `stock`.

**Messages are read and acted on.**
- Each message has a read status. `GET /api/messages/inbox?agent=` lists an agent's unread messages, and
  `POST /api/messages/read` marks them read. An agent reads only its own inbox; an administrator can read any.
- When the head runs a task, the agent's unread messages about it go into its working context and count as read:
  changed inputs, released results, decisions on its requests, answers to its questions.
- The head reads its own inbox each step.

**Work resumes by itself.** When a processed change reopens tasks, the worker queues one run of each affected
project's head (`resume_projects`), so the reopened work is redone without anyone asking.

**Replay.** A processed event returns its stored outcome when processed again. `python -m cie.rem.cli replay`
re-applies a tenant's event log into a new tenant and compares the outcomes.

## 5. Context builder (`cie.context`)

**Permissions come first.** Every channel reads through the requester's visibility (scope, clearance and access
list, in SQL). A record the requester may not see is never loaded, summarised or counted. The channels:

| Channel | What it adds |
|---|---|
| structured | entity views of the records the request names: current values with their sources, dependencies, unresolved conflicts, possible identity matches |
| traversal | typed traversal of the live state from the question: relationship paths, facts versus hypotheses, contradictions, missing evidence. A record without a source pointer is never evidence. |
| keyword and semantic | hybrid search over knowledge memory |
| original sources | the documents and pages the knowledge-memory items cite |

A task's context also carries:
- its instructions, acceptance criteria, limits and deadline;
- the unresolved conflicts of the records it names;
- what its dependencies handed over, and the outputs it should release;
- the decisions already taken in its project (requests, re-plans, actions), newest first.

**A task's information profile** (`profile` when it is proposed, or in a plan):
- `entities`: records loaded into its context as they are now, besides what traversal and search find.
- `triggers`: the fields whose change matters to it (section 4).
- `period`: the time period it is about. The worker sees it; search is not filtered by it.

**Budget.**
- The budget is 25% of the model's context window, capped at 60,000 tokens. The default is 8,000.
- Channels get 30/30/40 shares, and unused tokens flow to the next channel.
- When items do not fit, the context says `complete: false` and returns a cursor. The cursor continues at the
  same snapshot and returns every item exactly once.

**Task inputs.** A task's inputs are the live-state records it used, with their versions. From then on, a change
to one of them flags or reopens the task (section 4), and the engine refuses to complete it on the old value
(section 3). The head agent builds every specialist's context with the agent's own principal. `inputs` sets what
counts as used:

| `inputs` | What becomes an input |
|---|---|
| `all` (default) | every live-state record placed in the context |
| `explicit` | the records the request names and the collections it scans |
| `relied` | nothing when the context is built. On submit, the result's state references and calculation inputs are recorded, at their versions as of the context's snapshot (`engine.relied_on`). A change between reading the context and submitting sends the task back. |

`relied` records only what the answer depends on, so changes to records the worker merely read reopen nothing. It
trusts the result to cite what it used. A result with no state references gets no inputs and is never refreshed,
so use `relied` only for workers whose findings carry them.

`relied` is the recommended setting for workers whose findings carry state references. In the pre-registered study
2 it kept every answer right and removed every re-run of an unaffected project, both with the deterministic analyst
and with Llama 3.1 8B citing its own records (`docs/LOOP_RESULTS.md`). `all` stays the default for workers that
cite nothing.

**Exhaustive mode** answers questions about a whole collection, for example "which open orders of Project A arrive
after October 15?":
- The collection is a record type, optionally limited to one project.
- The check is deterministic: `{"field": "promised_date", "op": "gt", "value": "2026-10-15"}`, combinable with
  `all`, `any` and `not`. Numbers compare as numbers and ISO dates as dates.
- A record missing the field, or whose value cannot be compared, is **unreadable**: counted separately, never as a
  match or a non-match.

The scan covers every record of the collection the requester may see, in id order at one snapshot. It is never
truncated; only the listing of matches is paged. Coverage records the records visible, scanned, matched and
unreadable, and whether the scan was complete. Records hidden from the requester are not included, and neither are
records restricted since an earlier snapshot a cursor points to. Each build is stored in `context_runs`; an
exhaustive scan run for a task is also kept in the task's progress.

**API.** `POST /api/context` (focused or exhaustive) and `GET /api/context/runs/{id}`, which only the requester
or an administrator can read.

## 6. Verification and the publication gate (`cie.agents.verification`, `cie.agents.publication`)

**Methods per finding.** The verdict records, for each finding, which methods ran and why it failed:

| Method | When it runs | What it checks |
|---|---|---|
| citation | the finding has citations | the cited record exists and is current (not deleted, not superseded); its quote is on the cited page; the claim is lexically supported by it |
| state | the finding lists `state_refs` | each live-state record is still at the version the finding used; any stated field value is still the record's value |
| recalculation | the finding carries a `calculation` | the expression is recomputed from the current state and must match the stated value (tolerance 0.01 by default) |

The recalculation evaluator (`cie.agents.calc`) allows numbers, `+ - * / // % **`, parentheses, and `min`, `max`,
`abs`, `round` and `days_between`. It refuses names other than the given inputs, attribute access and any other
call. A finding with no citation, state reference or calculation has no evidence and fails. State checks read
through the verifier's permissions, so a record the verifier may not see cannot support a finding.

**Publication gate.** An agent workspace cannot silently become shared truth:
1. **Staging.** While a task runs, the agent's findings are written to its workspace for that project. This is a
   scope of kind `agent` under the project: project readers can inspect it, but default retrieval does not address
   it. Staged records are `unverified` and carry the highest clearance of what they cite.
2. **Publication.** When the task completes, each finding is published to the project scope only if it passed
   verification:
   - the reviewing agent's verdict, if there was a review;
   - otherwise a person's approval;
   - otherwise a verification run at publication.

   A published record is `verified`, names who verified it and by which methods, and links back to its workspace
   record. A finding that fails stays in the workspace, marked blocked, with the reasons. A finding may name the
   findings of the same result it rests on (`depends_on`, for example a conclusion and the figures behind it). It
   is blocked when any of them is, transitively.
3. **Withdrawal.** When a completed task is reopened because an input changed, its published findings become
   `disputed`. When it completes again, the new publication supersedes them.

The project synthesis is still written to the project scope. Each part of it is labelled as verified, not
independently verified, failed, or waiting on a person.

## 7. The action gateway (`cie.actions`)

Nothing acts on an external system without passing the gateway, and every check is recorded on the action: book a
shipment, notify a supplier, make a payment.

**Proposing** (`gateway.propose`, `POST /api/actions`, or a completed task's `actions`):
1. **Idempotency.** The key is unique per tenant. It is either given, or derived from the task, kind, target,
   payload and proposer, so the same action proposed twice is one action.
2. **Permission.** An agent may propose only the kinds granted to it (`Agent.config["actions"]`; by default
   operations `book_shipment` and `notify_supplier`, finance `payment`). A person needs write access to the project.
3. **Approval.** A person approves (an `action` approval) when either:
   - the kind always needs a person (`CIE_ACTIONS_ALWAYS_APPROVE`: payments, contract signatures and external
     messages by default); or
   - the amount is above the proposing agent's authority.

   Otherwise the action is approved as proposed.

A refused or stale action that is proposed again is checked again; a person's rejection stands. A completed task's
actions are proposed on completion. Their basis is the records its result relied on, and the task's revision.

**Executing** (the worker's `execute_action` job, or `POST /api/actions/{id}/execute`):
4. **Permission again**, in case the grant was withdrawn.
5. **Freshness.** The records the action rests on must be at the same versions, and the task that proposed it must
   still be completed at the same revision. Otherwise the action is `stale` and is not executed.
6. **Already executed.** An executed action is never executed again. The status is committed as `executing` before
   the connector is called, so after a crash the next attempt first asks whether the call went through. A failure
   is retried with the same key, so the other side can recognise the repeat.
7. **Result confirmed.** After executing, the connector reads back what the other side holds: `confirmed` or
   `unconfirmed`.

**Connectors** (`cie.actions.connectors`):
- `outbox`: a JSON-lines file, written once per key and confirmed by the payload hash. Something else delivers what
  it holds.
- Webhooks: named in `CIE_ACTION_WEBHOOKS`, with secrets read from environment variables. A webhook call carries
  an `Idempotency-Key` header and an HMAC-SHA256 signature, and is confirmed by reading back the receipt.

No ERP, email or payment system is connected in this build.

## 8. The loop benchmark (`cie.eval.bench_loop`)

This measures the loop the architecture asks to prove on one project: retrieval completeness, citation accuracy,
stale-state errors, missed dependencies, duplicate actions, task completion, latency and cost.

**Data.** Projects come from the controlled generator (FICTIONAL, GENERATED data), with prices and budgets added.
Expected answers come from the generator's own world model. The worlds are loaded into the tenant that holds the
EnterpriseRAG-Bench memory bank, so search has to find them among real text.

**How it runs.**
- For each project, an analyst answers "Can it deliver every milestone on time and within budget?" through the
  context builder, the workflow engine and the publication gate.
- The deterministic analyst applies the business definition exactly, so its arms isolate the loop.
- The model analyst (`llm-*` arms) gets the same data, with records under short aliases, and replies with JSON:
  milestones at risk, cost lines, cost, budget and verdicts. The harness builds the findings from that reply,
  citing exactly the records the model listed. Verification can catch a wrong cost or budget figure (recalculation
  against the records), and the answer, which rests on those figures, is then blocked with them. It cannot catch a
  wrong at-risk judgment.
- A stream of changes follows. Each change is delivered twice, and each supplier notice is also forwarded under a
  new key.

**Arms.**

| Arm | Analyst | Inputs | Routing |
|---|---|---|---|
| `loop` | deterministic | `all` | on |
| `loop-explicit` | deterministic | `explicit` | on |
| `loop-relied` | deterministic | `relied` | on |
| `no-routing` | deterministic | `all` | off |
| `llm-relied` | the configured model (`CIE_LLM_PROVIDER`, `CIE_LLM_MODEL`) | `relied` | on |
| `llm-no-routing` | the configured model | `relied` | off |

**Measures added for the model.**
- Answer accuracy when given: the whole answer, and each part (delivery verdict, budget verdict, cost, milestones at
  risk).
- Wrong answers served because the analyst erred. These are kept apart from stale answers: an answer is stale only
  if it was right when given.
- Wrong and right figures blocked by verification.
- Runs without a usable answer.
- Replies not in the requested JSON form, invented record ids, model calls, tokens and latency.

The pass criteria are fixed in advance in `docs/LOOP_PREREGISTRATION.md`:
- study 1: `loop` and `loop-explicit`, test worlds 301 to 303;
- study 2: `loop-relied` and the model arms, test worlds 304 to 306.

With `CIE_LOOP_COMPARE_KEYWORD_ENGINES=1`, every delay question is also asked with each keyword engine (full text
and BM25) at the same moment, so the engine's effect on search is measured apart from everything else.

The Colab notebook `notebooks/enterprise_rag_bench_colab.ipynb` runs the benchmark as Part 2, inside the
50,000-document memory bank. For the model arms, it runs Llama 3.1 8B on the GPU through Ollama.

```bash
python -m cie.eval.bench_loop --host-tenant <memory bank tenant> --seeds 301,302,303 --events 20 --arms loop,loop-explicit,no-routing
CIE_LLM_PROVIDER=local CIE_LLM_MODEL=<ollama model> CIE_LLM_BASE_URL=http://localhost:11434/v1 \
  python -m cie.eval.bench_loop --host-tenant <memory bank tenant> --seeds 304,305,306 --events 20 \
  --arms loop,loop-relied,llm-relied,llm-no-routing
```

**Found and fixed during development** (worlds 1, 2 and 4 only):
- A stock count or a new relationship did not change a record's version, so tasks that had used the record were
  not reopened. Records now carry `changed_seq`, the last change of any kind. Task inputs record the snapshot they
  were read at, and routing and the engine's stale check use both.
- A re-run kept the previous run's inputs. A record deleted since then made every submission look stale, until a
  person had to decide. A task's record inputs are now cleared whenever it starts running again.

**Observed during development.** Counting everything in the context as an input (the builder's default) reopens
many tasks whose answers did not depend on the change, because traversal brings in other projects' records. On
two development worlds, 106 of 149 routings were of unaffected projects, and the reaction to a change took about
6 s instead of about 0.8 s with `inputs="explicit"`. Nothing was missed either way. The default stays
conservative, because a model may rely on anything in its context; workers that declare what they use can pass
`inputs="explicit"`.

## 9. Status

These layers are built and tested (unit, integration and API tests; see `tests/test_state.py`,
`test_identity.py`, `test_workflow.py`, `test_routing.py`, `test_context.py`, `test_verification.py` and
`test_bench_loop.py`). The pre-registered loop run (test worlds 301 to 303, inside the 50,000-document memory
bank) met every criterion: no stale answers, no missed dependencies and no duplicate actions over 104 affected
project changes. Without routing, 347 stale answers were served. See `docs/LOOP_RESULTS.md`.

Study 2 (test worlds 304 to 306) also met every pre-registered criterion:
- **Relied inputs.** `loop-relied` kept every answer right with exactly one re-run per affected project (119),
  against 173 re-runs for `loop`. It used 21% fewer context tokens, and the typical time to refresh answers fell
  from 9.9 s to 5.1 s.
- **Llama 3.1 8B as the analyst.** The loop's guarantees held: no stale answers, no missed dependencies, no
  duplicate actions. But none of the model's answers was right: it never got the cost right, and judged the
  milestones at risk correctly in 20% of answers. Verification blocked all 152 wrong figures, so no model answer
  was published.
- **A gap.** A task whose answer the gate blocks still completes, holding that answer as its result.

Work requests between agents, their merging, limits and release on decline or failure, the evidence round, and
questions answered by a person are covered by tests (`tests/test_requests.py`). One test runs the whole flow with a
scripted model: operations asks finance, waits, and finishes with the answer. These are tests of the mechanism, not
a measurement with real models.

Results released early and the schedule order were tested in a pre-registered simulation (test worlds 401 to 410:
generated projects and simulated durations, over the real engine). Every criterion was met:
- projects finished about 20% sooner (median), and sooner on all ten worlds;
- after changes, re-runs fell from 653 to 237, and unneeded re-runs from 419 to 0;
- no task finished on a stale input.

The schedule order cut deadline misses from 6 to 2, but not the median finish time. See `docs/SCHEDULE_RESULTS.md`.

Tests cover the rest of the loop (`tests/test_authority.py`, `test_actions.py`, `test_agent_turns.py`,
`test_profile.py`):
- decision authority, and outputs held until a person approves;
- constraints, and re-planning within an agent's authority or by a person;
- the action gateway's seven checks, the outbox and a signed webhook;
- agents taking turns on their own, including handing work to each other with no head run;
- questions that pause a task;
- trigger fields, and the head told of reopenings.

These tests use scripted models and simulated connectors. They are not measurements with real models or real
external systems.

**Not built yet:**
- Sending a task back when the publication gate blocks its answer. Today the task completes holding the answer.
- Connectors to real systems (ERP, email, payments). The gateway has an outbox and a webhook connector.
- Search limited to a task's period.
- Re-planning that proposes new tasks: the head relaxes constraints within authority, or asks a person.
- The head deciding requests on their merits: it merges duplicates and declines work no agent does.
