from __future__ import annotations

import json
import shutil
import uuid

import pytest

from cie.eval import extract_facts as ef
from cie.memory import facts as mf
from tests.test_extract_facts import _args, _bench, _fake_model


def test_status_and_checks_without_a_database():
    assert [mf.status_of(r, n) for r, n in (("stop", 3), ("stop", 0), ("length", 9), ("skipped: x", 0), ("error: 500", 0))] == \
        ["done", "empty", "capped", "skipped", None]
    c = mf.checked(["The cap is 64 pages.", "The cap is 128 pages.", "Tags: eviction, cache", "Asha owns it."], "ENG-1", "We cap at 64 pages.")
    assert [x["numbers_in_section"] for x in c] == [True, False, None, None]
    assert [x["tag"] for x in c] == [False, False, True, False] and c[0]["support"] > c[3]["support"]
    s1 = mf.signature({"model": "m", "max_tokens": 768, "model_repo": "r@1"})
    assert s1 == mf.signature({"model_repo": "r@1", "max_tokens": 768, "model": "m"}) != mf.signature({"model": "m", "max_tokens": 512, "model_repo": "r@1"})


@pytest.mark.db
def test_facts_are_stored_in_parts_never_twice_and_with_permissions(session, world, tmp_path):
    from sqlalchemy import select, text

    from cie.core.models import SectionFacts
    from cie.governance.permissions import visible_scopes
    from cie.ingest.builder import build
    from cie.ingest.bulk import BulkLoader, CachedEmbedder
    from cie.ingest.sources import read
    from cie.memory.embeddings import HashedEmbedding
    from tests.conftest import TEST_URL

    session.commit()
    root = _bench(tmp_path)
    src = root / "generated_data" / "sources"
    mems = [build(read(p, str(p.relative_to(src)))) for p in sorted(src.rglob("*.json"))]
    url = TEST_URL.replace("postgresql+psycopg://", "postgresql://")
    loader = BulkLoader(url, tenant_id=world.tenant.id, company_id=world.company.id, scope_ids={"linear": world.legal.id},
                        embedder=CachedEmbedder(HashedEmbedding(384), None), log=lambda *a: None)
    loader.write_batch(mems)
    loader.finish()
    loader.close()

    # a Colab-style run over the same documents, with one passage that failed
    work = tmp_path / "work"
    ef.build_set(root, work, n_docs=None, seed=5, workers=1, log=lambda *a: None)
    passages = ef.load_jsonl(work / "passages.jsonl")

    def flaky(convs):
        return [{"text": "", "prompt_tokens": 0, "output_tokens": 0, "finish_reason": "error: 500"}
                if c[1]["content"].endswith(ef.passage_block(passages[1])) else o for c, o in zip(convs, _fake_model(convs), strict=True)]

    facts_file = work / "facts_fake.jsonl"
    ef.run_extraction(work / "passages.jsonl", facts_file, _args(), generate=flaky, log=lambda *a: None)
    assert sum(ef.failed(r) for r in ef.load_facts(facts_file)) == 1

    conn = mf._connect(url)
    tid = world.tenant.id
    first = mf.import_file(conn, tid, work, facts_file, log=lambda *a: None)
    assert first["added"] == len(passages) - 1 and first["failed_in_file"] == 1 and first.get("stale", 0) == 0
    again = mf.import_file(conn, tid, work, facts_file, log=lambda *a: None)
    assert again["added"] == 0 and again["already_stored"] == len(passages) - 1, "an import is never stored twice"
    sig = first["signature"]
    todo = mf.pending(conn, tid, sig)
    assert len(todo) == 1 and todo[0]["text"] == passages[1]["text"], "the failed passage stays pending"

    # the next run, straight from the database under the same extractor, asks only for what is missing
    settings = {**ef.run_signature("fake", 64), "model_repo": None}
    assert mf.signature(settings) == sig, "an imported run and a database run of one extractor share a signature"
    asked = []
    res = mf.extract(conn, tid, lambda c: asked.extend(c) or _fake_model(c), settings, log=lambda *a: None)
    assert res["asked"] == 1 and len(asked) == 1 and mf.pending(conn, tid, sig) == []

    # a stored row carries its checks; reading needs no re-check and follows permissions
    rows = list(session.scalars(select(SectionFacts).where(SectionFacts.tenant_id == tid)))
    assert len(rows) == len(passages) and all(r.facts and "numbers_in_section" in r.facts[0] for r in rows if r.n_facts)
    sec_ids = [r.section_id for r in rows]
    analyst = mf.facts_for_sections(session, tid, visible_scopes(session, world.analyst), sec_ids)
    outsider = mf.facts_for_sections(session, tid, visible_scopes(session, world.outsider), sec_ids)
    assert len(analyst) == len(passages) and outsider == {}, "facts keep the permissions of their section"

    # a new version of a document with the same text: its sections take the stored facts, the model is not asked
    old = session.execute(text("SELECT id FROM documents WHERE tenant_id = :t AND extra->>'dsid' = :d"),
                          {"t": tid, "d": passages[0]["doc"]}).scalar_one()
    new = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO documents (id, tenant_id, blob_id, family_id, version, previous_version_id, title, original_filename, source, "
                    "scope_id, sensitivity, acl, retention_policy, legal_hold, ingested_at, extra, status, injection_flags, pii_flags) "
                    "SELECT %s, tenant_id, blob_id, family_id, version + 1, id, title, original_filename, source, scope_id, sensitivity, acl, "
                    "retention_policy, legal_hold, now(), extra, status, injection_flags, pii_flags FROM documents WHERE id = %s", (new, old))
        cur.execute("INSERT INTO sections (id, tenant_id, document_id, extraction_id, scope_id, order_index, title, level, page_start, page_end, "
                    "text, text_sha256, token_estimate, spans, sensitivity) SELECT gen_random_uuid(), tenant_id, %s, extraction_id, scope_id, "
                    "order_index, title, level, page_start, page_end, text, text_sha256, token_estimate, spans, sensitivity FROM sections "
                    "WHERE document_id = %s", (new, old))
    conn.commit()
    n_new = len(mf.pending(conn, tid, sig))
    assert n_new == sum(1 for p in passages if p["doc"] == passages[0]["doc"]), "only the new version's sections are pending"

    def must_not_ask(convs):
        raise AssertionError("an unchanged section must not reach the model")

    res = mf.extract(conn, tid, must_not_ask, settings, log=lambda *a: None)
    assert res["reused"] == n_new and res["added"] == n_new and mf.pending(conn, tid, sig) == []

    # a facts file whose passage text is not the memory bank's is refused for that passage
    work2 = tmp_path / "work2"
    shutil.copytree(work, work2)
    ps = ef.load_jsonl(work2 / "passages.jsonl")
    ps[0]["text"] += " Changed after the load."
    (work2 / "passages.jsonl").write_text("\n".join(json.dumps(p) for p in ps) + "\n")
    meta = json.loads((work2 / "facts_fake.run.json").read_text())
    meta["signature"]["model"] = "other"
    (work2 / "facts_fake.run.json").write_text(json.dumps(meta))
    res = mf.import_file(conn, tid, work2, work2 / "facts_fake.jsonl", log=lambda *a: None)
    assert res["stale"] == 1, "facts are never stored against text the model did not read"
    st = mf.status(conn, tid)
    assert st[0]["current_sections"] == len(passages) and {o["signature"] for o in st[1:]} == {sig, res["signature"]}
    assert {o["signature"]: o["pending"] for o in st[1:]} == {sig: 0, res["signature"]: 2}, \
        "the stale passage and the one that failed in the file are still pending"
    conn.close()
