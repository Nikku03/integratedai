"""Domain events and routing of state changes to the tasks that used the changed records."""

from __future__ import annotations

import uuid

import pytest

from cie.agents.head import create_project
from cie.agents.registry import ensure_default_agents
from cie.core.models import AgentMessage, MessageKind, TaskStatus
from cie.state.events import process_event, submit_event
from cie.state.store import GraphReader
from cie.workflow import engine
from cie.workflow.models import TaskInvalidation

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}


def apply(session, world, kind, payload, key=None, principal=None):
    ev, _ = submit_event(session, world.tenant.id, kind=kind, payload=payload, idempotency_key=key or uuid.uuid4().hex,
                         principal_id=principal.id if principal else None)
    return ev, process_event(session, ev.id)


def node(t, key, **attrs):
    return {"op": "upsert_node", "type": t, "key": key, "name": key.upper(), "scope": "Acme", "attrs": attrs}


def view(session, world, t, key):
    return GraphReader(session, world.tenant.id, None).node_by_key(t, key)


@pytest.fixture
def books(session, world):
    apply(session, world, "ops", {"ops": [node("invoice", "inv7", amount=1000, status="issued", source_system="erp"),
                                          node("order", "o1", promised_date="2026-10-01", status="open", source_system="erp")]})


def pay(amount, version=None, record="PAY-1"):
    return {"type": "payment.confirmed", "entity": ["invoice", "inv7"], "source": {"system": "bank", "record": record, "kind": "system_of_record"},
            "occurred_at": "2026-09-28T10:00:00Z", "data": {"amount": amount}, **({"version": version} if version is not None else {})}


def test_payment_confirmed(session, world, books):
    v = view(session, world, "invoice", "inv7").version
    ev, s = apply(session, world, "domain", pay(400, version=v))
    inv = view(session, world, "invoice", "inv7")
    assert ev.status == "done" and inv.attrs["status"] == "partially_paid" and inv.attrs["amount_paid"] == 400
    ev, s = apply(session, world, "domain", pay(1000, version=v, record="PAY-2"))
    assert ev.status == "conflict", "the sender saw an older version: the event is refused whole"
    assert view(session, world, "invoice", "inv7").attrs["amount_paid"] == 400
    ev, s = apply(session, world, "domain", {**pay(1000, record="PAY-2"), "data": {"amount_paid_total": 1000}})
    assert view(session, world, "invoice", "inv7").attrs["status"] == "paid"
    with pytest.raises(ValueError, match="is about an invoice"):
        apply(session, world, "domain", {**pay(1), "entity": ["order", "o1"]})
    with pytest.raises(ValueError, match="unknown domain event type"):
        apply(session, world, "domain", {**pay(1), "type": "payment.teleported"})


def test_delivery_date_from_a_weaker_source_is_a_conflict(session, world, books):
    ev, s = apply(session, world, "domain", {"type": "delivery.date_changed", "entity": ["order", "o1"], "occurred_at": "2026-09-20",
                                             "source": {"system": "supplier_mail", "kind": "email"}, "data": {"new_date": "2026-10-20"}})
    assert s["field_decisions"][0]["status"] == "conflict" and view(session, world, "order", "o1").attrs["promised_date"] == "2026-10-01"
    ev, s = apply(session, world, "domain", {"type": "delivery.date_changed", "entity": ["order", "o1"], "occurred_at": "2026-09-21",
                                             "source": {"system": "erp"}, "data": {"new_date": "2026-10-20"}})
    assert view(session, world, "order", "o1").attrs["promised_date"] == "2026-10-20"


def test_changes_reopen_completed_tasks_once(session, world, books):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Routing")
    o1 = view(session, world, "order", "o1")

    def task(title, **kw):
        t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id, task_type="operations", title=title, **kw)
        return engine.accept(session, t, actor="test")

    a, run, later = task("delivery plan"), task("cost check"), task("not started")
    b = task("customer notice", depends_on=[(a.id, "requires")])
    for t in (a, run):
        engine.claim_task(session, t.id, worker="w", agent_id=agents["operations"].id)
        engine.record_inputs(session, t, records={o1.id: (o1.version, "order:o1")})
    engine.record_inputs(session, later, records={o1.id: (o1.version, "order:o1")})
    engine.submit(session, a.id, worker="w", result=GOOD)
    engine.claim_task(session, b.id, worker="w")
    engine.record_inputs(session, b, tasks=[a])
    engine.submit(session, b.id, worker="w", result=GOOD)
    assert a.status == b.status == S.completed and run.status == S.running
    ev, s = apply(session, world, "domain", {"type": "delivery.date_changed", "entity": ["order", "o1"], "source": {"system": "erp"},
                                             "data": {"new_date": "2026-11-15"}})
    assert s["tasks"] == {"reopened": [str(a.id)], "flagged": [str(run.id)], "noted": [str(later.id)]}
    assert a.status == S.ready and b.status == S.blocked, "the dependant that required it waits again"
    assert run.progress["stale_inputs"][0]["label"] == "order:o1"
    engine.submit(session, run.id, worker="w", result=GOOD)
    assert run.status == S.running and "inputs changed" in run.progress["changes_requested"]["notes"], "never completed on old values"
    from cie.workflow.models import TaskInput

    assert session.query(TaskInput).filter_by(task_id=run.id, ref_kind="record").count() == 0, "the old reads no longer count"
    engine.record_inputs(session, run, records={o1.id: (view(session, world, "order", "o1").version, "order:o1")})  # it reads again
    msgs = session.query(AgentMessage).filter_by(kind=MessageKind.input_changed).all()
    assert {m.task_id for m in msgs} == {a.id, run.id} and all("promised_date" not in str(m.payload) for m in msgs), "ids, not values"
    # the same change delivered again does nothing; a later change is handled once more
    from cie.state.events import ChangeSet
    from cie.workflow.routing import route_to_tasks

    again = route_to_tasks(session, ChangeSet(event=ev, seq=ev.seq, ops=[], prev=None, changed={o1.id: ["attrs.promised_date"]},
                                              deleted=[], restricted=[]))
    assert again == {} and session.query(TaskInvalidation).filter_by(task_id=a.id).count() == 1, "the same change: handled once"
    # a change that adds no version (a new relationship) still reaches the tasks that read the record before it
    engine.claim_task(session, a.id, worker="w")
    engine.record_inputs(session, a, records={o1.id: (view(session, world, "order", "o1").version, "order:o1")})
    engine.submit(session, a.id, worker="w", result=GOOD)
    assert a.status == S.completed
    apply(session, world, "ops", {"ops": [node("supplier", "s9"), {"op": "upsert_edge", "src": ["order", "o1"], "kind": "depends_on",
                                                                  "dst": ["supplier", "s9"]}]})
    assert a.status == S.ready and "relationships or stock" in a.progress["reopened"]["reason"]
    ev2, s2 = apply(session, world, "ops", {"ops": [{"op": "delete_node", "ref": ["order", "o1"]}]})
    inv = session.query(TaskInvalidation).filter_by(task_id=run.id, to_version=0).one()
    assert inv.action == "flagged" and str(run.id) in s2["tasks"]["flagged"]


def test_domain_event_api(session, world, books):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c = TestClient(app)
    h = {"X-API-Key": k}
    r = c.post("/api/state/domain-events", headers=h, json=pay(1000))
    assert r.status_code == 202 and r.json()["created"] is True and r.json()["status"] == "done"
    r2 = c.post("/api/state/domain-events", headers=h, json=pay(1000))
    assert r2.json()["created"] is False and r2.json()["event_id"] == r.json()["event_id"], "same source record: applied once"
    v = c.get("/api/state/entities/invoice/inv7", headers=h).json()
    assert v["status"] == "paid" and v["facts"]["amount_paid"]["statement"]["source"]["system"] == "bank"
    stale = {**pay(5, record="PAY-9"), "version": 1}
    assert c.post("/api/state/domain-events", headers=h, json=stale).status_code == 409
    assert c.post("/api/state/domain-events", headers=h, json={**pay(5), "source": {"system": "bank"}}).status_code == 400


def test_inputs_are_what_the_findings_rely_on(session, world, books):
    """inputs="relied": the context records nothing; the result's state references and calculation inputs become
    the inputs, read at the context's snapshot. A change to an uncited record reopens nothing; a cited one does."""
    from cie.context.builder import ContextRequest, build_context
    from cie.workflow.models import TaskInput

    apply(session, world, "ops", {"ops": [node("project", "pa", budget=100), node("order", "o2", qty=3, unit_price=10, status="open",
                                                                                  source_system="erp")]})
    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Relied")
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="operations", title="Order 2 cost"), actor="test")
    engine.claim_task(session, t.id, worker="w")
    ctx = build_context(session, world.tenant.id, world.admin, ContextRequest(entities=[["order", "o1"], ["order", "o2"], ["project", "pa"]],
                                                                             task_id=t.id, channels=("structured",), inputs="relied")).data
    assert ctx["inputs_recorded"] == 0 and session.query(TaskInput).filter_by(task_id=t.id).count() == 0
    pa = view(session, world, "project", "pa")
    result = {"summary": "cost", "findings": [
        {"claim": "Order 2 costs 30", "value": 30, "citations": [{"item_id": "1"}],
         "calculation": {"expression": "q * p", "inputs": {"q": {"ref": ["order", "o2"], "field": "qty"},
                                                           "p": {"ref": ["order", "o2"], "field": "unit_price"}}}},
        {"claim": "within the budget", "value": True, "state_refs": [{"ref": str(pa.id), "version": pa.version}]}]}
    # a change between reading the context and submitting is caught: the inputs are judged at the context's snapshot
    apply(session, world, "ops", {"ops": [{"op": "revise_node", "ref": ["order", "o2"], "attrs": {"qty": 4}}]})
    engine.submit(session, t.id, worker="w", result=result)
    assert t.status == S.running and t.progress["changes_requested"]["details"]["stale_inputs"][0]["label"] == "order:o2"
    build_context(session, world.tenant.id, world.admin, ContextRequest(entities=[["order", "o2"], ["project", "pa"]], task_id=t.id,
                                                                       channels=("structured",), inputs="relied"))
    result["findings"][0]["value"] = 40
    engine.submit(session, t.id, worker="w", result=result)
    assert t.status == S.completed
    got = {i.label: i.version for i in session.query(TaskInput).filter_by(task_id=t.id, ref_kind="record")}
    assert got == {"order:o2": view(session, world, "order", "o2").version, "project:pa": pa.version}, "o1 was read but not relied on"
    _, s = apply(session, world, "ops", {"ops": [{"op": "revise_node", "ref": ["order", "o1"], "attrs": {"qty": 9}}]})
    assert t.status == S.completed and not s.get("tasks"), "an uncited record changed: nothing to redo"
    # a new order joining the project changes the project, so an answer about the project is refreshed
    _, s = apply(session, world, "ops", {"ops": [node("order", "o3", qty=1, status="open") | {"project_keys": ["pa"]}]})
    assert t.status == S.ready and str(t.id) in s["tasks"]["reopened"]
