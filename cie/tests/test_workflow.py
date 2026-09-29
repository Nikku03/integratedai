"""Workflow engine: enforced lifecycle, leases, checkpoints, acceptance, limits, reviews, retries, stale inputs."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cie.agents.head import create_project
from cie.core import db as dbmod
from cie.core.models import Approval, Task, TaskStatus
from cie.workflow import engine
from cie.workflow.engine import LeaseLost, TransitionError

pytestmark = pytest.mark.db
S = TaskStatus


@pytest.fixture
def proj(session, world):
    return create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Workflow")


def new(session, world, proj, title="t", accept=True, **kw):
    t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id, task_type=kw.pop("task_type", "research"),
                       title=title, **kw)
    return engine.accept(session, t, actor="test") if accept else t


GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}


def test_transitions_are_enforced_and_logged(session, world, proj):
    t = new(session, world, proj, accept=False)
    assert t.status == S.proposed
    with pytest.raises(TransitionError):
        engine.transition(session, t, S.running, actor="x")
    with pytest.raises(TransitionError):
        engine.claim_task(session, t.id, worker="w")
    engine.accept(session, t, actor="lead")
    engine.claim_task(session, t.id, worker="w")
    engine.submit(session, t.id, worker="w", result=GOOD)
    assert t.status == S.completed and t.revision == 4
    with pytest.raises(TransitionError):
        engine.retry(session, t.id, authorized_by="lead")
    log = [(r.from_status, r.to_status) for r in engine.transitions(session, t.id)]
    assert log == [("proposed", "proposed"), ("proposed", "ready"), ("ready", "running"), ("running", "review"), ("review", "completed")]


def test_dependencies_block_and_release(session, world, proj):
    a = new(session, world, proj, "a")
    b = new(session, world, proj, "b", depends_on=[(a.id, "requires")])
    c = new(session, world, proj, "c", depends_on=[(a.id, "after")])
    assert b.status == S.blocked and c.status == S.blocked
    engine.claim_task(session, a.id, worker="w")
    engine.fail(session, a.id, actor="w", error="boom")
    engine.refresh(session, project_id=proj.id)
    assert b.status == S.blocked, "requires: the dependency must be completed"
    assert c.status == S.ready, "after: a settled dependency is enough"
    engine.retry(session, a.id, authorized_by=world.admin.id, reason="transient")
    assert a.status == S.ready and a.retry_authorized_by == world.admin.id and a.max_attempts >= 2
    engine.claim_task(session, a.id, worker="w")
    engine.submit(session, a.id, worker="w", result=GOOD)
    assert a.status == S.completed and b.status == S.ready


def test_claims_skip_locked_tasks(session, world, proj):
    new(session, world, proj, "one")
    new(session, world, proj, "two")
    session.commit()
    s1, s2, s3 = (dbmod.session_factory()() for _ in range(3))
    try:
        t1 = engine.claim(s1, world.tenant.id, worker="w1")
        t2 = engine.claim(s2, world.tenant.id, worker="w2")
        t3 = engine.claim(s3, world.tenant.id, worker="w3")
        assert t1 and t2 and t1.id != t2.id and t3 is None, "no task is claimed twice"
    finally:
        for s in (s1, s2, s3):
            s.rollback()
            s.close()


def test_expired_lease_is_reassigned_with_progress(session, world, proj):
    t = new(session, world, proj, max_attempts=2)
    engine.claim_task(session, t.id, worker="w1", lease_seconds=30)
    engine.checkpoint(session, t.id, worker="w1", progress={"pages_read": 40})
    with pytest.raises(LeaseLost):
        engine.heartbeat(session, t.id, worker="w2")
    engine.reclaim_expired(session, at=engine.now() + timedelta(hours=1))
    assert t.status == S.ready and t.progress["pages_read"] == 40 and t.lease_owner is None
    engine.claim_task(session, t.id, worker="w2")
    assert t.attempts == 2 and t.progress["pages_read"] == 40, "the next worker resumes from the checkpoint"
    with pytest.raises(LeaseLost):
        engine.submit(session, t.id, worker="w1", result=GOOD)
    engine.reclaim_expired(session, at=engine.now() + timedelta(hours=1))
    assert t.status == S.failed, "attempts exhausted"


def test_acceptance_limits_and_changes_requested(session, world, proj):
    t = new(session, world, proj, acceptance={"min_findings": 1, "citations_required": True}, limits={"max_cost_usd": 1.0, "tools": ["retrieval"]})
    engine.claim_task(session, t.id, worker="w")
    engine.submit(session, t.id, worker="w", result={"findings": [{"claim": "x", "citations": []}]})
    assert t.status == S.running and t.lease_owner == "w" and "without a citation" in t.progress["changes_requested"]["notes"]
    engine.submit(session, t.id, worker="w", result=GOOD, usage={"cost_usd": 0.2, "tools": ["retrieval"]})
    assert t.status == S.completed
    t2 = new(session, world, proj, limits={"max_cost_usd": 1.0, "tools": ["retrieval"]})
    engine.claim_task(session, t2.id, worker="w")
    engine.submit(session, t2.id, worker="w", result=GOOD, usage={"cost_usd": 3.0, "tools": ["retrieval", "web"]})
    assert t2.status == S.failed and "exceeds the limit" in engine.transitions(session, t2.id)[-1].reason
    assert "web" in engine.transitions(session, t2.id)[-1].reason


def test_review_rounds_then_a_person_decides(session, world, proj):
    a = new(session, world, proj, "risky", risk_level="high")
    dep = new(session, world, proj, "synthesis", task_type="synthesis", depends_on=[(a.id, "after")])
    engine.claim_task(session, a.id, worker="w")
    engine.submit(session, a.id, worker="w", result=GOOD)
    assert a.status == S.review and a.verification["awaiting"] == "agent"
    engine.review(session, a.id, reviewer="verifier", verdict="changes_requested", notes="finding 1 unsupported")
    assert a.status == S.running and a.review_rounds == 1
    engine.submit(session, a.id, worker="w", result=GOOD)
    engine.review(session, a.id, reviewer="verifier", verdict="changes_requested", notes="still unsupported")
    assert a.status == S.review and a.verification["awaiting"] == "human"
    assert session.query(Approval).filter_by(subject_id=str(a.id), status="pending").count() == 1
    engine.refresh(session, project_id=proj.id)
    assert dep.status == S.ready, "the synthesis may report work waiting on a person"
    engine.claim_task(session, dep.id, worker="head")
    engine.record_inputs(session, dep, tasks=[a])
    engine.submit(session, dep.id, worker="head", result={"answer": "a is pending"})
    assert dep.status == S.completed
    engine.review(session, a.id, reviewer="user:admin", verdict="passed", notes="checked by hand")
    assert a.status == S.completed
    assert dep.status == S.ready, "the synthesis reported it as pending; it is reopened now that it is decided"


def test_stale_inputs_block_completion_and_reopen_cascades(session, world, proj):
    from cie.state.events import process_event, submit_event
    from cie.state.store import GraphReader

    ev, _ = submit_event(session, world.tenant.id, kind="ops", idempotency_key="o", payload={"ops": [
        {"op": "upsert_node", "type": "order", "key": "o1", "name": "Order 1", "scope": "Acme", "attrs": {"qty": 1}}]})
    process_event(session, ev.id)
    o1 = GraphReader(session, world.tenant.id, None).node_by_key("order", "o1")
    a = new(session, world, proj, "a")
    b = new(session, world, proj, "b", depends_on=[(a.id, "requires")])
    engine.claim_task(session, a.id, worker="w")
    engine.record_inputs(session, a, records={o1.id: (o1.version, "order:o1")})
    ev, _ = submit_event(session, world.tenant.id, kind="ops", idempotency_key="o2", payload={"ops": [
        {"op": "revise_node", "ref": ["order", "o1"], "attrs": {"qty": 2}}]})
    process_event(session, ev.id)
    engine.submit(session, a.id, worker="w", result=GOOD)
    assert a.status == S.running and a.progress["changes_requested"]["details"]["stale_inputs"][0]["used"] == o1.version
    o1 = GraphReader(session, world.tenant.id, None).node_by_key("order", "o1")
    engine.record_inputs(session, a, records={o1.id: (o1.version, "order:o1")})
    engine.submit(session, a.id, worker="w", result=GOOD)
    assert a.status == S.completed and b.status == S.ready
    engine.claim_task(session, b.id, worker="w")
    engine.record_inputs(session, b, tasks=[a])
    engine.submit(session, b.id, worker="w", result=GOOD)
    changed = engine.reopen(session, a.id, actor="events", reason="order:o1 changed")
    assert a.status == S.ready and b.status == S.blocked and {t.id for t in changed} == {a.id, b.id}
    assert "dependency 'a' was reopened" in b.progress["reopened"]["reason"]
    # a new relationship adds no version to the record, but a task that read it before must not complete on it
    t2 = new(session, world, proj, "stock check")
    engine.claim_task(session, t2.id, worker="w")
    engine.record_inputs(session, t2, records={o1.id: (o1.version, "order:o1")})
    ev, _ = submit_event(session, world.tenant.id, kind="ops", idempotency_key="o3", payload={"ops": [
        {"op": "upsert_node", "type": "product", "key": "p1", "name": "P1", "scope": "Acme"},
        {"op": "upsert_edge", "src": ["order", "o1"], "kind": "depends_on", "dst": ["product", "p1"]}]})
    process_event(session, ev.id)
    engine.submit(session, t2.id, worker="w", result=GOOD)
    assert t2.status == S.running and t2.progress["changes_requested"]["details"]["stale_inputs"][0]["changed_at_seq"]


def test_overdue(session, world, proj):
    t = new(session, world, proj, deadline_at=engine.now() - timedelta(days=1))
    new(session, world, proj, deadline_at=engine.now() + timedelta(days=1))
    assert [x.id for x in engine.overdue(session, world.tenant.id)] == [t.id]


def test_task_api(session, world, proj):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    key = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(key)
    session.commit()
    c = TestClient(app)
    h = {"X-API-Key": key}
    r = c.post("/api/tasks", headers=h, json={"project_id": str(proj.id), "task_type": "research", "title": "Find the fee",
                                               "acceptance": {"min_findings": 1}, "limits": {"tools": ["retrieval"]}})
    assert r.status_code == 200 and r.json()["status"] == "ready"
    tid = r.json()["id"]
    got = c.post("/api/tasks/claim", headers=h, json={"worker": "w1"}).json()
    assert got["id"] == tid and got["status"] == "running"
    assert c.post(f"/api/tasks/{tid}/checkpoint", headers=h, json={"worker": "w1", "progress": {"step": 1}}).json()["progress"]["step"] == 1
    assert c.post(f"/api/tasks/{tid}/heartbeat", headers=h, json={"worker": "w2"}).status_code == 409
    r = c.post(f"/api/tasks/{tid}/submit", headers=h, json={"worker": "w1", "result": {"findings": []}})
    assert r.json()["status"] == "running", "no finding: changes requested"
    r = c.post(f"/api/tasks/{tid}/submit", headers=h, json={"worker": "w1", "result": GOOD, "usage": {"tools": ["retrieval", "shell"]}})
    assert r.json()["status"] == "failed"
    assert c.post(f"/api/tasks/{tid}/review", headers=h, json={"verdict": "passed"}).status_code == 409
    r = c.post(f"/api/tasks/{tid}/retry", headers=h, json={"reason": "tool list fixed"})
    assert r.json()["status"] == "ready"
    trans = c.get(f"/api/tasks/{tid}/transitions", headers=h).json()
    assert [x["to"] for x in trans][-2:] == ["failed", "ready"] and trans[-1]["actor"] == str(world.admin.id)
    assert c.post(f"/api/tasks/{tid}/cancel", headers=h, json={"reason": "no longer needed"}).json()["status"] == "cancelled"
    assert session.get(Task, __import__("uuid").UUID(tid)) is not None
