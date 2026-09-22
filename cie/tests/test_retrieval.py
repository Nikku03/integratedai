"""Hybrid retrieval, permissions, supersession, contradictions, cited answers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from cie.core.models import AuditLog, LinkKind, MemoryRecord, RecordType
from cie.extraction.pipeline import run_extraction
from cie.governance.permissions import AccessDenied
from cie.memory.records import contradict, create_record, link, supersede
from cie.retrieval.pipeline import Retriever
from tests.fixtures import CONTRACT_SECTIONS, make_pdf

pytestmark = pytest.mark.db


@pytest.fixture
def indexed(session, world, vault, embedder):
    pdf = make_pdf(CONTRACT_SECTIONS)
    doc = vault.ingest(session, tenant_id=world.tenant.id, data=pdf, filename="msa.pdf", scope_id=world.project.id,
                       doc_type="contract", file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    return doc


def test_exact_clause_with_page_provenance(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    result, res = r.answer("What does clause 3.1 say about the monthly fee?", world.admin, world.project.id)
    assert result.status == "answered"
    assert result.citations and result.citations[0]["page_no"] == 4
    assert result.citations[0]["document_id"] == str(indexed.id)
    assert "125,000" in result.answer or "125000" in result.answer
    # audit trail exists for search and answer
    actions = [a.action for a in session.scalars(select(AuditLog))]
    assert "search" in actions and "answer" in actions


def test_permission_enforced_zero_leaks(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    # analyst has reader (clearance 2) on Legal -> can see project under Legal
    res = r.retrieve("monthly fee", world.analyst, world.project.id)
    assert res.packet.items
    # outsider only has Finance -> denied on the Legal project
    with pytest.raises(AccessDenied):
        r.retrieve("monthly fee", world.outsider, world.project.id)
    # sensitivity ceiling: a restricted record is invisible to the analyst but visible to admin
    secret = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.fact,
                           summary="Restricted settlement amount USD 9,999,999", detail="settlement restricted",
                           sensitivity=4, keywords=["settlement"], embedder=embedder)
    session.commit()
    res_a = r.retrieve("settlement amount", world.analyst, world.project.id)
    assert all(it["id"] != str(secret.id) for it in res_a.packet.items)
    res_b = r.retrieve("settlement amount", world.admin, world.project.id)
    assert any(it["id"] == str(secret.id) for it in res_b.packet.items)
    # explicit ACL deny beats scope grant
    denied = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.fact,
                           summary="Board compensation memo total USD 777,777", detail="compensation memo",
                           acl={"deny": [str(world.analyst.id)]}, keywords=["compensation"], embedder=embedder)
    session.commit()
    res_c = r.retrieve("compensation memo", world.analyst, world.project.id)
    assert all(it["id"] != str(denied.id) for it in res_c.packet.items)


def test_current_vs_superseded(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    old = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.metric,
                        summary="Monthly fee is USD 125,000", content={"value": 125000.0, "currency": "USD", "name": "fee"},
                        detail="The monthly fee is USD 125,000.", valid_from=datetime(2025, 1, 15, tzinfo=UTC),
                        keywords=["monthly", "fee"], embedder=embedder, confidence=0.9)
    new = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.metric,
                        summary="Monthly fee is USD 140,000 after amendment 1", content={"value": 140000.0, "currency": "USD", "name": "fee"},
                        detail="Amendment 1 raises the monthly fee to USD 140,000.", valid_from=datetime(2025, 9, 1, tzinfo=UTC),
                        keywords=["monthly", "fee", "amendment"], embedder=embedder, confidence=0.9)
    supersede(session, old, new)
    session.commit()
    assert old.superseded_by_id == new.id and new.version == 2 and old.valid_to is not None
    res = r.retrieve("what is the current monthly fee", world.admin, world.project.id)
    ids = [it["id"] for it in res.packet.items]
    assert str(new.id) in ids and str(old.id) not in ids
    # point-in-time query sees the old value
    res_hist = r.retrieve("what was the monthly fee as of March 1, 2025", world.admin, world.project.id)
    ids_h = [it["id"] for it in res_hist.packet.items]
    assert str(old.id) in ids_h and str(new.id) not in ids_h
    res_all = r.retrieve("history of the monthly fee", world.admin, world.project.id, filters={"include_history": True})
    ids_all = [it["id"] for it in res_all.packet.items]
    assert str(old.id) in ids_all and str(new.id) in ids_all
    old_item = next(it for it in res_all.packet.items if it["id"] == str(old.id))
    assert old_item["superseded"] and old_item["superseded_by"] == str(new.id)


def test_contradiction_detected_and_surfaced(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    a = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.deadline,
                      summary="Notice period for termination is 90 days", content={"days": 90},
                      detail="Termination requires 90 days notice.", keywords=["notice", "termination"], embedder=embedder)
    b = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.deadline,
                      summary="Notice period for termination is 60 days", content={"days": 60},
                      detail="Termination requires 60 days notice per the email from the supplier.",
                      keywords=["notice", "termination"], embedder=embedder)
    c = contradict(session, a, b, "90 vs 60 days notice")
    session.commit()
    assert c.type == RecordType.contradiction and a.verification.value == "disputed"
    assert set(a.glyph["contradictions"]) == {str(b.id)} and a.glyph["status"] == "disputed"
    result, res = r.answer("What is the notice period for termination?", world.admin, world.project.id)
    assert result.status == "conflict"
    assert {ci["item_id"] for ci in result.citations} >= {str(a.id), str(b.id)}


def test_insufficient_evidence(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    result, res = r.answer("What is the CEO's favourite colour according to the zebra policy?", world.admin, world.project.id)
    assert result.status == "insufficient_evidence"


def test_graph_expansion_brings_dependency(session, world, embedder, indexed):
    r = Retriever(session, embedder=embedder)
    task = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.task,
                         summary="Renegotiate warehouse automation pricing", detail="Task to renegotiate pricing.",
                         keywords=["renegotiate", "pricing"], embedder=embedder)
    dep = create_record(session, tenant_id=world.tenant.id, scope_id=world.project2.id, type=RecordType.decision,
                        summary="Finance froze all supplier spend increases for FY2026", detail="Spend freeze decision.",
                        keywords=["freeze", "spend"], embedder=embedder)
    link(session, task, dep, LinkKind.depends_on, justification="pricing depends on spend freeze")
    session.commit()
    res = r.retrieve("renegotiate pricing task", world.admin, world.project.id, use_graph=True)
    ids = [it["id"] for it in res.packet.items]
    assert str(task.id) in ids
    assert str(dep.id) in ids, "cross-project dependency should arrive via graph expansion"
    dep_item = next(it for it in res.packet.items if it["id"] == str(dep.id))
    assert dep_item["horizon"] == 3 and dep_item["via"].startswith("depends_on")
    res_no = r.retrieve("renegotiate pricing task", world.admin, world.project.id, use_graph=False)
    assert str(dep.id) not in [it["id"] for it in res_no.packet.items]
    assert res.trace["graph_budget"] >= 4


def test_packet_is_reproducible(session, world, embedder, indexed):
    from cie.core.models import EvidencePacket
    from cie.retrieval.answer import extractive
    from cie.retrieval.intent import classify

    r = Retriever(session, embedder=embedder)
    result, res = r.answer("What is the late payment penalty?", world.admin, world.project.id)
    session.commit()
    stored = session.get(EvidencePacket, res.packet.id)
    again = extractive(stored, classify("What is the late payment penalty?"))
    assert again.answer == result.answer and again.citations == result.citations


def test_fake_llm_assisted_mode_verifies_claims(session, world, embedder, indexed):
    from cie.agents.providers import FakeProvider

    r = Retriever(session, embedder=embedder)
    provider = FakeProvider(lambda sys, user: "The monthly fee is USD 125,000 [1]. The moon is made of cheese [1].")
    result, res = r.answer("What is the monthly fee?", world.admin, world.project.id, mode="assisted", provider=provider)
    assert result.mode == "assisted"
    assert "cheese" not in result.answer and result.unsupported_claims and "cheese" in result.unsupported_claims[0]
    assert "<untrusted_document" in provider.calls[0][1]
    assert [r_.type.value for r_ in session.scalars(select(MemoryRecord).where(MemoryRecord.type == RecordType.metric))]
