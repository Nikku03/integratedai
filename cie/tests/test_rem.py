"""REM: versioned business graph, bounded exploration, change rules, consistency and permissions."""

from __future__ import annotations

import uuid

import pytest

from cie.governance.permissions import visible_scopes
from cie.rem.change import IdempotencyConflict, process_event, submit_event, visible_impacts
from cie.rem.models import RemImpact, RemResult, RemSuggestion
from cie.rem.query import QueryRequest, redact, requires_of, run_query
from cie.rem.store import GraphReader, GraphWriter

pytestmark = pytest.mark.db


def apply(session, world, ops, key=None, embedder=None, kind="ops"):
    ev, _ = submit_event(session, world.tenant.id, kind=kind, payload={"ops": ops} if kind == "ops" else ops,
                         idempotency_key=key or uuid.uuid4().hex)
    summary = process_event(session, ev.id, embedder=embedder)
    return ev, summary


def node(t, key, name=None, scope="Acme", **kw):
    return {"op": "upsert_node", "type": t, "key": key, "name": name or key, "scope": scope, **kw}


def edge(src, kind, dst, **kw):
    return {"op": "upsert_edge", "src": list(src), "kind": kind, "dst": list(dst), **kw}


def impacts_of(session, ev):
    return {(i.target_id, i.impact): i for i in session.query(RemImpact).filter(RemImpact.event_id == ev.id)}


def key_of(session, world, nid):
    return GraphReader(session, world.tenant.id, None).nodes([nid])[nid].key


def supply_world(session, world, embedder, *, stock=0, slack=0, extra_ops=()):
    ops = [node("project", "p1", "Project One"), node("supplier", "s1", "Supplier One", attrs={"source_system": "erp"}),
           node("product", "widget", "Widget"),
           node("milestone", "m1", "Milestone One", project_keys=["p1"], attrs={"due_date": "2026-11-15", "slack_days": slack}),
           node("order", "o1", "Order One", project_keys=["p1"], source_pointers=[{"system": "erp", "record": "o1"}],
                attrs={"product": "widget", "supplier": "s1", "qty": 10, "promised_date": "2026-11-01", "status": "open",
                       "source_system": "erp"}),
           node("task", "t1", "Task One", project_keys=["p1"], attrs={"status": "open"}),
           edge(("order", "o1"), "depends_on", ("supplier", "s1")),
           edge(("milestone", "m1"), "depends_on", ("order", "o1")),
           edge(("milestone", "m1"), "depends_on", ("product", "widget"), attrs={"qty": 10}),
           edge(("project", "p1"), "depends_on", ("milestone", "m1")),
           edge(("task", "t1"), "depends_on", ("milestone", "m1")),
           {"op": "set_stock", "product": "widget", "holder": ["project", "p1"], "on_hand": stock, "scope": "Acme",
            "source_pointers": [{"system": "inventory", "record": "bin-1"}]}, *extra_ops]
    return apply(session, world, ops, embedder=embedder)


def delay(session, world, date="2026-12-01", key=None, supplier="s1"):
    ev, _ = submit_event(session, world.tenant.id, kind="supplier_delay", payload={"supplier": supplier, "new_date": date},
                         idempotency_key=key or uuid.uuid4().hex)
    return ev, process_event(session, ev.id)


# ------------------------------------------------------------------------------------------------ storage
def test_versions_snapshots_and_deletion(session, world, embedder):
    ev1, s1 = apply(session, world, [node("order", "o1", attrs={"qty": 10})], embedder=embedder)
    ev2, s2 = apply(session, world, [{"op": "revise_node", "ref": ["order", "o1"], "attrs": {"qty": 12}}])
    ev3, s3 = apply(session, world, [node("order", "o1", attrs={"qty": 12})])  # identical: no new version
    assert not s3["changed"], "an identical re-submission must not create a version"
    r1, r2 = GraphReader(session, world.tenant.id, None, seq=s1["seq"]), GraphReader(session, world.tenant.id, None, seq=s2["seq"])
    assert r1.node_by_key("order", "o1").attrs["qty"] == 10 and r2.node_by_key("order", "o1").attrs["qty"] == 12
    assert s2["changed"][str(r2.node_by_key("order", "o1").id)] == ["attrs.qty"]
    _, s4 = apply(session, world, [{"op": "delete_node", "ref": ["order", "o1"]}])
    assert GraphReader(session, world.tenant.id, None).node_by_key("order", "o1") is None
    assert GraphReader(session, world.tenant.id, None, seq=s3["seq"]).node_by_key("order", "o1").version == 2, "history stays readable"


def test_business_edges_require_provenance_and_known_kinds(session, world):
    w = GraphWriter(session, world.tenant.id)
    w.begin()
    a, _, _ = w.upsert_node("task", "a", name="a", scope_id=world.company.id)
    b, _, _ = w.upsert_node("task", "b", name="b", scope_id=world.company.id)
    with pytest.raises(ValueError):
        w.upsert_edge(a, "similar_to", b)  # not a business relationship
    with pytest.raises(ValueError):
        w.upsert_edge(a, "depends_on", b, provenance="inferred")  # derived without recorded provenance
    eid = w.upsert_edge(a, "depends_on", b, provenance="inferred", derivation={"model": "x"})
    edges, _, _ = GraphReader(session, world.tenant.id, None, seq=w.seq).edges([a])
    assert edges[0].id == eid and edges[0].hypothesis, "model-inferred relationships stay hypotheses until verified"


# ------------------------------------------------------------------------------------------------ permissions
def test_paths_through_hidden_records_do_not_exist(session, world, embedder):
    # A (Finance, visible to outsider) -> B (Legal, hidden from outsider) -> C (Finance, visible)
    _, s = apply(session, world, [node("task", "A", "Alpha task", scope="Finance"), node("task", "B", "Bravo task", scope="Legal"),
                                  node("task", "C", "Charlie task", scope="Finance"),
                                  edge(("task", "A"), "depends_on", ("task", "B")), edge(("task", "B"), "depends_on", ("task", "C"))],
                 embedder=embedder)
    admin_reader = GraphReader(session, world.tenant.id, None)
    a = admin_reader.node_by_key("task", "A")
    out = run_query(session, world.tenant.id, visible_scopes(session, world.outsider),
                    QueryRequest(question="alpha", policy="traversal", start_hits=[(a.id, 1.0)]), embedder=embedder,
                    principal_id=world.outsider.id)
    keys = {e["key"] for e in out["entities"]}
    assert keys == {"A"}, f"B is hidden and C is only reachable through B: {keys}"
    full = run_query(session, world.tenant.id, visible_scopes(session, world.admin),
                     QueryRequest(question="alpha", policy="traversal", start_hits=[(a.id, 1.0)]), embedder=embedder,
                     principal_id=world.admin.id)
    assert {e["key"] for e in full["entities"]} == {"A", "B", "C"}


def test_caller_supplied_start_hits_are_permission_filtered(session, world, embedder):
    apply(session, world, [node("task", "secret", "Secret task", scope="Legal", sensitivity=2)], embedder=embedder)
    sid = GraphReader(session, world.tenant.id, None).node_by_key("task", "secret").id
    out = run_query(session, world.tenant.id, visible_scopes(session, world.outsider),
                    QueryRequest(question="secret", policy="rem", start_hits=[(sid, 1.0)]), embedder=embedder,
                    principal_id=world.outsider.id)
    assert out["entities"] == [] and "Secret" not in str(out)


def test_routing_shortcuts_are_navigation_only(session, world, embedder):
    _, s = apply(session, world, [node("task", "A", "Alpha", scope="Finance"), node("task", "D", "Delta", scope="Finance"),
                                  node("task", "E", "Echo", scope="Legal")], embedder=embedder)
    r = GraphReader(session, world.tenant.id, None)
    a, d, e = (r.node_by_key("task", k) for k in "ADE")
    w = GraphWriter(session, world.tenant.id)
    w.begin()
    w.add_routing(a.id, d.id, "expander-d2")
    w.add_routing(a.id, e.id, "expander-d2")
    session.flush()
    edges, _, _ = GraphReader(session, world.tenant.id, None).edges([a.id])
    assert edges == [], "routing shortcuts never appear as business relationships"
    out = run_query(session, world.tenant.id, visible_scopes(session, world.outsider),
                    QueryRequest(question="alpha", policy="rem+routing", start_hits=[(a.id, 1.0)]), embedder=embedder,
                    principal_id=world.outsider.id)
    ents = {x["key"]: x for x in out["entities"]}
    assert "D" in ents and ents["D"]["via"] == "routing" and ents["D"]["paths"][0][0]["kind"] == "routing"
    assert "E" not in ents, "a shortcut is not permission to see the record behind it"
    assert out["routing"]["shortcuts_followed"] == 1 and not out["contradictions"]


# ------------------------------------------------------------------------------------------------ budgets
def test_budget_stop_is_explicit_and_resumable(session, world, embedder):
    ops = [node("task", f"t{i}", f"Chain task {i}") for i in range(10)]
    ops += [edge(("task", f"t{i}"), "depends_on", ("task", f"t{i + 1}")) for i in range(9)]
    apply(session, world, ops, embedder=embedder)
    t0 = GraphReader(session, world.tenant.id, None).node_by_key("task", "t0")
    vis = visible_scopes(session, world.admin)
    first = run_query(session, world.tenant.id, vis, QueryRequest(question="chain", policy="traversal", start_hits=[(t0.id, 1.0)],
                                                                  limits={"max_visited": 2}), embedder=embedder, principal_id=world.admin.id)
    assert first["status"] == "incomplete" and first["stopping_reason"] == "budget:max_visited"
    assert any("frontier" in m["what"] for m in first["missing_evidence"])
    more = run_query(session, world.tenant.id, vis, QueryRequest(question="chain", policy="traversal", resume_from=uuid.UUID(first["result_id"]),
                                                                 limits={"max_visited": 50}), embedder=embedder, principal_id=world.admin.id)
    keys = [e["key"] for e in more["entities"]]
    assert len(keys) == len(set(keys)) and {"t0", "t1", "t2", "t3"} <= set(keys), keys  # depth 3 from t0
    assert more["snapshot_seq"] == first["snapshot_seq"], "a resumed exploration reads the same snapshot"
    with pytest.raises(PermissionError):
        run_query(session, world.tenant.id, visible_scopes(session, world.outsider),
                  QueryRequest(question="chain", resume_from=uuid.UUID(first["result_id"])), embedder=embedder,
                  principal_id=world.outsider.id)


def test_token_budget_limits_evidence(session, world, embedder):
    ops = [node("fact", f"f{i}", f"Fact {i}", summary="lorem ipsum " * 40, source_pointers=[{"system": "doc", "i": i}]) for i in range(6)]
    apply(session, world, ops, embedder=embedder)
    r = GraphReader(session, world.tenant.id, None)
    hits = [(r.node_by_key("fact", f"f{i}").id, 1.0 - i / 10) for i in range(6)]
    out = run_query(session, world.tenant.id, visible_scopes(session, world.admin),
                    QueryRequest(question="fact", policy="search", start_hits=hits, limits={"max_tokens": 300}), embedder=embedder,
                    principal_id=world.admin.id)
    assert out["budget"]["used"]["tokens"] <= 300 and out["status"] == "incomplete" and out["stopping_reason"] == "budget:max_tokens"


def test_aggregates_are_routed_to_the_database(session, world, embedder):
    apply(session, world, [node("order", f"o{i}", f"Widget order {i}") for i in range(3)], embedder=embedder)
    out = run_query(session, world.tenant.id, visible_scopes(session, world.admin), QueryRequest(question="How many widget orders are there?"),
                    embedder=embedder, principal_id=world.admin.id)
    assert out["status"] == "routed" and out["aggregate"]["matching_records_by_type"].get("order") == 3


# ------------------------------------------------------------------------------------------------ change rules
def test_delay_exposes_only_when_stock_slack_and_alternatives_do_not_cover(session, world, embedder):
    supply_world(session, world, embedder, stock=0)
    ev, summ = delay(session, world)
    imp = impacts_of(session, ev)
    r = GraphReader(session, world.tenant.id, None)
    m1, p1, t1 = r.node_by_key("milestone", "m1"), r.node_by_key("project", "p1"), r.node_by_key("task", "t1")
    assert (m1.id, "at_risk") in imp and (p1.id, "at_risk") in imp and (t1.id, "needs_review") in imp
    assert imp[(m1.id, "at_risk")].details["shortfall"] == 10


def test_stock_covers_the_delay(session, world, embedder):
    supply_world(session, world, embedder, stock=15)
    ev, _ = delay(session, world)
    imp = impacts_of(session, ev)
    m1 = GraphReader(session, world.tenant.id, None).node_by_key("milestone", "m1")
    assert (m1.id, "covered") in imp and not any(k[1] == "at_risk" for k in imp), "covered: nothing downstream is affected"


def test_slack_absorbs_a_short_delay(session, world, embedder):
    supply_world(session, world, embedder, stock=0, slack=10)
    ev, _ = delay(session, world, date="2026-11-20")  # 5 days late, 10 days slack
    assert not impacts_of(session, ev)


def test_cycles_terminate_and_multiple_paths_do_not_duplicate(session, world, embedder):
    extra = [node("order", "o2", "Order Two", project_keys=["p1"], source_pointers=[{"system": "erp", "record": "o2"}],
                  attrs={"product": "widget", "supplier": "s1", "qty": 5, "promised_date": "2026-11-02", "status": "open", "source_system": "erp"}),
             edge(("order", "o2"), "depends_on", ("supplier", "s1")), edge(("milestone", "m1"), "depends_on", ("order", "o2")),
             node("task", "t2", "Task Two", attrs={"status": "open"}),
             edge(("task", "t1"), "blocks", ("task", "t2")), edge(("task", "t2"), "blocks", ("task", "t1")),
             edge(("milestone", "m1"), "depends_on", ("project", "p1"))]  # a cycle through the project too
    supply_world(session, world, embedder, stock=0, extra_ops=extra)
    ev, summ = delay(session, world)
    imp = impacts_of(session, ev)
    r = GraphReader(session, world.tenant.id, None)
    m1 = r.node_by_key("milestone", "m1")
    assert sum(1 for k in imp if k[0] == m1.id) == 1, "two late orders, one assessment"
    # the milestone is unverified tracker data (grade 0.7); a second late order adds a path, not confidence
    assert imp[(m1.id, "at_risk")].confidence == 0.7, "extra paths do not raise the grade"
    sugg = session.query(RemSuggestion).filter(RemSuggestion.tenant_id == world.tenant.id).all()
    assert len(sugg) == len({s.dedupe_key for s in sugg}) == 1
    # the same delay again under a new key re-evaluates but creates no second task
    delay(session, world, date="2026-12-02")
    assert session.query(RemSuggestion).filter(RemSuggestion.tenant_id == world.tenant.id).count() == 1
    out = run_query(session, world.tenant.id, visible_scopes(session, world.admin),
                    QueryRequest(question="task", policy="traversal", start_hits=[(r.node_by_key("task", "t1").id, 1.0)]),
                    embedder=embedder, principal_id=world.admin.id)
    assert out["status"] == "complete" and len({e["id"] for e in out["entities"]}) == len(out["entities"])


def test_new_evidence_supersedes_the_assessment(session, world, embedder):
    supply_world(session, world, embedder, stock=0)
    ev1, _ = delay(session, world)
    ev2, _ = apply(session, world, [
        node("order", "alt", "Alternative order", project_keys=["p1"], source_pointers=[{"system": "erp", "record": "alt"}],
             attrs={"product": "widget", "supplier": "s2", "qty": 10, "promised_date": "2026-11-10", "status": "open", "source_system": "erp"}),
        edge(("milestone", "m1"), "depends_on", ("order", "alt"))])
    r = GraphReader(session, world.tenant.id, None)
    current, tasks = visible_impacts(session, r)
    m1 = r.node_by_key("milestone", "m1")
    assert [i["impact"] for i in current if i["target"]["id"] == str(m1.id) and i["rule"] == "R1"] == ["covered"]
    assert not any(i["impact"] == "at_risk" for i in current) and not tasks
    old, _ = visible_impacts(session, GraphReader(session, world.tenant.id, None, seq=ev1.seq))
    assert any(i["impact"] == "at_risk" for i in old), "the earlier snapshot still shows what was believed then"


def test_unblock_contract_change_and_deletion(session, world, embedder):
    _, _ = apply(session, world, [
        node("task", "a", "Task A", attrs={"status": "open"}), node("task", "b", "Task B", attrs={"status": "open"}),
        node("task", "c", "Task C", attrs={"status": "open"}),
        edge(("task", "a"), "blocks", ("task", "c")), edge(("task", "b"), "blocks", ("task", "c")),
        node("contract", "k", "Contract K", source_pointers=[{"system": "contract_repository"}], attrs={"term": "12 months"}),
        node("milestone", "m", "Milestone M"), edge(("milestone", "m"), "governed_by", ("contract", "k")),
        node("order", "o", "Order O", source_pointers=[{"system": "erp"}]),
        node("artifact", "sum", "Summary of O", authoritative=False, attrs={"source_system": "generated"}),
        edge(("artifact", "sum"), "derived_from", ("order", "o")), edge(("milestone", "m"), "depends_on", ("order", "o"))],
        embedder=embedder)
    r = lambda: GraphReader(session, world.tenant.id, None)  # noqa: E731
    ev, _ = submit_event(session, world.tenant.id, kind="task_status", payload={"task": "a", "status": "done"}, idempotency_key="a-done")
    process_event(session, ev.id)
    assert not impacts_of(session, ev), "C is still blocked by B"
    ev, _ = submit_event(session, world.tenant.id, kind="task_status", payload={"task": "b", "status": "done"}, idempotency_key="b-done")
    process_event(session, ev.id)
    assert (r().node_by_key("task", "c").id, "unblocked") in impacts_of(session, ev)
    ev, _ = apply(session, world, [{"op": "revise_node", "ref": ["contract", "k"], "attrs": {"term": "6 months"}}])
    assert (r().node_by_key("milestone", "m").id, "needs_review") in impacts_of(session, ev)
    ev, _ = apply(session, world, [{"op": "delete_node", "ref": ["order", "o"]}])
    imp = impacts_of(session, ev)
    assert (r().node_by_key("milestone", "m").id, "needs_review") in imp and (r().node_by_key("artifact", "sum").id, "invalidated") in imp
    assert r().node_by_key("artifact", "sum").review_status == "invalidated"


def test_revocation_invalidates_summaries_and_cached_results(session, world, embedder):
    apply(session, world, [node("fact", "x", "Budget figure X", scope="Finance", source_pointers=[{"system": "erp"}]),
                           node("artifact", "digest", "Finance digest", scope="Finance", authoritative=False,
                                attrs={"source_system": "generated"}),
                           edge(("artifact", "digest"), "derived_from", ("fact", "x"))], embedder=embedder)
    x = GraphReader(session, world.tenant.id, None).node_by_key("fact", "x")
    out = run_query(session, world.tenant.id, visible_scopes(session, world.outsider),
                    QueryRequest(question="budget", policy="traversal", start_hits=[(x.id, 1.0)]), embedder=embedder,
                    principal_id=world.outsider.id)
    assert any(e["key"] == "x" for e in out["entities"])
    assert any(h["kind"] == "generated_summary" for h in out["hypotheses"]) and not any(f["node"]["key"] == "digest" for f in out["facts"])
    ev, summ = submit_event(session, world.tenant.id, kind="restrict", payload={"ref": ["fact", "x"], "scope": "Legal", "sensitivity": 2},
                            idempotency_key="restrict-x")
    process_event(session, ev.id)
    assert (GraphReader(session, world.tenant.id, None).node_by_key("artifact", "digest").id, "invalidated") in impacts_of(session, ev)
    row = session.get(RemResult, uuid.UUID(out["result_id"]))
    assert row.stale and "changed" in row.stale_reason
    now_visible = {str(k) for k in GraphReader(session, world.tenant.id, visible_scopes(session, world.outsider)).nodes(
        [uuid.UUID(i) for i in requires_of(row.output)])}
    filtered = redact(row.output, now_visible)
    assert not any(e["key"] == "x" for e in filtered["entities"]), "stored results are re-filtered with current permissions"


# ------------------------------------------------------------------------------------------------ events
def test_events_are_idempotent(session, world, embedder):
    supply_world(session, world, embedder, stock=0)
    ev1, s1 = delay(session, world, key="delay-1")
    n = session.query(RemImpact).count()
    ev2, created = submit_event(session, world.tenant.id, kind="supplier_delay", payload={"supplier": "s1", "new_date": "2026-12-01"},
                                idempotency_key="delay-1")
    assert ev2.id == ev1.id and not created
    assert process_event(session, ev1.id) == s1 and session.query(RemImpact).count() == n, "a processed event is never applied twice"
    with pytest.raises(IdempotencyConflict):
        submit_event(session, world.tenant.id, kind="supplier_delay", payload={"supplier": "s1", "new_date": "2027-01-01"},
                     idempotency_key="delay-1")


def test_reachability_baseline_marks_everything_connected(session, world, embedder):
    supply_world(session, world, embedder, stock=15)
    ev, _ = submit_event(session, world.tenant.id, kind="supplier_delay", payload={"supplier": "s1", "new_date": "2026-12-01"},
                         idempotency_key="baseline")
    summary = process_event(session, ev.id, policy="reachability")
    keys = {key_of(session, world, i.target_id) for i in session.query(RemImpact).filter(RemImpact.event_id == ev.id)}
    assert {"m1", "p1", "t1"} <= keys and summary["policy"] == "reachability", "the baseline flags covered work too"


# ------------------------------------------------------------------------------------------------ demonstration
def test_supplier_delay_demonstration(session, vault, embedder):
    from cie.eval import rem_demo

    res = rem_demo.run(session, vault, embedder)
    failed = {k: v for k, v in res["checks"].items() if not v["ok"]}
    assert not failed, failed


# ------------------------------------------------------------------------------------------------ HTTP
def test_rem_api(session, world, embedder):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key
    from cie.core.settings import Settings, get_settings

    keys = {p: secrets.token_urlsafe(12) for p in ("admin", "outsider", "analyst")}
    for p, k in keys.items():
        getattr(world, p).api_key_hash = hash_key(k)
    supply_world(session, world, embedder, stock=0, extra_ops=[
        node("requirement", "pen", "Penalty clause 7", scope="Legal", sensitivity=2, source_pointers=[{"system": "contract_repository"}],
             attrs={"kind": "late_delivery_penalty"}), edge(("milestone", "m1"), "governed_by", ("requirement", "pen"))])
    session.commit()
    c = TestClient(app)
    h = {p: {"X-API-Key": k} for p, k in keys.items()}
    r = c.post("/api/rem/query", headers=h["admin"], json={"question": "Milestone One widget"})
    assert r.status_code == 200 and r.json()["policy"] == "traversal", "the conventional traversal is the default"
    assert c.post("/api/rem/query", headers=h["admin"], json={"question": "widget", "policy": "rem"}).status_code == 400
    app.dependency_overrides[get_settings] = lambda: Settings(rem_policy_enabled=True)
    try:
        r = c.post("/api/rem/query", headers=h["admin"], json={"question": "Milestone One widget", "limits": {"max_tokens": 500}})
        assert r.status_code == 200 and r.json()["policy"] == "rem"
    finally:
        app.dependency_overrides.clear()
    result_id = r.json()["result_id"]
    body = {"kind": "supplier_delay", "payload": {"supplier": "s1", "new_date": "2026-12-01"}, "idempotency_key": "api-delay", "wait": True}
    ev = c.post("/api/rem/changes", headers=h["admin"], json=body)
    assert ev.status_code == 202 and ev.json()["created"], ev.text
    again = c.post("/api/rem/changes", headers=h["admin"], json=body).json()
    assert again["event_id"] == ev.json()["event_id"] and not again["created"]
    conflict = c.post("/api/rem/changes", headers=h["admin"], json={**body, "payload": {"supplier": "s1", "new_date": "2027-02-01"}})
    assert conflict.status_code == 409
    queued = c.post("/api/rem/changes", headers=h["admin"], json={**body, "idempotency_key": "api-delay-2", "wait": False}).json()
    assert queued["job_id"] and queued["status"] == "queued"
    eid = ev.json()["event_id"]
    full = c.get(f"/api/rem/impacts/{eid}", headers=h["admin"]).json()
    assert {i["impact"] for i in full["impacts"]} >= {"at_risk", "needs_review"}
    assert any(t["capability"] == "finance" for t in full["suggested_tasks"])
    hidden = c.get(f"/api/rem/impacts/{eid}", headers=h["outsider"]).json()
    assert "Penalty" not in str(hidden) and not any(t["capability"] in ("finance", "legal") for t in hidden["suggested_tasks"])
    assert c.get(f"/api/rem/explanations/{result_id}", headers=h["outsider"]).status_code == 403
    exp = c.get(f"/api/rem/explanations/{result_id}", headers=h["admin"]).json()
    assert exp["stale"] and exp["reproduce"]["body"]["snapshot_seq"] == exp["snapshot_seq"] and exp["trace"]["exploration"]
    blocked = c.post("/api/rem/changes", headers=h["outsider"], json={"kind": "ops", "idempotency_key": "x", "wait": True,
                                                                     "payload": {"ops": [node("task", "evil", scope="Legal")]}})
    assert blocked.status_code == 403
