"""Identity resolution for business entities: stable ids, identifiers, match proposals and confirmed aliases.

Rules:

* A **strong identifier** (VAT or tax number, registration number, customer or supplier number, IBAN, DUNS, LEI,
  SKU, GTIN, employee id, a person's email) names one entity of a type. A new record carrying one that is already
  known *is* that entity.
* A **conflicting strong identifier** means different entities. Two suppliers with different VAT numbers are never
  the same supplier, however alike their names.
* **Name similarity alone never merges.** A close name, or a shared weak identifier (phone, domain, address), only
  creates a match proposal. The records stay separate until a person or an authorised process confirms it, and a
  rejected pair is not proposed again.
* **Confirming a match** makes the newer record an alias of the older one. The alias's identifiers, relationships
  and memberships move to the canonical record, and its field statements are replayed through the canonical
  record's authority rules, so disagreements become conflicts rather than silent overwrites. The alias's id and
  business key keep resolving to the canonical record, and its history stays readable.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from cie.memory.entities import normalise as normalise_name
from cie.state.fields import RESERVED_FIELDS, FieldStore, Source
from cie.state.models import (
    RemNode,
    RemNodeVersion,
    RemStock,
    StateAlias,
    StateConflict,
    StateField,
    StateIdentifier,
    StateMatchProposal,
)
from cie.state.store import GraphReader, GraphWriter

STRONG_SCHEMES = ("customer_number", "supplier_number", "tax_id", "vat", "registration_number", "iban", "duns", "lei", "email",
                  "sku", "gtin", "employee_id")
# one value per entity: two different values mean two different entities
SINGLE_VALUED = ("customer_number", "supplier_number", "tax_id", "vat", "registration_number", "duns", "lei", "employee_id")
WEAK_SCHEMES = ("phone", "domain", "address", "postcode", "name")
MERGEABLE_TYPES = ("customer", "supplier", "person", "product", "team", "company")
NAME_THRESHOLD = 90
WEAK_NAME_THRESHOLD = 60


def strength(scheme: str) -> str:
    if scheme in STRONG_SCHEMES:
        return "strong"
    if scheme in WEAK_SCHEMES or scheme.startswith("x_"):
        return "weak"
    raise ValueError(f"unknown identifier scheme {scheme!r} (strong: {', '.join(STRONG_SCHEMES)}; weak: {', '.join(WEAK_SCHEMES)}, or x_*)")


def normalise_identifier(scheme: str, value: Any) -> str:
    v = str(value).strip()
    if scheme == "email":
        return v.lower()
    if scheme == "domain":
        v = re.sub(r"^https?://", "", v.lower())
        return re.sub(r"^www\.", "", v).split("/")[0]
    if scheme == "phone":
        return ("+" if v.startswith("+") else "") + re.sub(r"\D", "", v)
    if scheme in ("name", "address"):
        return normalise_name(v) if scheme == "name" else re.sub(r"\s+", " ", v.lower())
    return re.sub(r"[\s.\-/]", "", v).upper()


def canonical_of(session: Session, tenant_id: uuid.UUID, node_id: uuid.UUID) -> uuid.UUID | None:
    """The canonical record a merged record resolves to, or None if it was never merged."""
    cur, seen = node_id, set()
    while cur not in seen:
        seen.add(cur)
        nxt = session.scalar(select(StateAlias.canonical_id).where(StateAlias.tenant_id == tenant_id, StateAlias.alias_id == cur))
        if nxt is None:
            return cur if cur != node_id else None
        cur = nxt
    return cur


def has_aliases(session: Session, tenant_id: uuid.UUID) -> bool:
    return session.scalar(select(StateAlias.alias_id).where(StateAlias.tenant_id == tenant_id).limit(1)) is not None


def find_by_identifier(session: Session, tenant_id: uuid.UUID, entity_type: str, scheme: str, value: Any) -> uuid.UUID | None:
    v = normalise_identifier(scheme, value)
    nid = session.scalar(select(StateIdentifier.node_id).where(
        StateIdentifier.tenant_id == tenant_id, StateIdentifier.entity_type == entity_type, StateIdentifier.scheme == scheme,
        StateIdentifier.value == v, StateIdentifier.status == "active").limit(1))
    if nid is None:
        return None
    return canonical_of(session, tenant_id, nid) or nid


def identifiers_of(session: Session, tenant_id: uuid.UUID, node_ids) -> dict[uuid.UUID, list[StateIdentifier]]:
    out: dict[uuid.UUID, list[StateIdentifier]] = {}
    ids = list(node_ids)
    if not ids:
        return out
    for r in session.scalars(select(StateIdentifier).where(StateIdentifier.tenant_id == tenant_id, StateIdentifier.node_id.in_(ids),
                                                           StateIdentifier.status == "active")):
        out.setdefault(r.node_id, []).append(r)
    return out


@dataclass
class Candidate:
    node_id: uuid.UUID
    key: str
    name: str
    score: float
    method: str
    reasons: list[str]


@dataclass
class Resolution:
    status: str  # matched | new | conflicting_identifiers
    node_id: uuid.UUID | None = None
    method: str = ""
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)  # possible matches: proposals, never merges
    distinct: list[dict[str, Any]] = field(default_factory=list)  # excluded by a conflicting strong identifier
    colliding: dict[str, uuid.UUID] = field(default_factory=dict)  # scheme -> record already holding the value


def resolve_entity(session: Session, tenant_id: uuid.UUID, entity_type: str, name: str, identifiers: dict[str, Any] | None = None,
                   key: str | None = None, reader: GraphReader | None = None, limit: int = 20) -> Resolution:
    """Decide whether a described entity is a known one. Read-only. ``reader`` (with the caller's permissions)
    limits the candidates reported to records the caller may see."""
    ids = {s: normalise_identifier(s, v) for s, v in (identifiers or {}).items() if v not in (None, "")}
    for s in ids:
        strength(s)
    if key:
        nid = session.scalar(select(RemNode.id).where(RemNode.tenant_id == tenant_id, RemNode.type == entity_type, RemNode.key == key))
        if nid is not None:
            return Resolution("matched", canonical_of(session, tenant_id, nid) or nid, "business_key", f"business key {key}")
    strong_hits: dict[str, uuid.UUID] = {}
    for s, v in ids.items():
        if strength(s) == "strong":
            nid = find_by_identifier(session, tenant_id, entity_type, s, v)
            if nid is not None:
                strong_hits[s] = nid
    if len(set(strong_hits.values())) == 1:
        nid = next(iter(strong_hits.values()))
        mine = identifiers_of(session, tenant_id, [nid]).get(nid, [])
        clash = [f"{i.scheme} {i.value} vs {ids[i.scheme]}" for i in mine
                 if i.scheme in SINGLE_VALUED and i.scheme in ids and i.value != ids[i.scheme]]
        if not clash:
            return Resolution("matched", nid, "strong_identifier", "same " + ", ".join(sorted(strong_hits)))
        return Resolution("conflicting_identifiers", None, "", f"shares {', '.join(sorted(strong_hits))} but differs in {'; '.join(clash)}",
                          colliding=strong_hits)
    if len(set(strong_hits.values())) > 1:
        return Resolution("conflicting_identifiers", None, "", "its identifiers belong to different records: "
                          + ", ".join(f"{s} -> {n}" for s, n in sorted(strong_hits.items())), colliding=strong_hits)
    # no strong identifier matched: look for possible matches by name and weak identifiers
    key_name = normalise_name(name)
    cur = (select(RemNodeVersion.node_id, RemNode.key, RemNodeVersion.name)
           .join(RemNode, RemNode.id == RemNodeVersion.node_id)
           .where(RemNodeVersion.tenant_id == tenant_id, RemNode.type == entity_type, RemNode.deleted_seq.is_(None),
                  RemNodeVersion.sys_to.is_(None)))
    by_name = session.execute(cur.where(func.similarity(RemNodeVersion.name, name) > 0.3)
                              .order_by(func.similarity(RemNodeVersion.name, name).desc()).limit(limit * 2)).all()
    weak = {s: v for s, v in ids.items() if strength(s) == "weak"}
    weak_hits: dict[uuid.UUID, list[str]] = {}
    for s, v in weak.items():
        for (nid,) in session.execute(select(StateIdentifier.node_id).where(
                StateIdentifier.tenant_id == tenant_id, StateIdentifier.entity_type == entity_type, StateIdentifier.scheme == s,
                StateIdentifier.value == v, StateIdentifier.status == "active").limit(limit)):
            weak_hits.setdefault(canonical_of(session, tenant_id, nid) or nid, []).append(f"same {s}")
    rows = {r[0]: (r[1], r[2]) for r in by_name}
    missing = set(weak_hits) - set(rows)
    if missing:
        rows.update({r[0]: (r[1], r[2]) for r in session.execute(cur.where(RemNodeVersion.node_id.in_(missing))).all()})
    known = identifiers_of(session, tenant_id, rows)
    visible = reader.visible_ids(rows) if reader is not None and reader.vis is not None else set(rows)
    res = Resolution("new")
    for nid, (k, cname) in rows.items():
        if nid not in visible:
            continue
        names = [normalise_name(cname)] + [i.value for i in known.get(nid, []) if i.scheme == "name"]
        score = max((fuzz.token_sort_ratio(key_name, n) for n in names if n), default=0.0)
        clash = [f"{i.scheme} {i.value} vs {ids[i.scheme]}" for i in known.get(nid, [])
                 if i.scheme in SINGLE_VALUED and i.scheme in ids and i.value != ids[i.scheme]]
        if clash:
            if score >= NAME_THRESHOLD or nid in weak_hits:
                res.distinct.append({"node_id": str(nid), "key": k, "name": cname, "reason": "different " + "; ".join(clash)})
            continue
        reasons = list(weak_hits.get(nid, []))
        if score >= NAME_THRESHOLD:
            reasons.insert(0, f"name similarity {score:.0f}")
        elif not (reasons and score >= WEAK_NAME_THRESHOLD):
            continue
        res.candidates.append(Candidate(nid, k, cname, round(score, 1), "weak_identifier" if nid in weak_hits else "name_similarity", reasons))
    res.candidates.sort(key=lambda c: -c.score)
    res.candidates = res.candidates[:limit]
    return res


def _pair(a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    return (a, b) if str(a) < str(b) else (b, a)


class IdentityStore:
    """Identity operations within one event."""

    def __init__(self, session: Session, writer: GraphWriter, fields: FieldStore, principal_id: uuid.UUID | None = None):
        self.s = session
        self.w = writer
        self.fields = fields
        self.principal_id = principal_id
        self.results: list[dict[str, Any]] = []
        self._aliases: bool | None = None

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.w.tenant_id

    def aliases_exist(self) -> bool:
        if self._aliases is None:
            self._aliases = has_aliases(self.s, self.tenant_id)
        return self._aliases

    # ------------------------------------------------------------------------------------------ identifiers
    def add_identifier(self, node_id: uuid.UUID, scheme: str, value: Any, source: dict[str, Any] | None = None,
                       replace: bool = False) -> dict[str, Any]:
        node = self.s.get(RemNode, node_id)
        st, v = strength(scheme), normalise_identifier(scheme, value)
        if not v:
            raise ValueError(f"empty {scheme}")
        mine = [i for i in identifiers_of(self.s, self.tenant_id, [node_id]).get(node_id, []) if i.scheme == scheme]
        if any(i.value == v for i in mine):
            return {"node": str(node_id), "scheme": scheme, "status": "known"}
        if st == "strong":
            holder = find_by_identifier(self.s, self.tenant_id, node.type, scheme, v)
            if holder is not None and holder != node_id:
                p = self.propose(node_id, holder, 100.0, "shared_strong_identifier", [f"both carry {scheme} {v}"])
                return {"node": str(node_id), "scheme": scheme, "status": "held_by_another_record", "holder": str(holder),
                        "proposal": str(p.id) if p is not None else None}
            if scheme in SINGLE_VALUED and mine:
                if not replace:
                    raise ValueError(f"{node.type} {node.key} already has {scheme} {mine[0].value}; pass replace to change it")
                for i in mine:
                    i.status = "retired"
                self.s.flush()
        self.s.add(StateIdentifier(tenant_id=self.tenant_id, node_id=node_id, entity_type=node.type, scheme=scheme, value=v,
                                   raw=str(value)[:300], strength=st, source=source or {}, recorded_seq=self.w._need_seq()))
        self.s.flush()
        return {"node": str(node_id), "scheme": scheme, "status": "added"}

    # ------------------------------------------------------------------------------------------ proposals
    def propose(self, a: uuid.UUID, b: uuid.UUID, score: float, method: str, reasons: list[str]) -> StateMatchProposal | None:
        a, b = _pair(a, b)
        p = self.s.scalar(select(StateMatchProposal).where(StateMatchProposal.tenant_id == self.tenant_id, StateMatchProposal.a_id == a,
                                                           StateMatchProposal.b_id == b))
        if p is not None:
            if p.status == "proposed":  # the same pair again: keep one proposal, with every reason
                p.reasons = list(dict.fromkeys(list(p.reasons or []) + reasons))
                p.score = max(p.score, score)
            return p if p.status == "proposed" else None  # a rejected or confirmed pair is not proposed again
        t = self.s.get(RemNode, a).type
        p = StateMatchProposal(tenant_id=self.tenant_id, a_id=a, b_id=b, entity_type=t, score=score, method=method, reasons=reasons,
                               status="proposed", created_seq=self.w._need_seq())
        self.s.add(p)
        self.s.flush()
        return p

    def reject(self, proposal_id: uuid.UUID, note: str = "") -> dict[str, Any]:
        p = self._proposal(proposal_id)
        p.status, p.decided_by, p.decided_seq = "rejected", self.principal_id, self.w._need_seq()
        p.reasons = list(p.reasons or []) + ([f"rejected: {note}"] if note else ["rejected"])
        r = {"proposal": str(p.id), "status": "rejected"}
        self.results.append(r)
        return r

    def _proposal(self, proposal_id: uuid.UUID) -> StateMatchProposal:
        p = self.s.get(StateMatchProposal, proposal_id, with_for_update=True)
        if p is None or p.tenant_id != self.tenant_id:
            raise ValueError(f"unknown match proposal {proposal_id}")
        if p.status != "proposed":
            raise ValueError(f"the proposal is already {p.status}")
        return p

    # ------------------------------------------------------------------------------------------ upsert
    def upsert_entity(self, op: dict[str, Any], index: int, scope_id: uuid.UUID) -> dict[str, Any]:
        et, name = str(op["type"]), str(op["name"])
        ids = dict(op.get("identifiers") or {})
        src = Source.from_dict(op.get("source") or {"system": "direct"})
        res = resolve_entity(self.s, self.tenant_id, et, name, ids, key=op.get("key"))
        out: dict[str, Any] = {"op": "upsert_entity", "type": et, "name": name, "resolution": res.status, "method": res.method,
                               "reason": res.reason}
        if res.status == "matched":
            nid = res.node_id
            node = self.s.get(RemNode, nid)
            if node.deleted_seq is not None:
                raise ValueError(f"{et} {node.key} was deleted")
        else:
            key = op.get("key") or f"{et}_{hashlib.sha1(f'{self.w.event_id}:{index}'.encode()).hexdigest()[:10]}"
            nid, _, _ = self.w.upsert_node(et, key, name=name, scope_id=scope_id, summary=op.get("summary", ""), attrs={},
                                           sensitivity=int(op.get("sensitivity", 1)), acl=op.get("acl"),
                                           source_pointers=op.get("source_pointers", []), verification="unverified")
            node = self.s.get(RemNode, nid)
        out.update({"node": str(nid), "key": node.key})
        added = []
        for s, v in ids.items():
            if res.status == "conflicting_identifiers" and s in res.colliding:
                continue  # already held by other records: never claimed twice
            try:
                added.append(self.add_identifier(nid, s, v, {"system": src.system, "record": src.record}))
            except ValueError as e:
                added.append({"scheme": s, "status": "not_added", "reason": str(e)})
        cur = self.w.current(nid)
        if normalise_name(name) and normalise_name(name) != normalise_name(cur.name):
            added.append(self.add_identifier(nid, "name", name, {"system": src.system}))
        out["identifiers"] = added
        decisions = [self.fields.observe(nid, k, v, src, effective_at=op.get("effective_at"), evidence=op.get("evidence"))
                     for k, v in (op.get("attrs") or {}).items()]
        out["fields"] = [{"field": d.field, "status": d.status} for d in decisions]
        proposals = []
        for c in res.candidates if res.status != "matched" else []:
            if c.node_id == nid:
                continue
            p = self.propose(nid, c.node_id, c.score, c.method, c.reasons)
            if p is not None:
                proposals.append({"proposal": str(p.id), "with": c.key, "score": c.score, "reasons": c.reasons})
        for s, holder in res.colliding.items():
            p = self.propose(nid, holder, 100.0, "shared_strong_identifier", [f"both carry {s} {normalise_identifier(s, ids[s])}"])
            if p is not None:
                proposals.append({"proposal": str(p.id), "with": str(holder), "score": 100.0, "reasons": p.reasons})
        out["proposals"], out["distinct_from"] = proposals, res.distinct
        self.results.append(out)
        return out

    def redirect_upsert(self, alias_id: uuid.UUID, canonical_id: uuid.UUID, op: dict[str, Any]) -> dict[str, Any]:
        """An upsert of a merged record's key: its values become statements about the canonical record."""
        attrs = dict(op.get("attrs") or {})
        system = str(attrs.get("source_system") or (op.get("source") or {}).get("system") or "direct")
        src = Source.from_dict({**(op.get("source") or {}), "system": system})
        decisions = [self.fields.observe(canonical_id, k, v, src, effective_at=op.get("effective_at") or attrs.get("source_date"),
                                         evidence=op.get("source_pointers")) for k, v in attrs.items() if k not in RESERVED_FIELDS]
        out = {"op": "upsert_node", "redirected_from": str(alias_id), "node": str(canonical_id),
               "fields": [{"field": d.field, "status": d.status} for d in decisions]}
        self.results.append(out)
        return out

    # ------------------------------------------------------------------------------------------ merge
    def confirm(self, proposal_id: uuid.UUID, canonical: Any = None, note: str = "") -> dict[str, Any]:
        p = self._proposal(proposal_id)
        a, b = self.s.get(RemNode, p.a_id), self.s.get(RemNode, p.b_id)
        if canonical in (None, ""):
            # the older record keeps its id; created by the same event: the one with more strong identifiers, then the key
            ids = identifiers_of(self.s, self.tenant_id, [a.id, b.id])

            def rank(n: RemNode) -> tuple:
                return (n.created_seq, -sum(1 for i in ids.get(n.id, []) if i.strength == "strong"), n.key)

            keep, alias = (a, b) if rank(a) <= rank(b) else (b, a)
        else:
            want = uuid.UUID(str(canonical)) if not isinstance(canonical, uuid.UUID) else canonical
            if want not in (a.id, b.id):
                raise ValueError("canonical must be one of the two records")
            keep, alias = (a, b) if want == a.id else (b, a)
        r = self.merge(alias.id, keep.id)
        p.status, p.decided_by, p.decided_seq = "confirmed", self.principal_id, self.w._need_seq()
        if note:
            p.reasons = list(p.reasons or []) + [f"confirmed: {note}"]
        r["proposal"] = str(p.id)
        return r

    def merge(self, alias_id: uuid.UUID, canonical_id: uuid.UUID) -> dict[str, Any]:
        seq = self.w._need_seq()
        an, cn = self.s.get(RemNode, alias_id), self.s.get(RemNode, canonical_id)
        av, cv = self.w.current(alias_id), self.w.current(canonical_id)
        if av is None or cv is None:
            raise ValueError("both records must exist")
        if an.type != cn.type or an.type not in MERGEABLE_TYPES:
            raise ValueError(f"only records of the same type among {MERGEABLE_TYPES} can be merged")
        if (av.scope_id, av.sensitivity) != (cv.scope_id, cv.sensitivity) or (av.acl or {}) != (cv.acl or {}):
            raise ValueError("the records have different access; give them the same scope, clearance and access list first")
        mine = identifiers_of(self.s, self.tenant_id, [alias_id, canonical_id])
        cids = {(i.scheme, i.value) for i in mine.get(canonical_id, [])}
        clash = [f"{i.scheme} {i.value} vs {j.value}" for i in mine.get(alias_id, []) for j in mine.get(canonical_id, [])
                 if i.scheme == j.scheme and i.scheme in SINGLE_VALUED and i.value != j.value]
        if clash:
            raise ValueError("different entities: " + "; ".join(clash))
        for i in mine.get(alias_id, []):  # identifiers move to the canonical record
            if (i.scheme, i.value) in cids:
                i.status = "retired"
            else:
                i.node_id = canonical_id
        self.s.flush()
        if normalise_name(av.name) != normalise_name(cv.name):
            self.add_identifier(canonical_id, "name", av.name, {"system": "merge"})
        # relationships move to the canonical record
        reader = GraphReader(self.s, self.tenant_id, None, seq=seq)
        edges, _, _ = reader.edges([alias_id], direction="both")
        moved = 0
        for e in edges:
            src = canonical_id if e.src == alias_id else e.src
            dst = canonical_id if e.dst == alias_id else e.dst
            if src == dst:
                continue
            self.w.upsert_edge(src, e.kind, dst, provenance=e.provenance, status=e.status, attrs=e.attrs, source_pointers=e.source_pointers,
                               derivation=e.derivation or ({"merged_from": str(alias_id)} if e.provenance != "explicit" else None),
                               valid_from=e.valid_from, valid_to=e.valid_to, source_key=f"merge:{alias_id}")
            moved += 1
        stock_left = 0
        for row in self.s.scalars(select(RemStock).where(RemStock.tenant_id == self.tenant_id, RemStock.sys_to.is_(None),
                                                         (RemStock.product_id == alias_id) | (RemStock.holder_id == alias_id))).all():
            prod = canonical_id if row.product_id == alias_id else row.product_id
            holder = canonical_id if row.holder_id == alias_id else row.holder_id
            clash_row = self.s.scalar(select(RemStock.id).where(RemStock.tenant_id == self.tenant_id, RemStock.product_id == prod,
                                                                RemStock.holder_id == holder, RemStock.sys_to.is_(None)))
            if clash_row is not None:
                stock_left += 1  # both records hold stock for the same pair: a person decides
                continue
            self.w.set_stock(prod, holder, on_hand=float(row.qty_on_hand), reserved=float(row.qty_reserved or 0), scope_id=row.scope_id,
                             sensitivity=row.sensitivity, source_pointers=list(row.source_pointers or []))
            row.sys_to = seq
        if set(av.project_ids or []) - set(cv.project_ids or []) or set(av.department_ids or []) - set(cv.department_ids or []):
            self.w.revise(canonical_id, project_ids=list(dict.fromkeys(list(cv.project_ids or []) + list(av.project_ids or []))),
                          department_ids=list(dict.fromkeys(list(cv.department_ids or []) + list(av.department_ids or []))))
        # the alias's statements are replayed through the canonical record's authority rules
        replayed = []
        for name in (av.attrs or {}):
            if name not in RESERVED_FIELDS and self.fields.current(alias_id, name) is None:
                self.fields._baseline(an, name)
        for st in self.s.scalars(select(StateField).where(StateField.tenant_id == self.tenant_id, StateField.node_id == alias_id,
                                                          StateField.status.in_(("current", "conflict")))
                                 .order_by(StateField.recorded_seq)).all():
            d = self.fields.observe(canonical_id, st.field, st.value, Source(system=st.source_system, kind=st.source_kind,
                                                                                  record=st.source_record, method=st.method),
                                    effective_at=st.effective_at, evidence=list(st.evidence or []))
            replayed.append({"field": d.field, "status": d.status})
        for c in self.s.scalars(select(StateConflict).where(StateConflict.tenant_id == self.tenant_id, StateConflict.node_id == alias_id,
                                                            StateConflict.status == "open")):
            c.status, c.resolution, c.resolved_seq, c.note = "resolved", "merged", seq, f"record merged into {canonical_id}"
        self.s.execute(update(StateAlias).where(StateAlias.tenant_id == self.tenant_id, StateAlias.canonical_id == alias_id)
                       .values(canonical_id=canonical_id))
        self.s.add(StateAlias(alias_id=alias_id, tenant_id=self.tenant_id, alias_type=an.type, alias_key=an.key, canonical_id=canonical_id,
                              merged_seq=seq, merged_by=self.principal_id))
        for p in self.s.scalars(select(StateMatchProposal).where(
                StateMatchProposal.tenant_id == self.tenant_id, StateMatchProposal.status == "proposed",
                (StateMatchProposal.a_id == alias_id) | (StateMatchProposal.b_id == alias_id))):
            p.status, p.decided_seq = "superseded", seq
            p.reasons = list(p.reasons or []) + [f"{an.key} was merged into {cn.key}"]
        self.w.delete_node(alias_id)
        self._aliases = True
        r = {"op": "merge", "alias": str(alias_id), "alias_key": an.key, "canonical": str(canonical_id), "canonical_key": cn.key,
             "relationships_moved": moved, "statements_replayed": replayed, "stock_rows_left": stock_left}
        self.results.append(r)
        return r
