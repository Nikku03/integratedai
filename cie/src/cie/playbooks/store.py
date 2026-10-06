"""Playbooks in the company: drafts, a person's approval, decisions from live facts, and deciding again when a fact
changes.

* ``save`` stores a new version as a draft, with every problem the checker finds and, for each rule, whether its
  quote appears in the source documents. A draft without problems gets an approval request (kind ``playbook``).
* ``approve`` (a person) makes it the version that decides and retires the one before. Current decisions of the
  playbook are made again with it.
* ``decide`` reads the facts: those the request supplies, and those the playbook binds to the live state
  (``"from": {"entity": "supplier", "key": "{supplier}", "field": "certified"}``). A bound fact is always read from
  the live state, under the requester's permissions; a value the request supplies for it is ignored. A field with an
  open conflict between sources is unknown.
* ``route_change`` (called for every applied state event) makes again the current decisions that read a changed,
  deleted or restricted record. A new decision supersedes the old one for the same playbook, goal and subject.
"""

from __future__ import annotations

import re
import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cie.core.models import Approval, Principal
from cie.core.util import utcnow
from cie.governance.audit import audit
from cie.playbooks import logic
from cie.playbooks.models import Playbook, PlaybookDecision

REDECIDE_LIMIT = 1000


def _norm(text: str) -> str:
    text = text.replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"[\s|*`_#>]+", " ", text).strip().casefold()


def check_quotes(spec: dict[str, Any], texts: list[str]) -> dict[str, bool]:
    """For each rule (``name`` or ``name#k`` for a rule's k-th part), whether its quote is in the sources: the same
    words in the same order, ignoring case, spacing and table bars."""
    hay = [_norm(t) for t in texts if t]
    out: dict[str, bool] = {}
    count: dict[str, int] = {}
    for r in spec.get("rules") or []:
        if not isinstance(r, dict):
            continue
        n = str(r.get("name") or "")
        k = count.get(n, 0)
        count[n] = k + 1
        q = _norm(str(r.get("quote") or ""))
        out[n if k == 0 else f"{n}#{k}"] = bool(q) and any(q in h for h in hay)
    return out


@lru_cache(maxsize=256)
def _compile_cached(spec_json: str) -> logic.Playbook:
    import json

    return logic.compile_playbook(json.loads(spec_json))


def compiled(row: Playbook) -> logic.Playbook:
    import json

    return _compile_cached(json.dumps(row.spec, sort_keys=True, default=str))


def save(session: Session, tenant_id: uuid.UUID, key: str, spec: dict[str, Any], *, drafted_by: str,
         source_document_ids: list[uuid.UUID] | None = None, source_texts: list[str] | None = None, note: str = "",
         principal_id: uuid.UUID | None = None) -> Playbook:
    """Store ``spec`` as the next draft version of ``key``."""
    key = key.strip()[:120]
    if not key:
        raise ValueError("a playbook needs a key")
    version = (session.scalar(select(func.max(Playbook.version)).where(Playbook.tenant_id == tenant_id, Playbook.key == key)) or 0) + 1
    probs = logic.problems(spec)
    row = Playbook(id=uuid.uuid4(), tenant_id=tenant_id, key=key, version=version, name=str(spec.get("name") or key)[:300], status="draft",
                   spec=spec, spec_hash=logic.spec_hash(spec), problems=probs,
                   quotes=check_quotes(spec, source_texts) if source_texts else {},
                   source_document_ids=list(source_document_ids or []), drafted_by=drafted_by[:120], note=note)
    session.add(row)
    session.flush()
    if not probs:
        missing_quotes = [k for k, ok in row.quotes.items() if not ok]
        ap = Approval(tenant_id=tenant_id, kind="playbook", subject_id=str(row.id), requested_by=drafted_by[:100],
                      summary=f"Playbook {key} v{version} ({row.name}): {len(spec.get('rules') or [])} rules deciding "
                              f"{spec.get('decision')}." + (f" Quotes not found in the sources: {', '.join(missing_quotes)}." if missing_quotes else ""))
        session.add(ap)
        session.flush()
        row.approval_id = ap.id
    audit(session, tenant_id=tenant_id, principal_id=principal_id, action="playbook.draft", resource_kind="playbook", resource_id=row.id,
          details={"key": key, "version": version, "problems": len(probs), "by": drafted_by})
    session.flush()
    return row


def approve(session: Session, playbook_id: uuid.UUID, *, approve: bool, by: str, principal_id: uuid.UUID | None = None,
            reason: str = "") -> Playbook:
    """A person's decision on a draft. Approving retires the version that decided before and makes the current
    decisions of the playbook again."""
    row = session.get(Playbook, playbook_id, with_for_update=True)
    if row is None or row.status != "draft":
        raise ValueError("no draft playbook with that id")
    if approve and row.problems:
        raise ValueError("a draft with problems cannot be approved: " + "; ".join(row.problems[:3]))
    if approve:
        for old in session.scalars(select(Playbook).where(Playbook.tenant_id == row.tenant_id, Playbook.key == row.key,
                                                          Playbook.status == "approved")):
            old.status = "retired"
        row.status, row.approved_by, row.approved_at = "approved", principal_id, utcnow()
    else:
        row.status = "rejected"
    row.note = (row.note + f"\n{'approved' if approve else 'rejected'} by {by}: {reason}").strip()
    if row.approval_id:
        ap = session.get(Approval, row.approval_id)
        if ap is not None and ap.status == "pending":
            ap.status, ap.decided_by, ap.decided_at, ap.reason = ("approved" if approve else "rejected"), principal_id, utcnow(), reason
    audit(session, tenant_id=row.tenant_id, principal_id=principal_id, action=f"playbook.{row.status}", resource_kind="playbook",
          resource_id=row.id, details={"key": row.key, "version": row.version, "by": by})
    session.flush()
    if approve:
        for d in list(session.scalars(select(PlaybookDecision).where(
                PlaybookDecision.tenant_id == row.tenant_id, PlaybookDecision.playbook_key == row.key,
                PlaybookDecision.status == "current", PlaybookDecision.subject != "").limit(REDECIDE_LIMIT))):
            redecide(session, d, reason=f"playbook {row.key} v{row.version} approved by {by}")
    return row


def approved(session: Session, tenant_id: uuid.UUID, key: str) -> Playbook | None:
    return session.scalar(select(Playbook).where(Playbook.tenant_id == tenant_id, Playbook.key == key, Playbook.status == "approved")
                          .order_by(Playbook.version.desc()).limit(1))


# ---------------------------------------------------------------------------------------------- live facts
class StateFacts(logic.FactSource):
    """Facts from the request, and facts bound to the live state (read under ``visibility``; None: the system)."""

    def __init__(self, session: Session, tenant_id: uuid.UUID, visibility, given: dict[str, Any] | None = None):
        from cie.state.store import GraphReader

        self.s, self.tenant_id = session, tenant_id
        self.given = logic.Given(given)
        self.reader = GraphReader(session, tenant_id, visibility)
        self.records: dict[str, dict[str, Any]] = {}  # ref -> {ref, version, label}
        self.keys: set[str] = set()
        self.ignored: list[str] = []

    def get(self, name: str, spec: dict[str, Any], lookup) -> logic.Fact:
        src = spec.get("from")
        if not src:
            return self.given.get(name, spec, lookup)
        if name in self.given.values:
            self.ignored.append(name)
        parts = []
        for piece in re.split(r"(\{[^}]*\})", str(src["key"])):
            if piece.startswith("{") and piece.endswith("}"):
                v = lookup(piece[1:-1])
                if v is None:
                    return logic.Fact(None, {"kind": "state", "entity": src["entity"], "field": src["field"],
                                             "detail": f"the record's key needs {piece[1:-1]}, which is unknown"})
                parts.append(str(v))
            else:
                parts.append(piece)
        type_, key, fld = str(src["entity"]), "".join(parts), str(src["field"])
        label = f"{type_}:{key}"
        self.keys.add(label[:340])
        n = self.reader.node_by_key(type_, key)
        if n is None:
            from cie.state.events import _canonical_view

            n = _canonical_view(self.reader, type_, key)
        if n is None:
            return logic.Fact(None, {"kind": "state", "record": label, "field": fld, "detail": "no such record visible"})
        self.records[str(n.id)] = {"ref": str(n.id), "version": n.version, "label": label}
        self.keys.add(f"{n.type}:{n.key}"[:340])
        raw = n.name if fld == "name" else (n.attrs or {}).get(fld)
        from cie.state.models import StateConflict, StateField

        source = {"kind": "state", "record": label, "ref": str(n.id), "version": n.version, "field": fld}
        st = self.s.scalar(select(StateField).where(StateField.tenant_id == self.tenant_id, StateField.node_id == n.id,
                                                    StateField.field == fld, StateField.status == "current").limit(1))
        if st is not None:
            source["statement"] = {"system": st.source_system, "record": st.source_record, "kind": st.source_kind}
        conflict = self.s.scalar(select(StateConflict.id).where(StateConflict.tenant_id == self.tenant_id, StateConflict.node_id == n.id,
                                                                StateConflict.field == fld, StateConflict.status == "open").limit(1))
        if conflict is not None:
            return logic.Fact(None, {**source, "conflict": str(conflict)}, "sources disagree on it (an open conflict)")
        v, note = logic.normalize(spec["type"], raw)
        return logic.Fact(v, source, note)


def _visibility(session: Session, principal_id: uuid.UUID | None):
    if principal_id is None:
        return None
    from cie.governance.permissions import visible_scopes

    p = session.get(Principal, principal_id)
    return visible_scopes(session, p) if p is not None else None


def decide(session: Session, tenant_id: uuid.UUID, key: str, *, given: dict[str, Any] | None = None, goal: str | None = None,
           subject: str = "", principal_id: uuid.UUID | None = None, requested_by: str = "", reason: str = "requested") -> PlaybookDecision:
    """Decide with the approved version of ``key``. Raises ``LookupError`` when none is approved."""
    row = approved(session, tenant_id, key)
    if row is None:
        raise LookupError(f"no approved playbook '{key}'")
    dec = _decide(session, row, given=given or {}, goal=goal, subject=subject, principal_id=principal_id,
                  requested_by=requested_by, reason=reason)
    assert dec is not None
    return dec


def _decide(session: Session, row: Playbook, *, given: dict[str, Any], goal: str | None, subject: str, principal_id, requested_by: str,
            reason: str, previous: PlaybookDecision | None = None) -> PlaybookDecision | None:
    """Evaluate and store a decision. With ``previous`` (deciding again), nothing is stored when the playbook
    version, the answer and every fact read are as before: None is returned."""
    pb = compiled(row)
    src = StateFacts(session, row.tenant_id, _visibility(session, principal_id), given)
    d = logic.evaluate(pb, src, goal)
    if previous is not None and previous.playbook_id == row.id and previous.answer == d.answer and previous.inputs == d.inputs:
        return None
    notes = d.notes + [f"{n}: the value given was ignored; it is read from the company's records" for n in sorted(set(src.ignored))]
    dec = PlaybookDecision(id=uuid.uuid4(), tenant_id=row.tenant_id, playbook_id=row.id, playbook_key=row.key, goal=d.goal,
                           subject=subject[:300], answer=d.answer, given=dict(given), inputs=d.inputs, sources=d.sources, proof=d.proof,
                           why=d.why, missing=d.missing, notes=notes, based_on={"records": list(src.records.values())},
                           record_keys=sorted(src.keys), status="current", reason=reason[:2000], principal_id=principal_id,
                           requested_by=requested_by[:120], seq=src.reader.seq)
    if subject:
        olds = [previous] if previous is not None else list(session.scalars(select(PlaybookDecision).where(
            PlaybookDecision.tenant_id == row.tenant_id, PlaybookDecision.playbook_key == row.key, PlaybookDecision.goal == d.goal,
            PlaybookDecision.subject == subject, PlaybookDecision.status == "current")))
        for old in olds:
            old.status, old.superseded_by = "superseded", dec.id
    elif previous is not None:
        previous.status, previous.superseded_by = "superseded", dec.id
    session.add(dec)
    audit(session, tenant_id=row.tenant_id, principal_id=principal_id, action="playbook.decide", resource_kind="playbook_decision",
          resource_id=dec.id, details={"key": row.key, "version": row.version, "goal": d.goal, "subject": subject, "answer": d.answer,
                                       "from": previous.answer if previous is not None else None, "reason": reason[:200]})
    session.flush()
    return dec


def redecide(session: Session, old: PlaybookDecision, *, reason: str) -> PlaybookDecision | None:
    """Make a current decision again with the approved playbook and today's facts. Returns the new decision, or None
    when nothing it read changed (or no version is approved any more)."""
    row = approved(session, old.tenant_id, old.playbook_key)
    if row is None or old.status != "current":
        return None
    return _decide(session, row, given=old.given or {}, goal=old.goal, subject=old.subject, principal_id=old.principal_id,
                   requested_by=old.requested_by, reason=reason, previous=old)


def route_change(session: Session, cs) -> dict[str, Any]:
    """Make again the current decisions that read a record this change touched."""
    from cie.state.models import RemNode

    ids = set(cs.changed) | set(cs.deleted) | set(cs.restricted)
    if not ids:
        return {}
    keys = [f"{t}:{k}"[:340] for t, k in session.execute(select(RemNode.type, RemNode.key).where(RemNode.id.in_(ids))).all()]
    if not keys:
        return {}
    rows = list(session.scalars(select(PlaybookDecision).where(PlaybookDecision.tenant_id == cs.event.tenant_id,
                                                               PlaybookDecision.status == "current",
                                                               PlaybookDecision.record_keys.overlap(keys)).limit(REDECIDE_LIMIT)))
    changed, same = [], 0
    for d in rows:
        new = redecide(session, d, reason=f"a record it read changed (event {cs.event.id}, seq {cs.seq})")
        if new is None:
            same += 1
        else:
            changed.append({"decision": str(new.id), "replaces": str(d.id), "subject": d.subject, "from": d.answer, "to": new.answer})
    return {"redecided": changed, "unchanged": same} if rows else {}


def verify_decision(session: Session, dec: PlaybookDecision) -> list[str]:
    """Check a stored decision's proof against the playbook version it was made with and its recorded facts."""
    row = session.get(Playbook, dec.playbook_id)
    if row is None:
        return ["its playbook is gone"]
    errs = logic.verify(compiled(row), dec.proof or {}, dec.inputs or {})
    if not errs and (dec.proof or {}).get("result") != {"yes": True, "no": False, "unknown": None}.get(dec.answer, "?"):
        errs.append("the recorded answer is not the proof's result")
    return errs


def decision_view(dec: PlaybookDecision, row: Playbook | None = None) -> dict[str, Any]:
    return {"id": str(dec.id), "playbook": dec.playbook_key, "version": row.version if row else None, "goal": dec.goal,
            "subject": dec.subject, "answer": dec.answer, "why": dec.why, "missing": dec.missing, "notes": dec.notes,
            "inputs": dec.inputs, "sources": dec.sources, "status": dec.status,
            "superseded_by": str(dec.superseded_by) if dec.superseded_by else None, "reason": dec.reason,
            "created_at": dec.created_at.isoformat() if dec.created_at else None}


def playbook_view(row: Playbook, *, full: bool = False) -> dict[str, Any]:
    out = {"id": str(row.id), "key": row.key, "version": row.version, "name": row.name, "status": row.status,
           "decision": (row.spec or {}).get("decision"), "question": (row.spec or {}).get("question", ""), "problems": row.problems,
           "quotes_found": row.quotes, "drafted_by": row.drafted_by, "approval_id": str(row.approval_id) if row.approval_id else None,
           "approved_at": row.approved_at.isoformat() if row.approved_at else None,
           "source_document_ids": [str(x) for x in row.source_document_ids or []]}
    if full:
        out["spec"] = row.spec
    return out
