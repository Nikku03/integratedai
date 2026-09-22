"""HTTP-level vertical slice: ingest → jobs → search → answer → source page → audit."""

from __future__ import annotations

import secrets

import pytest
from fastapi.testclient import TestClient

from cie.api.app import app
from cie.api.deps import hash_key
from tests.fixtures import CONTRACT_SECTIONS, make_pdf

pytestmark = pytest.mark.db


@pytest.fixture
def client(session, world):
    key_admin, key_outsider = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    world.admin.api_key_hash = hash_key(key_admin)
    world.outsider.api_key_hash = hash_key(key_outsider)
    session.commit()
    c = TestClient(app)
    c.admin = {"X-API-Key": key_admin}
    c.outsider = {"X-API-Key": key_outsider}
    return c


def test_vertical_slice_over_http(client, world, session):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/documents").status_code == 401

    pdf = make_pdf(CONTRACT_SECTIONS)
    r = client.post("/api/ingest", headers=client.admin, files={"file": ("msa.pdf", pdf, "application/pdf")},
                    data={"scope_id": str(world.project.id), "doc_type": "contract"})
    assert r.status_code == 200, r.text
    doc = r.json()["document"]
    assert doc["sha256"] and doc["status"] == "ingested" and r.json()["job_id"]

    # OCR / extraction status before processing
    st = client.get(f"/api/documents/{doc['id']}/extraction", headers=client.admin).json()
    assert st["job"]["status"] == "queued"
    done = client.post("/api/jobs/run", headers=client.admin).json()
    assert done and done[0]["status"] == "done", done
    st = client.get(f"/api/documents/{doc['id']}/extraction", headers=client.admin).json()
    assert st["status"] == "indexed" and st["extraction"]["completeness"]["passed"]

    # search + answer with page-level provenance
    res = client.post("/api/search", headers=client.admin, json={"query": "monthly fee", "scope_id": str(world.project.id)})
    assert res.status_code == 200 and res.json()["items"]
    ans = client.post("/api/answer", headers=client.admin,
                      json={"query": "What is the monthly fee in clause 3.1?", "scope_id": str(world.project.id)}).json()
    assert ans["status"] == "answered" and ans["citations"][0]["page_no"] == 4
    cite = ans["citations"][0]
    page = client.get(f"/api/sources/{cite['document_id']}/pages/{cite['page_no']}", headers=client.admin).json()
    assert page["page_no"] == 4 and any(b["id"] == cite["block_id"] for b in page["blocks"])
    img = client.get(f"/api/sources/{cite['document_id']}/pages/{cite['page_no']}/image", headers=client.admin)
    assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content[:4] == b"\x89PNG"
    dl = client.get(f"/api/sources/{cite['document_id']}/download", headers=client.admin)
    assert dl.content == pdf and dl.headers["X-Checksum-SHA256"] == doc["sha256"]

    # the packet can be fetched again by id (reproducibility)
    pk = client.get(f"/api/evidence/{ans['packet_id']}", headers=client.admin).json()
    assert pk["id"] == ans["packet_id"] and pk["items"]

    # permissions: outsider (Finance only) is denied on the Legal project and its documents
    assert client.post("/api/search", headers=client.outsider, json={"query": "monthly fee", "scope_id": str(world.project.id)}).status_code == 403
    assert client.get(f"/api/documents/{doc['id']}", headers=client.outsider).status_code == 403
    assert client.get("/api/documents", headers=client.outsider).json() == []

    # audit trail on the document and the answer
    aud = client.get("/api/audit", headers=client.admin, params={"resource_id": doc["id"]}).json()
    assert {a["action"] for a in aud} >= {"ingest", "source.view", "source.download"}
    assert any(a["outcome"] == "denied" for a in client.get("/api/audit", headers=client.admin).json())

    # memory revision via API
    rec = client.post("/api/memory/records", headers=client.admin, json={
        "scope_id": str(world.project.id), "type": "fact", "summary": "Supplier SLA is 99.5% uptime",
        "content": {"sla": 99.5}, "detail": "SLA 99.5%", "keywords": ["sla", "uptime"]}).json()
    rev = client.post(f"/api/memory/records/{rec['id']}/supersede", headers=client.admin, json={
        "new_record": {"scope_id": str(world.project.id), "type": "fact", "summary": "Supplier SLA is 99.9% uptime",
                       "content": {"sla": 99.9}, "detail": "SLA raised to 99.9%", "keywords": ["sla", "uptime"]},
        "justification": "amendment 2"}).json()
    assert rev["version"] == 2 and rev["supersedes_id"] == rec["id"]
    hist = client.get(f"/api/memory/records/{rec['id']}/history", headers=client.admin).json()
    assert [h["version"] for h in hist] == [1, 2] and hist[0]["superseded_by_id"] == rev["id"]
    m = client.get("/api/metrics/summary", headers=client.admin).json()
    assert m["counts"]["documents"] == 1 and "retrieval_latency_ms" in m["metrics"]
