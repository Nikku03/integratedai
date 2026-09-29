"""Field-level source authority: which statement of a field is current, and why.

Every observed value is kept as a ``StateField`` row with its source, method, evidence, event time and recorded
time. Whether it becomes the current value is decided by rules, never by arrival order alone:

1. no current value: it becomes current;
2. the same value as the current one: it corroborates it (and becomes the backing statement if its source is
   more authoritative);
3. a more authoritative source (lower rank): it replaces the current value, unless it describes an earlier
   moment than the current value, which opens a conflict (the authoritative system may not know yet);
4. a less authoritative source with a different value: a conflict is opened and the current value stays;
5. an equally authoritative source: the later event time wins, an earlier one is kept as history (a late report).
   Without times, a status that follows the current one in the lifecycle wins and one that precedes it is history;
   the same source updating its own statement wins; otherwise a conflict is opened.

Ranks come from ``state_authority`` rules (most specific match of entity type, field and source system) and fall
back to the kind of source. A status change must also be an allowed transition (``cie.state.lifecycle``).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.state import domain
from cie.state.lifecycle import check_transition, states
from cie.state.models import SOURCE_KINDS, RemNode, StateAuthority, StateConflict, StateField
from cie.state.store import GraphWriter

DEFAULT_KIND_RANK = {"system_of_record": 10, "human": 30, "document": 50, "email": 70, "chat": 80, "agent": 90, "unknown": 100}
FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
RESERVED_FIELDS = ("last_verified_at", "verification_method", "verified_by")


@dataclass
class Source:
    system: str
    kind: str = "unknown"
    record: str = ""
    method: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Source:
        d = dict(d or {})
        system = str(d.get("system") or "").strip()
        if not system:
            raise ValueError("an observation needs source.system (where the value came from)")
        kind = str(d.get("kind") or ("system_of_record" if system in domain.SYSTEM_OF_RECORD else "unknown"))
        if kind not in SOURCE_KINDS:
            raise ValueError(f"source.kind must be one of {SOURCE_KINDS}")
        return cls(system=system[:64], kind=kind, record=str(d.get("record") or "")[:300], method=str(d.get("method") or "")[:40])


def as_datetime(v: Any) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=UTC)
    s = str(v)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        d = domain.as_date(s)
        if d is None:
            raise ValueError(f"not a date or time: {s!r}") from None
        return datetime(d.year, d.month, d.day, tzinfo=UTC)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _same(a: Any, b: Any) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


class Authority:
    """Rank lookup for one tenant, loaded once per event."""

    def __init__(self, session: Session, tenant_id: uuid.UUID):
        self.rules = {(r.entity_type, r.field, r.source_system): r.rank
                      for r in session.scalars(select(StateAuthority).where(StateAuthority.tenant_id == tenant_id))}

    def rank(self, entity_type: str, field_name: str, src: Source) -> tuple[int, str]:
        for t, f in ((entity_type, field_name), (entity_type, "*"), ("*", field_name), ("*", "*")):
            r = self.rules.get((t, f, src.system))
            if r is not None:
                return r, f"authority rule {t}.{f} for {src.system}"
        return DEFAULT_KIND_RANK[src.kind], f"default rank for a {src.kind.replace('_', ' ')} source"


@dataclass
class Decision:
    node_id: uuid.UUID
    field: str
    status: str
    reason: str
    field_id: uuid.UUID | None = None
    conflict_id: uuid.UUID | None = None


@dataclass
class FieldStore:
    """Applies observations within one event (one sequence number)."""

    session: Session
    writer: GraphWriter
    authority: Authority
    principal_id: uuid.UUID | None = None
    decisions: list[Decision] = field(default_factory=list)
    written: set[tuple[uuid.UUID, str]] = field(default_factory=set)  # attributes this store set itself

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.writer.tenant_id

    @property
    def seq(self) -> int:
        return self.writer._need_seq()

    def current(self, node_id: uuid.UUID, field_name: str) -> StateField | None:
        return self.session.scalar(select(StateField).where(StateField.tenant_id == self.tenant_id, StateField.node_id == node_id,
                                                            StateField.field == field_name, StateField.status == "current"))

    def _baseline(self, node: RemNode, field_name: str) -> StateField | None:
        """The attribute as it stands, when it was written directly (import, ingestion) and has no statement yet."""
        cur = self.writer.current(node.id)
        if cur is None or field_name not in (cur.attrs or {}):
            return None
        system = str((cur.attrs or {}).get("source_system") or "direct")
        src = Source(system=system, kind="system_of_record" if system in domain.SYSTEM_OF_RECORD else "unknown", method="direct_write")
        rank, why = self.authority.rank(node.type, field_name, src)
        eff = None
        try:
            eff = as_datetime((cur.attrs or {}).get("source_date"))
        except ValueError:
            pass
        row = StateField(tenant_id=self.tenant_id, node_id=node.id, field=field_name, value=cur.attrs[field_name], source_system=system,
                         source_record=node.key, source_kind=src.kind, method="direct_write",
                         evidence=list(cur.source_pointers or [])[:5], rank=rank, effective_at=eff, recorded_seq=cur.sys_from,
                         status="current", decision=f"value recorded directly on the record at seq {cur.sys_from}; {why}",
                         verification=cur.verification if cur.verification == "verified" else "unverified", event_id=cur.event_id)
        self.session.add(row)
        self.session.flush()
        return row

    def _apply(self, node_id: uuid.UUID, field_name: str, value: Any) -> None:
        self.writer.revise(node_id, attrs={field_name: value})
        self.written.add((node_id, field_name))

    def _conflict(self, node_id: uuid.UUID, field_name: str, cur: StateField | None, new: StateField, reason: str) -> StateConflict:
        c = StateConflict(tenant_id=self.tenant_id, node_id=node_id, field=field_name, current_field_id=cur.id if cur else None,
                          challenger_field_id=new.id, reason=reason, status="open", opened_seq=self.seq)
        self.session.add(c)
        self.session.flush()
        return c

    def _close_disputes(self, node_id: uuid.UUID, field_name: str, why: str) -> None:
        for c in self.session.scalars(select(StateConflict).where(StateConflict.tenant_id == self.tenant_id, StateConflict.node_id == node_id,
                                                                  StateConflict.field == field_name, StateConflict.status == "open")):
            c.status, c.resolution, c.resolved_seq, c.note = "resolved", "superseded", self.seq, why
            ch = self.session.get(StateField, c.challenger_field_id)
            if ch is not None and ch.status == "conflict":
                ch.status, ch.superseded_seq = "superseded", self.seq

    def observe(self, node_id: uuid.UUID, field_name: str, value: Any, src: Source, *, effective_at: Any = None,
                evidence: list[Any] | None = None) -> Decision:
        if not FIELD_NAME.match(field_name) or field_name in RESERVED_FIELDS:
            raise ValueError(f"cannot observe field {field_name!r}")
        node = self.session.get(RemNode, node_id)
        if node is None or node.tenant_id != self.tenant_id or node.deleted_seq is not None:
            raise ValueError(f"unknown record {node_id}")
        rank, why_rank = self.authority.rank(node.type, field_name, src)
        eff = as_datetime(effective_at)
        cur = self.current(node_id, field_name) or self._baseline(node, field_name)
        new = StateField(tenant_id=self.tenant_id, node_id=node_id, field=field_name, value=value, source_system=src.system,
                         source_record=src.record, source_kind=src.kind, method=src.method, evidence=list(evidence or []), rank=rank,
                         effective_at=eff, recorded_seq=self.seq, status="pending", event_id=self.writer.event_id)
        self.session.add(new)
        self.session.flush()

        def become_current(reason: str, old_status: str | None = "superseded") -> Decision:
            if field_name == "status":
                blocked = check_transition(node.type, str(cur.value) if cur is not None and cur.value is not None else None, str(value))
                if blocked:
                    return conflict(f"status change not applied: {blocked}")
            if cur is not None and old_status:
                cur.status, cur.superseded_seq = old_status, self.seq
            new.status, new.decision = "current", reason
            self._close_disputes(node_id, field_name, f"a new current value was established at seq {self.seq}")
            if cur is None or not _same(cur.value, value):
                self._apply(node_id, field_name, value)
            return self._record(Decision(node_id, field_name, "current", reason, new.id))

        def conflict(reason: str) -> Decision:
            new.status, new.decision = "conflict", reason
            c = self._conflict(node_id, field_name, cur, new, reason)
            return self._record(Decision(node_id, field_name, "conflict", reason, new.id, c.id))

        def keep(status: str, reason: str) -> Decision:
            new.status, new.decision = status, reason
            return self._record(Decision(node_id, field_name, status, reason, new.id))

        src_desc = f"{src.system} ({src.kind.replace('_', ' ')}, rank {rank}: {why_rank})"
        if cur is None:
            return become_current(f"first statement of {field_name}, from {src_desc}")
        cur_desc = f"{cur.source_system} (rank {cur.rank})"
        if _same(cur.value, value):
            if rank < cur.rank:
                cur.status, cur.superseded_seq = "corroboration", self.seq
                new.status, new.decision = "current", f"same value, now backed by the more authoritative {src_desc}"
                return self._record(Decision(node_id, field_name, "current", new.decision, new.id))
            return keep("corroboration", f"{src_desc} states the same value as {cur_desc}")
        earlier = eff is not None and cur.effective_at is not None and eff < cur.effective_at
        later = eff is not None and cur.effective_at is not None and eff > cur.effective_at
        if rank < cur.rank:
            if earlier:
                return conflict(f"{src_desc} is more authoritative than {cur_desc}, but describes an earlier moment "
                                f"({eff.date()} vs {cur.effective_at.date()}); it may not reflect the later report")
            return become_current(f"{src_desc} is more authoritative for {node.type}.{field_name} than {cur_desc}")
        if rank > cur.rank:
            return conflict(f"{src_desc} disagrees with the current value from the more authoritative {cur_desc}; "
                            f"the current value stays until this is resolved")
        if later:
            return become_current(f"later statement ({eff.date()}) from an equally authoritative source than {cur_desc} ({cur.effective_at.date()})")
        if earlier:
            return keep("history", f"late report: describes {eff.date()}, before the current value from {cur_desc} ({cur.effective_at.date()})")
        if field_name == "status" and states(node.type) is not None and cur.value is not None and not _same(cur.value, value):
            # the lifecycle orders statuses when time cannot: a next status is later, a previous one is a late report
            if check_transition(node.type, str(cur.value), str(value)) is None and check_transition(node.type, None, str(value)) is None:
                return become_current(f"{value!r} follows {cur.value!r} in the {node.type} lifecycle ({src_desc}, as authoritative as {cur_desc})")
            if (check_transition(node.type, None, str(value)) is None and check_transition(node.type, None, str(cur.value)) is None
                    and check_transition(node.type, str(value), str(cur.value)) is None):
                return keep("history", f"late report: {value!r} comes before the current {cur.value!r} in the {node.type} lifecycle")
        if src.system == cur.source_system and (not src.record or src.record == cur.source_record):
            return become_current(f"update from the same source ({src.system}{':' + src.record if src.record else ''})")
        return conflict(f"{src_desc} and {cur_desc} are equally authoritative and their times do not order them")

    def _record(self, d: Decision) -> Decision:
        self.decisions.append(d)
        return d

    # ------------------------------------------------------------------------------------------ resolution
    def resolve(self, conflict_id: uuid.UUID, accept: str, note: str = "") -> Decision:
        c = self.session.get(StateConflict, conflict_id, with_for_update=True)
        if c is None or c.tenant_id != self.tenant_id:
            raise ValueError(f"unknown conflict {conflict_id}")
        if c.status != "open":
            raise ValueError("the conflict is already resolved")
        if accept not in ("current", "challenger"):
            raise ValueError("accept must be 'current' or 'challenger'")
        ch = self.session.get(StateField, c.challenger_field_id)
        cur = self.current(c.node_id, c.field)
        c.status, c.resolved_by, c.resolved_seq, c.note = "resolved", self.principal_id, self.seq, note[:2000]
        if accept == "current":
            c.resolution = "kept_current"
            ch.status, ch.superseded_seq = "rejected", self.seq
            ch.decision = f"{ch.decision}; rejected when conflict {c.id} was resolved"
            return self._record(Decision(c.node_id, c.field, "rejected", "resolved in favour of the current value", ch.id, c.id))
        c.resolution = "accepted_challenger"
        if cur is not None:
            cur.status, cur.superseded_seq = "superseded", self.seq
        ch.status, ch.decision = "current", f"{ch.decision}; accepted when conflict {c.id} was resolved"
        if cur is None or not _same(cur.value, ch.value):
            self._apply(c.node_id, c.field, ch.value)
        return self._record(Decision(c.node_id, c.field, "current", "resolved in favour of the challenging value", ch.id, c.id))

    # ------------------------------------------------------------------------------------------ verification
    def verify(self, node_id: uuid.UUID, fields: list[str] | None, method: str, at: Any = None) -> Decision:
        when = as_datetime(at) or datetime.now(UTC)
        node = self.session.get(RemNode, node_id)
        cur = self.writer.current(node_id)
        if node is None or cur is None:
            raise ValueError(f"unknown record {node_id}")
        names = fields or [k for k in (cur.attrs or {}) if k not in RESERVED_FIELDS]
        for name in names:
            row = self.current(node_id, name) or self._baseline(node, name)
            if row is not None:
                row.verification, row.verified_at = "verified", when
        self.writer.revise(node_id, attrs={"last_verified_at": when.isoformat(), "verification_method": method[:200],
                                           "verified_by": str(self.principal_id) if self.principal_id else "system"},
                           **({"verification": "verified"} if fields is None else {}))
        return self._record(Decision(node_id, "*" if fields is None else ",".join(names), "verified", method))

    # ------------------------------------------------------------------------------------------ direct writes
    def reconcile_direct(self, changed: dict[uuid.UUID, list[str]]) -> int:
        """A direct attribute write (import, revise) replaces the statement it overwrote; mark it so the entity view
        never shows a source for a value that source did not give."""
        pairs = {(nid, f.split(".", 1)[1]) for nid, fs in changed.items() for f in fs
                 if f.startswith("attrs.") and (nid, f.split(".", 1)[1]) not in self.written}
        if not pairs:
            return 0
        rows = self.session.scalars(select(StateField).where(StateField.tenant_id == self.tenant_id, StateField.status == "current",
                                                             StateField.node_id.in_({n for n, _ in pairs})))
        n = 0
        for r in rows:
            if (r.node_id, r.field) not in pairs:
                continue
            cur = self.writer.current(r.node_id)
            if cur is None or not _same((cur.attrs or {}).get(r.field), r.value):
                r.status, r.superseded_seq = "overwritten", self.seq
                r.decision = f"{r.decision}; replaced by a direct write at seq {self.seq}"
                n += 1
        return n
