"""Playbooks: three-valued decisions, proofs and their checker, missing facts, drafting, storage and approval,
live facts, deciding again on change, the action gateway, the API and the command line."""

from __future__ import annotations

import copy
import json
import secrets
import uuid

import pytest

from cie.playbooks.draft import draft
from cie.playbooks.logic import compile_playbook, evaluate, problems, summary, verify

SHIP = {
    "name": "Shipping release", "question": "May the order ship?", "decision": "may_ship",
    "facts": {"approved": {"type": "boolean"}, "inspected": {"type": "boolean"}, "supplier_certified": {"type": "boolean"},
              "permit_revoked": {"type": "boolean"}},
    "rules": [{"name": "may_ship", "when": "approved and inspected and supplier_certified unless permit_revoked",
               "quote": "Ship only when approved, inspected and the supplier is certified, unless the permit is revoked."}],
}

SPEND = {
    "name": "Expense approval", "question": "May the expense be paid?", "decision": "may_pay",
    "facts": {"amount_usd": {"type": "number", "description": "amount in US dollars"},
              "expense_type": {"type": "text", "values": ["reimbursable", "capital", "strategic"]},
              "approvals": {"type": "list", "values": ["manager", "finance", "legal", "exec"]},
              "receipts": {"type": "boolean"}, "submitted_on": {"type": "date"}},
    "rules": [
        {"name": "needs_finance", "when": "amount_usd > 250", "quote": "$251–$2,500 | Manager + Finance reviewer"},
        {"name": "needs_legal", "when": "amount_usd > 25000 or expense_type == \"strategic\"", "quote": "> $25,000 | Finance + Legal"},
        {"name": "approved_enough", "when": "\"manager\" in approvals and (not needs_finance or \"finance\" in approvals) "
                                            "and (not needs_legal or \"legal\" in approvals)"},
        {"name": "on_time", "when": "submitted_on <= 2026-12-31"},
        {"name": "may_pay", "when": "approved_enough and on_time and (receipts or amount_usd <= 250)"},
    ],
}


@pytest.fixture(scope="module")
def ship():
    return compile_playbook(SHIP)


@pytest.fixture(scope="module")
def spend():
    return compile_playbook(SPEND)


# ---------------------------------------------------------------------------------------------- logic
def test_unknown_is_not_false(ship):
    base = {"approved": True, "inspected": True, "permit_revoked": False}
    d = evaluate(ship, base)
    assert d.answer == "unknown" and summary(d) == "unknown: needs supplier_certified"
    assert evaluate(ship, {**base, "supplier_certified": False}).answer == "no"
    assert evaluate(ship, {**base, "supplier_certified": True}).answer == "yes"
    assert evaluate(ship, {**base, "supplier_certified": True, "permit_revoked": None}).answer == "unknown", "an unknown exception"
    assert evaluate(ship, {"approved": False}).answer == "no", "a false part settles it, whatever is unknown"
    assert evaluate(ship, {**base, "supplier_certified": True, "permit_revoked": True}).answer == "no"


def test_only_what_the_goal_needs_is_read(ship):
    d = evaluate(ship, {"approved": True, "inspected": False, "supplier_certified": True})
    assert d.answer == "no" and d.facts_read == 2 and d.rules_evaluated == 1, "it stops at the first false part"
    many = copy.deepcopy(SHIP)
    many["facts"].update({f"noise_{i}": {"type": "number"} for i in range(300)})
    many["rules"] += [{"name": f"noise_rule_{i}", "when": f"noise_{i} > {i}"} for i in range(300)]
    d = evaluate(compile_playbook(many), {"approved": True, "inspected": True, "supplier_certified": True, "permit_revoked": False})
    assert d.answer == "yes" and d.rules_evaluated == 1 and d.facts_read == 4, "300 unrelated rules are never touched"


def test_numbers_dates_text_and_lists(spend):
    ok = {"approvals": ["manager", "finance"], "receipts": True, "submitted_on": "2026-10-01", "expense_type": "capital"}
    assert evaluate(spend, {**ok, "amount_usd": 2500}).answer == "yes"
    assert evaluate(spend, {**ok, "amount_usd": "$25,001"}).answer == "no", "above 25,000 legal must approve too"
    assert evaluate(spend, {**ok, "amount_usd": 250, "approvals": ["Manager"], "receipts": False}).answer == "yes", \
        "250 is not above 250; text compares without case; no receipts needed"
    assert evaluate(spend, {**ok, "amount_usd": 251, "approvals": "manager"}).answer == "no"
    assert evaluate(spend, {**ok, "amount_usd": 100, "expense_type": "Strategic"}).answer == "no", "strategic spend needs legal"
    assert evaluate(spend, {**ok, "amount_usd": 100, "submitted_on": "2027-01-01"}).answer == "no"
    d = evaluate(spend, {**ok, "amount_usd": "lots"})
    assert d.answer == "unknown" and any("not a number" in n for n in d.notes)


def test_missing_facts_name_what_would_settle_it(spend):
    d = evaluate(spend, {"approvals": ["manager"], "receipts": True, "submitted_on": "2026-10-01", "expense_type": "capital"})
    assert d.answer == "unknown"
    m = d.missing[0]
    assert m["fact"] == "amount_usd" and m["settles"] == ["no", "yes"]
    assert m["outcomes"][0] == {"value": 249, "answer": "yes", "to": 250} and m["outcomes"][1]["value"] == 251
    # unknown approvals with a known amount: the facts are tried one at a time
    d = evaluate(spend, {"amount_usd": 900, "receipts": True, "submitted_on": "2026-10-01", "expense_type": "capital"})
    m = d.missing[0]
    assert m["fact"] == "approvals" and m["settles"] == ["no", "yes"]
    assert {"value": ["manager"], "answer": "no"} in m["outcomes"], "the manager alone is not enough for 900"
    assert m["outcomes"][-1] == {"value": ["exec", "finance", "legal", "manager"], "answer": "yes"}


def test_the_checker_accepts_honest_proofs_and_rejects_tampered_ones(spend, ship):
    facts = {"approvals": ["manager"], "receipts": True, "submitted_on": "2026-10-01", "expense_type": "capital", "amount_usd": 2600}
    d = evaluate(spend, facts)
    assert d.answer == "no" and verify(spend, d.proof, d.inputs) == []
    assert verify(spend, json.loads(json.dumps(d.proof)), d.inputs) == [], "a proof survives a JSON round trip"

    def tampered(fn):
        p = copy.deepcopy(d.proof)
        fn(p)
        return verify(spend, p, d.inputs)

    def flip_result(p):
        p["steps"][-1]["value"], p["result"] = True, True

    def change_fact(p):
        next(s for s in p["steps"] if s.get("name") == "amount_usd")["value"] = 100

    def drop_step(p):
        p["steps"].pop(3)

    def skip_part(p):  # claim the 'and' was settled after its first part
        s = next(s for s in p["steps"] if s.get("kind") == "and" and len(s["args"]) > 1)
        s["args"] = s["args"][:1]

    def change_constant(p):
        next(s for s in p["steps"] if s.get("kind") == "cmp" and "const" in s["args"][1])["args"][1]["const"] = 2600

    for fn in (flip_result, change_fact, drop_step, skip_part, change_constant):
        assert tampered(fn), f"{fn.__name__} goes unnoticed"
    assert verify(spend, d.proof, {**d.inputs, "amount_usd": 100}), "the proof must match the recorded facts"
    assert verify(ship, d.proof, d.inputs) == ["the proof was made with another version of the playbook"]


def test_problems_are_reported_in_words():
    def with_rule(when, **extra):
        s = copy.deepcopy(SPEND)
        s["rules"].append({"name": "z", "when": when})
        s.update(extra)
        return problems(s)

    assert "plain numbers" in with_rule("amount_usd > $2,500")[0]
    assert "did you mean amount_usd" in with_rule("amount > 5")[0]
    assert "use 'in'" in with_rule("approvals > 3")[0]
    assert "not one of the values of expense_type" in with_rule('expense_type == "Capitol"')[0]
    assert "write dates without quotes" in with_rule('submitted_on > "2026-01-01"')[0]
    assert "not a yes/no condition" in with_rule("amount_usd")[0]
    assert "ends too early" in with_rule("needs_finance and")[0]
    s = copy.deepcopy(SPEND)
    s["rules"] += [{"name": "a", "when": "b"}, {"name": "b", "when": "a"}]
    assert any("circle" in p for p in problems(s))
    assert any("'decision' must name" in p for p in problems({**SPEND, "decision": "nope"}))


def test_a_rule_written_twice_holds_when_either_part_does():
    s = copy.deepcopy(SHIP)
    s["rules"].append({"name": "may_ship", "when": "permit_revoked == false and approved", "quote": "second"})
    pb = compile_playbook(s)
    assert len(pb.rules["may_ship"].parts) == 2
    d = evaluate(pb, {"approved": True, "inspected": False, "permit_revoked": False})
    assert d.answer == "yes" and verify(pb, d.proof, d.inputs) == [] and "second" in d.why[0]


def test_budget_and_fresh_state_per_decision(ship):
    d = evaluate(ship, {"approved": True, "inspected": True}, budget=2)
    assert d.answer == "unknown" and d.notes == ["stopped after 2 steps"]
    a = evaluate(ship, {"approved": True, "inspected": True, "supplier_certified": True, "permit_revoked": False})
    b = evaluate(ship, {"approved": True})
    assert (a.answer, b.answer) == ("yes", "unknown"), "nothing carries over from one decision to the next"


def test_drafting_checks_and_repairs_the_model_output():
    policy = ("Ship only when approved, inspected and the supplier is certified, unless the permit is revoked. "
              "Night shipments need the site lead.")
    outs = iter([
        'Sure! ```json\n{"rules": [{"name": "may_ship", "when": "approved and inspected and certified", "quote": "x"}], '
        '"decision": "may_ship"}```',
        '{"rules": [{"name": "may_ship", "when": "approved and inspected and supplier_certified unless permit_revoked", '
        '"quote": "Ship only when approved, inspected and the supplier is certified, unless the permit is revoked."}], '
        '"decision": "may_ship", "gaps": ["night shipments need the site lead"]}',
    ])
    seen = []

    def gen(system, user):
        seen.append(user)
        return next(outs)

    d = draft(gen, policy, question="May the order ship?", facts=SHIP["facts"], decision="may_ship")
    assert d.ok and d.attempts == 2 and d.quotes == {"may_ship": True} and d.gaps == ["night shipments need the site lead"]
    assert "'certified' is not a fact" in seen[1], "the second attempt is told what was wrong"
    d = draft(lambda s, u: "no idea", policy, question="?", facts=SHIP["facts"], decision="may_ship", repairs=0)
    assert d.problems == ["the answer is not JSON"]


def test_command_line(tmp_path, capsys):
    from cie.cli import main

    f = tmp_path / "pb.json"
    f.write_text(json.dumps(SHIP))
    assert main(["playbook", "check", str(f)]) == 0
    capsys.readouterr()
    assert main(["playbook", "decide", str(f), "--facts", '{"approved": true, "inspected": true}']) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["answer"] == "unknown" and out["verified"] and out["missing"][0]["fact"] == "supplier_certified"


# ---------------------------------------------------------------------------------------------- in the company
BOUND = copy.deepcopy(SHIP)
BOUND["facts"]["supplier"] = {"type": "text", "description": "the supplier's key"}
BOUND["facts"]["supplier_certified"] = {"type": "boolean", "from": {"entity": "supplier", "key": "{supplier}", "field": "certified"}}


def _apply(session, world, ops):
    from cie.state.events import process_event, submit_event

    ev, _ = submit_event(session, world.tenant.id, kind="ops", payload={"ops": ops}, idempotency_key=uuid.uuid4().hex)
    return process_event(session, ev.id)


def _supplier(session, world, certified, key="s1", **attrs):
    return _apply(session, world, [{"op": "upsert_node", "type": "supplier", "key": key, "name": key.upper(), "scope": "Acme",
                                    "attrs": {"certified": certified, "source_system": "erp", **attrs}}])


def _approved(session, world, spec=BOUND, key="shipping"):
    from cie.playbooks import store

    row = store.save(session, world.tenant.id, key, spec, drafted_by="test", source_texts=[SHIP["rules"][0]["quote"]])
    return store.approve(session, row.id, approve=True, by="test", principal_id=world.admin.id)


@pytest.mark.db
def test_save_approve_decide_and_decide_again_when_a_record_changes(session, world):
    from cie.core.models import Approval
    from cie.playbooks import store

    row = store.save(session, world.tenant.id, "shipping", BOUND, drafted_by="test", source_texts=["Ship only when approved, "
                                                                                                   "inspected and the supplier is certified, unless the permit is revoked."])
    assert row.status == "draft" and row.quotes == {"may_ship": True}
    assert session.query(Approval).filter_by(kind="playbook", subject_id=str(row.id)).one().status == "pending"
    with pytest.raises(LookupError):
        store.decide(session, world.tenant.id, "shipping", given={})
    store.approve(session, row.id, approve=True, by="test", principal_id=world.admin.id)
    given = {"approved": True, "inspected": True, "permit_revoked": False, "supplier": "s1"}
    d1 = store.decide(session, world.tenant.id, "shipping", given=given, subject="order:o1")
    assert d1.answer == "unknown" and d1.sources["supplier_certified"]["detail"] == "no such record visible"
    assert d1.record_keys == ["supplier:s1"]
    summary_ = _supplier(session, world, True)  # the supplier record arrives: the decision is made again
    assert summary_["decisions"]["redecided"][0]["to"] == "yes"
    session.refresh(d1)
    d2 = session.get(type(d1), d1.superseded_by)
    assert d1.status == "superseded" and d2.answer == "yes" and d2.status == "current"
    assert d2.based_on["records"][0]["label"] == "supplier:s1" and store.verify_decision(session, d2) == []
    _supplier(session, world, True, note="unrelated")  # a change that does not touch what it read: nothing new
    assert session.query(type(d1)).filter_by(subject="order:o1", status="current").one().id == d2.id
    _supplier(session, world, False)
    d3 = session.query(type(d1)).filter_by(subject="order:o1", status="current").one()
    assert d3.answer == "no" and "a record it read changed" in d3.reason
    d3.proof["result"] = True
    assert store.verify_decision(session, d3), "a tampered stored decision is caught"


@pytest.mark.db
def test_bound_facts_come_from_the_records_and_an_open_conflict_makes_them_unknown(session, world):
    from cie.playbooks import store

    _approved(session, world)
    _supplier(session, world, True)
    given = {"approved": True, "inspected": True, "permit_revoked": False, "supplier": "s1", "supplier_certified": False}
    d = store.decide(session, world.tenant.id, "shipping", given=given)
    assert d.answer == "yes" and any("ignored" in n for n in d.notes), "a request cannot overrule the company's records"
    _apply(session, world, [{"op": "observe", "ref": ["supplier", "s1"], "field": "certified", "value": False,
                             "source": {"system": "mail", "kind": "email"}}])
    d = store.decide(session, world.tenant.id, "shipping", given=given)
    assert d.answer == "unknown" and "conflict" in d.sources["supplier_certified"]
    assert d.missing[0]["fact"] == "supplier_certified"


@pytest.mark.db
def test_a_requester_sees_only_the_records_they_may_see(session, world):
    from cie.playbooks import store

    _approved(session, world)
    _apply(session, world, [{"op": "upsert_node", "type": "supplier", "key": "s9", "name": "S9", "scope": "Legal",
                             "attrs": {"certified": True}}])
    given = {"approved": True, "inspected": True, "permit_revoked": False, "supplier": "s9"}
    assert store.decide(session, world.tenant.id, "shipping", given=given, principal_id=world.analyst.id).answer == "yes"
    assert store.decide(session, world.tenant.id, "shipping", given=given, principal_id=world.outsider.id).answer == "unknown"


@pytest.mark.db
def test_a_new_version_retires_the_old_and_current_decisions_follow_it(session, world):
    from cie.playbooks import store

    v1 = _approved(session, world)
    _supplier(session, world, True)
    d = store.decide(session, world.tenant.id, "shipping", subject="order:o1",
                     given={"approved": True, "inspected": True, "permit_revoked": False, "supplier": "s1"})
    assert d.answer == "yes"
    stricter = copy.deepcopy(BOUND)
    stricter["facts"]["export_cleared"] = {"type": "boolean"}
    stricter["rules"][0]["when"] += " or not export_cleared"
    bad = store.save(session, world.tenant.id, "shipping", {**stricter, "decision": "missing"}, drafted_by="test")
    with pytest.raises(ValueError, match="cannot be approved"):
        store.approve(session, bad.id, approve=True, by="test")
    v2 = _approved(session, world, stricter)
    session.refresh(v1)
    assert (v1.status, v2.status, v2.version) == ("retired", "approved", 3)
    now = session.query(type(d)).filter_by(subject="order:o1", status="current").one()
    assert now.playbook_id == v2.id and now.answer == "unknown" and now.missing[0]["fact"] == "export_cleared"


@pytest.mark.db
def test_the_gateway_lets_the_playbook_decide_actions(session, world, monkeypatch, tmp_path):
    from cie.actions import gateway
    from cie.actions.connectors import OutboxConnector
    from cie.agents.head import create_project
    from cie.agents.registry import ensure_default_agents
    from cie.core.settings import get_settings

    monkeypatch.setattr(get_settings(), "actions_playbooks", {"book_shipment": "shipping"})
    proj = create_project(session, tenant_id=world.tenant.id, parent_scope=world.company, name="Delivery")
    ops = ensure_default_agents(session, world.tenant.id, world.company)["operations"]

    def book(**payload):
        return gateway.propose(session, tenant_id=world.tenant.id, kind="book_shipment", target="outbox", requested_by=ops.name,
                               agent=ops, project_id=proj.id, payload={"supplier": "s1", "permit_revoked": False, **payload})

    a = book(approved=True, inspected=True)
    assert a.status == "awaiting_approval" and "no approved playbook 'shipping'" in a.checks[-2]["detail"]
    _approved(session, world)
    _supplier(session, world, False)
    a = book(approved=True, inspected=True, n=2)
    assert a.status == "refused" and "says no" in a.checks[-1]["detail"]
    _supplier(session, world, True)
    a = book(approved=True, inspected=True, n=3)
    assert a.status == "approved" and a.based_on["playbook_decision"]["answer"] == "yes"
    assert any(r["label"] == "supplier:s1" for r in a.based_on["records"]), "the records it read join the action's basis"
    u = book(approved=True, n=4)
    assert u.status == "awaiting_approval" and "it needs inspected" in u.checks[-2]["detail"]
    _supplier(session, world, False)  # the certificate is withdrawn before the shipment is booked
    gateway.execute(session, a.id, connectors={"outbox": OutboxConnector(tmp_path / "outbox.jsonl")}, actor="w")
    assert a.status == "stale" and any("playbook shipping now answers no" in c["detail"] for c in a.checks)


@pytest.mark.db
def test_api(session, world):
    from fastapi.testclient import TestClient

    from cie.api.app import app
    from cie.api.deps import hash_key
    from cie.core.models import Approval

    k = secrets.token_urlsafe(12)
    world.admin.api_key_hash = hash_key(k)
    session.commit()
    c, h = TestClient(app), {"X-API-Key": k}
    r = c.post("/api/playbooks", headers=h, json={"key": "shipping", "spec": SHIP})
    assert r.status_code == 201 and r.json()["status"] == "draft" and r.json()["problems"] == []
    assert c.post("/api/playbooks/shipping/decide", headers=h, json={"facts": {}}).status_code == 404, "a draft does not decide"
    ap = session.query(Approval).filter_by(kind="playbook", subject_id=r.json()["id"]).one()
    assert c.post(f"/api/approvals/{ap.id}/decide", headers=h, json={"approve": True, "reason": "matches the policy"}).status_code == 200
    d = c.post("/api/playbooks/shipping/decide", headers=h, json={"facts": {"approved": True, "inspected": True}}).json()
    assert d["answer"] == "unknown" and d["missing"][0]["fact"] == "supplier_certified" and d["version"] == 1
    v = c.post(f"/api/playbooks/decisions/{d['id']}/verify", headers=h).json()
    assert v["ok"] and v["steps"] > 3
    assert c.get(f"/api/playbooks/decisions/{d['id']}", headers=h, params={"proof": True}).json()["proof"]["goal"] == "may_ship"
    assert [p["status"] for p in c.get("/api/playbooks", headers=h).json()] == ["approved"]
    assert c.post("/api/playbooks/draft", headers=h, json={"key": "x", "question": "?", "facts": {"a": {"type": "boolean"}},
                                                        "document_ids": [str(uuid.uuid4())]}).status_code == 409
