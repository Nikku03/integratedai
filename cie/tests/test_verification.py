"""Verification: recalculation from the live state, state freshness, methods per finding; the publication gate."""

from __future__ import annotations

import uuid

import pytest

from cie.agents import publication
from cie.agents.calc import CalcError, evaluate
from cie.agents.head import create_project
from cie.agents.registry import ensure_default_agents
from cie.agents.verification import verify_result
from cie.core.models import MemoryRecord, RecordType, TaskStatus, VerificationStatus
from cie.governance.permissions import visible_scopes
from cie.memory.records import create_record
from cie.state.events import process_event, submit_event
from cie.state.store import GraphReader
from cie.workflow import engine

S = TaskStatus


def test_calculator_is_arithmetic_only():
    assert evaluate("qty * price - discount", {"qty": 10, "price": 120, "discount": 50}) == 1150
    assert evaluate("round(max(a, b) / 3, 2)", {"a": 10, "b": 20}) == 6.67
    assert evaluate("days_between(ordered, promised)", {"ordered": "2026-10-01", "promised": "2026-10-15"}) == 14
    assert evaluate("-x ** 2", {"x": 3}) == -9
    for bad in ("__import__('os')", "x.real", "open('f')", "(lambda: 1)()", "2 ** 1000", "1 / 0", "y", "[1][0]", "'a' + 'b'"):
        with pytest.raises(CalcError):
            evaluate(bad, {"x": 1})





def apply(session, world, ops):
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=uuid.uuid4().hex)
    return process_event(session, ev.id)


@pytest.fixture
def po(session, world):
    apply(session, world, [{"op": "upsert_node", "type": "order", "key": "po1", "name": "PO 1", "scope": "Acme",
                            "attrs": {"qty": 10, "unit_price": 120, "promised_date": "2026-10-20"}},
                           {"op": "upsert_node", "type": "order", "key": "po2", "name": "PO 2", "scope": "Legal", "sensitivity": 3,
                            "attrs": {"qty": 1}}])


def cost_finding(value=1200.0):
    return {"claim": "PO 1 costs 1200", "kind": "metric", "value": value,
            "calculation": {"expression": "qty * unit_price", "inputs": {"qty": {"ref": ["order", "po1"], "field": "qty"},
                                                                         "unit_price": {"ref": ["order", "po1"], "field": "unit_price"}}}}


@pytest.mark.db
def test_recalculation_uses_the_current_state(session, world, po):
    reader = GraphReader(session, world.tenant.id, None)
    v = verify_result(session, {"findings": [cost_finding()]}, reader=reader)
    assert v.passed and v.details[0]["methods"] == ["recalculation"] and v.details[0]["recomputed"] == 1200
    apply(session, world, [{"op": "revise_node", "ref": ["order", "po1"], "attrs": {"qty": 11}}])
    v = verify_result(session, {"findings": [cost_finding()]}, reader=GraphReader(session, world.tenant.id, None))
    assert not v.passed and "recomputed 1320" in v.details[0]["reasons"][0]
    bad = cost_finding()
    bad["calculation"]["inputs"]["qty"] = {"ref": ["order", "po2"], "field": "qty"}
    v = verify_result(session, {"findings": [bad]}, reader=GraphReader(session, world.tenant.id, visible_scopes(session, world.analyst)))
    assert not v.passed and "not found or not visible" in v.details[0]["reasons"][0], "the verifier's permissions apply"


@pytest.mark.db
def test_state_freshness_and_values(session, world, po):
    r = GraphReader(session, world.tenant.id, None)
    ver = r.node_by_key("order", "po1").version
    f = {"claim": "PO 1 arrives on 20 October", "state_refs": [{"ref": ["order", "po1"], "version": ver, "field": "promised_date",
                                                                "value": "2026-10-20"}]}
    v = verify_result(session, {"findings": [f]}, reader=r)
    assert v.passed and v.details[0]["methods"] == ["state"]
    apply(session, world, [{"op": "revise_node", "ref": ["order", "po1"], "attrs": {"promised_date": "2026-11-02"}}])
    v = verify_result(session, {"findings": [f]}, reader=GraphReader(session, world.tenant.id, None))
    reasons = v.details[0]["reasons"]
    assert not v.passed and any(x.startswith("stale:") for x in reasons) and any("'2026-11-02'" in x for x in reasons)
    v = verify_result(session, {"findings": [{"claim": "trust me"}]}, reader=r)
    assert not v.passed and v.details[0]["reasons"][0].startswith("no evidence")
    v = verify_result(session, {"findings": [f]})
    assert not v.passed and "need a state reader" in v.details[0]["reasons"][0]


@pytest.mark.db
def test_superseded_citation_fails(session, world, embedder):
    old = create_record(session, tenant_id=world.tenant.id, scope_id=world.company.id, type=RecordType.fact, summary="Fee is 100 per month",
                        detail="Fee is 100 per month", embedder=embedder)
    new = create_record(session, tenant_id=world.tenant.id, scope_id=world.company.id, type=RecordType.fact, summary="Fee is 120 per month",
                        detail="Fee is 120 per month", embedder=embedder)
    old.superseded_by_id = new.id
    session.flush()
    v = verify_result(session, {"findings": [{"claim": "Fee is 100 per month", "citations": [{"item_id": str(old.id)}]}]})
    assert not v.passed and "superseded" in v.details[0]["reasons"][0] and v.details[0]["methods"] == ["citation"]


@pytest.mark.db
def test_publication_gate(session, world, embedder):
    from cie.retrieval.pipeline import Retriever

    agents = ensure_default_agents(session, world.tenant.id, world.company)
    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Gate")
    src = create_record(session, tenant_id=world.tenant.id, scope_id=proj.scope_id, type=RecordType.fact, summary="Termination notice is 90 days",
                        detail="Either party may terminate with 90 days notice", sensitivity=2, keywords=["termination", "notice"], embedder=embedder)
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="legal", title="Notice period"), actor="test")
    engine.claim_task(session, t.id, worker="w", agent_id=agents["legal"].id)
    result = {"summary": "notice", "findings": [
        {"claim": "Termination notice is 90 days", "citations": [{"item_id": str(src.id)}], "confidence": 0.9},
        {"claim": "Termination requires board approval", "citations": [{"item_id": str(uuid.uuid4())}], "confidence": 0.4}]}
    staged = publication.stage(session, t, agents["legal"], proj, result, embedder=embedder)
    assert all(r.verification == VerificationStatus.unverified for r in staged)
    assert staged[0].sensitivity == 2, "a workspace record keeps the clearance of what it cites"
    ws_ids = {str(r.id) for r in staged}
    packet = Retriever(session, embedder=embedder).retrieve("termination notice board approval", world.admin, proj.scope_id).packet
    assert not ws_ids & {i["id"] for i in packet.items}, "the workspace is not shared memory"
    engine.submit(session, t.id, worker="w", result=result)
    assert t.status == S.completed
    out = publication.publish(session, t, verifier="head", reader=GraphReader(session, world.tenant.id, None), embedder=embedder)
    assert len(out["published"]) == 1 and len(out["blocked"]) == 1
    pub = session.get(MemoryRecord, uuid.UUID(out["published"][0]))
    assert pub.scope_id == proj.scope_id and pub.verification == VerificationStatus.verified and pub.content["methods"] == ["citation"]
    assert pub.sensitivity == 2 and pub.content["workspace_record_id"] in ws_ids
    blocked = session.get(MemoryRecord, uuid.UUID(out["blocked"][0]))
    assert blocked.content["publication"]["status"] == "blocked" and "not found" in blocked.content["publication"]["reasons"][0]
    packet = Retriever(session, embedder=embedder).retrieve("termination notice", world.admin, proj.scope_id).packet
    assert str(pub.id) in {i["id"] for i in packet.items}
    assert publication.publish(session, t, verifier="head", reader=GraphReader(session, world.tenant.id, None))["published"] == [], "once"
    # reopening withdraws what was published; completing again republishes and supersedes it
    assert publication.withdraw(session, t.id, "input changed") == 1 and pub.verification == VerificationStatus.disputed
    engine.reopen(session, t.id, actor="test", reason="input changed")
    engine.claim_task(session, t.id, worker="w")
    publication.stage(session, t, agents["legal"], proj, result, embedder=embedder)
    engine.submit(session, t.id, worker="w", result=result)
    again = publication.publish(session, t, verifier="head", reader=GraphReader(session, world.tenant.id, None), embedder=embedder)
    assert len(again["published"]) == 1 and pub.superseded_by_id == uuid.UUID(again["published"][0])


@pytest.mark.db
def test_a_conclusion_is_blocked_with_the_figures_it_rests_on(session, world, embedder):
    agents = ensure_default_agents(session, world.tenant.id, world.company)
    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Rests on")
    src = create_record(session, tenant_id=world.tenant.id, scope_id=proj.scope_id, type=RecordType.fact, summary="Termination notice is 90 days",
                        detail="Either party may terminate with 90 days notice", keywords=["termination", "notice"], embedder=embedder)
    t = engine.accept(session, engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id,
                                              task_type="legal", title="Notice period"), actor="test")
    engine.claim_task(session, t.id, worker="w", agent_id=agents["legal"].id)
    good = {"claim": "Termination notice is 90 days", "citations": [{"item_id": str(src.id)}]}
    result = {"summary": "notice", "findings": [
        good, {"claim": "Notice costs 500", "value": 500, "calculation": {"expression": "400", "inputs": {}}},
        {**good, "depends_on": [1]}, {**good, "depends_on": [2]}, {**good, "depends_on": [0]}]}
    publication.stage(session, t, agents["legal"], proj, result, embedder=embedder)
    engine.submit(session, t.id, worker="w", result=result)
    out = publication.publish(session, t, verifier="head", reader=GraphReader(session, world.tenant.id, None), embedder=embedder)
    assert len(out["published"]) == 2 and len(out["blocked"]) == 3, "1 fails; 2 rests on it, 3 on 2; 0 and 4 stand"
    why = {session.get(MemoryRecord, uuid.UUID(b)).content["finding"]: session.get(MemoryRecord, uuid.UUID(b)).content["publication"]["reasons"]
           for b in out["blocked"]}
    assert why[2] == ["rests on finding 1, which failed verification"] and why[3] == ["rests on finding 2, which failed verification"]
