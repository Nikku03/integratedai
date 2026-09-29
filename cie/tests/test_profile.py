"""A task's information profile: trigger fields, the records it is about, past decisions; the head hears of reopenings."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cie.agents import ledger, messages
from cie.agents.head import HeadAgent
from cie.agents.providers import FakeProvider
from cie.core.models import MessageKind, TaskStatus
from cie.workflow import engine
from cie.workflow.models import TaskInvalidation
from tests.test_requests import OnePlan, agents, evidence, proj  # noqa: F401
from tests.test_routing import apply, node, view

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}
WATCH = {"triggers": {"order": ["promised_date", "status"]}}


def watcher(session, world, proj, agents, profile=WATCH):  # noqa: F811
    apply(session, world, "ops", {"ops": [node("order", "o1", promised_date="2026-10-01", qty=10, status="open", source_system="erp")]})
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="operations", title="Delivery date", profile=profile), actor="test")
    engine.claim_task(session, t.id, worker="w", agent_id=agents["operations"].id)
    o1 = view(session, world, "order", "o1")
    engine.record_inputs(session, t, records={o1.id: (o1.version, "order:o1")})
    return t


def revise(session, world, **attrs):
    return apply(session, world, "ops", {"ops": [{"op": "revise_node", "ref": ["order", "o1"], "attrs": attrs}]})


def test_only_the_fields_a_task_watches_reopen_it(session, world, proj, agents):  # noqa: F811
    t = watcher(session, world, proj, agents)
    engine.submit(session, t.id, worker="w", result=GOOD)
    assert t.status == S.completed
    _, s = revise(session, world, qty=12)
    assert t.status == S.completed and not s.get("tasks") and session.query(TaskInvalidation).count() == 0, "qty is not watched"
    _, s = revise(session, world, promised_date="2026-10-20")
    assert t.status == S.ready and s["tasks"]["reopened"] == [str(t.id)]


def test_a_running_task_completes_through_an_unwatched_change(session, world, proj, agents):  # noqa: F811
    t = watcher(session, world, proj, agents)
    revise(session, world, qty=12)
    engine.submit(session, t.id, worker="w", result=GOOD)
    assert t.status == S.completed, "the order moved to a new version, but not in a field the task watches"
    u = watcher(session, world, proj, agents, profile=None)  # no profile: every change matters
    revise(session, world, qty=13)
    engine.submit(session, u.id, worker="w", result=GOOD)
    assert u.status == S.running and "inputs changed" in u.progress["changes_requested"]["notes"]


def test_the_head_hears_of_every_reopened_task(session, world, proj, agents):  # noqa: F811
    proj.head_agent_id = agents["head"].id
    t = watcher(session, world, proj, agents)
    engine.submit(session, t.id, worker="w", result=GOOD)
    revise(session, world, status="late")
    to_head = messages.inbox(session, agents["head"], kinds=[MessageKind.input_changed])
    assert [m.payload["action"] for m in to_head] == ["reopened"] and to_head[0].task_id == t.id
    assert [m.kind for m in messages.inbox(session, agents["operations"], task_id=t.id)] == [MessageKind.input_changed]


def test_records_decisions_period_and_deadline_reach_the_worker(session, world, proj, agents, evidence, embedder):  # noqa: F811
    apply(session, world, "ops", {"ops": [node("order", "po-7", promised_date="2026-10-03", qty=4, status="open", source_system="erp")]})
    ledger.append(session, tenant_id=world.tenant.id, project_id=proj.id, kind="decision",
                  content={"decision": "request accepted", "title": "Check the freight budget"}, actor="head")
    plan = OnePlan("operations", "Delivery", "fees")
    plan.spec.profile = {"entities": [["order", "po-7"]], "period": {"from": "2026-10-01", "to": "2026-10-09"}}
    prompts = []

    def model(system, user):
        prompts.append(user)
        return json.dumps({"summary": "ok", "findings": []})

    head = HeadAgent(session, proj, embedder=embedder, provider=FakeProvider(model), planner=plan)
    deadline = datetime(2026, 10, 9, 17, tzinfo=UTC)
    (t,) = head.start("Delivery by Friday", deadline_at=deadline)
    assert t.deadline_at == deadline
    head.run(max_steps=3)
    p = prompts[0]
    assert "The records this task is about" in p and "2026-10-03" in p, "the order as it is now"
    assert "request accepted: Check the freight budget" in p and "Period: 2026-10-01 to 2026-10-09" in p
    assert t.status == S.completed and t.progress["context"]["records"][0]["entity"] == "order:po-7"
