"""Context builder: permissions first, channels within a budget, a cursor, task inputs; exhaustive coverage."""

from __future__ import annotations

import uuid

import pytest

from cie.context import builder as B
from cie.context import checks
from cie.context.builder import ContextRequest, build_context
from cie.context.models import ContextRun
from cie.state.events import process_event, submit_event
from cie.state.store import NodeView

pytestmark = pytest.mark.db


def apply(session, world, ops):
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=uuid.uuid4().hex)
    return process_event(session, ev.id)


def node(t, key, scope="Acme", **kw):
    return {"op": "upsert_node", "type": t, "key": key, "name": kw.pop("name", key.upper()), "scope": scope, **kw}


def nv(**attrs):
    return NodeView(id=uuid.uuid4(), type="order", key="k", version=1, name="n", summary="", attrs=attrs, project_ids=[], department_ids=[],
                    scope_id=uuid.uuid4(), sensitivity=1, source_pointers=[], root_sources=[], verification="unverified", authoritative=True,
                    valid_from=None, valid_to=None, recorded_at=None, review_status=None, sys_from=1)


def test_checks_are_deterministic_and_honest_about_missing_values():
    late = {"field": "promised_date", "op": "gt", "value": "2026-10-15"}
    assert checks.evaluate(late, nv(promised_date="2026-10-20")) is True
    assert checks.evaluate(late, nv(promised_date="2026-10-01")) is False
    with pytest.raises(checks.Unreadable):
        checks.evaluate(late, nv(status="open"))
    with pytest.raises(checks.Unreadable):
        checks.evaluate(late, nv(promised_date="soon"))
    assert checks.evaluate({"field": "qty", "op": "ge", "value": 10}, nv(qty="12")) is True
    assert checks.evaluate({"all": [late, {"field": "status", "op": "in", "value": ["open", "confirmed"]}]},
                           nv(promised_date="2026-11-01", status="open")) is True
    assert checks.evaluate({"any": [late, {"field": "status", "op": "eq", "value": "open"}]}, nv(status="open")) is True
    assert checks.evaluate({"not": {"field": "owner", "op": "exists"}}, nv()) is True
    assert checks.evaluate({"field": "status", "op": "eq", "value": "open"}, nv(status=3)) is False
    with pytest.raises(ValueError):
        checks.validate({"field": "x", "op": "like"})


def test_budget_follows_the_model():
    assert B.budget_for_model("claude-sonnet") == 50_000
    assert B.budget_for_model("llama3:8b") == 2048
    assert B.budget_for_model("llama3.1:70b") == 32_000
    assert B.budget_for_model(None) == 8000


@pytest.fixture
def supply(session, world, embedder):
    ops = [node("project", "pa", name="Project A"), node("supplier", "s1", name="Northwind Supplies"),
           node("milestone", "m1", name="Project A delivery milestone", project_keys=["pa"], attrs={"due_date": "2026-10-15", "status": "planned"},
                source_pointers=[{"system": "project_tracker", "record": "M1"}]),
           node("order", "o1", name="Order 1 steel beams for Project A", project_keys=["pa"], source_pointers=[{"system": "erp", "record": "PO-1"}],
                attrs={"promised_date": "2026-10-01", "status": "open", "source_system": "erp", "qty": 10}),
           node("order", "o2", name="Order 2 cables for Project A", project_keys=["pa"], source_pointers=[{"system": "erp", "record": "PO-2"}],
                attrs={"promised_date": "2026-10-20", "status": "open", "source_system": "erp", "qty": 5}),
           node("order", "o3", name="Order 3 secret prototype", scope="Legal", sensitivity=3, project_keys=["pa"],
                source_pointers=[{"system": "erp", "record": "PO-3"}], attrs={"promised_date": "2026-12-01"}),
           node("order", "o4", name="Order 4 unscheduled", project_keys=["pa"], attrs={"status": "open"}),
           {"op": "upsert_edge", "src": ["milestone", "m1"], "kind": "depends_on", "dst": ["order", "o1"]},
           {"op": "upsert_edge", "src": ["milestone", "m1"], "kind": "depends_on", "dst": ["order", "o2"]},
           {"op": "upsert_edge", "src": ["milestone", "m1"], "kind": "depends_on", "dst": ["order", "o3"]},
           {"op": "upsert_edge", "src": ["order", "o1"], "kind": "depends_on", "dst": ["supplier", "s1"]},
           {"op": "observe", "ref": ["order", "o1"], "field": "promised_date", "value": "2026-10-25", "source": {"system": "mail", "kind": "email"}}]
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key="supply")
    process_event(session, ev.id, embedder=embedder)


def test_focused_context_and_the_change_loop(session, world, embedder, supply):
    from cie.agents.head import create_project
    from cie.workflow import engine

    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="operations", title="Can Project A deliver by October 15?"), actor="test")
    engine.claim_task(session, t.id, worker="w")
    ctx = build_context(session, world.tenant.id, world.admin,
                        ContextRequest(question="Project A delivery milestone orders", task_id=t.id, entities=[["order", "o1"], ["milestone", "m1"]],
                                       project_keys=["pa"], budget_tokens=20_000), embedder=embedder)
    d = ctx.data
    assert {e["entity_id"] for e in d["entities"]} == {"order:o1", "milestone:m1"}
    assert d["unresolved"] and d["unresolved"][0]["field"] == "promised_date", "the email's disagreement travels with the context"
    assert d["state_evidence"] and d["sources"]["traversal"]["evidence"] >= 1
    assert d["complete"] and d["cursor"] is None and d["inputs_recorded"] >= 2
    assert session.get(ContextRun, ctx.run_id).task_id == t.id
    # the loop: a change to a record in the context flags the running task, and it cannot complete on the old value
    s = apply(session, world, [{"op": "observe", "ref": ["order", "o1"], "field": "promised_date", "value": "2026-10-18",
                                "source": {"system": "erp"}}])
    assert str(t.id) in s["tasks"]["flagged"]
    engine.submit(session, t.id, worker="w", result={"findings": []})
    assert t.status.value == "running" and t.progress["changes_requested"]["details"]["stale_inputs"]


def test_permissions_come_first(session, world, embedder, supply):
    from cie.core.models import Permission, Principal, PrincipalKind
    from cie.governance.permissions import ensure_role, grant_role

    p = Principal(tenant_id=world.tenant.id, kind=PrincipalKind.user, name="ops-reader", attributes={})
    session.add(p)
    session.flush()
    grant_role(session, tenant_id=world.tenant.id, principal=p, role=ensure_role(session, world.tenant.id, "reader", Permission.read, 2),
               scope=world.company)
    session.flush()
    ctx = build_context(session, world.tenant.id, p, ContextRequest(question="Project A orders secret prototype",
                                                                    entities=[["order", "o3"], ["order", "o2"]], budget_tokens=20_000),
                        embedder=embedder)
    text = str({k: v for k, v in ctx.data.items() if k != "question"})
    assert "secret prototype" not in text and "o3" not in {e["key"] for e in ctx.data["entities"]}
    assert ctx.data["sources"]["structured"] == {"requested": 2, "visible": 1, "returned": 1}


def test_budget_and_cursor(session, world, embedder, supply):
    first = build_context(session, world.tenant.id, world.admin, ContextRequest(entities=[["order", k] for k in ("o1", "o2", "o4")],
                                                                                channels=("structured",), budget_tokens=500), embedder=embedder).data
    assert not first["complete"] and first["cursor"] and len(first["entities"]) < 3
    got = [e["entity_id"] for e in first["entities"]]
    cur = first["cursor"]
    while cur:
        nxt = build_context(session, world.tenant.id, world.admin, ContextRequest(entities=[["order", k] for k in ("o1", "o2", "o4")],
                                                                                  channels=("structured",), budget_tokens=500, cursor=cur),
                            embedder=embedder).data
        got += [e["entity_id"] for e in nxt["entities"]]
        cur = nxt["cursor"]
    assert got == ["order:o1", "order:o2", "order:o4"], "every item once, in order"
    with pytest.raises(ValueError):
        build_context(session, world.tenant.id, world.admin, ContextRequest(entities=[], cursor="garbage!"), embedder=embedder)


def test_exhaustive_mode_records_coverage(session, world, embedder, supply, monkeypatch):
    late = {"field": "promised_date", "op": "gt", "value": "2026-10-15"}
    req = ContextRequest(mode="exhaustive", collection={"type": "order", "project_key": "pa"}, check=late)
    d = build_context(session, world.tenant.id, world.admin, req).data
    cov = d["coverage"]
    assert (cov["visible_records"], cov["scanned"], cov["matched"], cov["unreadable"], cov["complete"]) == (4, 4, 2, 1, True)
    assert {m["entity_id"] for m in d["matches"]} == {"order:o2", "order:o3"}
    assert d["unreadable_records"][0]["entity_id"] == "order:o4"
    # a requester who may not see the Legal order: it is neither scanned nor counted
    from cie.core.models import Permission, Principal, PrincipalKind
    from cie.governance.permissions import ensure_role, grant_role

    p = Principal(tenant_id=world.tenant.id, kind=PrincipalKind.user, name="ops", attributes={})
    session.add(p)
    session.flush()
    grant_role(session, tenant_id=world.tenant.id, principal=p, role=ensure_role(session, world.tenant.id, "reader", Permission.read, 2),
               scope=world.company)
    session.flush()
    cov = build_context(session, world.tenant.id, p, req).data["coverage"]
    assert (cov["visible_records"], cov["scanned"], cov["matched"]) == (3, 3, 1)
    # listing pages; the scan is never truncated
    monkeypatch.setattr(B, "MAX_LISTED", 1)
    page = build_context(session, world.tenant.id, world.admin, req).data
    assert page["coverage"]["matched"] == 2 and len(page["matches"]) == 1 and page["listed"]["more"]
    page2 = build_context(session, world.tenant.id, world.admin, ContextRequest(**{**req.__dict__, "cursor": page["cursor"]})).data
    assert {page["matches"][0]["entity_id"], page2["matches"][0]["entity_id"]} == {"order:o2", "order:o3"} and not page2["listed"]["more"]
    with pytest.raises(ValueError):
        build_context(session, world.tenant.id, world.admin, ContextRequest(mode="exhaustive", collection={}))


def test_context_api(session, world, embedder, supply):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    keys = {p: secrets.token_urlsafe(12) for p in ("admin", "analyst")}
    for p, k in keys.items():
        getattr(world, p).api_key_hash = hash_key(k)
    session.commit()
    c = TestClient(app)
    h = {p: {"X-API-Key": k} for p, k in keys.items()}
    r = c.post("/api/context", headers=h["admin"], json={"mode": "exhaustive", "collection": {"type": "order"},
                                                         "check": {"field": "status", "op": "eq", "value": "open"}})
    assert r.status_code == 200 and r.json()["coverage"]["matched"] == 3
    run = r.json()["context_run_id"]
    assert c.get(f"/api/context/runs/{run}", headers=h["admin"]).json()["coverage"]["complete"] is True
    assert c.get(f"/api/context/runs/{run}", headers=h["analyst"]).status_code == 404
    r = c.post("/api/context", headers=h["analyst"], json={"mode": "exhaustive", "collection": {"type": "order"}})
    cov = r.json()["coverage"]
    assert (cov["visible_records"], cov["scanned"], cov["complete"]) == (0, 0, True), "company records and a too-sensitive one: none visible"
    assert c.post("/api/context", headers=h["admin"], json={}).status_code == 400
    r = c.post("/api/context", headers=h["admin"], json={"entities": [["order", "o2"]], "question": "cables"})
    assert r.status_code == 200 and r.json()["entities"][0]["entity_id"] == "order:o2"
