"""Business conventions the rules rely on. Written down once so rules, demo, generator and docs agree.

Edge directions (A kind B):

* supplier ``supplies`` product            * order ``depends_on`` supplier (fulfilment)
* milestone ``depends_on`` order           * milestone ``depends_on`` product  (attrs.qty: quantity needed)
* project ``depends_on`` milestone         * task ``depends_on`` milestone;  task ``blocks`` task
* milestone ``governed_by`` requirement    * requirement ``derived_from`` contract (the clause it comes from)
* passage ``derived_from`` document        * passage ``supports`` record (the text states the record's value)
* claim ``derived_from`` passage           * claim ``contradicts`` record / record ``supersedes`` claim (rule R0)
* generated summary (artifact, authoritative = false) ``derived_from`` the records it summarises

Attributes: order {product, supplier, qty, promised_date, status, revision, source_system, source_date};
milestone {due_date, slack_days}; task {status}; requirement {kind, ...}; claim {subject_type, subject_key,
attr, value, stated_on}. Exact inventory lives in ``rem_stock`` (product, holder project), never in text.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

# REM recommends the capability a follow-up needs; the head agent chooses which agent does it.
CAPABILITY_BY_TYPE = {"order": "operations", "supplier": "operations", "product": "operations", "milestone": "operations",
                      "task": "operations", "project": "operations", "team": "operations", "invoice": "finance",
                      "contract": "legal", "requirement": "legal", "document": "research", "passage": "research",
                      "claim": "research", "fact": "research", "decision": "research", "risk": "operations",
                      "artifact": "research", "customer": "operations", "person": "operations", "department": "operations",
                      "company": "research", "agent": "research"}
SYSTEM_OF_RECORD = ("erp", "contract_repository", "inventory", "project_tracker")
PENALTY_KINDS = ("late_delivery_penalty", "penalty", "liquidated_damages")


def capability_for(node_type: str) -> str:
    return CAPABILITY_BY_TYPE.get(node_type, "research")


def as_date(v: Any) -> date | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def effective_due(milestone_attrs: dict[str, Any]) -> date | None:
    """The latest acceptable arrival for a milestone's inputs: due date plus documented slack."""
    due = as_date(milestone_attrs.get("due_date"))
    if due is None:
        return None
    return due + timedelta(days=float(milestone_attrs.get("slack_days") or 0))


def is_open_order(attrs: dict[str, Any]) -> bool:
    return str(attrs.get("status", "open")) == "open"


def later_record(a_attrs: dict[str, Any], a_auth: bool, b_attrs: dict[str, Any], b_auth: bool) -> int:
    """Chronology between two conflicting statements: +1 if a is current, -1 if b is, 0 if undecided.
    An authoritative system-of-record statement dated later wins; the other stays in history."""
    da = as_date(a_attrs.get("source_date") or a_attrs.get("stated_on"))
    db = as_date(b_attrs.get("source_date") or b_attrs.get("stated_on"))
    sa = a_auth and str(a_attrs.get("source_system")) in SYSTEM_OF_RECORD
    sb = b_auth and str(b_attrs.get("source_system")) in SYSTEM_OF_RECORD
    if da and db and da != db:
        if da > db and sa:
            return 1
        if db > da and sb:
            return -1
    if sa != sb and (da is None or db is None or da == db):
        return 1 if sa else -1
    return 0
