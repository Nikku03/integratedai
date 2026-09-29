"""Live state events: idempotent events -> versioned state changes, in commit order.

An event is stored once per (tenant, idempotency key); submitting it again returns the stored event. Processing
happens in one transaction under the tenant lock: the event takes the next sequence number; version checks run
against the state it will change; its operations write new versions and field statements (nothing is overwritten
or removed); generated content derived from changed records is invalidated and narrowed to its sources' access;
cached results that used a changed record are marked stale; and an optional analysis (such as REM's change rules)
runs on the snapshot that includes the change. A crash rolls all of it back and the worker's retry applies it
once; a processed event is never applied twice.

The analysis reads the new state and may write only derived, labelled content (rule or inferred relationships,
review marks on generated records). It never decides identity, permissions, transaction order or task status.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cie.core.models import Scope
from cie.governance.audit import audit
from cie.state import domain
from cie.state.consistency import invalidate_derived, invalidate_results, propagate_access
from cie.state.fields import Authority, FieldStore, Source
from cie.state.identity import IdentityStore
from cie.state.models import RemEvent, RemNode, RemStock, StateConflict
from cie.state.store import GraphReader, GraphWriter

EVENT_KINDS = ("ops", "supplier_delay", "stock_count", "task_status", "restrict", "domain")
FIELD_OPS = ("observe", "set_status", "set_owner", "verify_entity", "resolve_conflict")
IDENTITY_OPS = ("upsert_entity", "add_identifier", "confirm_match", "reject_match")
VERSIONED_OPS = ("revise_node", "delete_node", "restrict_node", "observe", "set_status", "set_owner", "verify_entity")
TERMINAL = ("done", "rejected", "conflict")


class IdempotencyConflict(ValueError):
    """The idempotency key was already used for a different payload."""


class Unauthorized(PermissionError):
    """The submitting principal may not write a record the event would create, change or delete."""


class StaleWrite(RuntimeError):
    """The event was based on a version of a record that has since changed."""


def _digest(kind: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps([kind, payload], sort_keys=True, default=str).encode()).hexdigest()


def submit_event(session: Session, tenant_id: uuid.UUID, *, kind: str, payload: dict[str, Any], idempotency_key: str,
                 principal_id: uuid.UUID | None = None) -> tuple[RemEvent, bool]:
    """Store an event once. Returns (event, created). Re-submitting the same key and payload is a no-op."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"event kind must be one of {EVENT_KINDS}")
    digest = _digest(kind, payload)
    ev = session.scalar(select(RemEvent).where(RemEvent.tenant_id == tenant_id, RemEvent.idempotency_key == idempotency_key))
    if ev is not None:
        if (ev.summary or {}).get("payload_sha256") not in (None, digest):
            raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was used for a different event")
        return ev, False
    ev = RemEvent(tenant_id=tenant_id, idempotency_key=idempotency_key, kind=kind, payload=payload, principal_id=principal_id,
                  status="queued", summary={"payload_sha256": digest})
    try:
        with session.begin_nested():  # a concurrent submit of the same key wins the race; return its event
            session.add(ev)
            session.flush()
    except IntegrityError:
        other = session.scalar(select(RemEvent).where(RemEvent.tenant_id == tenant_id, RemEvent.idempotency_key == idempotency_key))
        if other is None:
            raise
        if (other.summary or {}).get("payload_sha256") not in (None, digest):
            raise IdempotencyConflict(f"idempotency key {idempotency_key!r} was used for a different event") from None
        return other, False
    return ev, True


# ---------------------------------------------------------------------------------------------- operations
def _scope_id(session: Session, tenant_id: uuid.UUID, scope: Any, cache: dict) -> uuid.UUID:
    if isinstance(scope, uuid.UUID):
        return scope
    s = str(scope)
    if s in cache:
        return cache[s]
    try:
        sid = uuid.UUID(s)
        if session.scalar(select(Scope.id).where(Scope.tenant_id == tenant_id, Scope.id == sid)) is None:
            raise ValueError(f"unknown scope {s!r}")
    except ValueError as e:
        if "unknown scope" in str(e):
            raise
        ids = session.scalars(select(Scope.id).where(Scope.tenant_id == tenant_id, Scope.name == s)).all()
        if not ids:
            raise ValueError(f"unknown scope {s!r}") from None
        if len(ids) > 1:
            raise ValueError(f"scope name {s!r} is ambiguous in this tenant; use the scope id") from None
        sid = ids[0]
    cache[s] = sid
    return sid


def _ref(writer: GraphWriter, ref) -> uuid.UUID:
    """A record reference: its id, ``[type, key]``, or ``{"type", "scheme", "value"}`` (a strong identifier). A record
    merged into another resolves to the canonical record."""
    from cie.state.identity import canonical_of, find_by_identifier

    if isinstance(ref, dict):
        if "scheme" in ref:
            nid = find_by_identifier(writer.s, writer.tenant_id, str(ref["type"]), str(ref["scheme"]), ref["value"])
            if nid is None:
                raise ValueError(f"unknown record {ref['type']} with {ref['scheme']} {ref['value']}")
            return nid
        ref = [ref["type"], ref["key"]]
    if isinstance(ref, (uuid.UUID, str)):
        nid = ref if isinstance(ref, uuid.UUID) else uuid.UUID(ref)
        row = writer.s.execute(select(RemNode.id, RemNode.deleted_seq).where(RemNode.id == nid, RemNode.tenant_id == writer.tenant_id)).first()
        if row is None:
            raise ValueError(f"unknown record {nid}")  # never another tenant's record
    else:
        row = writer.s.execute(select(RemNode.id, RemNode.deleted_seq).where(RemNode.tenant_id == writer.tenant_id, RemNode.type == ref[0],
                                                                              RemNode.key == ref[1])).first()
        if row is None:
            raise ValueError(f"unknown record {ref[0]}:{ref[1]}")
    if row.deleted_seq is not None:
        return canonical_of(writer.s, writer.tenant_id, row.id) or row.id
    return row.id


def authorize_ops(session: Session, tenant_id: uuid.UUID, vis, ops: list[dict[str, Any]]) -> None:
    """Raise ``Unauthorized`` unless ``vis`` may write every record the operations touch: the current scope of a record
    that is changed, restricted or deleted, the scope a record is put in, both ends of a relationship, and the scope of
    a stock row. ``vis`` None is the system itself (ingestion, replay)."""
    if vis is None:
        return
    w = GraphWriter(session, tenant_id)
    scopes: dict = {}
    pending: dict[tuple[str, str], uuid.UUID] = {}

    def need(scope_id, what: str) -> None:
        if scope_id is None or not vis.can_write(scope_id):
            raise Unauthorized(f"write access required for {what}")

    def current_scope(ref, what: str):
        if isinstance(ref, (list, tuple)) and tuple(ref) in pending:
            return pending[tuple(ref)]
        try:
            nid = _ref(w, ref)
        except ValueError:
            raise Unauthorized(f"write access required for {what}") from None  # unknown and invisible look the same
        cur = w.current(nid)
        return cur.scope_id if cur is not None else None

    for op in ops:
        k = op.get("op")
        if k == "upsert_node":
            new = _scope_id(session, tenant_id, op["scope"], scopes)
            need(new, f"{op['type']} {op['key']}")
            nid = w.node_id(op["type"], op["key"])
            cur = w.current(nid) if nid else None
            if cur is not None:
                need(cur.scope_id, f"{op['type']} {op['key']}")
            elif nid is not None and _merged(w, op["type"], op["key"]):  # its values will go to the canonical record
                need(current_scope(_merged(w, op["type"], op["key"])[1], "the merged record"), "the merged record")
            pending[(op["type"], op["key"])] = new
        elif k in ("revise_node", "delete_node", "restrict_node"):
            need(current_scope(op["ref"], "the record"), "the record")
            if k == "restrict_node" and "scope" in op:
                need(_scope_id(session, tenant_id, op["scope"], scopes), "the new scope")
            if k == "revise_node" and ({"authoritative", "verification"} & set(op)) and not vis.is_admin:
                raise Unauthorized("only an administrator can change verification or authority")
        elif k in ("observe", "set_status", "set_owner", "verify_entity"):
            need(current_scope(op["ref"], "the record"), "the record")
            if k == "verify_entity" and not _can_verify(session, vis):
                raise Unauthorized("only an administrator or a principal allowed to verify can mark a record verified")
        elif k == "upsert_entity":
            from cie.state.identity import resolve_entity

            need(_scope_id(session, tenant_id, op["scope"], scopes), f"{op['type']} {op['name']}")
            res = resolve_entity(session, tenant_id, str(op["type"]), str(op["name"]), op.get("identifiers"), key=op.get("key"))
            if res.status == "matched":
                need(current_scope(res.node_id, "the matched record"), "the matched record")
        elif k == "add_identifier":
            need(current_scope(op["ref"], "the record"), "the record")
        elif k in ("confirm_match", "reject_match"):
            from cie.state.models import StateMatchProposal

            try:
                p = session.get(StateMatchProposal, uuid.UUID(str(op["proposal"])))
            except ValueError:
                p = None
            if p is None or p.tenant_id != tenant_id:
                raise Unauthorized("write access required for both records")
            need(current_scope(p.a_id, "both records"), "both records")
            need(current_scope(p.b_id, "both records"), "both records")
        elif k == "resolve_conflict":
            try:
                c = session.get(StateConflict, uuid.UUID(str(op["conflict"])))
            except ValueError:
                c = None
            if c is None or c.tenant_id != tenant_id:
                raise Unauthorized("write access required for the conflict's record")
            need(current_scope(c.node_id, "the conflict's record"), "the conflict's record")
        elif k in ("upsert_edge", "close_edge"):
            need(current_scope(op["src"], "the relationship's source"), "the relationship's source")
            need(current_scope(op["dst"], "the relationship's target"), "the relationship's target")
        elif k == "set_stock":
            need(_scope_id(session, tenant_id, op["scope"], scopes), "the stock record")
            try:
                prod, holder = _ref(w, ["product", op["product"]]), _ref(w, op["holder"])
            except ValueError:
                raise Unauthorized("write access required for the stock record") from None
            row = session.scalar(select(RemStock).where(RemStock.tenant_id == tenant_id, RemStock.product_id == prod,
                                                        RemStock.holder_id == holder, RemStock.sys_to.is_(None)))
            if row is not None:
                need(row.scope_id, "the stock record")
        else:
            raise ValueError(f"unknown operation {k!r}")


def _can_verify(session: Session, vis) -> bool:
    if vis is None or vis.is_admin:
        return True
    from cie.core.models import Principal

    p = session.get(Principal, vis.principal_id)
    return bool(p is not None and (p.attributes or {}).get("can_verify"))


def _canonical_view(reader: GraphReader, type_: str, key: str):
    """The canonical record behind a merged record's key, as the reader sees it."""
    from cie.state.models import StateAlias

    canonical = reader.s.scalar(select(StateAlias.canonical_id).where(StateAlias.tenant_id == reader.tenant_id,
                                                                      StateAlias.alias_type == type_, StateAlias.alias_key == key))
    if canonical is None:
        return None
    from cie.state.identity import canonical_of

    canonical = canonical_of(reader.s, reader.tenant_id, canonical) or canonical
    return reader.nodes([canonical]).get(canonical)


def translate(kind: str, payload: dict[str, Any], reader: GraphReader) -> list[dict[str, Any]]:
    """Domain events -> generic operations. Every translation is explicit and reads exact values from the graph."""
    if kind == "ops":
        return list(payload.get("ops", []))
    if kind == "supplier_delay":
        sup = reader.node_by_key("supplier", payload["supplier"]) or _canonical_view(reader, "supplier", payload["supplier"])
        if sup is None:
            raise ValueError(f"unknown supplier {payload['supplier']!r}")
        new_date = domain.as_date(payload["new_date"])
        ops: list[dict[str, Any]] = list(payload.get("ops", []))  # e.g. the notice document and its passage
        edges, views, _ = reader.edges([sup.id], kinds=("depends_on",), direction="in")
        for e in edges:
            o = views.get(e.src)
            if o is None or o.type != "order" or not domain.is_open_order(o.attrs):
                continue
            if payload.get("product") and str(o.attrs.get("product")) != payload["product"]:
                continue
            cur = domain.as_date(o.attrs.get("promised_date"))
            if cur is not None and cur >= new_date:
                continue
            ops.append({"op": "revise_node", "ref": ["order", o.key],
                        "attrs": {"promised_date": new_date.isoformat(), "delay_notice": payload.get("notice"),
                                  "revision": int(o.attrs.get("revision") or 1) + 1,
                                  "source_date": payload.get("notice_date", new_date.isoformat())},
                        "add_source_pointers": payload.get("source_pointers", [])})
        return ops
    if kind == "stock_count":
        return [{"op": "set_stock", **payload}]
    if kind == "task_status":
        return [{"op": "revise_node", "ref": ["task", payload["task"]], "attrs": {"status": payload["status"]}}]
    if kind == "restrict":
        return [{"op": "restrict_node", **payload}]
    if kind == "domain":
        from cie.state.domain_events import translate_domain

        return translate_domain(payload, reader)
    raise ValueError(kind)


def apply_ops(session: Session, writer: GraphWriter, ops: list[dict[str, Any]], fields: FieldStore | None = None,
              identity: IdentityStore | None = None) -> tuple[list[uuid.UUID], list[uuid.UUID]]:
    """Apply operations at the writer's sequence number. Returns (deleted ids, restricted ids)."""
    scopes: dict = {}
    deleted, restricted = [], []
    fields = fields or FieldStore(session, writer, Authority(session, writer.tenant_id))
    identity = identity or IdentityStore(session, writer, fields, fields.principal_id)
    for i, op in enumerate(ops):
        kind = op["op"]
        if kind in FIELD_OPS:
            _apply_field_op(writer, fields, op)
        elif kind in IDENTITY_OPS:
            _apply_identity_op(session, writer, identity, op, i, scopes)
        elif kind == "upsert_node" and identity.aliases_exist() and _merged(writer, op["type"], op["key"]):
            alias, canonical = _merged(writer, op["type"], op["key"])
            identity.redirect_upsert(alias, canonical, op)
        elif kind == "upsert_node":
            projects = [_ref(writer, ["project", k]) for k in op.get("project_keys", [])]
            departments = [_ref(writer, ["department", k]) for k in op.get("department_keys", [])]
            writer.upsert_node(op["type"], op["key"], name=op["name"], summary=op.get("summary", ""), attrs=op.get("attrs", {}),
                               scope_id=_scope_id(session, writer.tenant_id, op["scope"], scopes),
                               sensitivity=int(op.get("sensitivity", 1)), acl=op.get("acl"), project_ids=projects,
                               department_ids=departments, source_pointers=op.get("source_pointers", []),
                               root_sources=op.get("root_sources", []), verification=op.get("verification", "unverified"),
                               authoritative=bool(op.get("authoritative", True)), valid_from=op.get("valid_from"),
                               valid_to=op.get("valid_to"))
        elif kind == "revise_node":
            nid = _ref(writer, op["ref"])
            cur = writer.current(nid)
            changes: dict[str, Any] = {}
            if "attrs" in op:
                changes["attrs"] = op["attrs"]
            for f in ("name", "summary", "verification", "valid_from", "valid_to", "authoritative", "root_sources"):
                if f in op:
                    changes[f] = op[f]
            if op.get("add_source_pointers"):
                changes["source_pointers"] = list(cur.source_pointers or []) + [p for p in op["add_source_pointers"]
                                                                                if p not in (cur.source_pointers or [])]
            writer.revise(nid, **changes)
        elif kind == "upsert_edge":
            writer.upsert_edge(_ref(writer, op["src"]), op["kind"], _ref(writer, op["dst"]), provenance=op.get("provenance", "explicit"),
                               status=op.get("status"), attrs=op.get("attrs"), source_pointers=op.get("source_pointers"),
                               derivation=op.get("derivation"), valid_from=op.get("valid_from"), valid_to=op.get("valid_to"),
                               source_key=op.get("source_key", ""))
        elif kind == "close_edge":
            writer.close_edges(src=_ref(writer, op["src"]), dst=_ref(writer, op["dst"]), kind=op.get("kind"))
            for r in (op["src"], op["dst"]):
                writer.changed.setdefault(_ref(writer, r), []).append(f"edge:{op.get('kind')}")
        elif kind == "set_stock":
            writer.set_stock(_ref(writer, ["product", op["product"]]), _ref(writer, op["holder"]), on_hand=float(op["on_hand"]),
                             reserved=float(op.get("reserved", 0)), scope_id=_scope_id(session, writer.tenant_id, op["scope"], scopes),
                             sensitivity=int(op.get("sensitivity", 1)), source_pointers=op.get("source_pointers", []))
        elif kind == "delete_node":
            nid = _ref(writer, op["ref"])
            writer.delete_node(nid)
            deleted.append(nid)
        elif kind == "restrict_node":
            nid = _ref(writer, op["ref"])
            changes = {}
            if "scope" in op:
                changes["scope_id"] = _scope_id(session, writer.tenant_id, op["scope"], scopes)
            if "sensitivity" in op:
                changes["sensitivity"] = int(op["sensitivity"])
            if "acl" in op:
                changes["acl"] = op["acl"]
            writer.revise(nid, **changes)
            restricted.append(nid)
        else:
            raise ValueError(f"unknown operation {kind!r}")
    return deleted, restricted


def _apply_field_op(writer: GraphWriter, fields: FieldStore, op: dict[str, Any]) -> None:
    kind = op["op"]
    if kind == "resolve_conflict":
        fields.resolve(uuid.UUID(str(op["conflict"])), str(op.get("accept", "")), str(op.get("note", "")))
        return
    nid = _ref(writer, op["ref"])
    if kind == "verify_entity":
        fields.verify(nid, op.get("fields"), str(op.get("method") or "verified"), op.get("at"))
        return
    src = Source.from_dict(op.get("source"))
    if kind == "observe":
        values = dict(op["values"]) if "values" in op else {str(op["field"]): op.get("value")}
    elif kind == "set_status":
        values = {"status": str(op["status"])}
    else:  # set_owner
        values = {"owner": str(op["owner"])}
    for name, value in values.items():
        d = fields.observe(nid, name, value, src, effective_at=op.get("effective_at"), evidence=op.get("evidence"))
        if kind == "set_owner" and d.status == "current":
            person = writer.node_id("person", str(op["owner"])) or writer.node_id("team", str(op["owner"]))
            writer.close_edges(src=nid, kind="owned_by")
            if person is not None:
                writer.upsert_edge(nid, "owned_by", person, source_pointers=list(op.get("evidence") or []))


def _merged(writer: GraphWriter, type_: str, key: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    from cie.state.identity import canonical_of

    row = writer.s.execute(select(RemNode.id, RemNode.deleted_seq).where(RemNode.tenant_id == writer.tenant_id, RemNode.type == type_,
                                                                          RemNode.key == key)).first()
    if row is None or row.deleted_seq is None:
        return None
    canonical = canonical_of(writer.s, writer.tenant_id, row.id)
    return (row.id, canonical) if canonical is not None else None


def _apply_identity_op(session: Session, writer: GraphWriter, identity: IdentityStore, op: dict[str, Any], index: int,
                       scopes: dict) -> None:
    kind = op["op"]
    if kind == "upsert_entity":
        identity.upsert_entity(op, index, _scope_id(session, writer.tenant_id, op["scope"], scopes))
    elif kind == "add_identifier":
        identity.results.append(identity.add_identifier(_ref(writer, op["ref"]), str(op["scheme"]), op["value"], op.get("source"),
                                                        replace=bool(op.get("replace"))))
    elif kind == "confirm_match":
        identity.confirm(uuid.UUID(str(op["proposal"])), op.get("canonical"), str(op.get("note", "")))
    elif kind == "reject_match":
        identity.reject(uuid.UUID(str(op["proposal"])), str(op.get("note", "")))


def check_versions(writer: GraphWriter, ops: list[dict[str, Any]]) -> None:
    """Refuse the event when an operation names the version it was based on and the record has moved on."""
    for op in ops:
        if op.get("op") not in VERSIONED_OPS or op.get("expected_version") is None:
            continue
        nid = _ref(writer, op["ref"])
        cur = writer.current(nid)
        have = cur.version if cur is not None else None
        if have != int(op["expected_version"]):
            node = writer.s.get(RemNode, nid)
            raise StaleWrite(f"{node.type} {node.key} is at version {have}, not {op['expected_version']}; re-read it and resubmit")


# ---------------------------------------------------------------------------------------------- processing
@dataclass
class ChangeSet:
    """What one event changed, for analyses and task routing."""

    event: RemEvent
    seq: int
    ops: list[dict[str, Any]]
    prev: GraphReader
    changed: dict[uuid.UUID, list[str]]  # excluding deleted records
    deleted: list[uuid.UUID]
    restricted: list[uuid.UUID]
    decisions: list[Any] = field(default_factory=list)


class AnalysisWriter:
    """What an analysis may write: derived relationships (rule or inferred, with their derivation) and review marks
    on generated records. Anything else raises."""

    def __init__(self, writer: GraphWriter):
        self._w = writer
        self.s = writer.s
        self.tenant_id = writer.tenant_id

    @property
    def changed(self) -> dict[uuid.UUID, list[str]]:
        return self._w.changed

    def current(self, node_id: uuid.UUID):
        return self._w.current(node_id)

    def upsert_edge(self, src: uuid.UUID, kind: str, dst: uuid.UUID, *, provenance: str, **kw) -> uuid.UUID:
        if provenance not in ("rule", "inferred"):
            raise PermissionError("an analysis may only add derived relationships")
        return self._w.upsert_edge(src, kind, dst, provenance=provenance, **kw)

    def revise(self, node_id: uuid.UUID, **changes) -> list[str]:
        cur = self._w.current(node_id)
        if set(changes) != {"review_status"} or cur is None or cur.authoritative:
            raise PermissionError("an analysis may only mark generated records for review")
        return self._w.revise(node_id, **changes)


Analysis = Callable[[Session, ChangeSet, AnalysisWriter, dict[str, Any]], dict[str, Any]]


def _memberships(session: Session, tenant_id: uuid.UUID, changed: dict[uuid.UUID, list[str]], seq: int) -> set[uuid.UUID]:
    """The projects and departments a record joined or left in this change. A project changes when its membership
    does, so an answer about a project's orders is refreshed when an order is added to it or removed from it."""
    from cie.state.models import RemNodeVersion

    moved = [nid for nid, fs in changed.items() if {"created", "deleted", "project_ids", "department_ids"} & set(fs)]
    if not moved:
        return set()
    out: set[uuid.UUID] = set()
    rows = session.execute(select(RemNodeVersion.project_ids, RemNodeVersion.department_ids).where(
        RemNodeVersion.tenant_id == tenant_id, RemNodeVersion.node_id.in_(moved),
        (RemNodeVersion.sys_to.is_(None)) | (RemNodeVersion.sys_to >= seq))).all()
    for projects, departments in rows:  # the version before the change and the one after it
        out |= set(projects or []) | set(departments or [])
    return out


def _visibility(session: Session, principal_id: uuid.UUID | None):
    if principal_id is None:
        return None
    from cie.core.models import Principal
    from cie.governance.permissions import visible_scopes

    principal = session.get(Principal, principal_id)
    return visible_scopes(session, principal) if principal is not None else None


def _finish(session: Session, ev: RemEvent, status: str, error: str) -> dict[str, Any]:
    ev.status, ev.error, ev.processed_at = status, error, datetime.now(UTC)
    ev.summary = {**(ev.summary or {}), "status": status, "error": error}
    audit(session, tenant_id=ev.tenant_id, principal_id=ev.principal_id, action="state.change", resource_kind="rem_event",
          resource_id=ev.id, details={"kind": ev.kind, "status": status}, outcome="denied" if status == "rejected" else "conflict")
    session.flush()
    return ev.summary


def process_event(session: Session, event_id: uuid.UUID, *, embedder=None, analysis: Analysis | None = None,
                  analysis_name: str = "none", limits: dict[str, Any] | None = None, route_tasks: bool = True) -> dict[str, Any]:
    """Apply one event to the live state, then run ``analysis`` (optional) on the new snapshot."""
    ev = session.get(RemEvent, event_id, with_for_update=True, populate_existing=True)
    if ev is None:
        raise KeyError(event_id)
    if ev.status in TERMINAL:
        return ev.summary
    ev.attempts = (ev.attempts or 0) + 1
    vis = _visibility(session, ev.principal_id)
    savepoint = session.begin_nested()
    writer = GraphWriter(session, ev.tenant_id, embedder=embedder, event_id=ev.id)
    seq = writer.begin()
    prev = GraphReader(session, ev.tenant_id, None, seq=seq - 1)
    ops = translate(ev.kind, ev.payload, prev)
    try:
        authorize_ops(session, ev.tenant_id, vis, ops)  # checked again under the tenant lock, on the state it will change
        check_versions(writer, ops)
    except Unauthorized as e:
        savepoint.rollback()  # nothing applied, no sequence number used
        return _finish(session, ev, "rejected", str(e))
    except StaleWrite as e:
        savepoint.rollback()
        return _finish(session, ev, "conflict", str(e))
    t_ops = time.perf_counter()
    fields = FieldStore(session, writer, Authority(session, ev.tenant_id), principal_id=ev.principal_id)
    identity = IdentityStore(session, writer, fields, ev.principal_id)
    deleted, restricted = apply_ops(session, writer, ops, fields, identity)
    overwritten = fields.reconcile_direct(writer.changed)
    # any change of scope, clearance or access list is a restriction for content derived from the record
    restricted += [k for k, f in writer.changed.items() if k not in restricted and "created" not in f
                   and {"scope_id", "sensitivity", "acl"} & set(f)]
    op_changed = {str(k): sorted(set(v)) for k, v in writer.changed.items()}
    narrowed = propagate_access(writer, restricted, seq)
    invalidated = invalidate_derived(writer, dict(writer.changed), deleted, restricted, seq)
    for pid in _memberships(session, ev.tenant_id, writer.changed, seq):  # a project whose members changed has changed
        if pid not in deleted:
            writer.changed.setdefault(pid, []).append("membership")
    ops_ms = (time.perf_counter() - t_ops) * 1000
    cs = ChangeSet(event=ev, seq=seq, ops=ops, prev=prev, changed={k: v for k, v in writer.changed.items() if k not in deleted},
                   deleted=deleted, restricted=restricted, decisions=fields.decisions)
    t_an = time.perf_counter()
    result: dict[str, Any] = {"impacts": 0, "suggestions": 0, "status": "complete", "stopping_reason": "no_analysis",
                              "budget": {}, "rule_log": []}
    if analysis is not None:
        result.update(analysis(session, cs, AnalysisWriter(writer), limits or {}))
    detect_ms = (time.perf_counter() - t_an) * 1000
    if writer.changed:  # every kind of change, including relationships and stock counts, which add no node version
        session.execute(update(RemNode).where(RemNode.tenant_id == ev.tenant_id, RemNode.id.in_(list(writer.changed)))
                        .values(changed_seq=seq))
    stale = invalidate_results(session, ev.tenant_id, list(writer.changed), restricted, seq, ev.id)
    routed: dict[str, Any] = {}
    if route_tasks:
        from cie.workflow.routing import route_to_tasks

        routed = route_to_tasks(session, cs)
    ev.seq = seq
    ev.status = "done"
    ev.processed_at = datetime.now(UTC)
    ev.summary = {**(ev.summary or {}), "seq": seq, "policy": analysis_name, "operations": len(ops),
                  "changed": {str(k): sorted(set(v)) for k, v in writer.changed.items()}, "op_changed": op_changed,
                  "ops_ms": round(ops_ms, 1), "detect_ms": round(detect_ms, 1),
                  "deleted": [str(d) for d in deleted], "restricted": [str(r) for r in restricted],
                  "access_narrowed": [str(n) for n in narrowed], "invalidated": [str(n) for n in invalidated],
                  "field_decisions": [{"node": str(d.node_id), "field": d.field, "status": d.status, "reason": d.reason,
                                       "conflict": str(d.conflict_id) if d.conflict_id else None} for d in fields.decisions],
                  "identity": identity.results, "overwritten_statements": overwritten, "stale_results": stale, "tasks": routed, **result}
    audit(session, tenant_id=ev.tenant_id, principal_id=ev.principal_id, action="state.change", resource_kind="rem_event",
          resource_id=ev.id, details={"seq": seq, "kind": ev.kind, "impacts": result.get("impacts", 0), "analysis": analysis_name})
    savepoint.commit()
    session.flush()
    return ev.summary
