"""Agents working on their own (turns), and questions that pause a task until a person answers."""

from __future__ import annotations

import json
import secrets

import pytest

from cie.agents import messages
from cie.agents.head import HeadAgent
from cie.agents.providers import FakeProvider
from cie.agents.runtime import run_agent_turn, run_agents
from cie.core.models import Approval, Job, MessageKind, Task, TaskStatus
from cie.workflow import engine
from tests.test_requests import OnePlan, agents, evidence, proj  # noqa: F401

pytestmark = pytest.mark.db
S = TaskStatus


def reply(**kw):
    return json.dumps({"summary": "", "findings": [], **kw})


def admin_client(session, world):
    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    return TestClient(app), {"X-API-Key": k}


def test_a_blocking_question_pauses_the_task_until_a_person_answers(session, world, proj, agents, evidence, embedder):  # noqa: F811
    def model(system, user):
        if "Yes, charter" in user:
            return reply(summary="charter booked")
        return reply(summary="options found", questions=[{"question": "May we charter a plane?", "wait": True}])

    provider = FakeProvider(model)
    head = HeadAgent(session, proj, embedder=embedder, provider=provider, planner=OnePlan("operations", "Delivery", "fees"))
    (t,) = head.start("Delivery by Friday")
    head.run(max_steps=5)
    assert t.status == S.blocked and "a person's answer to 1 question(s)" in engine.waiting_for(session, [t.id])[t.id]
    a = session.query(Approval).filter_by(kind="question").one()
    c, h = admin_client(session, world)
    assert c.post(f"/api/approvals/{a.id}/decide", headers=h, json={"approve": True, "reason": "Yes, charter"}).status_code == 200
    session.expire_all()
    t = session.get(Task, t.id)
    assert t.status == S.ready and session.query(Job).filter_by(kind="agent_task").count() == 1, "the project's work resumes"
    HeadAgent(session, proj, embedder=embedder, provider=provider).run(max_steps=5)
    assert t.status == S.completed and t.result["summary"] == "charter booked"
    assert [x for s_, x in provider.calls][-1].count("Yes, charter") == 1, "the answer was in its context"


def test_agents_work_on_their_own_and_hand_work_to_each_other(session, world, proj, agents, evidence, embedder):  # noqa: F811
    def model(system, user):
        if "operations specialist" in system:
            if "within_budget" in user:
                return reply(summary="booked within budget")
            return reply(summary="needs a budget check", requests=[{"role": "finance", "title": "Check $2,000 of expediting", "wait": True}])
        return reply(summary="fine", outputs={"answer": {"within_budget": True}})

    ops = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                                task_type="operations", title="Find a delivery option"), actor="test")
    turns = run_agents(session, world.tenant.id, provider=FakeProvider(model), embedder=embedder, log=lambda *a: None)
    fin = session.query(Task).filter_by(parent_id=ops.id).one()
    assert ops.status == S.completed and ops.result["summary"] == "booked within budget" and fin.status == S.completed
    assert [(r["agent"], r["task_id"]) for r in turns] == [("operations", str(ops.id)), ("finance", str(fin.id)), ("operations", str(ops.id))]
    assert ops.assigned_agent_id == agents["operations"].id and fin.assigned_agent_id == agents["finance"].id
    assert run_agent_turn(session, agents["head"])["task_id"] is None, "the head's own work is not taken by turns"


def test_an_answer_after_completion_makes_the_agent_reconsider(session, world, proj, agents, evidence, embedder):  # noqa: F811
    calls = []

    def model(system, user):
        calls.append(user)
        if "Use the 3pm slot" in user:
            return reply(summary="rebooked for 3pm")
        return reply(summary="booked for 9am", questions=["Is the 9am slot fine?"])

    provider = FakeProvider(model)
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="operations", title="Book a slot"), actor="test")
    run_agents(session, world.tenant.id, provider=provider, embedder=embedder, log=lambda *a: None)
    assert t.status == S.completed and t.result["summary"] == "booked for 9am", "a question that does not block"
    a = session.query(Approval).filter_by(kind="question").one()
    c, h = admin_client(session, world)
    c.post(f"/api/approvals/{a.id}/decide", headers=h, json={"approve": True, "reason": "Use the 3pm slot"})
    session.expire_all()
    turns = run_agents(session, world.tenant.id, provider=provider, embedder=embedder, log=lambda *a: None)
    t = session.get(Task, t.id)
    assert turns[0]["reopened"] == [str(t.id)] and t.status == S.completed and t.result["summary"] == "rebooked for 3pm"
    assert messages.inbox(session, agents["operations"], kinds=[MessageKind.answer], unread_only=True) == [], "read once it ran"
