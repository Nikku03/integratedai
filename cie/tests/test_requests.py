"""Agents ask each other for work, and act on their inbox: evidence rounds, questions to a person, answers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.agents import messages
from cie.agents.head import HeadAgent, create_project
from cie.agents.planner import TaskSpec
from cie.agents.providers import FakeProvider
from cie.agents.registry import ensure_default_agents
from cie.core.models import AgentMessage, Approval, MessageKind, TaskDependency, TaskStatus
from cie.workflow import engine

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}


@pytest.fixture
def proj(session, world):
    return create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")


@pytest.fixture
def agents(session, world):
    return ensure_default_agents(session, world.tenant.id, world.company)


def new(session, world, proj, title, **kw):
    t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                       task_type=kw.pop("task_type", "operations"), title=title, **kw)
    return engine.accept(session, t, actor="test")


def running(session, world, proj, agents, title="Find a delivery option before Friday", role="operations"):
    t = new(session, world, proj, title, task_type=role)
    return engine.claim_task(session, t.id, worker="w", agent_id=agents[role].id)


def test_the_requester_waits_for_the_answer_and_reads_it(session, world, proj, agents):
    lg = running(session, world, proj, agents)
    r = engine.request_work(session, lg.id, worker="w", task_type="finance", title="Check the budget for $2,000 of expediting",
                            agent_name="operations")
    assert r.status == S.proposed and r.parent_id == lg.id and r.metrics["depth"] == 1
    assert lg.status == S.blocked and lg.progress["requests"][0]["status"] == "proposed", "it steps aside, progress kept"
    engine.decide_request(session, r.id, decision="accept", actor="head")
    assert r.status == S.ready and lg.status == S.blocked
    engine.claim_task(session, r.id, worker="fin", agent_id=agents["finance"].id)
    engine.submit(session, r.id, worker="fin", result=GOOD)
    assert r.status == S.running and "output 'answer' not released" in r.progress["changes_requested"]["notes"], "a request must answer"
    engine.submit(session, r.id, worker="fin", result={**GOOD, "outputs": {"answer": {"approved": True, "within": 12000}}})
    assert r.status == S.completed and lg.status == S.ready and lg.progress["requests"][0]["status"] == "completed"
    engine.claim_task(session, lg.id, worker="w")
    assert engine.upstream(session, lg)[0]["value"] == {"approved": True, "within": 12000}
    engine.submit(session, lg.id, worker="w", result=GOOD)
    assert lg.status == S.completed


@pytest.mark.parametrize("end", ["decline", "fail"])
def test_a_declined_or_failed_request_releases_the_requester(session, world, proj, agents, end):
    lg = running(session, world, proj, agents)
    r = engine.request_work(session, lg.id, worker="w", task_type="finance", title="Check the budget", agent_name="operations")
    if end == "decline":
        engine.decide_request(session, r.id, decision="decline", actor="head", reason="no budget questions this week")
    else:
        engine.decide_request(session, r.id, decision="accept", actor="head")
        engine.claim_task(session, r.id, worker="fin")
        engine.fail(session, r.id, actor="fin", error="the ledger is unavailable")
    assert lg.status == S.ready and session.get(TaskDependency, (lg.id, r.id)) is None, "it no longer waits"
    note = lg.progress["requests"][0]
    assert note["status"] == ("cancelled" if end == "decline" else "failed") and note["reason"]
    told = messages.inbox(session, agents["operations"], unread_only=True)
    assert [m.kind for m in told] == [MessageKind.work_decision] and told[0].payload["request_task_id"] == str(r.id)


def test_merge_and_limits(session, world, proj, agents):
    a = running(session, world, proj, agents, "Plan A")
    b = running(session, world, proj, agents, "Plan B")
    ra = engine.request_work(session, a.id, worker="w", task_type="finance", title="Check the expediting budget")
    engine.decide_request(session, ra.id, decision="accept", actor="head")
    rb = engine.request_work(session, b.id, worker="w", task_type="finance", title="Check the expediting budget")
    engine.decide_request(session, rb.id, decision="merge", actor="head", into=ra.id)
    assert rb.status == S.cancelled and session.get(TaskDependency, (b.id, ra.id)).outputs == ["answer"], "B waits for A's request"
    assert b.status == S.blocked
    # at most REQUEST_MAX_PER_TASK requests per task, and REQUEST_MAX_DEPTH deep
    c = running(session, world, proj, agents, "Plan C")
    for n in range(engine.REQUEST_MAX_PER_TASK):
        engine.request_work(session, c.id, worker="w", task_type="legal", title=f"question {n}", wait=False)
    with pytest.raises(ValueError, match="at most"):
        engine.request_work(session, c.id, worker="w", task_type="legal", title="one more", wait=False)
    cur = running(session, world, proj, agents, "Plan D")
    for depth in range(1, engine.REQUEST_MAX_DEPTH + 1):
        r = engine.request_work(session, cur.id, worker="w", task_type="finance", title=f"level {depth}", wait=False)
        engine.decide_request(session, r.id, decision="accept", actor="head")
        cur = engine.claim_task(session, r.id, worker="w")
    with pytest.raises(ValueError, match="deep"):
        engine.request_work(session, cur.id, worker="w", task_type="legal", title="too deep")


# ------------------------------------------------------------------------------------------ the head, end to end
@pytest.fixture
def evidence(session, world, vault, embedder, proj):
    from cie.extraction.pipeline import run_extraction
    from tests.fixtures import CONTRACT_SECTIONS, make_pdf

    doc = vault.ingest(session, tenant_id=world.tenant.id, data=make_pdf(CONTRACT_SECTIONS), filename="msa.pdf", scope_id=proj.scope_id,
                       doc_type="contract", file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    session.commit()
    return doc


class OnePlan:
    name = "one_task"

    def __init__(self, role, title, query):
        self.spec = TaskSpec("t", role, title, "Stay within $12,000.", risk_level="low", priority=3, query=query)

    def plan(self, objective, forced_specialists=None):
        return [self.spec]


def reply(**kw):
    return json.dumps({"summary": "", "findings": [], **kw})


def test_a_specialist_asks_another_waits_and_finishes_with_the_answer(session, world, proj, agents, evidence, embedder):
    def model(system, user):
        if "operations specialist" in system:
            if "within_budget" in user:  # finance's answer was handed over
                return reply(summary="Book the expedited freight: finance confirmed it is within budget")
            return reply(summary="Expedited freight costs $2,000 more", requests=[
                {"role": "finance", "title": "Check the budget for $2,000 of expedited freight", "brief": "Budget $12,000", "wait": True},
                {"role": "operations", "title": "not to itself", "wait": True}])
        if "finance specialist" in system:
            return reply(summary="Within budget", outputs={"answer": {"within_budget": True, "remaining": 10000}})
        return reply()

    provider = FakeProvider(model)
    head = HeadAgent(session, proj, embedder=embedder, provider=provider, planner=OnePlan("operations", "Find a delivery option", "fees"))
    (ops,) = head.start("Get the supplier delivery here by Friday within $12,000")
    head.run(max_steps=10)
    session.commit()
    fin = session.query(type(ops)).filter_by(parent_id=ops.id).one()
    assert fin.task_type == "finance" and fin.status == S.completed and fin.metrics["requested_by"] == "operations"
    assert ops.status == S.completed and "within budget" in ops.result["summary"]
    assert [r.to_status for r in engine.transitions(session, ops.id)] == [
        "proposed", "ready", "running", "blocked", "ready", "running", "review", "completed"]
    assert ops.progress["requests"] == [{"task_id": str(fin.id), "task_type": "finance", "title": fin.title, "wait": True,
                                         "status": "completed", "decision": "accept", "reason": "", "by": "head"}]
    kinds = [(m.kind, m.payload.get("decision") or m.payload.get("status")) for m in
             session.query(AgentMessage).filter_by(task_id=ops.id).order_by(AgentMessage.created_at)]
    assert (MessageKind.work_request, None) in kinds and (MessageKind.work_decision, "accepted") in kinds
    assert (MessageKind.dependency_notification, "released") in kinds, "operations was told when the answer arrived"
    second = [u for s_, u in provider.calls if "operations specialist" in s_][1]
    assert "Messages for this task" in second and "work_decision" in second and "Work you already asked" in second
    assert messages.inbox(session, agents["operations"], task_id=ops.id, unread_only=True) == [], "delivered and read"


def test_an_agent_that_needs_more_evidence_gets_another_round(session, world, proj, agents, evidence, embedder):
    prompts = []

    def model(system, user):
        prompts.append(user)
        if len(prompts) == 1:
            return reply(summary="need the notice terms", evidence_requests=["termination notice period days"])
        return reply(summary="done")

    agents["legal"].model = "llama3"  # an 8k window: its first packet holds only part of the contract
    head = HeadAgent(session, proj, embedder=embedder, provider=FakeProvider(model),
                     planner=OnePlan("legal", "Check the payment terms", "monthly fee invoice"))
    (t,) = head.start("Review the contract")
    head.run(max_steps=5)
    asked = session.query(AgentMessage).filter_by(task_id=t.id, kind=MessageKind.evidence_request).one()
    assert asked.payload["query"] == "termination notice period days" and t.progress["evidence_round"] == 1
    assert asked.payload["found"] > 0 and len(prompts) == 2, "re-run with the new evidence"
    assert prompts[1].count("<untrusted_document") > prompts[0].count("<untrusted_document")
    assert t.status == S.completed and t.result["summary"] == "done"


def test_a_question_goes_to_a_person_and_the_answer_to_the_agent(session, world, proj, agents, evidence, embedder):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    def model(system, user):
        return reply(summary="options found", questions=["May we pay for air freight?"])

    head = HeadAgent(session, proj, embedder=embedder, provider=FakeProvider(model), planner=OnePlan("operations", "Options", "fees"))
    (t,) = head.start("Delivery")
    head.run(max_steps=5)
    a = session.query(Approval).filter_by(kind="question").one()
    assert "May we pay for air freight?" in a.summary and a.requested_by == "operations"
    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c = TestClient(app)
    assert c.post(f"/api/approvals/{a.id}/decide", headers={"X-API-Key": k}, json={"approve": True, "reason": "Yes, up to $3,000"}).status_code == 200
    ans = messages.inbox(session, agents["operations"], kinds=[MessageKind.answer], unread_only=True)
    assert ans[0].payload["answer"] == "Yes, up to $3,000" and ans[0].payload["question"] == "May we pay for air freight?"
    assert ans[0].task_id == t.id


def test_requests_api(session, world, proj, agents):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key
    from cie.core.models import Job

    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c, h = TestClient(app), {"X-API-Key": k}
    t = c.post("/api/tasks", headers=h, json={"project_id": str(proj.id), "task_type": "operations", "title": "Logistics"}).json()
    c.post(f"/api/tasks/{t['id']}/claim", headers=h, json={"worker": "w"})
    r = c.post(f"/api/tasks/{t['id']}/requests", headers=h, json={"worker": "w", "task_type": "finance", "title": "Budget check"})
    assert r.status_code == 200 and r.json()["status"] == "proposed" and r.json()["acceptance"] == {"outputs": ["answer"]}
    assert c.get(f"/api/tasks/{t['id']}", headers=h).json()["status"] == "blocked"
    assert session.query(Job).filter_by(kind="agent_task").count() == 1, "a head run is queued to decide it"
    d = c.post(f"/api/tasks/{r.json()['id']}/request-decision", headers=h, json={"decision": "decline", "reason": "not now"}).json()
    assert d["status"] == "cancelled" and c.get(f"/api/tasks/{t['id']}", headers=h).json()["status"] == "ready"
    assert c.post(f"/api/tasks/{t['id']}/request-decision", headers=h, json={"decision": "accept"}).status_code == 409, "not a request"
