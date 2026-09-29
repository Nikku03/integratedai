"""Identity resolution for business entities: identifiers decide, names only propose, confirmation merges."""

from __future__ import annotations

import uuid

import pytest

from cie.state.events import process_event, submit_event
from cie.state.models import StateConflict, StateIdentifier, StateMatchProposal
from cie.state.store import GraphReader
from cie.state.views import entity_view

pytestmark = pytest.mark.db


def apply(session, world, ops, principal=None):
    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=uuid.uuid4().hex,
                         principal_id=principal.id if principal is not None else None)
    return ev, process_event(session, ev.id)


def entity(t, name, scope="Acme", **kw):
    return {"op": "upsert_entity", "type": t, "name": name, "scope": scope, **kw}


def ident(summary, i=0):
    return summary["identity"][i]


def test_strong_identifier_matches_and_names_do_not(session, world):
    _, s = apply(session, world, [entity("supplier", "Northwind Ltd", identifiers={"vat": "GB 123 456"},
                                         attrs={"payment_terms": "30d"}, source={"system": "erp"})])
    first = ident(s)
    assert first["resolution"] == "new" and first["key"].startswith("supplier_")
    _, s = apply(session, world, [entity("supplier", "Northwind Logistics", identifiers={"vat": "gb123456"})])
    assert ident(s)["resolution"] == "matched" and ident(s)["node"] == first["node"] and ident(s)["method"] == "strong_identifier"
    names = session.query(StateIdentifier).filter_by(scheme="name").all()
    assert [n.value for n in names] == ["northwind logistics"], "the other spelling is kept as a weak identifier"
    # a different VAT number means a different supplier, however alike the name
    _, s = apply(session, world, [entity("supplier", "Northwind Ltd", identifiers={"vat": "GB999"})])
    assert ident(s)["resolution"] == "new" and ident(s)["proposals"] == []
    assert ident(s)["distinct_from"][0]["key"] == first["key"]
    # the same name with no identifiers only proposes a match; it is never merged
    _, s = apply(session, world, [entity("supplier", "Northwind Limited")])
    other = ident(s)
    assert other["resolution"] == "new" and other["node"] != first["node"]
    assert len(other["proposals"]) == 2, "both Northwind records are possible matches"
    assert session.query(StateMatchProposal).filter_by(status="proposed").count() == 2


def test_identifiers_pointing_to_different_records_are_not_decided(session, world):
    apply(session, world, [entity("customer", "Alpine Ski House", key="c1", identifiers={"vat": "AT1"}),
                           entity("customer", "Alpine Ski", key="c2", identifiers={"customer_number": "C-2"})])
    _, s = apply(session, world, [entity("customer", "Alpine Ski House", identifiers={"vat": "AT1", "customer_number": "C-2"})])
    r = ident(s)
    assert r["resolution"] == "conflicting_identifiers" and len(r["proposals"]) == 2, "a new record, proposed with each holder"
    assert all(i["status"] != "added" or i["scheme"] == "name" for i in r["identifiers"]), "held identifiers are not claimed twice"
    assert session.query(StateMatchProposal).filter_by(method="shared_strong_identifier").count() == 2


def test_rejected_pairs_are_not_proposed_again(session, world):
    apply(session, world, [entity("customer", "Contoso Medical GmbH", key="c1")])
    _, s = apply(session, world, [entity("customer", "Contoso Medical AG", key="c2")])
    pid = ident(s)["proposals"][0]["proposal"]
    apply(session, world, [{"op": "reject_match", "proposal": pid, "note": "different legal entities"}])
    _, s = apply(session, world, [{"op": "add_identifier", "ref": ["customer", "c2"], "scheme": "phone", "value": "+43 1 234"},
                                  entity("customer", "Contoso Medical AG", key="c2", attrs={"segment": "health"})])
    assert ident(s, 1)["resolution"] == "matched" and ident(s, 1)["method"] == "business_key" and ident(s, 1)["proposals"] == []
    _, s = apply(session, world, [entity("customer", "Contoso Medical AG")])
    assert {p["with"] for p in ident(s)["proposals"]} == {"c1", "c2"}, "a third record may still be proposed with each"
    w = session.query(StateMatchProposal).filter_by(status="rejected").one()
    assert "rejected: different legal entities" in w.reasons


def test_confirming_a_match_merges_into_the_older_record(session, world):
    apply(session, world, [{"op": "upsert_node", "type": "project", "key": "p1", "name": "Project 1", "scope": "Acme"},
                           entity("supplier", "Fabrikam Inc", key="fab", identifiers={"supplier_number": "S-17"},
                                  attrs={"payment_terms": "30d"}, source={"system": "erp"})])
    _, s = apply(session, world, [entity("supplier", "Fabrikam Incorporated", key="fab2", identifiers={"phone": "+44 20 7946 0000"},
                                         attrs={"payment_terms": "45d", "country": "UK"}, source={"system": "mail", "kind": "email"}),
                                  {"op": "upsert_node", "type": "order", "key": "o1", "name": "Order 1", "scope": "Acme"},
                                  {"op": "upsert_edge", "src": ["order", "o1"], "kind": "depends_on", "dst": ["supplier", "fab2"]}])
    pid = ident(s)["proposals"][0]["proposal"]
    assert GraphReader(session, world.tenant.id, None).node_by_key("supplier", "fab").attrs["payment_terms"] == "30d"
    ev, s = apply(session, world, [{"op": "confirm_match", "proposal": pid, "note": "same company, checked registry"}], principal=world.admin)
    m = s["identity"][-1]
    assert m["op"] == "merge" and m["canonical_key"] == "fab" and m["alias_key"] == "fab2" and m["relationships_moved"] == 1
    replayed = {r["field"]: r["status"] for r in m["statements_replayed"]}
    assert replayed == {"payment_terms": "conflict", "country": "current"}, "the email's terms do not beat the ERP's"
    r = GraphReader(session, world.tenant.id, None)
    fab = r.node_by_key("supplier", "fab")
    assert fab.attrs["payment_terms"] == "30d" and fab.attrs["country"] == "UK"
    assert r.node_by_key("supplier", "fab2") is None
    edges, views, _ = r.edges([fab.id], kinds=("depends_on",), direction="in")
    assert [views[e.src].key for e in edges] == ["o1"]
    assert {(i.scheme, i.node_id) for i in session.query(StateIdentifier).filter_by(status="active")} >= {
        ("supplier_number", fab.id), ("phone", fab.id)}, "identifiers move; the same normalised name adds no alias name"
    assert session.query(StateConflict).filter_by(node_id=fab.id, field="payment_terms", status="open").count() == 1
    assert session.get(StateMatchProposal, uuid.UUID(pid)).status == "confirmed"
    # the old key keeps resolving to the canonical record
    apply(session, world, [{"op": "upsert_edge", "src": ["supplier", "fab2"], "kind": "supplies", "dst": ["project", "p1"]}])
    assert len(GraphReader(session, world.tenant.id, None).edges([fab.id], kinds=("supplies",), direction="out")[0]) == 1
    v = entity_view(session, GraphReader(session, world.tenant.id, None), "supplier", "fab2")
    assert v["resolved_from"] == "supplier:fab2" and v["key"] == "fab" and "supplier:fab2" in v["aliases"]
    assert {"scheme": "supplier_number", "value": "S17", "strength": "strong"} in v["identifiers"]
    # an import that still sends the old key: its values become statements about the canonical record
    _, s = apply(session, world, [{"op": "upsert_node", "type": "supplier", "key": "fab2", "name": "Fabrikam Incorporated", "scope": "Acme",
                                   "attrs": {"country": "GB", "source_system": "erp"}}])
    assert s["identity"][0]["redirected_from"]
    r = GraphReader(session, world.tenant.id, None)
    assert r.node_by_key("supplier", "fab2") is None and r.node_by_key("supplier", "fab").attrs["country"] == "GB"
    # a reference by identifier finds it too
    _, s = apply(session, world, [{"op": "observe", "ref": {"type": "supplier", "scheme": "supplier_number", "value": "s-17"},
                                   "field": "rating", "value": "A", "source": {"system": "erp"}}])
    assert s["field_decisions"][0]["node"] == str(fab.id)


def test_merge_refusals(session, world):
    apply(session, world, [entity("supplier", "Adatum Corp", key="a1", identifiers={"vat": "DE1"})])
    _, s = apply(session, world, [entity("supplier", "Adatum Corporation", key="a2")])
    pid = ident(s)["proposals"][0]["proposal"]
    apply(session, world, [{"op": "add_identifier", "ref": ["supplier", "a2"], "scheme": "vat", "value": "DE2"}])
    with pytest.raises(ValueError, match="different entities"):
        apply(session, world, [{"op": "confirm_match", "proposal": pid}])


def test_merge_needs_the_same_access(session, world):
    apply(session, world, [entity("customer", "Tailspin Toys", key="t1")])
    _, s = apply(session, world, [entity("customer", "Tailspin Toys Ltd", key="t2", scope="Legal")])
    pid = ident(s)["proposals"][0]["proposal"]
    with pytest.raises(ValueError, match="different access"):
        apply(session, world, [{"op": "confirm_match", "proposal": pid}])


def test_shared_strong_identifier_found_later_is_proposed_not_merged(session, world):
    apply(session, world, [entity("supplier", "Litware", key="l1", identifiers={"duns": "123"}), entity("supplier", "LW Group", key="l2")])
    _, s = apply(session, world, [{"op": "add_identifier", "ref": ["supplier", "l2"], "scheme": "duns", "value": "123"}])
    assert s["identity"][0]["status"] == "held_by_another_record"
    p = session.query(StateMatchProposal).one()
    assert p.method == "shared_strong_identifier" and p.score == 100.0
    assert GraphReader(session, world.tenant.id, None).node_by_key("supplier", "l2") is not None


def test_confirming_needs_write_access_to_both_records(session, world):
    from cie.core.models import Permission, Principal, PrincipalKind
    from cie.governance.permissions import ensure_role, grant_role

    ed = Principal(tenant_id=world.tenant.id, kind=PrincipalKind.user, name="legal-editor", attributes={})
    session.add(ed)
    session.flush()
    grant_role(session, tenant_id=world.tenant.id, principal=ed, role=ensure_role(session, world.tenant.id, "editor", Permission.write, 2),
               scope=world.legal)
    apply(session, world, [entity("person", "Dana Lee", key="d1", scope="Legal"), entity("person", "Dana Lee", key="d2", scope="Legal")])
    p = session.query(StateMatchProposal).one()
    ev, _ = apply(session, world, [{"op": "confirm_match", "proposal": str(p.id)}], principal=ed)
    assert ev.status == "done"
    apply(session, world, [entity("person", "Sam Roe", key="s1"), entity("person", "Sam Roe", key="s2", scope="Legal")])
    p2 = session.query(StateMatchProposal).filter_by(status="proposed").one()
    ev, _ = apply(session, world, [{"op": "confirm_match", "proposal": str(p2.id)}], principal=ed)
    assert ev.status == "rejected", "no write access to the company-scope record"


def test_identity_api(session, world):
    import secrets

    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key

    keys = {p: secrets.token_urlsafe(12) for p in ("admin", "analyst")}
    for p, k in keys.items():
        getattr(world, p).api_key_hash = hash_key(k)
    apply(session, world, [entity("supplier", "Proseware Inc", key="pw", identifiers={"vat": "FR77"}),
                           entity("supplier", "Proseware Incorporated", key="pw2")])
    session.commit()
    c = TestClient(app)
    h = {p: {"X-API-Key": k} for p, k in keys.items()}
    r = c.post("/api/state/identity/resolve", headers=h["admin"], json={"type": "supplier", "name": "Proseware", "identifiers": {"vat": "fr 77"}})
    assert r.json()["status"] == "matched" and r.json()["record"]["key"] == "pw"
    r = c.post("/api/state/identity/resolve", headers=h["analyst"], json={"type": "supplier", "name": "Proseware", "identifiers": {"vat": "FR77"}})
    assert r.json()["record"] is None and r.json()["note"], "a match the caller may not see is not described"
    r = c.post("/api/state/identity/resolve", headers=h["admin"], json={"type": "supplier", "name": "Proseware Incorporated"})
    assert r.json()["status"] == "new" and {m["key"] for m in r.json()["possible_matches"]} == {"pw", "pw2"}
    assert c.get("/api/state/identity/proposals", headers=h["analyst"]).json()["proposals"] == []
    props = c.get("/api/state/identity/proposals", headers=h["admin"]).json()["proposals"]
    assert len(props) == 1
    r = c.post(f"/api/state/identity/proposals/{props[0]['proposal_id']}/confirm", headers=h["admin"], json={"note": "same"})
    assert r.status_code == 200 and r.json()["identity"][-1]["canonical_key"] == "pw"
    assert c.get("/api/state/entities/supplier/pw2", headers=h["admin"]).json()["key"] == "pw"
