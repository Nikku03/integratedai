"""Structured-source ingestion: reading exports, building memory, bulk writing with links,
entities, projects and cross-document contradictions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from cie.ingest.builder import build, chunk, sentences
from cie.ingest.bulk import _conflicting_sentences
from cie.ingest.sources import own_keys, person_name, read, sensitivity_of

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


def test_sensitivity_labels_default_to_restricted_unless_open():
    assert sensitivity_of({"confidentiality": "internal"}) == 1 and sensitivity_of({}) == 1
    for label in ("restricted", "Restricted (customer-sensitive)", "restricted (security/legal/customer-sensitive)", "confidential",
                  "private", "team-only", "leadership-only", "something new"):
        assert sensitivity_of({"confidentiality": label}) == 2, label
    assert sensitivity_of({"confidentiality": "internal", "visibility": "private"}) == 2, "the strictest label wins"


def test_nul_characters_are_stripped_and_pr_numbers_need_a_repo(tmp_path):
    obj = {**TICKET, "description": "Stack trace\u0000 ends here. The cap is 64 pages."}
    p = _write(tmp_path, "linear/eng/nul.json", obj)  # json.dumps writes the NUL as the \u0000 escape exports carry
    doc = read(p, "linear/eng/nul.json")
    assert all("\x00" not in t for _, t in doc.fields) and "ends here" in doc.body
    assert own_keys("github", "github/pr.json", {"pr_number": 42}) == [], "PR #42 exists in every repository"
    assert own_keys("github", "github/pr.json", {"pr_number": 42, "repo": "redwood/router"}) == ["pr:redwood-router#42"]


def test_mail_headers_never_become_sentences_or_summaries(tmp_path):
    text = ("- From: Karthik Iyer <karthik@redwood.com>\n- To: Soojin Lee <soojin@redwood.com>\n"
            "- On Tue, Jun 16, 2026 at 08:22 AM Soojin Lee <soojin.lee@redwood.com> wrote:\n"
            "- As discussed, the pilot moves to the dedicated pool next week.")
    ss = sentences(text)
    assert ss == ["As discussed, the pilot moves to the dedicated pool next week."], ss
    mail = {"thread_id": "t-1", "mailbox_owner": "Soojin Lee", "subject": "Pilot move", "title_field_name": "subject",
            "content_field_names": ["messages"], "messages": [text.replace("- ", "")], "dataset_doc_uuid": "dsid_" + "e" * 32}
    mem = build(read(_write(tmp_path, "gmail/t-1.json", mail), "gmail/t-1.json"))
    assert "@" not in mem.summary and "wrote" not in mem.summary, mem.summary


def test_records_cite_the_section_that_holds_them(tmp_path):
    obj = {**TICKET, "acceptance_criteria": "Eviction p99 stays under 250 ms at 2x burst.",  # short field: the Details section
           "content_field_names": ["description", "action_items", "root_cause", "acceptance_criteria"],
           "risks": ["Cap too low for long contexts"]}  # metadata only: no section
    mem = build(read(_write(tmp_path, "linear/eng/eng-7.json", obj), "linear/eng/eng-7.json"))
    for r in mem.records[1:]:
        if r.section is not None:
            probe = r.detail.split(": ", 1)[-1][:30] if r.content.get("field") else r.detail[:30]
            assert probe.split()[0] in mem.sections[r.section][1], (r.type, r.summary, r.section)
    crit = next(r for r in mem.records if r.content.get("field") == "acceptance_criteria")
    assert mem.sections[crit.section][0].endswith("— Details")
    risk = next(r for r in mem.records if r.content.get("field") == "risks")
    assert risk.section is None, "a metadata-only field has no section to cite"


def test_identifiers_are_not_conflicting_numbers():
    assert _conflicting_sentences(["See PR #123 which fixes the retry loop in the billing worker queue"],
                                  ["See PR #456 which fixes the retry loop in the billing worker queue"]) == []
    assert _conflicting_sentences(["The p95 latency for the checkout flow dropped to 380ms after rollout"],
                                  ["The p95 latency for the checkout flow dropped to 450ms after rollout"])


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
    # the same key on an unrelated record (identifiers collide in real exports), and a restricted record in another department
    # that names Omar and a person nobody else names
    e = {**c, "dataset_doc_uuid": "dsid_" + "f" * 32, "title": "Office plants watering rota", "project": None, "dependencies": [],
         "summary": "Plants are watered on Fridays.", "description": "The rota rotates weekly.\u0000", "labels": []}
    d = {"key": "SEC-9", "title": "Customer breach review", "created_at": "2026-02-03", "creator": "Lena Ortiz", "assignee": "Omar Haddad",
         "confidentiality": "restricted (customer-sensitive)", "description": "Review of the incident with the affected customer.",
         "title_field_name": "title", "content_field_names": ["description"], "dataset_doc_uuid": "dsid_" + "9" * 32}
    files = [(f"linear/eng/{o['key']}.json", o) for o in (a, b, c)] + [("linear/eng/ENG-103-plants.json", e), ("jira/sec/SEC-9.json", d)]
    mems = [build(read(_write(tmp_path, rel, o), rel)) for rel, o in files]
    url = TEST_URL.replace("postgresql+psycopg://", "postgresql://")
    loader = BulkLoader(url, tenant_id=world.tenant.id, company_id=world.company.id, scope_ids={"linear": world.legal.id, "jira": world.finance.id},
                        embedder=CachedEmbedder(HashedEmbedding(384), tmp_path / "cache.sqlite"))
    loader.write_batch(mems)
    stats = loader.finish()
    loader.close()
    session.expire_all()
    docs = {d.extra["dsid"]: d for d in session.scalars(select(Document).where(Document.tenant_id == world.tenant.id))}
    assert len(docs) == 5 and stats.get("documents_failed", 0) == 0
    assert all(":" in d.original_filename and "/" not in d.original_filename for d in docs.values()), "the export path never becomes a filename"
    recs = list(session.scalars(select(MemoryRecord).where(MemoryRecord.tenant_id == world.tenant.id)))
    card = {r.source_document_id: r for r in recs if r.type == RecordType.document}
    ra, rb, rc = (card[docs[x].id] for x in ("dsid_" + "a" * 32, "dsid_" + "c" * 32, "dsid_" + "d" * 32))
    links = {(x.src_id, x.dst_id, x.kind) for x in session.scalars(select(RecordLink).where(RecordLink.tenant_id == world.tenant.id))}
    assert (ra.id, rb.id, LinkKind.depends_on) in links, "ENG-101 depends on ENG-102"
    assert (rc.id, ra.id, LinkKind.depends_on) in links
    people = [r for r in recs if r.type == RecordType.person]
    assert sorted(p.summary for p in people) == ["Lena Ortiz", "Maya Chen", "Omar Haddad"], "one entity per person, company-wide"
    omar = next(p for p in people if p.summary == "Omar Haddad")
    assert omar.sensitivity == 1 and (ra.id, omar.id, LinkKind.mentions) in links and str(omar.id) in ra.entity_ids
    assert omar.content["documents"] == 4, "the company-wide profile counts only company-wide documents (not the restricted review)"
    lena = next(p for p in people if p.summary == "Lena Ortiz")
    assert lena.sensitivity == 2, "a person known only from a restricted document is restricted"
    rd = card[docs["dsid_" + "9" * 32].id]
    assert rd.sensitivity == 2 and docs["dsid_" + "9" * 32].sensitivity == 2
    re_ = card[docs["dsid_" + "f" * 32].id]
    assert not any(k == LinkKind.references for s_, d_, k in links if {s_, d_} == {rc.id, re_.id}), "a shared key alone does not make one object"
    tasks = [r for r in recs if r.type == RecordType.task and r.event_time is not None]
    assert tasks and all(t.valid_from is None for t in tasks), "a due date is not the moment a task becomes true"
    projects = [r for r in recs if r.type == RecordType.project]
    assert {p.content["name"] for p in projects} == {"runtime-stability", "billing"}
    assert any(k == LinkKind.relates_to for s_, d_, k in links if {s_, d_} == {ra.id, rb.id}), "same-project siblings are chained"
    # a and b are near-duplicates that disagree on the latency target: a disputed fact on each side and, since both live in
    # one scope, a contradiction record quoting both; the documents themselves are not marked as contradicting
    assert stats["near_duplicate_pairs"] >= 1 and stats["contradictions"] >= 1
    contradiction = next(r for r in recs if r.type == RecordType.contradiction)
    assert "250" in contradiction.detail and "400" in contradiction.detail
    facts = {r.id: r for r in recs if r.type == RecordType.fact and "conflict_with_record" in (r.content or {})}
    assert facts and all(str(r.id) not in r.detail and r.scope_id == world.legal.id for r in facts.values())
    assert any((x, y, LinkKind.contradicts) in links for x in facts for y in facts)
    assert all(k != LinkKind.contradicts for s_, d_, k in links if {s_, d_} == {ra.id, rb.id})
    assert all(r.tsv is not None for r in recs), "every record is searchable"
    cached = CachedEmbedder(HashedEmbedding(384), tmp_path / "cache.sqlite")
    cached.embed([mems[0].records[0].embed])
    assert cached.hits == 1, "embeddings are cached on disk"
