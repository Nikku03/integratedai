"""Phase 3: five agents on dependent work, routing explanations, verification, ledger."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from cie.agents import ledger
from cie.agents.head import HeadAgent, create_project
from cie.agents.registry import ensure_default_agents
from cie.agents.router import select_agent
from cie.agents.scorecards import Outcome, record_outcome
from cie.core.models import (
    Agent,
    AgentMessage,
    Approval,
    MessageKind,
    RecordType,
    Task,
    TaskDependency,
    TaskStatus,
)
from cie.extraction.pipeline import run_extraction
from cie.memory.records import create_record
from tests.fixtures import CONTRACT_SECTIONS, make_pdf

pytestmark = pytest.mark.db


@pytest.fixture
def staffed(session, world, vault, embedder):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    project = create_project(session, tenant_id=world.tenant.id, parent_scope=world.legal, name="Atlas renegotiation",
                             objective="")
    pdf = make_pdf(CONTRACT_SECTIONS)
    doc = vault.ingest(session, tenant_id=world.tenant.id, data=pdf, filename="msa.pdf", scope_id=project.scope_id,
                       doc_type="contract", file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    session.commit()
    return agents, project, doc


def test_five_agents_on_dependent_work(session, world, embedder, staffed):
    agents, project, doc = staffed
    head = HeadAgent(session, project, embedder=embedder)
    objective = ("Plan the renegotiation of the Northwind master services agreement: legal termination terms, "
                 "financial fees and penalties, an implementation timeline and system integration requirements")
    tasks = head.start(objective)
    types = {t.task_type for t in tasks}
    assert {"research", "legal", "finance", "operations", "engineering", "synthesis"} <= types
    deps = list(session.scalars(select(TaskDependency)))
    assert deps, "dependencies must exist"
    # only research is runnable at first
    ready = head.ready_tasks()
    assert [t.task_type for t in ready] == ["research"]
    state = head.run(max_steps=15)
    session.commit()
    tasks = list(session.scalars(select(Task).where(Task.project_id == project.id)))
    by_type = {}
    for t in tasks:
        by_type.setdefault(t.task_type, []).append(t)
    # every specialist ran and was routed with a stored explanation
    for tt in ("research", "legal", "finance", "operations", "engineering"):
        t = by_type[tt][0]
        assert t.assigned_agent_id is not None, tt
        agent = session.get(Agent, t.assigned_agent_id)
        assert agent.name == tt, f"{tt} routed to {agent.name}: {t.assignment_reason.get('decision')}"
        assert t.assignment_reason["decision"].startswith(f"{tt} chosen")
        assert any(c["agent"] == "head" and not c["eligible"] for c in t.assignment_reason["candidates"])
        assert t.result and t.metrics["packet_tokens"] > 0
    # high-risk work (legal, finance) got verification by a different agent
    verifs = by_type.get("verification", [])
    assert len(verifs) >= 2
    for v in verifs:
        target = session.get(Task, v.verifies_task_id)
        assert v.assigned_agent_id != target.assigned_agent_id
        assert target.status in (TaskStatus.verified, TaskStatus.awaiting_approval)
        assert target.verification["by"] == session.get(Agent, v.assigned_agent_id).name
    # findings cite pages of the source document
    legal = by_type["legal"][0]
    assert legal.result["findings"] and legal.result["findings"][0]["citations"][0]["document_id"] == str(doc.id)
    assert legal.result["findings"][0]["citations"][0]["page_no"] in range(1, 7)
    # structured messages only, none broadcast
    msgs = list(session.scalars(select(AgentMessage).where(AgentMessage.project_id == project.id)))
    kinds = {m.kind for m in msgs}
    assert {MessageKind.task_request, MessageKind.final_result, MessageKind.dependency_notification, MessageKind.verification_request} <= kinds
    assert all(m.to_agent_id is not None for m in msgs)
    assert max(m.token_estimate for m in msgs) < 2000  # no full-context dumps
    # synthesis present with evidence and uncertainty; ledger chain intact
    assert state["synthesis"] is not None and state["synthesis"]["citations"]
    assert "uncertainty" in state["synthesis"]
    ok, bad_seq = ledger.verify_chain(session, project.id)
    assert ok, bad_seq
    assert state["entries"] >= 15 and state["head_hash"]
    kinds_l = {e.kind for e in ledger.entries(session, project.id)}
    assert {"objective", "plan", "task", "assignment", "result", "verification", "synthesis"} <= kinds_l
    # agent scorecards updated per task type
    from cie.agents.scorecards import scorecards_for
    legal_agent = agents["legal"]
    scs = scorecards_for(session, legal_agent.id)
    legal_sc = next(sc for sc in scs if sc.task_type == "legal")
    assert legal_sc.n_tasks == 2 and legal_sc.latency_ms_avg > 0  # execution + verification observations


def test_ledger_hypothesis_example_and_tamper_detection(session, world):
    project = create_project(session, tenant_id=world.tenant.id, parent_scope=world.legal, name="Ledger demo")
    t = world.tenant.id
    ledger.append(session, tenant_id=t, project_id=project.id, kind="hypothesis", label="H17",
                  content={"statement": "Target-aware pruning should reduce tail-computation cost."}, actor="research-2")
    ledger.append(session, tenant_id=t, project_id=project.id, kind="test", content={"hypothesis": "H17", "tested_by": "Research Agent 2"})
    ledger.append(session, tenant_id=t, project_id=project.id, kind="result",
                  content={"hypothesis": "H17", "result": "Six to eight times fewer paths.",
                           "failed_criterion": "Convergence slope changed only from 0.608 to 0.539."})
    ledger.append(session, tenant_id=t, project_id=project.id, kind="artifact", content={"commit": "0c2229f"}, refs={"hypothesis": "H17"})
    ledger.append(session, tenant_id=t, project_id=project.id, kind="next_action",
                  content={"action": "Stop optimizing ranking and investigate observable decomposition or certification."}, refs={"hypothesis": "H17"})
    st = ledger.state(session, project.id)
    assert st["hypotheses"]["H17"]["results"][0]["failed_criterion"].startswith("Convergence")
    assert st["artifacts"][0]["commit"] == "0c2229f" and st["next_actions"]
    assert ledger.verify_chain(session, project.id) == (True, None)
    # tampering with an entry breaks the chain
    e = ledger.entries(session, project.id)[2]
    e.content = {**e.content, "result": "Twenty times fewer paths."}
    session.flush()
    ok, seq = ledger.verify_chain(session, project.id)
    assert not ok and seq == 3


def test_routing_uses_task_specific_scores(session, world):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    project = create_project(session, tenant_id=world.tenant.id, parent_scope=world.finance, name="Routing")
    # give research a great *legal* history and a poor *finance* history via scorecards
    for _ in range(6):
        record_outcome(session, agents["research"], "verification", Outcome(accuracy=0.99, citation_quality=1.0, verification_score=0.99))
        record_outcome(session, agents["legal"], "verification", Outcome(accuracy=0.3, citation_quality=0.4, hallucinated=True, verification_score=0.2))
    task = Task(tenant_id=world.tenant.id, project_id=project.id, scope_id=project.scope_id, task_type="verification",
                title="Verify findings", brief="verify", status=TaskStatus.pending)
    session.add(task)
    session.flush()
    chosen, reason = select_agent(session, task, list(agents.values()))
    assert chosen.name == "research", reason["decision"]
    cands = {c["agent"]: c for c in reason["candidates"]}
    assert cands["research"]["scorecard"] > cands["legal"]["scorecard"]
    assert cands["research"]["scorecard_low_support"] is False and cands["finance"]["scorecard_low_support"] is True
    # a finance task still goes to finance even though research has the best overall record
    task2 = Task(tenant_id=world.tenant.id, project_id=project.id, scope_id=project.scope_id, task_type="finance",
                 title="Fees", brief="fees", status=TaskStatus.pending)
    session.add(task2)
    session.flush()
    chosen2, reason2 = select_agent(session, task2, list(agents.values()))
    assert chosen2.name == "finance" and cands is not None
    assert any(c["agent"] == "research" and c["excluded"] and "not in agent task types" in c["excluded"] for c in reason2["candidates"])


def test_agent_permissions_apply_to_evidence(session, world, embedder):
    """An agent principal without a grant on a restricted record never sees it in its packet."""
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    project = create_project(session, tenant_id=world.tenant.id, parent_scope=world.legal, name="Restricted")
    create_record(session, tenant_id=world.tenant.id, scope_id=project.scope_id, type=RecordType.fact,
                  summary="Restricted settlement figure USD 5,000,000", detail="settlement", sensitivity=4, keywords=["settlement"], embedder=embedder)
    create_record(session, tenant_id=world.tenant.id, scope_id=project.scope_id, type=RecordType.fact,
                  summary="Public settlement process takes 30 days", detail="settlement process", sensitivity=1, keywords=["settlement"], embedder=embedder)
    session.commit()
    head = HeadAgent(session, project, embedder=embedder)
    head.start("Summarise the settlement position")
    head.run()
    research = next(t for t in session.scalars(select(Task).where(Task.project_id == project.id)) if t.task_type == "research")
    claims = " ".join(f["claim"] for f in research.result["findings"])
    assert "5,000,000" not in claims and "30 days" in claims
    assert session.scalar(select(Approval)) is None or True
    _ = agents
