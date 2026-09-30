"""BM25 keyword search: the index proposes, SQL disposes; queued rows are searched before they are indexed;
rebuilds switch atomically; tenants without an index use full text."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import and_, select, text

from cie.core.models import MemoryRecord, RecordType, Section, VerificationStatus
from cie.core.settings import get_settings
from cie.retrieval import bm25, lexical
from cie.retrieval.lexical_models import LexicalQueue, LexicalState

pytestmark = pytest.mark.db


@pytest.fixture
def lexdir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "lexical_index_dir", tmp_path / "lexical")
    bm25._readers.clear()
    return tmp_path / "lexical"


def rec(session, world, summary, detail, scope=None, **kw):
    r = MemoryRecord(tenant_id=world.tenant.id, scope_id=(scope or world.company).id, type=kw.pop("type", RecordType.fact),
                     summary=summary, detail=detail, content={}, source_locations=[], confidence=0.9,
                     verification=VerificationStatus.unverified, sensitivity=kw.pop("sensitivity", 1), acl={}, version=1,
                     family_id=uuid.uuid4(), keywords=kw.pop("keywords", []), content_sha256=uuid.uuid4().hex, **kw)
    session.add(r)
    session.flush()
    session.execute(text("UPDATE memory_records SET tsv = to_tsvector('english', summary || ' ' || coalesce(detail, '')) WHERE id = :i"),
                    {"i": r.id})
    return r


def url():
    return get_settings().test_database_url


def base(world):
    return and_(MemoryRecord.tenant_id == world.tenant.id, MemoryRecord.deleted_at.is_(None))


def ids(hits):
    return [h for h, _ in hits]


def test_rows_are_queued_by_the_triggers_and_build_takes_them_in(session, world, lexdir):
    a = rec(session, world, "Northwind freight contract", "The Northwind freight contract renews in March with a 4% uplift.")
    session.commit()
    assert session.scalar(select(LexicalQueue.row_id).where(LexicalQueue.row_id == a.id)) == a.id, "queued on insert"
    assert lexical.search_records(session, "Northwind renewal uplift", base(world), 5, tenant_id=world.tenant.id, engine="bm25", info=(i := {})) \
        and i["engine"] == "fts", "no index yet: full text"
    out = bm25.build(url(), world.tenant.id, log=lambda *a: None)
    assert out["records"] >= 1 and out["queue_cleared"] >= 1
    session.expire_all()
    assert session.get(LexicalState, world.tenant.id).status == "ready"
    assert session.scalar(select(LexicalQueue.id).where(LexicalQueue.tenant_id == world.tenant.id)) is None
    hits = lexical.search_records(session, "Northwind freight uplift", base(world), 5, tenant_id=world.tenant.id, engine="bm25", info=(i := {}))
    assert i["engine"] == "bm25" and ids(hits)[0] == a.id


def test_query_terms_are_stemmed_once(session, world, lexdir):
    a = rec(session, world, "Pricing proposal", "Redwood's proposal for the Year 1 package.")
    session.commit()
    bm25.build(url(), world.tenant.id, log=lambda *a: None)
    assert bm25.query_terms("What did the proposal say?") == ["propos"]
    assert ids(lexical.search_records(session, "proposal", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == [a.id], \
        "stemming the stem ('propo') would miss the indexed term"


def test_sql_disposes_what_bm25_proposes(session, world, lexdir):
    seen = rec(session, world, "Budget for Project Falcon", "Project Falcon budget is 120,000 USD.")
    hidden = rec(session, world, "Budget for Project Falcon (board)", "Project Falcon budget is 150,000 USD per the board.",
                 scope=world.finance, sensitivity=4)
    gone = rec(session, world, "Budget for Project Falcon (draft)", "Project Falcon budget draft.")
    session.commit()
    bm25.build(url(), world.tenant.id, log=lambda *a: None)
    gone.deleted_at = gone.recorded_at
    session.commit()
    f = and_(base(world), MemoryRecord.sensitivity <= 2)
    hits = ids(lexical.search_records(session, "Project Falcon budget", f, 10, tenant_id=world.tenant.id, engine="bm25"))
    assert seen.id in hits and hidden.id not in hits and gone.id not in hits


def test_queued_rows_are_searched_before_they_are_indexed_and_rewording_wins(session, world, lexdir):
    old = rec(session, world, "Carrier choice", "We ship with Maersk from Rotterdam.")
    session.commit()
    bm25.build(url(), world.tenant.id, log=lambda *a: None)
    new = rec(session, world, "Warehouse move", "The Leipzig warehouse opens in May.")
    old.detail = "We ship with Hapag-Lloyd from Hamburg."
    session.commit()
    assert session.scalar(select(text("count(*)")).select_from(LexicalQueue).where(LexicalQueue.tenant_id == world.tenant.id)) == 2
    assert ids(lexical.search_records(session, "Leipzig warehouse", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == [new.id]
    assert ids(lexical.search_records(session, "Hamburg carrier", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == [old.id]
    assert ids(lexical.search_records(session, "Rotterdam Maersk", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == [], \
        "the index's copy of a re-worded row is ignored"
    assert bm25.sync(url(), world.tenant.id) == 2
    session.expire_all()
    bm25._readers.clear()
    assert session.scalar(select(LexicalQueue.id).where(LexicalQueue.tenant_id == world.tenant.id)) is None
    assert ids(lexical.search_records(session, "Hamburg carrier", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == [old.id]
    assert ids(lexical.search_records(session, "Rotterdam Maersk", base(world), 5, tenant_id=world.tenant.id, engine="bm25")) == []


def test_sections_documents_and_many_candidates(session, world, lexdir, vault):
    from datetime import UTC, datetime

    from cie.extraction.pipeline import run_extraction
    from tests.fixtures import CONTRACT_SECTIONS, make_pdf

    doc = vault.ingest(session, tenant_id=world.tenant.id, data=make_pdf(CONTRACT_SECTIONS), filename="msa.pdf", scope_id=world.company.id,
                       doc_type="contract", file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
    session.commit()
    run_extraction(session, doc, vault=vault, ocr=None)
    for i in range(300):  # a common word in many rows: the few rows the principal may read still come back
        rec(session, world, f"note {i}", "termination notice", sensitivity=5)
    session.commit()
    bm25.build(url(), world.tenant.id, log=lambda *a: None)
    sf = and_(Section.tenant_id == world.tenant.id)
    hits = lexical.search_sections(session, "termination notice", sf, 5, tenant_id=world.tenant.id, engine="bm25", info=(i := {}))
    assert i["engine"] == "bm25" and hits
    assert all(session.get(Section, h).document_id == doc.id for h in ids(hits))
    only = lexical.search_sections(session, "termination", sf, 5, tenant_id=world.tenant.id, engine="bm25", document_ids=[uuid.uuid4()])
    assert only == [], "restricted to other documents"
    low = and_(base(world), MemoryRecord.sensitivity <= 2)
    r = lexical.search_records(session, "termination notice", low, 5, tenant_id=world.tenant.id, engine="bm25", info=(i := {}))
    assert all(session.get(MemoryRecord, h).sensitivity <= 2 for h in ids(r)) and i["rounds"] >= 1


def test_rebuild_switches_versions_and_a_long_tail_falls_back(session, world, lexdir, monkeypatch):
    rec(session, world, "Alpha", "alpha bravo")
    session.commit()
    first = bm25.build(url(), world.tenant.id, log=lambda *a: None)["version"]
    second = bm25.build(url(), world.tenant.id, log=lambda *a: None)["version"]
    d = bm25.tenant_dir(world.tenant.id)
    assert first != second and bm25.current_version(d) == second and not (d / first).exists()
    monkeypatch.setattr(get_settings(), "lexical_tail_max", 1)
    rec(session, world, "Charlie", "charlie delta")
    rec(session, world, "Echo", "echo foxtrot")
    session.commit()
    assert not bm25.ready(session, world.tenant.id)
    lexical.search_records(session, "charlie", base(world), 5, tenant_id=world.tenant.id, engine="bm25", info=(i := {}))
    assert i["engine"] == "fts"


def test_sync_all_drops_the_queue_of_tenants_without_an_index(session, world, lexdir):
    rec(session, world, "Golf", "golf hotel")
    session.commit()
    assert session.scalar(select(text("count(*)")).select_from(LexicalQueue)) >= 1
    assert bm25.sync_all(url()) == {}
    session.expire_all()
    assert session.scalar(select(text("count(*)")).select_from(LexicalQueue)) == 0
