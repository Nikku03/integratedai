"""Live state: field-level source authority, conflicts, lifecycle, version checks, entity views, consistency."""

from __future__ import annotations

import uuid

import pytest

from cie.governance.permissions import visible_scopes
from cie.state.events import AnalysisWriter, process_event, submit_event
from cie.state.models import StateAuthority, StateConflict, StateField
from cie.state.store import GraphReader, GraphWriter
from cie.state.views import entity_view

pytestmark = pytest.mark.db


def apply(session, world, ops, principal=None, key=None):
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=key or uuid.uuid4().hex,
                         principal_id=principal.id if principal is not None else None)
    return ev, process_event(session, ev.id)


def node(t, key, name=None, scope="Acme", **kw):
    return {"op": "upsert_node", "type": t, "key": key, "name": name or key, "scope": scope, **kw}


def observe(key, field, value, system, kind=None, t="order", **kw):
    return {"op": "observe", "ref": [t, key], "field": field, "value": value,
            "source": {"system": system, **({"kind": kind} if kind else {}), "record": kw.pop("record", "")}, **kw}


def attrs(session, world, t, key):
    return GraphReader(session, world.tenant.id, None).node_by_key(t, key).attrs


def decisions(summary):
    return [(d["field"], d["status"]) for d in summary["field_decisions"]]


@pytest.fixture
def erp_order(session, world):
    apply(session, world, [node("supplier", "s1", "Supplier One"), node("person", "ana", "Ana"),
                           node("order", "o184", "Order 184", attrs={"promised_date": "2026-10-01", "status": "open",
                                                                    "source_system": "erp", "source_date": "2026-09-01"})])


def test_less_authoritative_source_opens_a_conflict_and_keeps_the_current_value(session, world, erp_order):
    _, s = apply(session, world, [observe("o184", "promised_date", "2026-10-20", "mail", kind="email", effective_at="2026-09-20",
                                          evidence=[{"document": "email-1", "quote": "we will ship on 20 Oct"}])])
    assert decisions(s) == [("promised_date", "conflict")]
    assert attrs(session, world, "order", "o184")["promised_date"] == "2026-10-01", "a newer email does not override the ERP"
    c = session.query(StateConflict).one()
    assert c.status == "open" and "more authoritative" in c.reason
    cur = session.query(StateField).filter_by(field="promised_date", status="current").one()
    assert cur.source_system == "erp" and cur.method == "direct_write", "the directly written value became the baseline statement"
    # the ERP itself reports the change later: it becomes current and the dispute is closed
    _, s = apply(session, world, [observe("o184", "promised_date", "2026-10-20", "erp", effective_at="2026-09-21")])
    assert decisions(s) == [("promised_date", "current")]
    assert attrs(session, world, "order", "o184")["promised_date"] == "2026-10-20"
    session.refresh(c)
    assert c.status == "resolved" and c.resolution == "superseded"


def test_more_authoritative_source_replaces_but_not_with_an_older_statement(session, world):
    apply(session, world, [node("order", "o2", "Order 2")])
    _, s = apply(session, world, [observe("o2", "qty", 10, "chat", kind="chat", effective_at="2026-09-10")])
    assert decisions(s) == [("qty", "current")]
    _, s = apply(session, world, [observe("o2", "qty", 12, "erp", effective_at="2026-09-12")])
    assert decisions(s) == [("qty", "current")] and attrs(session, world, "order", "o2")["qty"] == 12
    # a document states a later value, then the ERP sends an older snapshot: that is a conflict, not a replacement
    apply(session, world, [{"op": "observe", "ref": ["order", "o2"], "field": "note", "value": "x", "source": {"system": "crm", "kind": "human"}}])
    _, s = apply(session, world, [observe("o2", "note", "y", "erp", effective_at="2026-01-01")])
    assert decisions(s) == [("note", "current")], "no event time on the current statement: authority decides"
    apply(session, world, [observe("o2", "discount", 5, "crm", kind="human", effective_at="2026-09-20")])
    _, s = apply(session, world, [observe("o2", "discount", 0, "erp", effective_at="2026-09-01")])
    assert decisions(s) == [("discount", "conflict")] and attrs(session, world, "order", "o2")["discount"] == 5


def test_equal_authority_is_ordered_by_event_time_not_arrival(session, world):
    apply(session, world, [node("order", "o3", "Order 3")])
    apply(session, world, [observe("o3", "promised_date", "2026-11-01", "docs", kind="document", effective_at="2026-09-10")])
    _, s = apply(session, world, [observe("o3", "promised_date", "2026-10-01", "wiki", kind="document", effective_at="2026-09-01")])
    assert decisions(s) == [("promised_date", "history")], "a late report of an earlier value is kept as history"
    assert attrs(session, world, "order", "o3")["promised_date"] == "2026-11-01"
    _, s = apply(session, world, [observe("o3", "promised_date", "2026-12-01", "wiki", kind="document", effective_at="2026-09-15")])
    assert decisions(s) == [("promised_date", "current")] and attrs(session, world, "order", "o3")["promised_date"] == "2026-12-01"
    _, s = apply(session, world, [observe("o3", "promised_date", "2026-12-24", "sharepoint", kind="document")])
    assert decisions(s) == [("promised_date", "conflict")], "same rank and no time to order them"
    _, s = apply(session, world, [observe("o3", "promised_date", "2026-12-01", "notes", kind="document")])
    assert decisions(s) == [("promised_date", "corroboration")]


def test_authority_rules_override_the_default_ranks(session, world, erp_order):
    session.add(StateAuthority(tenant_id=world.tenant.id, entity_type="order", field="promised_date", source_system="supplier_portal", rank=5))
    session.flush()
    _, s = apply(session, world, [observe("o184", "promised_date", "2026-10-05", "supplier_portal", kind="document")])
    assert decisions(s) == [("promised_date", "current")] and attrs(session, world, "order", "o184")["promised_date"] == "2026-10-05"
    assert "authority rule order.promised_date" in s["field_decisions"][0]["reason"]
    _, s = apply(session, world, [observe("o184", "qty", 3, "supplier_portal", kind="document")])
    assert decisions(s) == [("qty", "current")], "the rule is per field; qty had no value yet"


def test_status_changes_follow_the_lifecycle(session, world, erp_order):
    _, s = apply(session, world, [{"op": "set_status", "ref": ["order", "o184"], "status": "shipped", "source": {"system": "erp"}}])
    assert decisions(s) == [("status", "current")] and attrs(session, world, "order", "o184")["status"] == "shipped"
    _, s = apply(session, world, [{"op": "set_status", "ref": ["order", "o184"], "status": "open", "source": {"system": "erp"}}])
    assert decisions(s) == [("status", "history")], "an earlier status arriving late is a late report"
    assert attrs(session, world, "order", "o184")["status"] == "shipped"
    _, s = apply(session, world, [{"op": "set_status", "ref": ["order", "o184"], "status": "cancelled", "source": {"system": "erp"}}])
    assert decisions(s) == [("status", "conflict")], "shipped -> cancelled is not an allowed transition"
    assert "cannot go from 'shipped' to 'cancelled'" in s["field_decisions"][0]["reason"]
    assert attrs(session, world, "order", "o184")["status"] == "shipped"
    _, s = apply(session, world, [{"op": "set_status", "ref": ["order", "o184"], "status": "teleported", "source": {"system": "erp"}}])
    assert decisions(s) == [("status", "conflict")] and "is not a status of order" in s["field_decisions"][0]["reason"]


def test_resolving_a_conflict(session, world, erp_order):
    apply(session, world, [observe("o184", "promised_date", "2026-10-20", "mail", kind="email")])
    c = session.query(StateConflict).one()
    _, s = apply(session, world, [{"op": "resolve_conflict", "conflict": str(c.id), "accept": "challenger", "note": "confirmed by phone"}],
                 principal=world.admin)
    assert attrs(session, world, "order", "o184")["promised_date"] == "2026-10-20"
    session.refresh(c)
    assert c.status == "resolved" and c.resolution == "accepted_challenger" and c.resolved_by == world.admin.id
    apply(session, world, [observe("o184", "qty", 1, "erp"), observe("o184", "qty", 2, "mail", kind="email")])
    c2 = session.query(StateConflict).filter_by(status="open").one()
    apply(session, world, [{"op": "resolve_conflict", "conflict": str(c2.id), "accept": "current"}])
    assert attrs(session, world, "order", "o184")["qty"] == 1
    assert session.get(StateField, c2.challenger_field_id).status == "rejected"
    with pytest.raises(ValueError, match="already resolved"):
        apply(session, world, [{"op": "resolve_conflict", "conflict": str(c2.id), "accept": "current"}])


def test_stale_write_is_refused_whole(session, world, erp_order):
    v = GraphReader(session, world.tenant.id, None).node_by_key("order", "o184").version
    last = GraphReader(session, world.tenant.id, None).seq
    ev, s = apply(session, world, [observe("o184", "qty", 5, "erp"),
                                   {"op": "set_status", "ref": ["order", "o184"], "status": "shipped", "source": {"system": "erp"},
                                    "expected_version": v - 1}])
    assert ev.status == "conflict" and "re-read it and resubmit" in ev.error
    assert "qty" not in attrs(session, world, "order", "o184"), "nothing of a refused event is applied"
    assert GraphReader(session, world.tenant.id, None).seq == last, "and it takes no sequence number"
    assert process_event(session, ev.id)["status"] == "conflict", "processing it again changes nothing"
    ev, s = apply(session, world, [{"op": "set_status", "ref": ["order", "o184"], "status": "shipped", "source": {"system": "erp"},
                                    "expected_version": v}])
    assert ev.status == "done" and attrs(session, world, "order", "o184")["status"] == "shipped"


def test_direct_write_marks_the_statement_it_overwrote(session, world, erp_order):
    apply(session, world, [observe("o184", "qty", 5, "erp")])
    _, s = apply(session, world, [{"op": "revise_node", "ref": ["order", "o184"], "attrs": {"qty": 7}}])
    assert s["overwritten_statements"] == 1
    assert session.query(StateField).filter_by(field="qty", status="overwritten").count() == 1
    view = entity_view(session, GraphReader(session, world.tenant.id, None), "order", "o184")
    assert view["facts"]["qty"]["value"] == 7 and view["facts"]["qty"]["statement"]["source"]["method"] == "direct_write"


def test_verification_needs_permission(session, world, erp_order):
    from cie.core.models import Permission, Principal, PrincipalKind
    from cie.governance.permissions import ensure_role, grant_role

    ed = Principal(tenant_id=world.tenant.id, kind=PrincipalKind.user, name="editor", attributes={})
    session.add(ed)
    session.flush()
    grant_role(session, tenant_id=world.tenant.id, principal=ed, role=ensure_role(session, world.tenant.id, "editor", Permission.write, 2),
               scope=world.company)
    session.flush()
    ev, _ = apply(session, world, [{"op": "verify_entity", "ref": ["order", "o184"], "method": "checked against ERP"}], principal=ed)
    assert ev.status == "rejected"
    ed.attributes = {"can_verify": True}
    session.flush()
    ev, _ = apply(session, world, [{"op": "verify_entity", "ref": ["order", "o184"], "method": "checked against ERP"}], principal=ed)
    assert ev.status == "done"
    view = entity_view(session, GraphReader(session, world.tenant.id, None), "order", "o184")
    assert view["last_verified_at"] and view["verification"] == "verified"
    assert view["facts"]["promised_date"]["statement"]["verification"] == "verified"


def test_entity_view(session, world, erp_order):
    apply(session, world, [node("milestone", "m1", "Milestone 1", attrs={"status": "planned"}),
                           {"op": "upsert_edge", "src": ["order", "o184"], "kind": "depends_on", "dst": ["supplier", "s1"]},
                           {"op": "upsert_edge", "src": ["milestone", "m1"], "kind": "depends_on", "dst": ["order", "o184"]},
                           {"op": "set_owner", "ref": ["order", "o184"], "owner": "ana", "source": {"system": "erp"}},
                           observe("o184", "promised_date", "2026-10-20", "mail", kind="email",
                                   evidence=[{"document": "email-1", "quote": "20 Oct"}])])
    v = entity_view(session, GraphReader(session, world.tenant.id, None), "order", "o184")
    assert v["entity_id"] == "order:o184" and v["status"] == "open" and v["owner"] == "ana" and v["version"] >= 2
    assert {(d["relation"], d["direction"], d["key"]) for d in v["dependencies"]} >= {
        ("depends_on", "out", "s1"), ("depends_on", "in", "m1"), ("owned_by", "out", "ana")}
    assert v["facts"]["promised_date"]["value"] == "2026-10-01"
    assert v["facts"]["promised_date"]["statement"]["source"]["system"] == "erp"
    assert v["unresolved"][0]["field"] == "promised_date" and v["unresolved"][0]["challenger"]["value"] == "2026-10-20"
    assert v["unresolved"][0]["challenger"]["evidence"][0]["document"] == "email-1"
    # someone who may not see the order gets nothing
    apply(session, world, [{"op": "restrict_node", "ref": ["order", "o184"], "scope": "Legal"}])
    assert entity_view(session, GraphReader(session, world.tenant.id, visible_scopes(session, world.analyst)), "order", "o184") is not None
    assert entity_view(session, GraphReader(session, world.tenant.id, visible_scopes(session, world.outsider)), "order", "o184") is None
    seen = entity_view(session, GraphReader(session, world.tenant.id, visible_scopes(session, world.analyst)), "order", "o184")
    assert not {"s1", "m1", "ana"} & {d["key"] for d in seen["dependencies"]}, "dependencies it may not see are left out"


def test_restricting_a_source_narrows_generated_content_without_any_analysis(session, world):
    apply(session, world, [node("contract", "c1", "Contract 1"), node("artifact", "sum", "Summary", authoritative=False),
                           {"op": "upsert_edge", "src": ["artifact", "sum"], "kind": "derived_from", "dst": ["contract", "c1"]}])
    _, s = apply(session, world, [{"op": "restrict_node", "ref": ["contract", "c1"], "scope": "Legal", "sensitivity": 3}])
    assert s["policy"] == "none" and s["impacts"] == 0
    r = GraphReader(session, world.tenant.id, None)
    art = r.node_by_key("artifact", "sum")
    assert art.scope_id == world.legal.id and art.sensitivity == 3 and art.review_status == "invalidated"
    _, s = apply(session, world, [{"op": "revise_node", "ref": ["contract", "c1"], "attrs": {"term": "5y"}}])
    assert s["invalidated"] == [], "already invalidated; not marked twice"


def test_analysis_writer_only_writes_derived_content(session, world):
    apply(session, world, [node("order", "o9", "Order 9"), node("artifact", "a9", "Gen", authoritative=False)])
    w = GraphWriter(session, world.tenant.id)
    w.begin()
    aw = AnalysisWriter(w)
    o9 = w.node_id("order", "o9")
    with pytest.raises(PermissionError):
        aw.revise(o9, review_status="invalidated")
    with pytest.raises(PermissionError):
        aw.revise(w.node_id("artifact", "a9"), scope_id=world.legal.id)
    with pytest.raises(PermissionError):
        aw.upsert_edge(o9, "depends_on", w.node_id("artifact", "a9"), provenance="explicit")
    assert aw.revise(w.node_id("artifact", "a9"), review_status="needs_review")


def test_state_api(session, world, erp_order):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    keys = {p: secrets.token_urlsafe(12) for p in ("admin", "outsider", "analyst")}
    for p, k in keys.items():
        getattr(world, p).api_key_hash = hash_key(k)
    session.commit()
    c = TestClient(app)
    h = {p: {"X-API-Key": k} for p, k in keys.items()}
    body = {"kind": "ops", "idempotency_key": "e1", "payload": {"ops": [observe("o184", "promised_date", "2026-10-20", "mail", kind="email")]}}
    r = c.post("/api/state/events", headers=h["outsider"], json=body)
    assert r.status_code == 403, "readers cannot write"
    r = c.post("/api/state/events", headers=h["admin"], json=body)
    assert r.status_code == 202 and r.json()["field_decisions"][0]["status"] == "conflict"
    assert c.post("/api/state/events", headers=h["admin"], json=body).json()["created"] is False
    v = c.get("/api/state/entities/order/o184", headers=h["admin"]).json()
    assert v["facts"]["promised_date"]["value"] == "2026-10-01" and len(v["unresolved"]) == 1
    assert c.get("/api/state/entities/order/o184", headers=h["analyst"]).status_code == 404, "company-scope record, Legal reader"
    assert c.get("/api/state/entities/order/nope", headers=h["admin"]).status_code == 404
    assert c.get("/api/state/conflicts", headers=h["analyst"]).json()["conflicts"] == []
    conflicts = c.get("/api/state/conflicts", headers=h["admin"]).json()["conflicts"]
    assert len(conflicts) == 1
    assert c.get(f"/api/state/events/{r.json()['event_id']}", headers=h["analyst"]).status_code == 404, "not the submitter"
    assert c.get(f"/api/state/events/{r.json()['event_id']}", headers=h["admin"]).json()["status"] == "done"
    r2 = c.post(f"/api/state/conflicts/{conflicts[0]['conflict_id']}/resolve", headers=h["admin"], json={"accept": "challenger"})
    assert r2.status_code == 200 and r2.json()["status"] == "done"
    assert c.get("/api/state/entities/order/o184", headers=h["admin"]).json()["facts"]["promised_date"]["value"] == "2026-10-20"
    stale = {"kind": "ops", "idempotency_key": "e2", "payload": {"ops": [
        {"op": "set_status", "ref": ["order", "o184"], "status": "shipped", "source": {"system": "erp"}, "expected_version": 1}]}}
    assert c.post("/api/state/events", headers=h["admin"], json=stale).status_code == 409
    rule = {"entity_type": "order", "field": "promised_date", "source_system": "mail", "rank": 1}
    assert c.put("/api/state/authority", headers=h["analyst"], json=rule).status_code == 403
    assert c.put("/api/state/authority", headers=h["admin"], json=rule).status_code == 200
    assert c.get("/api/state/authority", headers=h["analyst"]).json()["rules"][0]["source_system"] == "mail"
