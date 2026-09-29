"""Outputs released early, output-level dependencies, scheduling, the inbox and automatic continuation."""

from __future__ import annotations

from datetime import timedelta

import pytest

from cie.agents import messages
from cie.agents.head import create_project
from cie.agents.registry import ensure_default_agents
from cie.core.models import AgentMessage, MessageKind, TaskStatus
from cie.workflow import engine
from cie.workflow.models import TaskInput

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}


@pytest.fixture
def proj(session, world):
    return create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")


def new(session, world, proj, title, **kw):
    t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                       task_type=kw.pop("task_type", "operations"), title=title, **kw)
    return engine.accept(session, t, actor="test")


def test_a_released_output_starts_the_tasks_that_need_only_it(session, world, proj):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    logistics = new(session, world, proj, "Find a delivery option before Friday", acceptance={"outputs": ["expedite_cost", "plan"]})
    finance = new(session, world, proj, "Check the budget for expediting", depends_on=[(logistics.id, "requires", ["expedite_cost"])])
    notice = new(session, world, proj, "Tell the customer", depends_on=[(logistics.id, "requires")])
    assert finance.status == S.blocked and notice.status == S.blocked
    assert "expedite_cost (not released yet)" in engine.waiting_for(session, [finance.id])[finance.id][0]
    engine.claim_task(session, logistics.id, worker="lg", agent_id=agents["operations"].id)
    assert [d["output"] for d in engine.deliverables(session, logistics)] == ["expedite_cost", "plan"], "the awaited one first"

    o, changed = engine.publish_output(session, logistics.id, worker="lg", key="expedite_cost", value={"usd": 2000}, summary="air freight")
    assert changed and o.version == 1
    assert finance.status == S.ready and notice.status == S.blocked, "finance can start; the notice waits for the whole plan"
    engine.claim_task(session, finance.id, worker="fin", agent_id=agents["finance"].id)
    up = engine.upstream(session, finance)
    assert up[0]["output"] == "expedite_cost" and up[0]["value"] == {"usd": 2000}
    assert session.get(TaskInput, (finance.id, "output", o.id)).version == 1, "what it used is its input"

    # the same value again disturbs nobody; the finance check completes on it
    assert engine.publish_output(session, logistics.id, worker="lg", key="expedite_cost", value={"usd": 2000})[1] is False
    engine.submit(session, finance.id, worker="fin", result=GOOD)
    assert finance.status == S.completed

    # logistics must release everything it declared before it can complete
    engine.submit(session, logistics.id, worker="lg", result=GOOD)
    assert logistics.status == S.running and "output 'plan' not released" in logistics.progress["changes_requested"]["notes"]
    engine.submit(session, logistics.id, worker="lg", result={**GOOD, "outputs": {"plan": "air freight, arrives Thursday"}})
    assert logistics.status == S.completed and notice.status == S.ready

    # a changed value reopens only the task that used the old one
    engine.reopen(session, logistics.id, actor="test", reason="supplier delay")
    assert finance.status == S.completed, "being revised is not yet a change"
    assert notice.status == S.blocked, "a whole-task dependant waits again"
    engine.claim_task(session, logistics.id, worker="lg")
    o2, changed = engine.publish_output(session, logistics.id, worker="lg", key="expedite_cost", value={"usd": 2600})
    assert changed and o2.version == 2 and finance.status == S.ready and "expedite_cost changed" in finance.progress["reopened"]["reason"]
    kinds = [m.payload.get("status") for m in messages.inbox(session, agents["finance"], unread_only=True)
             if m.kind == MessageKind.dependency_notification]
    assert kinds == ["revised"], "at the first release finance had no agent yet (it reads the value in its context when it starts)"


def test_a_reopened_task_must_re_release_and_unchanged_values_disturb_nobody(session, world, proj):
    p = new(session, world, proj, "Producer")
    used = new(session, world, proj, "Used it", depends_on=[(p.id, "requires", ["cost"])])
    later = new(session, world, proj, "Not started", depends_on=[(p.id, "requires", ["cost"])])
    engine.claim_task(session, p.id, worker="p")
    engine.publish_output(session, p.id, worker="p", key="cost", value=10)
    engine.claim_task(session, used.id, worker="u")
    engine.upstream(session, used)
    engine.submit(session, used.id, worker="u", result=GOOD)
    engine.submit(session, p.id, worker="p", result=GOOD)
    assert p.status == used.status == S.completed and later.status == S.ready
    engine.reopen(session, p.id, actor="test", reason="an input changed")
    assert later.status == S.blocked and "cost (being revised)" in engine.waiting_for(session, [later.id])[later.id][0]
    engine.claim_task(session, p.id, worker="p")
    engine.submit(session, p.id, worker="p", result=GOOD)
    assert p.status == S.running and "not re-released since the task was reopened" in p.progress["changes_requested"]["notes"]
    engine.publish_output(session, p.id, worker="p", key="cost", value=10)
    assert later.status == S.ready and used.status == S.completed, "same value: the task that used it is not redone"
    engine.submit(session, p.id, worker="p", result=GOOD)
    assert p.status == S.completed


def test_a_running_consumer_of_a_changed_value_cannot_complete_on_it(session, world, proj):
    p = new(session, world, proj, "Producer")
    c = new(session, world, proj, "Consumer", depends_on=[(p.id, "requires", ["cost"])])
    engine.claim_task(session, p.id, worker="p")
    engine.publish_output(session, p.id, worker="p", key="cost", value=10)
    engine.claim_task(session, c.id, worker="c")
    engine.upstream(session, c)
    engine.publish_output(session, p.id, worker="p", key="cost", value=12)
    assert c.progress["stale_inputs"][-1]["to_version"] == 2
    engine.submit(session, c.id, worker="c", result=GOOD)
    assert c.status == S.running and "inputs changed" in c.progress["changes_requested"]["notes"]
    engine.upstream(session, c)  # it reads the new value
    engine.submit(session, c.id, worker="c", result=GOOD)
    assert c.status == S.completed


def test_schedule_runs_first_what_meets_deadlines_and_unblocks_the_most(session, world, proj):
    at = engine.now()
    free = new(session, world, proj, "Nothing waits on it", metrics={"estimate_seconds": 60})
    head_of_chain = new(session, world, proj, "Three tasks wait on it", metrics={"estimate_seconds": 60})
    mid = new(session, world, proj, "mid", depends_on=[(head_of_chain.id, "requires")], metrics={"estimate_seconds": 600})
    new(session, world, proj, "end", depends_on=[(mid.id, "requires")], metrics={"estimate_seconds": 600})
    new(session, world, proj, "side", depends_on=[(head_of_chain.id, "requires", ["x"])], metrics={"estimate_seconds": 60})
    urgent = new(session, world, proj, "Due in an hour", deadline_at=at + timedelta(hours=1), metrics={"estimate_seconds": 1800})
    order = engine.schedule(session, tenant_id=world.tenant.id, project_id=proj.id, at=at)
    assert [t.title for t, _ in order] == ["Due in an hour", "Three tasks wait on it", "Nothing waits on it"]
    assert order[0][1]["slack_s"] == 1800.0 and order[1][1]["unblocks"] == 3 and order[1][1]["critical_path_s"] == 1260.0
    top = new(session, world, proj, "Explicit priority", priority=1)
    assert engine.schedule(session, tenant_id=world.tenant.id, project_id=proj.id, at=at)[0][0].id == top.id, "priority comes first"
    got = engine.claim(session, world.tenant.id, worker="w", project_id=proj.id, at=at)
    assert got.id == top.id and engine.transitions(session, got.id)[-1].details["schedule"]["rank"] == 1
    got = engine.claim(session, world.tenant.id, worker="w", project_id=proj.id, at=at)
    assert got.id == urgent.id
    assert engine.claim(session, world.tenant.id, worker="w", project_id=proj.id, order="fifo").id == free.id, "fifo: oldest first"


def test_inbox_read_status(session, world, proj):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    t = new(session, world, proj, "t")
    m = messages.send(session, tenant_id=world.tenant.id, project_id=proj.id, kind=MessageKind.failure_report, task_id=t.id,
                      to_agent=agents["finance"], payload={"task_id": str(t.id), "error": "x"})
    assert [x.id for x in messages.inbox(session, agents["finance"], unread_only=True)] == [m.id]
    assert messages.mark_read(session, agents["legal"], [m.id]) == 0, "only the recipient marks its messages"
    assert messages.mark_read(session, agents["finance"], [m.id]) == 1 and messages.mark_read(session, agents["finance"], [m.id]) == 0
    assert messages.inbox(session, agents["finance"], unread_only=True) == [] and session.get(AgentMessage, m.id).read_at is not None


def test_a_change_that_reopens_tasks_queues_their_project_once(session, world, proj):
    from cie.core.models import Job
    from cie.workers.worker import resume_projects

    t = new(session, world, proj, "t")
    summary = {"tasks": {"reopened": [str(t.id)]}}
    assert resume_projects(session, world.tenant.id, summary) == [proj.id]
    assert resume_projects(session, world.tenant.id, summary) == [], "already queued"
    job = session.query(Job).filter_by(kind="agent_task").one()
    assert job.payload["project_id"] == str(proj.id) and "objective" not in job.payload


def test_outputs_api(session, world, proj):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    ensure_default_agents(session, world.tenant.id, world.company)
    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c, h = TestClient(app), {"X-API-Key": k}
    a = c.post("/api/tasks", headers=h, json={"project_id": str(proj.id), "task_type": "operations", "title": "Logistics",
                                               "estimate_seconds": 3600}).json()
    b = c.post("/api/tasks", headers=h, json={"project_id": str(proj.id), "task_type": "finance", "title": "Budget",
                                               "depends_on": [{"task_id": a["id"], "outputs": ["cost"]}]}).json()
    assert b["status"] == "blocked" and b["dependency_outputs"] == {a["id"]: ["cost"]}
    assert [x["title"] for x in c.get(f"/api/projects/{proj.id}/schedule", headers=h).json()] == ["Logistics"]
    c.post(f"/api/tasks/{a['id']}/claim", headers=h, json={"worker": "w"})
    r = c.post(f"/api/tasks/{a['id']}/outputs", headers=h, json={"worker": "w", "key": "cost", "value": 2000}).json()
    assert r == {"key": "cost", "version": 1, "changed": True, "status": "current"}
    assert c.get(f"/api/tasks/{b['id']}", headers=h).json()["status"] == "ready"
    out = c.get(f"/api/tasks/{b['id']}/outputs", headers=h).json()
    assert out["upstream"][0]["value"] == 2000
    assert c.post(f"/api/tasks/{a['id']}/outputs", headers=h, json={"worker": "other", "key": "cost", "value": 1}).status_code == 409
    r = c.get("/api/messages/inbox", headers=h, params={"agent": "finance"})
    assert r.status_code == 200 and r.json() == [], "an administrator reads any inbox (finance was never assigned here)"
    assert c.get("/api/messages/inbox", headers=h, params={"agent": "nobody"}).status_code == 404
    from cie.core.models import Principal

    legal_key = secrets.token_urlsafe(12)
    session.get(Principal, ensure_default_agents(session, world.tenant.id, world.company)["legal"].principal_id).api_key_hash = hash_key(legal_key)
    session.commit()
    lh = {"X-API-Key": legal_key}
    assert c.get("/api/messages/inbox", headers=lh, params={"agent": "finance"}).status_code == 403, "not another agent's inbox"
    assert c.get("/api/messages/inbox", headers=lh, params={"agent": "legal"}).status_code == 200
