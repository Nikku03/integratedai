"""Decision authority per agent, task constraints, and re-planning when no option meets them."""

from __future__ import annotations

import json
import secrets

import pytest

from cie.agents.head import HeadAgent, create_project
from cie.agents.providers import FakeProvider
from cie.agents.registry import ensure_default_agents
from cie.core.models import Approval, TaskStatus
from cie.workflow import engine
from cie.workflow.models import TaskOutput

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}
BUDGET = {"output": "option", "field": "cost_usd", "op": "le", "value": 12000,
          "flex": {"up_to": 15000, "approver": "finance", "authority": "spend_usd"}}


@pytest.fixture
def proj(session, world):
    return create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")


@pytest.fixture
def agents(session, world):
    return ensure_default_agents(session, world.tenant.id, world.company)


def running(session, world, proj, agents, role, title="t", **kw):
    t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id, task_type=role, title=title, **kw)
    engine.accept(session, t, actor="test")
    return engine.claim_task(session, t.id, worker="w", agent_id=agents[role].id if role in agents else None)


def spend(amount):
    return {**GOOD, "decisions": [{"kind": "spend_usd", "amount": amount, "subject": "expedited freight"}],
            "outputs": {"answer": {"approved": True, "usd": amount}}}


def test_a_decision_within_authority_stands(session, world, proj, agents):
    assert agents["finance"].config["authority"] == {"spend_usd": 5000}
    t = running(session, world, proj, agents, "finance", acceptance={"outputs": ["answer"]})
    engine.submit(session, t.id, worker="w", result=spend(2000))
    assert t.status == S.completed and t.verification["authorised"][0] == {
        "kind": "spend_usd", "amount": 2000.0, "subject": "expedited freight", "agent": "finance", "limit": 5000}


@pytest.mark.parametrize("approve", [True, False])
def test_above_authority_a_person_decides_and_the_answer_waits(session, world, proj, agents, approve):
    ops = running(session, world, proj, agents, "operations", "Find a delivery option")
    req = engine.request_work(session, ops.id, worker="w", task_type="finance", title="Approve $8,000 of expediting")
    engine.decide_request(session, req.id, decision="accept", actor="head")
    engine.claim_task(session, req.id, worker="fin", agent_id=agents["finance"].id)
    engine.submit(session, req.id, worker="fin", result=spend(8000))
    assert req.status == S.review and engine.awaiting_person(req) and "above its authority of 5000" in req.verification["authority"][0]["why"]
    assert session.query(TaskOutput).filter_by(task_id=req.id).count() == 0, "the answer is held"
    assert ops.status == S.blocked
    a = session.query(Approval).filter_by(kind="task_result", subject_id=str(req.id)).one()
    assert "above its authority" in a.summary
    engine.review(session, req.id, reviewer="user:cfo", verdict="passed" if approve else "failed", notes="cfo decision")
    if approve:
        assert req.status == S.completed and ops.status == S.ready
        assert session.query(TaskOutput).filter_by(task_id=req.id, key="answer").one().value == {"approved": True, "usd": 8000}
    else:
        assert req.status == S.failed and ops.status == S.ready and ops.progress["requests"][0]["status"] == "failed"


def test_a_worker_with_no_authority_cannot_decide_alone(session, world, proj, agents):
    t = running(session, world, proj, agents, "legal")
    engine.submit(session, t.id, worker="w", result=spend(10))
    assert engine.awaiting_person(t) and "with no authority" in t.verification["authority"][0]["why"]


def test_constraints_are_checked_on_release_and_submission(session, world, proj, agents):
    t = running(session, world, proj, agents, "operations", acceptance={"outputs": ["option"], "constraints": [BUDGET]})
    with pytest.raises(ValueError, match="breaks the task's constraints"):
        engine.publish_output(session, t.id, worker="w", key="option", value={"cost_usd": 14000})
    engine.submit(session, t.id, worker="w", result={**GOOD, "outputs": {"option": {"cost_usd": 14000}}})
    assert t.status == S.running and "cost_usd le 12000 is broken (it is 14000)" in t.progress["changes_requested"]["notes"]
    engine.submit(session, t.id, worker="w", result={**GOOD, "outputs": {"option": {"cost_usd": 11000}}})
    assert t.status == S.completed


def test_no_option_meets_the_constraints_the_head_relaxes_within_authority(session, world, proj, agents):
    t = running(session, world, proj, agents, "operations", acceptance={"outputs": ["option"], "constraints": [BUDGET]})
    engine.submit(session, t.id, worker="w", result={**GOOD, "infeasible": {"reason": "every carrier is above budget",
                                                                            "best": {"option": {"cost_usd": 14000, "carrier": "air"}}}})
    assert t.status == S.review and t.verification["awaiting"] == "head"
    assert t.verification["infeasible"]["violates"] == ["option.cost_usd le 12000 is broken (it is 14000)"]
    head = HeadAgent(session, proj)
    # finance may approve up to 5,000: relaxing a budget to 14,000 is beyond it, so a person decides
    assert head.replan() == [(t, "sent to a person")] and engine.awaiting_person(t)
    a = session.query(Approval).filter_by(kind="replan", subject_id=str(t.id)).one()
    assert "beyond the authority of finance" in a.summary
    engine.resolve_infeasible(session, t.id, decision="relax", actor="user:coo", reason="budget raised",
                              constraints=[{**BUDGET, "value": 15000}])
    assert t.status == S.running and t.acceptance["constraints"][0]["value"] == 15000 and a.status == "resolved"
    # with enough authority, the head relaxes the budget itself and takes the best option
    agents["finance"].config = {"authority": {"spend_usd": 20000}}
    engine.submit(session, t.id, worker="w", result={**GOOD, "infeasible": {"reason": "still no carrier under 15,000",
                                                                            "best": {"option": {"cost_usd": 14500}}}})
    engine.resolve_infeasible(session, t.id, decision="relax", actor="user:coo", constraints=[BUDGET])  # back to 12,000 with flex
    engine.submit(session, t.id, worker="w", result={**GOOD, "infeasible": {"reason": "no carrier under 12,000",
                                                                            "best": {"option": {"cost_usd": 14500}}}})
    assert head.replan() == [(t, "relaxed within authority")]
    assert t.status == S.completed and t.acceptance["constraints"][0]["value"] == 14500
    assert t.acceptance["constraints"][0]["relaxed_from"] == 12000
    assert session.query(TaskOutput).filter_by(task_id=t.id, key="option").one().value == {"cost_usd": 14500}


def test_a_person_accepts_the_best_option_or_drops_the_task(session, world, proj, agents):
    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    ts = []
    for _ in range(2):
        t = running(session, world, proj, agents, "operations", acceptance={"outputs": ["option"], "constraints": [{**BUDGET, "flex": {}}]})
        engine.submit(session, t.id, worker="w", result={**GOOD, "infeasible": {"reason": "no", "best": {"option": {"cost_usd": 13000}}}})
        ts.append(t)
    HeadAgent(session, proj).replan()
    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c, h = TestClient(app), {"X-API-Key": k}
    for t, approve in zip(ts, (True, False), strict=True):
        a = session.query(Approval).filter_by(kind="replan", subject_id=str(t.id)).one()
        assert c.post(f"/api/approvals/{a.id}/decide", headers=h, json={"approve": approve, "reason": "call made"}).status_code == 200
        session.expire_all()
    accepted, dropped = (session.get(type(ts[0]), t.id) for t in ts)
    assert accepted.status == S.completed and accepted.verification["overridden_constraints"]
    assert dropped.status == S.failed
    r = c.put(f"/api/agents/{agents['legal'].id}/authority", headers=h, json={"authority": {"approve_terms": True}, "actions": ["send_email"]})
    assert r.json()["authority"] == {"approve_terms": True} and r.json()["actions"] == ["send_email"]


def test_the_head_holds_an_answer_above_authority_until_a_person_approves(session, world, proj, agents, vault, embedder):
    from datetime import UTC, datetime

    from cie.extraction.pipeline import run_extraction
    from tests.fixtures import CONTRACT_SECTIONS, make_pdf
    from tests.test_requests import OnePlan

    doc = vault.ingest(session, tenant_id=world.tenant.id, data=make_pdf(CONTRACT_SECTIONS), filename="msa.pdf", scope_id=proj.scope_id,
                       doc_type="contract", file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)

    def model(system, user):
        if "operations specialist" in system:
            if "approved" in user:
                return json.dumps({"summary": "book it", "findings": []})
            return json.dumps({"summary": "needs $8,000", "findings": [], "requests": [{"role": "finance", "title": "Approve $8,000", "wait": True}]})
        return json.dumps({"summary": "approved", "findings": [], "decisions": [{"kind": "spend_usd", "amount": 8000, "subject": "freight"}]})

    head = HeadAgent(session, proj, embedder=embedder, provider=FakeProvider(model), planner=OnePlan("operations", "Delivery", "fees"))
    (ops,) = head.start("Delivery by Friday")
    head.run(max_steps=10)
    fin = session.query(type(ops)).filter_by(parent_id=ops.id).one()
    assert engine.awaiting_person(fin) and ops.status == S.blocked, "the head waits for the person, and does not loop"
    engine.review(session, fin.id, reviewer="user:cfo", verdict="passed", notes="approved")
    head.run(max_steps=10)
    assert fin.status == S.completed and ops.status == S.completed and ops.result["summary"] == "book it"
