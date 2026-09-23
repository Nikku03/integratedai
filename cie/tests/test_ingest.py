"""Structured-source ingestion: reading exports, building memory, bulk writing with links,
entities, projects and cross-document contradictions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from cie.ingest.builder import build, chunk
from cie.ingest.sources import person_name, read

TICKET = {
    "key": "ENG-101", "team": "engineering", "title": "Stabilise KV cache eviction under burst load", "status": "In Progress", "priority": "P1",
    "created_at": "2026-02-01", "updated_at": "2026-02-10", "creator": "Maya Chen", "assignee": "Omar Haddad (SRE)", "project": "runtime-stability",
    "labels": ["kv-cache", "latency"], "dependencies": ["ENG-102"], "linked_issues": ["SUP-77"],
    "original_location": "linear/elsewhere/eng-101.json", "dataset_noise_document": True,  # export artefacts: never metadata
    "description": "Eviction stalls under burst load. The p99 latency target is 250 ms for chat routes.\n"
                   "We decided to cap the eviction batch at 64 pages. Rollout must complete by 2026-03-01.",
    "action_items": ["Omar Haddad - add eviction histogram - due 2026-02-20", "Maya Chen - review cap with SRE"],
    "root_cause": "Eviction ran in the request path when the pool was above 90% occupancy.",
    "title_field_name": "title", "content_field_names": ["description", "action_items", "root_cause"],
    "dataset_doc_uuid": "dsid_" + "a" * 32,
}


def _write(tmp_path: Path, rel: str, obj) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj) if not isinstance(obj, str) else obj)
    return p


def test_read_json_roles_references_and_artefacts(tmp_path):
    doc = read(_write(tmp_path, "linear/eng/eng-101.json", TICKET), "linear/eng/eng-101.json")
    assert doc.source == "linear" and doc.dsid == "dsid_" + "a" * 32 and doc.project == "runtime-stability"
    assert ("Maya Chen", "creator") in doc.people and ("Omar Haddad", "assignee") in doc.people
    assert "ENG-101" in doc.keys
    assert ("ENG-102", "depends_on") in doc.refs and ("SUP-77", "references") in doc.refs
    assert "original_location" not in doc.meta and "dataset_noise_document" not in doc.meta, "export artefacts must never become metadata"
    assert {"kv-cache", "latency", "in-progress", "p1", "linear"} <= set(doc.tags)
    assert doc.created.year == 2026 and doc.updated.day == 10


def test_read_plain_text_release_layout(tmp_path):
    rel = "confluence/space/dsid_" + "b" * 32 + "__retention-adr.txt"
    doc = read(_write(tmp_path, rel, "ADR-017: Retention policy\n\n## Status\nPublished"), rel)
    assert doc.dsid == "dsid_" + "b" * 32 and doc.source == "confluence" and doc.title.startswith("ADR-017")
    assert "Published" in doc.body and doc.meta == {}


def test_person_names_are_cleaned_or_rejected():
    assert person_name("Priya Nair (Solutions Engineer)") == "Priya Nair"
    assert person_name("kimberly_park") == "Kimberly Park"
    assert person_name("Julia Park <julia.park@medisys.com>") == "Julia Park"
    assert person_name("maria (CS)") is None and person_name("billing-bot") is None


def test_build_memory_card_typed_records_and_sections(tmp_path):
    mem = build(read(_write(tmp_path, "linear/eng/eng-101.json", TICKET), "linear/eng/eng-101.json"))
    card = mem.records[0]
    assert card.type == "document" and card.content["summary"] and card.content["project"] == "runtime-stability"
    assert "Omar Haddad" in card.mentions and "kv-cache" in card.keywords
    tasks = [r for r in mem.records if r.type == "task"]
    assert tasks and tasks[0].content.get("owner") == "Omar Haddad" and tasks[0].content.get("due", "").startswith("2026-02-20")
    assert any(r.type == "fact" and r.summary.startswith("Root cause") for r in mem.records)
    kinds = {r.type for r in mem.records}
    assert {"decision", "metric"} & kinds, kinds  # rule extraction over the description
    assert all(not r.summary[:1].islower() for r in mem.records[1:]), "typed records start at sentence boundaries"
    titles = [t for t, _, _ in mem.sections]
    assert titles[0] == TICKET["title"] and mem.sections[0][1].startswith("source: linear")
    assert any(t.endswith("— Details") or t.endswith("— Root cause") for t in titles)


def test_code_is_not_prose_for_rule_extraction(tmp_path):
    obj = {**TICKET, "description": '{"quant_profiles": ["int8"], "must": true}\n| a | b | c |\nThe rollout must finish in 30 days.',
           "action_items": [], "root_cause": ""}
    mem = build(read(_write(tmp_path, "linear/eng/eng-9.json", obj), "linear/eng/eng-9.json"))
    reqs = [r.summary for r in mem.records if r.type in ("requirement", "deadline")]
    assert reqs and all("{" not in r and "|" not in r for r in reqs)


def test_chunks_overlap_and_cover():
    text = ". ".join(f"Sentence number {i} about eviction" for i in range(200))
    parts = chunk(text, 500, 60)
    assert len(parts) > 5 and all(len(p) <= 520 for p in parts) and parts[-1].endswith("eviction")


@pytest.mark.db
def test_bulk_loader_links_entities_projects_and_contradictions(session, world, tmp_path):
    from cie.core.models import Document, LinkKind, MemoryRecord, RecordLink, RecordType
    from cie.ingest.bulk import BulkLoader, CachedEmbedder
    from cie.memory.embeddings import HashedEmbedding
    from tests.conftest import TEST_URL

    session.commit()
    a = {**TICKET, "summary": "Burst load eviction stalls on the dedicated pool."}
    b = {**TICKET, "key": "ENG-102", "dataset_doc_uuid": "dsid_" + "c" * 32, "dependencies": [], "linked_issues": [],
         "summary": "Burst load eviction stalls on the dedicated pool.",
         "description": "Eviction stalls under burst load. The p99 latency target is 400 ms for chat routes.\nNothing else changed."}
    c = {**TICKET, "key": "ENG-103", "dataset_doc_uuid": "dsid_" + "d" * 32, "title": "Unrelated billing export", "project": "billing",
         "summary": "Monthly invoices are exported as CSV.", "description": "Invoices are exported monthly.", "dependencies": ["ENG-101"],
         "labels": ["billing"], "linked_issues": [], "action_items": [], "root_cause": ""}
    mems = [build(read(_write(tmp_path, f"linear/eng/{o['key']}.json", o), f"linear/eng/{o['key']}.json")) for o in (a, b, c)]
    url = TEST_URL.replace("postgresql+psycopg://", "postgresql://")
    loader = BulkLoader(url, tenant_id=world.tenant.id, company_id=world.company.id, scope_ids={"linear": world.legal.id},
                        embedder=CachedEmbedder(HashedEmbedding(384), tmp_path / "cache.sqlite"))
    loader.write_batch(mems)
    stats = loader.finish()
    loader.close()
    session.expire_all()
    docs = {d.extra["dsid"]: d for d in session.scalars(select(Document).where(Document.tenant_id == world.tenant.id))}
    assert len(docs) == 3
    recs = list(session.scalars(select(MemoryRecord).where(MemoryRecord.tenant_id == world.tenant.id)))
    card = {r.source_document_id: r for r in recs if r.type == RecordType.document}
    ra, rb, rc = (card[docs[x].id] for x in ("dsid_" + "a" * 32, "dsid_" + "c" * 32, "dsid_" + "d" * 32))
    links = {(x.src_id, x.dst_id, x.kind) for x in session.scalars(select(RecordLink).where(RecordLink.tenant_id == world.tenant.id))}
    assert (ra.id, rb.id, LinkKind.depends_on) in links, "ENG-101 depends on ENG-102"
    assert (rc.id, ra.id, LinkKind.depends_on) in links
    people = [r for r in recs if r.type == RecordType.person]
    assert sorted(p.summary for p in people) == ["Maya Chen", "Omar Haddad"], "one entity per person, company-wide"
    omar = next(p for p in people if p.summary == "Omar Haddad")
    assert omar.content["documents"] == 3 and (ra.id, omar.id, LinkKind.mentions) in links and str(omar.id) in ra.entity_ids
    projects = [r for r in recs if r.type == RecordType.project]
    assert {p.content["name"] for p in projects} == {"runtime-stability", "billing"}
    assert any(k == LinkKind.relates_to for s_, d_, k in links if {s_, d_} == {ra.id, rb.id}), "same-project siblings are chained"
    # a and b are near-duplicates that disagree on the latency target: a disputed fact on each side and a contradiction record
    assert stats["near_duplicate_pairs"] == 1 and stats["contradictions"] >= 1
    contradiction = next(r for r in recs if r.type == RecordType.contradiction)
    assert "250" in contradiction.detail and "400" in contradiction.detail
    assert (ra.id, rb.id, LinkKind.contradicts) in links, "the two documents contradict each other"
    assert all(r.tsv is not None for r in recs), "every record is searchable"
    cached = CachedEmbedder(HashedEmbedding(384), tmp_path / "cache.sqlite")
    cached.embed([mems[0].records[0].embed])
    assert cached.hits == 1, "embeddings are cached on disk"
