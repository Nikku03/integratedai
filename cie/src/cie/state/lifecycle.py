"""Allowed status transitions per business entity type.

A status change that is not in this table is not applied: it opens a conflict for a person to resolve, because
an unexpected jump (an order "delivered" that was never "shipped") is more often a data problem than a fact.
Types without a lifecycle accept any status.
"""

from __future__ import annotations

LIFECYCLES: dict[str, dict[str, frozenset[str]]] = {
    "order": {
        "draft": frozenset({"open", "cancelled"}),
        "open": frozenset({"confirmed", "on_hold", "shipped", "delivered", "cancelled"}),
        "confirmed": frozenset({"on_hold", "shipped", "delivered", "cancelled"}),
        "on_hold": frozenset({"open", "confirmed", "cancelled"}),
        "shipped": frozenset({"delivered", "returned"}),
        "delivered": frozenset({"closed", "returned"}),
        "returned": frozenset({"closed"}),
        "cancelled": frozenset(),
        "closed": frozenset(),
    },
    "invoice": {
        "draft": frozenset({"issued", "void"}),
        "issued": frozenset({"partially_paid", "paid", "overdue", "void"}),
        "partially_paid": frozenset({"paid", "overdue"}),
        "overdue": frozenset({"partially_paid", "paid", "written_off"}),
        "paid": frozenset({"refunded"}),
        "refunded": frozenset(),
        "void": frozenset(),
        "written_off": frozenset(),
    },
    "milestone": {
        "planned": frozenset({"in_progress", "at_risk", "done", "cancelled"}),
        "in_progress": frozenset({"at_risk", "done", "cancelled"}),
        "at_risk": frozenset({"in_progress", "done", "cancelled"}),
        "done": frozenset({"in_progress"}),  # reopened
        "cancelled": frozenset(),
    },
    "task": {
        "open": frozenset({"in_progress", "blocked", "done", "cancelled"}),
        "in_progress": frozenset({"open", "blocked", "done", "cancelled"}),
        "blocked": frozenset({"open", "in_progress", "cancelled"}),
        "done": frozenset({"open"}),  # reopened
        "cancelled": frozenset(),
    },
    "project": {
        "proposed": frozenset({"active", "cancelled"}),
        "active": frozenset({"on_hold", "completed", "cancelled"}),
        "on_hold": frozenset({"active", "cancelled"}),
        "completed": frozenset({"active"}),
        "cancelled": frozenset(),
    },
    "contract": {
        "draft": frozenset({"signed", "void"}),
        "signed": frozenset({"active", "void"}),
        "active": frozenset({"expired", "terminated", "renewed"}),
        "renewed": frozenset({"active", "expired", "terminated"}),
        "expired": frozenset({"renewed"}),
        "terminated": frozenset(),
        "void": frozenset(),
    },
}

# statuses in which an order still has to arrive
OPEN_ORDER_STATUSES = ("draft", "open", "confirmed", "on_hold", "shipped")


def states(entity_type: str) -> frozenset[str] | None:
    lc = LIFECYCLES.get(entity_type)
    return frozenset(lc) if lc is not None else None


def check_transition(entity_type: str, old: str | None, new: str) -> str | None:
    """None when allowed; otherwise the reason it is not."""
    lc = LIFECYCLES.get(entity_type)
    if lc is None:
        return None
    if new not in lc:
        return f"{new!r} is not a status of {entity_type} (allowed: {', '.join(sorted(lc))})"
    if old is None or old == new:
        return None
    if old not in lc:
        return None  # an unknown earlier status (from before the lifecycle was defined) does not block a known one
    if new not in lc[old]:
        allowed = ", ".join(sorted(lc[old])) or "none; it is final"
        return f"{entity_type} cannot go from {old!r} to {new!r} (next statuses: {allowed})"
    return None
