"""Typed business events from other systems, translated into live-state operations.

A domain event names what happened, the record it is about, the version of that record the sender saw, and where
it came from::

    {"type": "payment.confirmed", "entity": ["invoice", "INV-7"], "version": 3,
     "source": {"system": "bank", "record": "PAY-991", "kind": "system_of_record"},
     "occurred_at": "2026-09-28T10:00:00Z", "data": {"amount": 1200.0}}

``entity`` is a record id, ``[type, key]`` or ``{"type", "scheme", "value"}`` (a strong identifier). ``version``,
when given, makes the event a conditional write: if the record has moved on, the whole event is refused as a
conflict (the sender should re-read and resend). Values become field statements with the event's source and time,
so the authority rules decide whether they become current.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from cie.state.store import GraphReader, NodeView

DOMAIN_EVENT_TYPES = ("payment.confirmed", "invoice.paid", "delivery.date_changed", "order.status_changed", "supplier.delay",
                      "entity.updated", "task.completed")


def _view(reader: GraphReader, ref: Any) -> NodeView | None:
    from cie.state.identity import canonical_of, find_by_identifier
    from cie.state.models import RemNode

    if isinstance(ref, dict) and "scheme" in ref:
        nid = find_by_identifier(reader.s, reader.tenant_id, str(ref["type"]), str(ref["scheme"]), ref["value"])
    elif isinstance(ref, (list, tuple)) or (isinstance(ref, dict) and "key" in ref):
        t, k = (ref[0], ref[1]) if isinstance(ref, (list, tuple)) else (ref["type"], ref["key"])
        nid = reader.s.scalar(select(RemNode.id).where(RemNode.tenant_id == reader.tenant_id, RemNode.type == t, RemNode.key == k))
    else:
        nid = uuid.UUID(str(ref))
    if nid is None:
        return None
    nid = canonical_of(reader.s, reader.tenant_id, nid) or nid
    return reader.nodes([nid]).get(nid)


def translate_domain(payload: dict[str, Any], reader: GraphReader) -> list[dict[str, Any]]:
    et = str(payload.get("type") or "")
    if et not in DOMAIN_EVENT_TYPES:
        raise ValueError(f"unknown domain event type {et!r} (known: {', '.join(DOMAIN_EVENT_TYPES)})")
    data = dict(payload.get("data") or {})
    source = dict(payload.get("source") or {})
    if not source.get("system"):
        raise ValueError("a domain event needs source.system")
    when = payload.get("occurred_at")
    evidence = list(payload.get("evidence") or [{"system": source["system"], "record": source.get("record", "")}])
    if et == "supplier.delay":
        from cie.state.events import translate

        sup = _view(reader, payload["entity"])
        if sup is None:
            raise ValueError("unknown supplier")
        return translate("supplier_delay", {"supplier": sup.key, "new_date": data["new_date"], "product": data.get("product"),
                                            "notice": data.get("notice"), "notice_date": str(when or data["new_date"])[:10],
                                            "source_pointers": evidence}, reader)
    node = _view(reader, payload["entity"])
    if node is None:
        raise ValueError(f"unknown record {payload.get('entity')!r}")
    ref = str(node.id)
    common = {"ref": ref, "source": source, "effective_at": when, "evidence": evidence}
    if payload.get("version") is not None:
        common["expected_version"] = int(payload["version"])
    if et in ("payment.confirmed", "invoice.paid"):
        if node.type != "invoice":
            raise ValueError(f"{et} is about an invoice, not a {node.type}")
        paid = float(data.get("amount_paid_total", data.get("amount", 0)))
        due = node.attrs.get("amount")
        status = "paid" if due is None or paid + 1e-9 >= float(due) else "partially_paid"
        return [{"op": "observe", "field": "amount_paid", "value": paid, **common},
                {"op": "set_status", "status": status, **common}]
    if et == "delivery.date_changed":
        return [{"op": "observe", "field": "promised_date", "value": str(data.get("promised_date") or data["new_date"])[:10], **common}]
    if et == "order.status_changed":
        return [{"op": "set_status", "status": str(data["status"]), **common}]
    if et == "task.completed":
        return [{"op": "set_status", "status": "done", **common}]
    # entity.updated
    return [{"op": "observe", "values": dict(data.get("values") or {}), **common}]
