"""HTTP-level agents and governance: run a project, inspect routing, approvals,
legal hold, deletion workflow."""

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
    key = secrets.token_urlsafe(16)
    world.admin.api_key_hash = hash_key(key)
    session.commit()
    c = TestClient(app)
    c.h = {"X-API-Key": key}
    return c


def test_project_run_and_agent_apis(client, world):
    pdf = make_pdf(CONTRACT_SECTIONS)
    doc = client.post("/api/ingest", headers=client.h, files={"file": ("msa.pdf", pdf, "application/pdf")},
                      data={"scope_id": str(world.project.id), "doc_type": "contract"}).json()["document"]
    client.post("/api/jobs/run", headers=client.h)
    agents = client.get("/api/agents", headers=client.h).json()
    assert {a["name"] for a in agents} == {"head", "research", "finance", "legal", "operations", "engineering"}
    proj = client.post("/api/projects", headers=client.h, json={"name": "Renegotiation", "parent_scope_id": str(world.legal.id)}).json()
    # a document in the project scope so agents have evidence
    client.post("/api/ingest", headers=client.h, files={"file": ("msa2.pdf", pdf, "application/pdf")},
                data={"scope_id": proj["scope_id"], "doc_type": "contract"})
    client.post("/api/jobs/run", headers=client.h)
    run = client.post(f"/api/projects/{proj['id']}/run", headers=client.h,
                      json={"objective": "Assess termination clauses and fee penalties of the Northwind agreement and plan the renegotiation"}).json()
    assert run["status"] == "completed" and run["ledger"]["synthesis"]
    tasks = client.get("/api/tasks", headers=client.h, params={"project_id": proj["id"]}).json()
    assert {t["task_type"] for t in tasks} >= {"research", "legal", "finance", "operations", "synthesis", "verification"}
    legal = next(t for t in tasks if t["task_type"] == "legal")
    assert legal["assigned_agent"] == "legal" and "chosen" in legal["assignment_reason"]["decision"]
    route = client.post(f"/api/tasks/{legal['id']}/route", headers=client.h).json()
    assert route["reason"]["candidates"]
    led = client.get(f"/api/projects/{proj['id']}/ledger", headers=client.h).json()
    assert led["chain_valid"] and led["entries"][0]["kind"] == "objective"
    fa = client.get(f"/api/projects/{proj['id']}/final-answer", headers=client.h).json()
    assert fa["citations"] and "confidence" in fa
    msgs = client.get("/api/messages", headers=client.h, params={"project_id": proj["id"]}).json()
    assert msgs and all(m["to"] for m in msgs)
    sc = client.get(f"/api/agents/{next(a['id'] for a in agents if a['name'] == 'legal')}/scorecards", headers=client.h).json()
    assert any(s["task_type"] == "legal" for s in sc["scorecards"])
    # human grading feeds the scorecard
    out = client.post(f"/api/agents/{next(a['id'] for a in agents if a['name'] == 'legal')}/outcome", headers=client.h,
                      json={"task_type": "legal", "accuracy": 0.9, "human_corrections": 1}).json()
    assert out["human_corrections"] == 1
    # bad message kind payload is rejected
    bad = client.post("/api/messages", headers=client.h, json={"project_id": proj["id"], "kind": "contradiction", "payload": {"task_id": "x"}, "to_agent": "legal"})
    assert bad.status_code == 400
    _ = doc


def test_deletion_workflow_with_legal_hold_and_approval(client, world, session):
    pdf = make_pdf(CONTRACT_SECTIONS[:2])
    doc = client.post("/api/ingest", headers=client.h, files={"file": ("x.pdf", pdf, "application/pdf")},
                      data={"scope_id": str(world.project.id)}).json()["document"]
    client.post("/api/jobs/run", headers=client.h)
    assert client.post(f"/api/documents/{doc['id']}/retention", headers=client.h, params={"policy": "1y"}).json()["retain_until"]
    assert client.post(f"/api/documents/{doc['id']}/legal-hold", headers=client.h, params={"on": True}).json()["legal_hold"]
    req = client.post("/api/deletion-requests", headers=client.h, json={"document_id": doc["id"], "reason": "GDPR request"}).json()
    assert req["status"] == "blocked_hold" and req["approval_id"] is None
    client.post(f"/api/documents/{doc['id']}/legal-hold", headers=client.h, params={"on": False})
    req = client.post("/api/deletion-requests", headers=client.h, json={"document_id": doc["id"], "reason": "GDPR request"}).json()
    assert req["status"] == "pending" and req["approval_id"]
    # still readable until approved
    assert client.get(f"/api/documents/{doc['id']}", headers=client.h).status_code == 200
    pend = client.get("/api/approvals", headers=client.h).json()
    assert any(a["id"] == req["approval_id"] and a["kind"] == "deletion" for a in pend)
    dec = client.post(f"/api/approvals/{req['approval_id']}/decide", headers=client.h, json={"approve": True, "reason": "ok"}).json()
    assert dec["status"] == "approved"
    assert client.get(f"/api/documents/{doc['id']}", headers=client.h).status_code == 404
    reqs = client.get("/api/deletion-requests", headers=client.h).json()
    assert any(r["status"] == "executed" for r in reqs)
    # no memory record from the deleted document is retrievable
    res = client.post("/api/search", headers=client.h, json={"query": "Master Services Agreement", "scope_id": str(world.project.id)}).json()
    assert all(it.get("document_id") != doc["id"] for it in res["items"])
    aud = client.get("/api/audit", headers=client.h, params={"resource_id": doc["id"]}).json()
    assert {a["action"] for a in aud} >= {"legal_hold.set", "legal_hold.clear", "deletion.request", "deletion.execute"}
    flags = client.get("/api/documents/" + doc["id"] + "/flags", headers=client.h)
    assert flags.status_code == 404  # deleted
