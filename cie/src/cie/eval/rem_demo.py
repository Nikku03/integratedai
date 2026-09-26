"""REM demonstration: a supplier delays a component used by two projects.

FICTIONAL DATA. Every company, person, product, order and document below is invented for this demonstration.

Scenario: Kestrel Components (fictional) delays all KX-7 controller boards to 2026-12-03.
* Project Aurora needs 30 boards by 2026-11-20 and holds 40 in stock: covered.
* Project Borealis needs 50 boards by 2026-11-15 and holds none: exposed. Its field trial is governed by a
  late-delivery penalty clause in contract C-77, which only Legal (clearance 3) may read.
* An older email (2026-10-02) says PO-1043 is 40 units due 2026-10-28; the later purchase-order revision
  (2026-10-09) says 50 units due 2026-11-05. The email stays in history; the revision is current.
* New evidence then arrives: an alternative order from a second supplier covers Borealis; a stock recount
  shows Aurora's stock is lower than recorded, which exposes Aurora.

``python -m cie.eval.rem_demo`` runs it on the configured database and prints the checks and the results.
"""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cie.core.models import Permission, Principal, PrincipalKind, Tenant
from cie.governance.permissions import ensure_role, grant_role, visible_scopes
from cie.rem.change import process_event, submit_event, visible_impacts
from cie.rem.ingest import document_ops, ingest_bundle, store_document
from cie.rem.query import QueryRequest, run_query
from cie.rem.store import GraphReader

FICTIONAL = "Fictional demonstration data: every company, person, product and document is invented."
OPS, AUR, BOR, LEGAL, FIN = "Operations", "Project Aurora", "Project Borealis", "Legal", "Finance"
QUESTION = "Which projects are affected by the Kestrel KX-7 controller board delivery delay, and what evidence supports that?"


def erp(record: str, rev: int = 1) -> list[dict[str, Any]]:
    return [{"system": "erp", "record": record, "revision": rev}]


BUNDLE: dict[str, Any] = {
    "note": FICTIONAL,
    "scopes": [{"name": "Northwind Assembly (fictional)", "kind": "company"},
               {"name": OPS, "kind": "department", "parent": "Northwind Assembly (fictional)"},
               {"name": FIN, "kind": "department", "parent": "Northwind Assembly (fictional)"},
               {"name": LEGAL, "kind": "department", "parent": "Northwind Assembly (fictional)"},
               {"name": AUR, "kind": "project", "parent": OPS},
               {"name": BOR, "kind": "project", "parent": OPS}],
    "nodes": [
        {"type": "project", "key": "aurora", "name": "Project Aurora", "scope": AUR, "attrs": {"source_system": "project_tracker"},
         "source_pointers": [{"system": "project_tracker", "record": "PRJ-AUR"}], "verification": "verified"},
        {"type": "project", "key": "borealis", "name": "Project Borealis", "scope": BOR, "attrs": {"source_system": "project_tracker"},
         "source_pointers": [{"system": "project_tracker", "record": "PRJ-BOR"}], "verification": "verified"},
        {"type": "supplier", "key": "kestrel", "name": "Kestrel Components (fictional supplier)", "scope": OPS,
         "attrs": {"source_system": "erp"}, "source_pointers": erp("SUP-118"), "verification": "verified"},
        {"type": "product", "key": "kx7", "name": "KX-7 controller board", "scope": OPS, "attrs": {"source_system": "erp", "sku": "KX-7"},
         "source_pointers": erp("SKU-KX-7"), "verification": "verified"},
        {"type": "milestone", "key": "aurora-pilot", "name": "Aurora pilot build", "scope": AUR, "project_keys": ["aurora"],
         "attrs": {"due_date": "2026-11-20", "source_system": "project_tracker"},
         "source_pointers": [{"system": "project_tracker", "record": "MS-AUR-3"}], "verification": "verified"},
        {"type": "milestone", "key": "borealis-trial", "name": "Borealis field trial", "scope": BOR, "project_keys": ["borealis"],
         "attrs": {"due_date": "2026-11-15", "source_system": "project_tracker"},
         "source_pointers": [{"system": "project_tracker", "record": "MS-BOR-2"}], "verification": "verified"},
        {"type": "order", "key": "PO-1042", "name": "PO-1042", "scope": AUR, "project_keys": ["aurora"],
         "attrs": {"product": "kx7", "supplier": "kestrel", "qty": 30, "promised_date": "2026-11-01", "status": "open",
                   "revision": 1, "source_system": "erp", "source_date": "2026-09-20"},
         "source_pointers": erp("PO-1042"), "verification": "verified"},
        {"type": "order", "key": "PO-1043", "name": "PO-1043", "scope": BOR, "project_keys": ["borealis"],
         "attrs": {"product": "kx7", "supplier": "kestrel", "qty": 50, "promised_date": "2026-11-05", "status": "open",
                   "revision": 2, "source_system": "erp", "source_date": "2026-10-09"},
         "source_pointers": erp("PO-1043", 2), "verification": "verified"},
        {"type": "task", "key": "aurora-assembly", "name": "Assemble Aurora pilot units", "scope": AUR, "project_keys": ["aurora"],
         "attrs": {"status": "open", "source_system": "project_tracker"}, "source_pointers": [{"system": "project_tracker", "record": "T-311"}]},
        {"type": "task", "key": "borealis-install", "name": "Install Borealis field units", "scope": BOR, "project_keys": ["borealis"],
         "attrs": {"status": "open", "source_system": "project_tracker"}, "source_pointers": [{"system": "project_tracker", "record": "T-402"}]},
        {"type": "task", "key": "borealis-training", "name": "Train Borealis site crew", "scope": BOR, "project_keys": ["borealis"],
         "attrs": {"status": "open", "source_system": "project_tracker"}, "source_pointers": [{"system": "project_tracker", "record": "T-405"}]},
        {"type": "customer", "key": "halden", "name": "Halden Utilities (fictional customer)", "scope": OPS,
         "attrs": {"source_system": "erp"}, "source_pointers": erp("CUS-77")},
        {"type": "contract", "key": "C-77", "name": "Field trial agreement C-77", "scope": LEGAL, "sensitivity": 3,
         "attrs": {"source_system": "contract_repository", "counterparty": "halden"},
         "source_pointers": [{"system": "contract_repository", "record": "C-77"}], "verification": "verified"},
        {"type": "requirement", "key": "C-77-9.2", "name": "Clause 9.2 late-delivery penalty", "scope": LEGAL, "sensitivity": 3,
         "attrs": {"kind": "late_delivery_penalty", "rate": "1.5% of contract value per week", "cap": "10%",
                   "source_system": "contract_repository"},
         "source_pointers": [{"system": "contract_repository", "record": "C-77", "clause": "9.2"}], "verification": "verified"},
        {"type": "artifact", "key": "status-2026-10-12", "name": "Weekly supply status summary (generated)", "scope": OPS,
         "summary": "All KX-7 deliveries for Aurora and Borealis are on track for early November.", "authoritative": False,
         "attrs": {"source_system": "generated", "generated_by": "status-summarizer"}},
    ],
    "documents": [
        {"key": "po-1042", "title": "Purchase order PO-1042", "scope": AUR, "project_keys": ["aurora"], "source_system": "erp",
         "date": "2026-09-20", "doc_type": "purchase_order", "verification": "verified",
         "text": "Purchase order PO-1042 (Northwind Assembly, fictional)\n\nPO-1042: 30 units of KX-7 controller board from Kestrel Components, promised delivery 2026-11-01, for Project Aurora.\n",
         "passages": [{"quote": "PO-1042: 30 units of KX-7 controller board from Kestrel Components, promised delivery 2026-11-01, for Project Aurora.",
                       "supports": [["order", "PO-1042"]]}]},
        {"key": "po-1043-rev2", "title": "Purchase order PO-1043 revision 2", "scope": BOR, "project_keys": ["borealis"],
         "source_system": "erp", "date": "2026-10-09", "doc_type": "purchase_order", "verification": "verified",
         "text": "Purchase order PO-1043, revision 2 (Northwind Assembly, fictional)\n\nPO-1043 revision 2: 50 units of KX-7 controller board from Kestrel Components, promised delivery 2026-11-05, for Project Borealis. This revision replaces revision 1 of 2026-09-22.\n",
         "passages": [{"quote": "PO-1043 revision 2: 50 units of KX-7 controller board from Kestrel Components, promised delivery 2026-11-05, for Project Borealis.",
                       "supports": [["order", "PO-1043"]]}]},
        {"key": "email-2026-10-02", "title": "Email from Kestrel sales, 2026-10-02", "scope": BOR, "project_keys": ["borealis"],
         "source_system": "email", "date": "2026-10-02", "doc_type": "email",
         "text": "From: sales@kestrel.example (fictional)\nDate: 2026-10-02\n\nHi team, confirming PO-1043 for 40 units of KX-7, delivery on 2026-10-28.\n",
         "claims": [{"key": "email-2026-10-02#qty", "name": "Email: PO-1043 is 40 units",
                     "quote": "confirming PO-1043 for 40 units of KX-7, delivery on 2026-10-28.",
                     "subject": ["order", "PO-1043"], "attr": "qty", "value": 40, "stated_on": "2026-10-02"}]},
        {"key": "contract-c77", "title": "Field trial agreement C-77 (excerpt)", "scope": LEGAL, "sensitivity": 3,
         "source_system": "contract_repository", "date": "2026-06-01", "doc_type": "contract", "verification": "verified",
         "text": "Field trial agreement C-77 between Northwind Assembly and Halden Utilities (both fictional)\n\nClause 9.2 Late delivery. If the field trial equipment is not delivered by the milestone date, the Supplier pays 1.5% of the contract value per week of delay, capped at 10%.\n",
         "passages": [{"quote": "Clause 9.2 Late delivery. If the field trial equipment is not delivered by the milestone date, the Supplier pays 1.5% of the contract value per week of delay, capped at 10%.",
                       "supports": [["requirement", "C-77-9.2"]]}]},
        {"key": "chat-2026-10-05", "title": "Borealis site chat, 2026-10-05", "scope": BOR, "project_keys": ["borealis"],
         "source_system": "chat", "date": "2026-10-05", "doc_type": "chat",
         "text": "#borealis-site (fictional)\n\nCrew training can only start once the KX-7 boards from PO-1043 are on site.\n",
         "passages": [{"key": "chat-2026-10-05#p1", "quote": "Crew training can only start once the KX-7 boards from PO-1043 are on site."}]},
    ],
    "edges": [
        {"src": ["supplier", "kestrel"], "kind": "supplies", "dst": ["product", "kx7"]},
        {"src": ["order", "PO-1042"], "kind": "depends_on", "dst": ["supplier", "kestrel"]},
        {"src": ["order", "PO-1043"], "kind": "depends_on", "dst": ["supplier", "kestrel"]},
        {"src": ["milestone", "aurora-pilot"], "kind": "depends_on", "dst": ["order", "PO-1042"]},
        {"src": ["milestone", "aurora-pilot"], "kind": "depends_on", "dst": ["product", "kx7"], "attrs": {"qty": 30}},
        {"src": ["milestone", "borealis-trial"], "kind": "depends_on", "dst": ["order", "PO-1043"]},
        {"src": ["milestone", "borealis-trial"], "kind": "depends_on", "dst": ["product", "kx7"], "attrs": {"qty": 50}},
        {"src": ["project", "aurora"], "kind": "depends_on", "dst": ["milestone", "aurora-pilot"]},
        {"src": ["project", "borealis"], "kind": "depends_on", "dst": ["milestone", "borealis-trial"]},
        {"src": ["task", "aurora-assembly"], "kind": "depends_on", "dst": ["milestone", "aurora-pilot"]},
        {"src": ["task", "borealis-install"], "kind": "depends_on", "dst": ["milestone", "borealis-trial"]},
        {"src": ["task", "borealis-install"], "kind": "blocks", "dst": ["task", "borealis-training"]},
        {"src": ["requirement", "C-77-9.2"], "kind": "derived_from", "dst": ["contract", "C-77"]},
        {"src": ["contract", "C-77"], "kind": "owned_by", "dst": ["customer", "halden"]},
        {"src": ["milestone", "borealis-trial"], "kind": "governed_by", "dst": ["requirement", "C-77-9.2"]},
        {"src": ["artifact", "status-2026-10-12"], "kind": "derived_from", "dst": ["order", "PO-1042"]},
        {"src": ["artifact", "status-2026-10-12"], "kind": "derived_from", "dst": ["order", "PO-1043"]},
        # proposed by a relation extractor from the chat message: a hypothesis until someone verifies it
        {"src": ["task", "borealis-training"], "kind": "depends_on", "dst": ["order", "PO-1043"], "provenance": "inferred",
         "derivation": {"model": "relation-extractor (demo annotation)", "source_passage": "chat-2026-10-05#p1"}},
    ],
    "stock": [
        {"product": "kx7", "holder": ["project", "aurora"], "on_hand": 40, "reserved": 0, "scope": AUR,
         "source_pointers": [{"system": "inventory", "record": "WH-2/bin-14", "counted_on": "2026-10-10"}]},
        {"product": "kx7", "holder": ["project", "borealis"], "on_hand": 0, "reserved": 0, "scope": BOR,
         "source_pointers": [{"system": "inventory", "record": "WH-3/bin-02", "counted_on": "2026-10-10"}]},
    ],
}

DELAY_NOTICE = {"key": "kestrel-notice-2026-10-20", "title": "Kestrel delay notice, 2026-10-20", "scope": OPS, "source_system": "email",
                "date": "2026-10-20", "doc_type": "email",
                "text": "From: logistics@kestrel.example (fictional)\nDate: 2026-10-20\n\nDue to a wafer shortage, all KX-7 controller board shipments are delayed; the new delivery date for open orders is 2026-12-03.\n",
                "passages": [{"key": "kestrel-notice-2026-10-20#p1",
                              "quote": "Due to a wafer shortage, all KX-7 controller board shipments are delayed; the new delivery date for open orders is 2026-12-03.",
                              "supports": [["order", "PO-1042"], ["order", "PO-1043"]]}]}
ALT_ORDER = {"key": "po-1051", "title": "Purchase order PO-1051", "scope": BOR, "project_keys": ["borealis"], "source_system": "erp",
             "date": "2026-10-22", "doc_type": "purchase_order", "verification": "verified",
             "text": "Purchase order PO-1051 (Northwind Assembly, fictional)\n\nPO-1051: 50 units of KX-7 controller board from Larkspur Electronics, promised delivery 2026-11-10, for Project Borealis.\n",
             "passages": [{"quote": "PO-1051: 50 units of KX-7 controller board from Larkspur Electronics, promised delivery 2026-11-10, for Project Borealis.",
                           "supports": [["order", "PO-1051"]]}]}
RECOUNT = {"key": "recount-2026-10-24", "title": "Inventory recount WH-2, 2026-10-24", "scope": AUR, "project_keys": ["aurora"],
           "source_system": "inventory", "date": "2026-10-24", "doc_type": "inventory_count", "verification": "verified",
           "text": "Inventory recount (fictional)\n\nRecount WH-2 bin 14: 20 KX-7 controller boards on hand; 20 boards found damaged and scrapped.\n",
           "passages": [{"quote": "Recount WH-2 bin 14: 20 KX-7 controller boards on hand; 20 boards found damaged and scrapped."}]}


class Demo:
    def __init__(self, session: Session, vault, embedder, tenant_name: str | None = None):
        self.s, self.vault, self.embedder = session, vault, embedder
        self.tenant = Tenant(name=tenant_name or f"rem-demo-{uuid.uuid4().hex[:6]}")
        session.add(self.tenant)
        session.flush()
        self.people: dict[str, Principal] = {}
        self.log: list[dict[str, Any]] = []

    def setup(self) -> dict[str, Any]:
        out = ingest_bundle(self.s, self.tenant.id, BUNDLE, vault=self.vault, embedder=self.embedder, name="northwind")
        from sqlalchemy import select

        from cie.core.models import Scope

        scopes = {s.name: s for s in self.s.scalars(select(Scope).where(Scope.tenant_id == self.tenant.id))}
        admin = ensure_role(self.s, self.tenant.id, "admin", Permission.admin, 4)
        reader2 = ensure_role(self.s, self.tenant.id, "reader", Permission.read, 2)
        reader3 = ensure_role(self.s, self.tenant.id, "counsel", Permission.read, 3)
        for name, grants in {"ops_lead": [(reader2, OPS)], "finance_analyst": [(reader2, FIN), (reader2, OPS)],
                             "legal_counsel": [(reader3, LEGAL), (reader2, OPS)],
                             "admin": [(admin, "Northwind Assembly (fictional)")]}.items():
            p = Principal(tenant_id=self.tenant.id, kind=PrincipalKind.user, name=name, attributes={})
            self.s.add(p)
            self.s.flush()
            for role, scope in grants:
                grant_role(self.s, tenant_id=self.tenant.id, principal=p, role=role, scope=scopes[scope])
            self.people[name] = p
        self.s.flush()
        return out

    def vis(self, who: str):
        return visible_scopes(self.s, self.people[who])

    def event(self, kind: str, payload: dict[str, Any], key: str, docs: list[dict[str, Any]] = ()) -> dict[str, Any]:
        from sqlalchemy import select

        from cie.core.models import Scope

        ops = []
        for doc in docs:
            sid = self.s.scalar(select(Scope.id).where(Scope.tenant_id == self.tenant.id, Scope.name == doc["scope"]))
            d = store_document(self.s, self.tenant.id, doc, sid, vault=self.vault, embedder=self.embedder)
            ops += document_ops(self.s, self.tenant.id, doc, d)
        payload = {**payload, "ops": ops + list(payload.get("ops", []))}
        ev, created = submit_event(self.s, self.tenant.id, kind=kind, payload=payload, idempotency_key=key,
                                   principal_id=self.people["admin"].id if "admin" in self.people else None)
        summary = process_event(self.s, ev.id, embedder=self.embedder)
        return {"event_id": str(ev.id), "created": created, **summary}

    def query(self, who: str, policy: str = "rem", question: str = QUESTION, **kw) -> dict[str, Any]:
        return run_query(self.s, self.tenant.id, self.vis(who), QueryRequest(question=question, policy=policy, **kw),
                         embedder=self.embedder, principal_id=self.people[who].id)

    def impacts(self, who: str, event_id: str | None = None) -> tuple[list, list]:
        reader = GraphReader(self.s, self.tenant.id, self.vis(who))
        from cie.rem.models import RemEvent

        keys = None
        if event_id:
            keys = (self.s.get(RemEvent, uuid.UUID(event_id)).summary or {}).get("suggestion_keys")
        return visible_impacts(self.s, reader, uuid.UUID(event_id) if event_id else None, suggestion_keys=keys)


def _assessment(impacts, key: str) -> str | None:
    cur = [i for i in impacts if i["target"]["key"] == key and i["status"] == "candidate" and i["rule"] == "R1"]
    return cur[-1]["impact"] if cur else None


def run(session: Session, vault, embedder) -> dict[str, Any]:
    """Run the scenario and return the outputs and the checks (each check is a named boolean with its detail)."""
    d = Demo(session, vault, embedder)
    checks: dict[str, Any] = {}
    setup = d.setup()
    ops_before = d.query("ops_lead")
    delay = d.event("supplier_delay", {"supplier": "kestrel", "product": "kx7", "new_date": "2026-12-03", "notice": "wafer shortage",
                                       "notice_date": "2026-10-20",
                                       "source_pointers": [{"passage": "kestrel-notice-2026-10-20#p1"}]},
                    "kestrel-delay-2026-10-20", docs=[DELAY_NOTICE])
    again = d.event("supplier_delay", {"supplier": "kestrel", "product": "kx7", "new_date": "2026-12-03", "notice": "wafer shortage",
                                       "notice_date": "2026-10-20",
                                       "source_pointers": [{"passage": "kestrel-notice-2026-10-20#p1"}]},
                    "kestrel-delay-2026-10-20", docs=[DELAY_NOTICE])
    ops_q = d.query("ops_lead")
    ops_trav = d.query("ops_lead", policy="traversal")
    legal_q = d.query("legal_counsel")
    ops_imp, ops_tasks = d.impacts("ops_lead", delay["event_id"])
    legal_imp, legal_tasks = d.impacts("legal_counsel", delay["event_id"])
    admin_imp, admin_tasks = d.impacts("admin", delay["event_id"])

    projects = {p["key"]: p for p in ops_q["candidate_affected"]["projects"]}
    checks["finds_both_projects"] = {"ok": {"aurora", "borealis"} <= set(projects), "projects": sorted(projects)}
    checks["covered_vs_exposed"] = {"ok": _assessment(admin_imp, "aurora-pilot") == "covered" and _assessment(admin_imp, "borealis-trial") == "at_risk",
                                    "aurora-pilot": _assessment(admin_imp, "aurora-pilot"), "borealis-trial": _assessment(admin_imp, "borealis-trial"),
                                    "aurora_project": projects.get("aurora", {}).get("assessment"),
                                    "borealis_project": projects.get("borealis", {}).get("assessment")}
    contra = [c for c in ops_q["contradictions"] if {c["a"]["key"], c["b"]["key"]} == {"email-2026-10-02#qty", "PO-1043"}]
    reader_now = GraphReader(session, d.tenant.id, None)
    email_claim = reader_now.node_by_key("claim", "email-2026-10-02#qty")
    checks["chronology_without_deleting_history"] = {
        "ok": bool(contra) and contra[0]["status"] == "resolved" and contra[0]["current"]["key"] == "PO-1043" and email_claim is not None,
        "resolution": contra[0] if contra else None, "email_claim_still_stored": email_claim is not None}
    uncited = [i for i in admin_imp if not i["evidence"] or not any(e.get("source_pointers") for e in i["evidence"])]
    checks["every_conclusion_cites_evidence"] = {"ok": not uncited and all(e["source_pointers"] for e in ops_q["evidence"]),
                                                 "impacts_without_sources": [i["target"]["key"] for i in uncited],
                                                 "evidence_items": len(ops_q["evidence"])}
    ops_text = json.dumps([ops_q, ops_imp, ops_tasks, ops_trav], default=str)
    legal_text = json.dumps([legal_q, legal_imp, legal_tasks], default=str)
    leaked = [s for s in ("1.5%", "Clause 9.2", "C-77", "late-delivery penalty") if s in ops_text]
    checks["restricted_clause_not_exposed"] = {"ok": not leaked and "Clause 9.2" in legal_text, "leaked_to_ops": leaked,
                                               "legal_sees_clause": "Clause 9.2" in legal_text}
    caps = {t["capability"] for t in admin_tasks}
    checks["proposes_ops_finance_contract_tasks"] = {"ok": {"operations", "finance", "legal"} <= caps,
                                                     "admin_view": sorted((t["capability"], t["title"]) for t in admin_tasks),
                                                     "ops_view": sorted((t["capability"], t["title"]) for t in ops_tasks),
                                                     "legal_view": sorted((t["capability"], t["title"]) for t in legal_tasks)}
    summary_now = reader_now.node_by_key("artifact", "status-2026-10-12")
    gen_as_fact = [f for f in ops_q["facts"] if f["node"]["type"] == "artifact"]
    checks["generated_summary_not_evidence"] = {"ok": summary_now.review_status == "invalidated" and not gen_as_fact,
                                                "review_status": summary_now.review_status}
    checks["idempotent_event"] = {"ok": again["event_id"] == delay["event_id"] and not again["created"],
                                  "same_event": again["event_id"] == delay["event_id"]}
    training = [t for t in ops_q["candidate_affected"]["tasks"] if t["key"] == "borealis-training"]
    checks["connected_is_not_affected"] = {"ok": not any(i["target"]["key"] == "borealis-training" for i in admin_imp),
                                           "note": "the crew-training task is two hops away (blocked by installation; an unverified inferred link to PO-1043) "
                                                   "and is not marked affected", "reported_as_candidate_task": bool(training)}

    # new evidence 1: an alternative order covers Borealis
    alt = d.event("ops", {"ops": [
        {"op": "upsert_node", "type": "supplier", "key": "larkspur", "name": "Larkspur Electronics (fictional supplier)", "scope": OPS,
         "attrs": {"source_system": "erp"}, "source_pointers": erp("SUP-240"), "verification": "verified"},
        {"op": "upsert_node", "type": "order", "key": "PO-1051", "name": "PO-1051", "scope": BOR, "project_keys": ["borealis"],
         "attrs": {"product": "kx7", "supplier": "larkspur", "qty": 50, "promised_date": "2026-11-10", "status": "open", "revision": 1,
                   "source_system": "erp", "source_date": "2026-10-22"}, "source_pointers": erp("PO-1051"), "verification": "verified"},
        {"op": "upsert_edge", "src": ["order", "PO-1051"], "kind": "depends_on", "dst": ["supplier", "larkspur"]},
        {"op": "upsert_edge", "src": ["milestone", "borealis-trial"], "kind": "depends_on", "dst": ["order", "PO-1051"]},
    ]}, "po-1051-created", docs=[])
    alt_docs = d.event("ops", {}, "po-1051-document", docs=[ALT_ORDER])
    admin_after_alt, admin_tasks_alt = d.impacts("admin")
    stale_ops = session.get(__import__("cie.rem.models", fromlist=["RemResult"]).RemResult, uuid.UUID(ops_q["result_id"]))
    ops_after = d.query("ops_lead")
    checks["updates_when_new_evidence_arrives"] = {
        "ok": _assessment(admin_after_alt, "borealis-trial") == "covered"
              and not any(i["target"]["key"] == "borealis" and i["impact"] == "at_risk" for i in admin_after_alt)
              and not any(t["capability"] in ("finance", "legal") for t in admin_tasks_alt) and stale_ops.stale,
        "borealis-trial": _assessment(admin_after_alt, "borealis-trial"), "open_tasks": sorted((t["capability"], t["title"]) for t in admin_tasks_alt),
        "earlier_ops_result_marked_stale": stale_ops.stale, "stale_reason": stale_ops.stale_reason}

    # new evidence 2: a recount shows Aurora's stock is lower than recorded
    recount = d.event("stock_count", {"product": "kx7", "holder": ["project", "aurora"], "on_hand": 20, "reserved": 0, "scope": AUR,
                                      "source_pointers": [{"system": "inventory", "record": "WH-2/bin-14", "counted_on": "2026-10-24",
                                                           "passage": "recount-2026-10-24#p1"}]}, "recount-2026-10-24", docs=[RECOUNT])
    admin_after_recount, tasks_after_recount = d.impacts("admin")
    checks["recount_exposes_aurora"] = {"ok": _assessment(admin_after_recount, "aurora-pilot") == "at_risk",
                                        "aurora-pilot": _assessment(admin_after_recount, "aurora-pilot"),
                                        "open_tasks": sorted((t["capability"], t["title"]) for t in tasks_after_recount)}
    return {"note": FICTIONAL, "tenant": d.tenant.name, "checks": checks, "passed": all(c["ok"] for c in checks.values()),
            "events": {"setup": _brief(setup), "delay": _brief(delay), "alternative_order": _brief(alt), "alt_document": _brief(alt_docs),
                       "recount": _brief(recount)},
            "queries": {"ops_before_delay": ops_before, "ops_after_delay_rem": ops_q, "ops_after_delay_traversal": ops_trav,
                        "legal_after_delay_rem": legal_q, "ops_after_new_evidence": ops_after},
            "impacts": {"ops_view": ops_imp, "legal_view": legal_imp, "admin_after_recount": admin_after_recount}}


def _brief(ev: dict[str, Any]) -> dict[str, Any]:
    return {k: ev.get(k) for k in ("event_id", "seq", "status", "stopping_reason", "impacts", "suggestions", "stale_results", "budget", "rule_log")}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI entry
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="eval_out/rem_demo.json")
    args = ap.parse_args(argv)
    from cie.core.db import session_scope
    from cie.memory.embeddings import get_embedding_provider
    from cie.vault.service import VaultService

    with session_scope() as s:
        res = run(s, VaultService(), get_embedding_provider())
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(res, indent=2, default=str))
    for name, c in res["checks"].items():
        print(f"{'PASS' if c['ok'] else 'FAIL'}  {name}")
    print(f"full output: {args.out}")
    return 0 if res["passed"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
