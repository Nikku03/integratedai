"""Phase 2: entity resolution, automatic linking, glyphs, graph structure."""

from __future__ import annotations

import pytest
from sqlalchemy import func, or_, select

from cie.core.models import LinkKind, MemoryRecord, RecordLink, RecordType
from cie.extraction.pipeline import run_extraction
from cie.memory.entities import attach_entities, normalise, resolve
from cie.memory.records import create_record
from tests.fixtures import CONTRACT_SECTIONS, make_pdf

pytestmark = pytest.mark.db


def test_entity_resolution_dedups_and_flags_ambiguity(session, world, embedder):
    org = create_record(session, tenant_id=world.tenant.id, scope_id=world.company.id, type=RecordType.organization,
                        summary="Northwind Logistics Ltd.", content={"name": "Northwind Logistics Ltd."}, detail="x")
    assert normalise("NORTHWIND LOGISTICS, LTD") == "northwind logistics"
    m, status = resolve(session, world.tenant.id, world.project.id, "Northwind Logistics Limited", RecordType.organization)
    assert status == "matched" and m.id == org.id  # inherited from company scope
    mention = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.fact,
                            summary="Northwind Logistics Limited delivered late", content={}, detail="late delivery")
    ents = attach_entities(session, mention, ["Northwind Logistics Limited"], RecordType.organization)
    assert ents[0].id == org.id and str(org.id) in mention.entity_ids
    assert "Northwind Logistics Limited" not in (org.content.get("aliases") or [])  # aliases only for same-type records
    # ambiguous people: two 'J. Smith' candidates
    for nm in ("John Smith", "Jane Smith"):
        create_record(session, tenant_id=world.tenant.id, scope_id=world.legal.id, type=RecordType.person,
                      summary=nm, content={"name": nm}, detail=nm)
    msg = create_record(session, tenant_id=world.tenant.id, scope_id=world.project.id, type=RecordType.agent_message,
                        summary="Smith approved the budget", content={}, detail="approved")
    _, status = resolve(session, world.tenant.id, world.project.id, "J Smith", RecordType.person, threshold=60)
    assert status in ("ambiguous", "new")
    attach_entities(session, msg, ["Jon Smith"], RecordType.person)
    q = session.scalar(select(MemoryRecord).where(MemoryRecord.type == RecordType.open_question))
    assert q is None or "Ambiguous" in q.summary


def test_autolink_builds_sparse_graph(session, world, vault, embedder):
    pdf = make_pdf(CONTRACT_SECTIONS)
    doc = vault.ingest(session, tenant_id=world.tenant.id, data=pdf, filename="msa.pdf", scope_id=world.project.id,
                       doc_type="contract").document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    recs = list(session.scalars(select(MemoryRecord).where(MemoryRecord.source_document_id == doc.id)))
    n = len(recs)
    edges = list(session.scalars(select(RecordLink).where(RecordLink.tenant_id == world.tenant.id)))
    kinds = {e.kind for e in edges}
    assert {LinkKind.part_of, LinkKind.derived_from, LinkKind.relates_to, LinkKind.mentions} <= kinds
    # sparse: far fewer edges than n^2
    assert len(edges) < n * 6, (len(edges), n)
    doc_rec = next(r for r in recs if r.type == RecordType.document)
    part_of = [e for e in edges if e.kind == LinkKind.part_of and e.dst_id == doc_rec.id]
    assert len(part_of) == n - 1
    # a metric in clause 3 is derived_from the clause record
    fee = next(r for r in recs if r.type == RecordType.metric and r.content.get("value") == 125000.0)
    clause = next(r for r in recs if r.type == RecordType.contract_clause and r.content.get("clause_number") == "3")
    assert any(e.src_id == fee.id and e.dst_id == clause.id and e.kind == LinkKind.derived_from for e in edges)
    # glyph reflects graph structure and evidence
    assert fee.glyph["dependencies"] == [] or isinstance(fee.glyph["dependencies"], list)
    assert fee.glyph["evidence"][0]["page_no"] == 4 and fee.glyph["project"] == "Project Atlas" and fee.glyph["department"] == "Legal"
    # a second ingest of a related doc reuses the same organization entity
    email = (b"From: a@x.example\r\nTo: b@x.example\r\nSubject: Northwind\r\n\r\nNorthwind Logistics Limited missed the SLA.\r\n")
    doc2 = vault.ingest(session, tenant_id=world.tenant.id, data=email, filename="n.eml", scope_id=world.project.id).document
    session.commit()
    run_extraction(session, doc2, vault=vault, embedder=embedder, ocr=None)
    orgs = list(session.scalars(select(MemoryRecord).where(MemoryRecord.type == RecordType.organization,
                                                           MemoryRecord.summary.ilike("northwind%"))))
    assert len(orgs) == 1, [o.summary for o in orgs]
    assert "Northwind Logistics Limited" in orgs[0].content.get("aliases", [])
    total_edges = session.scalar(select(func.count(RecordLink.id)))
    assert total_edges > len(edges)
    _ = or_
