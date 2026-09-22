"""Organisation views: entity profile, document card, scope digest; permission-filtered."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cie.core.models import LinkKind, MemoryRecord, RecordType
from cie.extraction.pipeline import run_extraction
from cie.governance.permissions import visible_scopes
from cie.memory import organise
from cie.memory.entities import attach_entities, remember_alias, resolve
from cie.memory.records import contradict, create_record, link
from tests.fixtures import CONTRACT_SECTIONS, make_pdf

pytestmark = pytest.mark.db


def test_entity_profile_groups_current_records_and_respects_permissions(session, world, embedder):
    t = world.tenant.id
    org = create_record(session, tenant_id=t, scope_id=world.company.id, type=RecordType.organization,
                        summary="Northwind Logistics Ltd.", content={"name": "Northwind Logistics Ltd."}, detail="x")
    fee_old = create_record(session, tenant_id=t, scope_id=world.legal.id, type=RecordType.metric, summary="monthly fee USD 125,000",
                            content={"value": 125000.0, "currency": "USD"}, detail="fee", entity_ids=[str(org.id)])
    fee_new = create_record(session, tenant_id=t, scope_id=world.legal.id, type=RecordType.metric, summary="monthly fee USD 140,000",
                            content={"value": 140000.0, "currency": "USD"}, detail="fee", entity_ids=[str(org.id)])
    from cie.memory.records import supersede

    supersede(session, fee_old, fee_new)
    notice = create_record(session, tenant_id=t, scope_id=world.legal.id, type=RecordType.deadline, summary="90 days notice",
                           content={"duration_days": 90}, detail="notice")
    link(session, notice, org, LinkKind.mentions)  # referenced by edge rather than entity_ids
    email = create_record(session, tenant_id=t, scope_id=world.legal.id, type=RecordType.deadline, summary="60 days notice",
                          content={"duration_days": 60}, detail="email says 60", entity_ids=[str(org.id)])
    contradict(session, notice, email, "email says 60 days, contract says 90")
    secret = create_record(session, tenant_id=t, scope_id=world.finance.id, type=RecordType.fact, summary="finance-only note",
                           content={}, detail="restricted", entity_ids=[str(org.id)])
    session.flush()

    admin = visible_scopes(session, world.admin)
    prof = organise.entity_profile(session, t, admin, org)
    types = prof["counts_by_type"]
    assert types.get("metric") == 1 and types.get("deadline") == 2 and types.get("fact") == 1, types
    assert [x["summary"] for x in prof["records_by_type"]["metric"]] == ["monthly fee USD 140,000"]  # superseded fee left out
    assert prof["contradictions"], "the recorded contradiction is surfaced"
    hist = organise.entity_profile(session, t, admin, org, include_history=True)
    assert hist["counts_by_type"]["metric"] == 2

    analyst = visible_scopes(session, world.analyst)  # reader on legal only
    prof_a = organise.entity_profile(session, t, analyst, org)
    assert "fact" not in prof_a["counts_by_type"], "finance-only record must not appear for the legal analyst"
    assert prof_a["counts_by_type"]["metric"] == 1

    found = organise.find_entities(session, t, admin, "Northwind Logistics Limited")
    assert found and found[0]["id"] == str(org.id)
    assert secret.id  # keep the reference: the record exists but is invisible above


def test_entity_resolution_uses_index_prefilter_and_aliases(session, world):
    t = world.tenant.id
    org = create_record(session, tenant_id=t, scope_id=world.company.id, type=RecordType.organization,
                        summary="Contoso Medical GmbH", content={"name": "Contoso Medical GmbH"}, detail="x")
    for i in range(30):  # unrelated organisations the prefilter must not need to score
        create_record(session, tenant_id=t, scope_id=world.company.id, type=RecordType.organization,
                      summary=f"Supplier {i} Holdings", content={"name": f"Supplier {i} Holdings"}, detail="x")
    session.flush()
    m, status = resolve(session, t, world.project.id, "Contoso Medical Gmbh", RecordType.organization)
    assert status == "matched" and m.id == org.id
    remember_alias(org, "CMG")  # what the extraction pipeline records when a matched mention is spelled differently
    session.flush()
    assert "cmg" in (org.keywords or []), "alias kept in the indexed keywords"
    m2, status2 = resolve(session, t, world.project.id, "CMG", RecordType.organization)
    assert status2 == "matched" and m2.id == org.id, "an alias with no trigram overlap is found through the keyword index"
    mention = create_record(session, tenant_id=t, scope_id=world.project.id, type=RecordType.fact,
                            summary="Contoso Medical delivered late", content={}, detail="late")
    ents = attach_entities(session, mention, ["Contoso Medical GmbH"], RecordType.organization)
    assert ents[0].id == org.id and str(org.id) in mention.entity_ids


def test_document_card_and_scope_digest(session, world, vault, embedder):
    pdf = make_pdf(CONTRACT_SECTIONS)
    doc = vault.ingest(session, tenant_id=world.tenant.id, data=pdf, filename="msa.pdf", scope_id=world.project.id,
                       doc_type="contract").document
    session.commit()
    run_extraction(session, doc, vault=vault, embedder=embedder, ocr=None)
    admin = visible_scopes(session, world.admin)
    card = organise.document_card(session, world.tenant.id, admin, doc)
    assert card["record_count"] > 5 and card["parties"], card["counts_by_type"]
    assert card["versions"] and card["versions"][0]["version"] == 1
    digest = organise.scope_digest(session, world.tenant.id, admin, world.company)
    assert digest["documents"] >= 1 and digest["records_total"] == sum(digest["records_by_type"].values())
    assert digest["top_entities"], "mentions edges rank the entities"
    n_org = session.scalar(select(MemoryRecord.id).where(MemoryRecord.source_document_id == doc.id, MemoryRecord.type == RecordType.organization))
    assert n_org is not None
    outsider = visible_scopes(session, world.outsider)  # finance only
    empty = organise.scope_digest(session, world.tenant.id, outsider, world.company)
    assert empty["records_by_type"] == {} and empty["documents"] == 0


def test_normalise_handles_dotted_and_stacked_suffixes():
    from cie.memory.entities import normalise

    assert normalise("Northwind Logistics L.L.C.") == normalise("Northwind Logistics LLC") == "northwind logistics"
    assert normalise("Contoso Medical S.A.") == normalise("Contoso Medical SA") == "contoso medical"
    assert normalise("Fourth Coffee Co. Ltd.") == "fourth coffee"
    assert normalise("Jane Smith") == "jane smith"
    assert normalise("Company") == "company"  # a bare suffix word stays a name rather than becoming empty
