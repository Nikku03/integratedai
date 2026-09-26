# REM: dependency exploration, evidence selection and change-impact tracking

REM connects evidence and consequences across the company. Given a **question** it returns a cited evidence
packet: relevant records, relationship paths, confirmed facts versus hypotheses, contradictions and missing
evidence. Given a **change** it returns the records that may be affected, why, and the verification tasks that
follow. It recommends the capability a task needs; the head agent decides who does it.

This is a new application of the REM ideas to enterprise data. It claims nothing from the numerical REM
inference work, and ordinary graph traversal is not called REM here: arm B below *is* ordinary typed traversal,
and it is the default until the REM policy beats it (see Results).

## 1. What existed (inspection)

| Where | What | Status for this work |
|---|---|---|
| `Nikku03/enzyme_Software` | No component named REM, and no REM inference engine, in the published history (one commit). Closest: NEXUS analogical memory banks (site-of-metabolism prediction: ECFP4/Tanimoto shortlist, Poincaré re-ranking, Gromov–Wasserstein label transport), `dream_phase.py` (sleep-style replay and imagination between training epochs), `RecursiveNeuralGraphGenerator` (bounded metabolite BFS), MoE/Bayesian routers. No expander or O(log N) construction exists. | Chemistry-specific; nothing transferable. Nothing is reused or claimed. |
| `integratedai` (this repo) | Vault, extraction with page and character pointers, typed memory records, hybrid search (exact, keyword, vector), RBAC+ABAC permissions filtered in SQL, durable job queue, audit, agent registry (head + five specialists). `retrieval/graph.py`, previously called "REM", is bounded breadth-first expansion over `record_links`. | Reused: vault, extraction, search, permissions, queue, audit, API auth. |
| Earlier CIE benchmarks | Graph expansion, topological cliques and the expander overlay gave no retrieval gain (`docs/BENCHMARKS.md`, `docs/TOPOLOGY.md`). | Why arm D is optional and off. |

Original numerical REM inference versus this adaptation: the former, as far as the repositories show, is a
scientific inference method with its own results; the latter is a typed, versioned business graph with explicit
rules and a transparent priority score. Results from one do not transfer to the other.

## 2. Place in the engine

| Component | Responsibility |
|---|---|
| Raw vault | original documents and attachments (immutable, content-addressed) |
| Databases | exact business values and calculations (`rem_stock`, ERP-like attributes, aggregates) |
| Search | exact lookup, keyword, semantic retrieval (`cie.retrieval`, plus REM's own record search) |
| **REM** (`cie.rem`) | dependency exploration, evidence selection, change-impact tracking |
| Head agent | objectives, judgment, task assignment, synthesis |
| Workflow scheduler | execution, retries, deadlines, task states (`cie.workers`; REM events run as `rem_change` jobs) |

REM is an API (`/api/rem/*`) and a library; any agent can call it and no agent has to run for a query. The
200M-token project memory and larger company memory are storage targets for the vault, databases and indexes,
not an active context size and not a capacity this work has demonstrated.

## 3. Graph model

G(t) = (V(t), E_business(t), E_routing(t)), in PostgreSQL (no separate graph database).

* **Nodes** (`rem_nodes` identity + `rem_node_versions`): stable id, tenant, type (company, department, project,
  person, team, agent, customer, supplier, product, contract, order, invoice, task, milestone, requirement, fact,
  claim, decision, risk, document, passage, artifact), business key, structured attributes, project/department
  memberships, source pointers, version, valid time (`valid_from/valid_to`), recorded time (`sys_from/sys_to`, the
  tenant's change sequence), permission scope, sensitivity and ACL, verification status, `authoritative` (false
  for generated content), review status, embedding, text index. No node per token: passages are source spans.
* **Business edges** (`rem_edges`): depends_on, blocks, supplies, governed_by, owned_by, supports, contradicts,
  supersedes, derived_from; direction, source pointers, validity interval, recorded time, provenance
  (`explicit`, `rule`, `inferred`) and, for derived edges, the derivation (rule id or model and inputs). Inferred
  edges are stored as hypotheses until verified. The writer refuses a derived edge without its derivation.
* **Routing edges** (`rem_routing_edges`): a separate table. Navigation only; never read as a relationship, as
  evidence or as access. The node behind a shortcut is loaded through the same permission filter.
* **Exact values** (`rem_stock`): quantities used by rules come from here, not from text.

Direction conventions are in `cie/rem/domain.py`.

## 4. Bounded horizons and budgets

Start: permission-filtered search results (REM's keyword and semantic record search, or hits supplied by the
caller, which are re-filtered). Then:

* H1: immediate dependencies (depends_on, blocks, supplies, governed_by), the records' own sources, versions,
  contradictions, owners;
* H2: dependencies of those plus supporting evidence;
* H3: dependencies only, and only records outside the start set's projects and departments.

Separate limits: `max_depth`, `max_visited` (strict), `max_tokens` (evidence returned; about four characters per
token), `max_db_calls`, `max_ms`. Reaching any of them gives `status: incomplete` with the limit as
`stopping_reason`; the frontier is saved and `resume_from` continues at the same snapshot. `targeted_searches` adds
starting records. Questions asking for counts or totals are routed to a database aggregate
(`status: routed`), not traversed. No logarithmic bound is claimed; costs are measured below.

## 5. Modes

**Query** (`POST /rem/query`): question, identity, project scope, valid-time `as_of`, snapshot → entities,
candidate affected projects and tasks, current assessments from change mode, evidence with exact source pointers,
relationship paths, confirmed facts versus hypotheses (unverified claims, inferred relationships, generated
summaries), contradictions resolved by chronology (history is kept), missing evidence, suggested tasks with a
capability, budget use, status and stopping reason.

**Change** (`POST /rem/changes`, worker job `rem_change`): events `ops` (generic upserts, edges, stock, deletion,
restriction), `supplier_delay`, `stock_count`, `task_status`, `restrict`. The event is applied as new versions at
the next sequence number, then explicit rules run:

| Rule | Consequence, and when |
|---|---|
| R0 value conflict | a claim that states a different value than its record → `contradicts` (rule-derived); if the record is a later system-of-record statement, `supersedes` |
| R1 supply exposure | a milestone is **at risk** only if, for a product it needs, stock held by its project plus open orders promised by the due date plus slack fall short; **covered** if some order is late but stock and on-time orders still cover it; **resolved** when an earlier assessment no longer holds |
| R2 dependents | at-risk milestone → its project at risk; open tasks that depend on it need review (tasks reached through an inferred link are flagged as hypotheses) |
| R3 penalty | at-risk milestone governed by a penalty clause → clause needs review; finance and legal tasks |
| R4 derived content | generated summaries of a changed record are invalidated; authoritative derived records need review |
| R5 unblocking | a completed task unblocks tasks with no other open blocker |
| R6 contract change | records governed by a changed contract or clause need review |
| R7 deletion | records that depended on a deleted record need review; supply is re-checked |
| R8 revocation | summaries of a record that became more restricted are invalidated |

A connected record is not affected unless a rule says so. Impacts are keyed by (target, impact); a rule fires once
per (rule, target, trigger), so cycles terminate and several paths merge into one impact (all paths kept, grade
not raised). Suggestions are deduplicated by key across paths and events. A new assessment of a milestone
supersedes the earlier assessment and the tasks that followed from it; earlier snapshots still show what was
believed then.

## 6. Priority (arm C)

priority = w_q·query_relevance + w_d·dependency_relevance + w_r·source_reliability + w_t·temporal_applicability
+ w_g·information_gain − w_c·retrieval_cost − w_x·redundancy

| Component | Definition |
|---|---|
| query relevance | cosine similarity of the record's text to the question |
| dependency relevance | normalised search score of the start record × edge-kind weight × provenance factor (explicit 1, rule 0.9, inferred 0.5) × 0.8 per hop × 0.5 per change of direction |
| source reliability | by source system (ERP/contract repository/inventory 1.0 … email 0.6, chat 0.5, generated 0.2) × verification factor |
| temporal applicability | 1 if valid at `as_of`; lower if expired, not yet valid, or under review |
| information gain | share of the record's original sources not yet covered (per evidence role), bonus for claims, risks, requirements |
| retrieval cost | tokens to read it (a whole document counts its full length) / token budget |
| redundancy | share of its original sources already covered by evidence of the same role |

Weights are hand-set heuristics (`cie.rem.priority.Weights`), not probabilities. Every start, expansion and
evidence choice is logged with its components (`GET /rem/explanations/{id}`). Permissions are not a component:
unreadable records are never loaded. Two texts from one original source count as one source (near-duplicate
documents share a root), so repeated summaries do not corroborate each other.

## 7. Consistency and protection

Idempotent events (unique key; a different payload under the same key is refused); one transaction per event under
a per-tenant advisory lock; versioned nodes, edges and stock; deletion and restriction are versions too; stale
marking of cached results through `rem_result_deps`; invalidation of generated summaries; snapshot-consistent reads;
audit entries for queries and changes. Every impact, task and output item carries `requires`, the ids of every
record it reveals (target, path, evidence); readers get an item only if they may see all of them, so restricted
records do not leak through paths, task titles, reasons, caches or counts. Stored results are re-filtered with the
reader's current permissions; `GET /rem/explanations/{id}` returns the request, snapshot, trace and a request body
that reproduces the read.

## 8. Setup and commands

```bash
cd cie && cie migrate                                   # adds the rem_* tables (revision f6a7b8c9d0e1)
cie rem demo                                            # fictional supplier-delay scenario, prints its checks
cie rem ingest bundle.json --tenant acme                # source records -> typed graph (one idempotent event)
cie rem query --tenant acme --principal ops_lead --question "..." --policy traversal
cie rem change --tenant acme --kind supplier_delay --payload delay.json --key delay-42
cie rem replay --tenant acme                            # re-apply events into a fresh tenant, compare impacts
cie rem bench dependency --split dev|heldout            # controlled dependency dataset
CIE_DATABASE_URL=...cie_erb cie rem bench erb --split dev|heldout --erb-tenant <loaded tenant> --erb-root <ERB checkout>
pytest tests/test_rem.py                                # needs the cie_test database
```

Feature flags: `CIE_REM_POLICY_ENABLED` (arm C available and default), `CIE_REM_ROUTING_ENABLED` (arm D). Both are
off; the default policy is typed traversal (arm B).

## 9. Results

See `docs/REM_RESULTS.md` (numbers, per split) and `docs/REM_PREREGISTRATION.md` (rules fixed before held-out).
