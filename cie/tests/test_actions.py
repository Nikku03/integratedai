"""The action gateway: permission, approval, freshness, already-executed, confirmation; connectors; tasks proposing."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid

import httpx
import pytest

from cie.actions import gateway
from cie.actions.connectors import OutboxConnector, WebhookConnector
from cie.actions.models import Action
from cie.agents.head import create_project
from cie.agents.registry import ensure_default_agents
from cie.core.models import Approval, Job, TaskStatus
from cie.state.events import process_event, submit_event
from cie.state.store import GraphReader
from cie.workflow import engine

pytestmark = pytest.mark.db
S = TaskStatus
GOOD = {"findings": [{"claim": "x", "citations": [{"item_id": "1"}]}], "summary": "ok"}


@pytest.fixture
def proj(session, world):
    return create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")


@pytest.fixture
def agents(session, world):
    return ensure_default_agents(session, world.tenant.id, world.company)


@pytest.fixture
def outbox(tmp_path):
    return OutboxConnector(tmp_path / "outbox.jsonl")


def order(session, world, qty=10):
    ev, _ = submit_event(session, world.tenant.id, kind="ops", idempotency_key=uuid.uuid4().hex,
                         payload={"ops": [{"op": "upsert_node", "type": "order", "key": "po-1", "name": "PO 1", "scope": "Acme",
                                           "attrs": {"qty": qty, "source_system": "erp"}}]})
    process_event(session, ev.id)
    return GraphReader(session, world.tenant.id, None).node_by_key("order", "po-1")


def book(session, world, proj, agent, **kw):
    return gateway.propose(session, tenant_id=world.tenant.id, kind=kw.pop("kind", "book_shipment"), target="outbox",
                           payload=kw.pop("payload", {"carrier": "air", "po": "po-1"}), requested_by=agent.name, agent=agent,
                           project_id=proj.id, **kw)


def test_permission_approval_and_idempotent_proposals(session, world, proj, agents):
    assert book(session, world, proj, agents["legal"]).status == "refused", "legal holds no grant for shipments"
    a = book(session, world, proj, agents["operations"])
    assert a.status == "approved" and [c["check"] for c in a.checks] == ["idempotency", "permission", "approval"]
    assert session.query(Job).filter_by(kind="execute_action").count() == 1, "queued for the worker"
    assert book(session, world, proj, agents["operations"]).id == a.id, "the same action proposed twice is one action"
    agents["legal"].config = {**agents["legal"].config, "actions": ["book_shipment"]}
    again = book(session, world, proj, agents["legal"])
    assert again.status == "approved" and again.id != a.id and again.checks[-3]["detail"].endswith("after it was refused: checked again")
    big = book(session, world, proj, agents["operations"], payload={"carrier": "charter"}, amount=4000)
    assert big.status == "awaiting_approval" and "above operations's spend_usd authority (1000)" in big.checks[-1]["detail"]
    pay = book(session, world, proj, agents["finance"], kind="payment", payload={"to": "carrier", "usd": 50}, amount=50)
    assert pay.status == "awaiting_approval" and "always needs a person's approval" in pay.checks[-1]["detail"], "even within authority"
    ap = session.query(Approval).filter_by(kind="action", subject_id=str(big.id)).one()
    assert "charter" in ap.summary
    gateway.decide(session, big.id, approve=False, by="user:coo", reason="too expensive")
    assert big.status == "rejected"
    with pytest.raises(ValueError, match="only an approved action"):
        gateway.execute(session, big.id, connectors={}, actor="x")


def test_execute_confirm_and_never_twice(session, world, proj, agents, outbox):
    rec = order(session, world)
    a = book(session, world, proj, agents["operations"], records=[{"ref": rec.id, "version": rec.version, "label": "order:po-1"}])
    gateway.execute(session, a.id, connectors={"outbox": outbox}, actor="w")
    assert a.status == "confirmed" and a.receipt["key"] == a.idempotency_key and a.attempts == 1
    assert [c["check"] for c in a.checks][-5:] == ["connector", "permission", "freshness", "executed", "confirmed"]
    gateway.execute(session, a.id, connectors={"outbox": outbox}, actor="w")
    assert a.checks[-1]["check"] == "already_executed" and len(outbox._lines()) == 1, "carried out once"


def test_a_stale_basis_is_not_executed(session, world, proj, agents, outbox):
    rec = order(session, world)
    a = book(session, world, proj, agents["operations"], records=[{"ref": rec.id, "version": rec.version, "label": "order:po-1"}])
    ev, _ = submit_event(session, world.tenant.id, kind="ops", idempotency_key="qty",
                         payload={"ops": [{"op": "revise_node", "ref": ["order", "po-1"], "attrs": {"qty": 12}}]})
    process_event(session, ev.id)
    gateway.execute(session, a.id, connectors={"outbox": outbox}, actor="w")
    assert a.status == "stale" and "order:po-1 is at version 2, not 1" in a.checks[-1]["detail"] and outbox._lines() == []


def test_crash_after_the_call_and_failures_retry_with_the_same_key(session, world, proj, agents, outbox):
    a = book(session, world, proj, agents["operations"])
    outbox.execute(a)  # the other side got it, then the process died before recording that
    a.status = "executing"
    gateway.execute(session, a.id, connectors={"outbox": outbox}, actor="w")
    assert a.status == "confirmed" and len(outbox._lines()) == 1 and "earlier attempt" in a.checks[-1]["detail"]

    class Flaky:
        name, calls = "flaky", 0

        def execute(self, action):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise ConnectionError("carrier API timed out")
            return outbox.execute(action)

        def confirm(self, action):
            return outbox.confirm(action)

    b = book(session, world, proj, agents["operations"], payload={"carrier": "sea"})
    b.target = "flaky"
    gateway.execute(session, b.id, connectors={"flaky": Flaky()}, actor="w")
    assert b.status == "failed" and "timed out" in b.error
    gateway.execute(session, b.id, connectors={"flaky": Flaky()}, actor="w")
    assert b.status == "confirmed" and b.attempts == 2


def test_webhook_connector_signs_and_reads_back(session, world, proj, agents):
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["key"], seen["sig"], seen["body"] = req.headers["Idempotency-Key"], req.headers["X-CIE-Signature"], req.content
            return httpx.Response(201, json={"id": "rcpt-9"})
        return httpx.Response(200, json={"idempotency_key": seen["key"]})

    hook = WebhookConnector("erp", "https://erp.example/actions", "s3cret", client=httpx.Client(transport=httpx.MockTransport(handler)))
    a = book(session, world, proj, agents["operations"])
    a.target = "erp"
    gateway.execute(session, a.id, connectors={"erp": hook}, actor="w")
    assert a.status == "confirmed" and a.receipt["id"] == "rcpt-9" and seen["key"] == a.idempotency_key
    assert seen["sig"] == hmac.new(b"s3cret", seen["body"], hashlib.sha256).hexdigest()


def test_a_task_proposes_actions_when_it_completes_and_the_worker_executes_them(session, world, proj, agents, outbox):
    from cie.workers.worker import handle

    rec = order(session, world)
    t = engine.propose(session, tenant_id=world.tenant.id, project_id=proj.id, scope_id=proj.scope_id, task_type="operations", title="Ship")
    engine.accept(session, t, actor="test")
    engine.claim_task(session, t.id, worker="w", agent_id=agents["operations"].id)
    engine.submit(session, t.id, worker="w", result={**GOOD, "findings": [{**GOOD["findings"][0], "state_refs": [{"ref": str(rec.id), "version": rec.version}]}],
                                                     "actions": [{"kind": "book_shipment", "payload": {"carrier": "air"}}]})
    (a,) = session.query(Action).filter_by(task_id=t.id).all()
    assert a.status == "approved" and a.based_on["task"] == {"id": str(t.id), "revision": t.revision}
    assert a.based_on["records"][0]["label"] == "order:po-1"
    job = session.query(Job).filter_by(kind="execute_action").one()
    assert handle(session, job, connectors={"outbox": outbox})["status"] == "confirmed"
    # a reopened task's actions are stale
    b = gateway.propose(session, tenant_id=world.tenant.id, kind="notify_supplier", target="outbox", payload={"msg": "shipped"},
                        requested_by="operations", agent=agents["operations"], task=t)
    engine.reopen(session, t.id, actor="test", reason="the order changed")
    gateway.execute(session, b.id, connectors={"outbox": outbox}, actor="w")
    assert b.status == "stale" and "the task that proposed it is ready" in b.checks[-1]["detail"]


def test_actions_api(session, world, proj, agents, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key
    from cie.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "actions_outbox", str(tmp_path / "api_outbox.jsonl"))
    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c, h = TestClient(app), {"X-API-Key": k}
    r = c.post("/api/actions", headers=h, json={"project_id": str(proj.id), "kind": "external_message", "payload": {"to": "supplier"}}).json()
    assert r["status"] == "awaiting_approval", "a person proposing an external message still needs an approval"
    ap = session.query(Approval).filter_by(kind="action", subject_id=r["id"]).one()
    assert c.post(f"/api/approvals/{ap.id}/decide", headers=h, json={"approve": True, "reason": "fine"}).status_code == 200
    done = c.post(f"/api/actions/{r['id']}/execute", headers=h).json()
    assert done["status"] == "confirmed" and json.loads((tmp_path / "api_outbox.jsonl").read_text())["key"] == done["idempotency_key"]
    assert [x["id"] for x in c.get("/api/actions", headers=h, params={"project_id": str(proj.id)}).json()] == [r["id"]]
    assert c.post(f"/api/actions/{r['id']}/cancel", headers=h).status_code == 409, "an executed action is not cancelled"
