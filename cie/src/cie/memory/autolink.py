"""Automatic sparse graph construction for records derived from one document.

Edges added (all local, no all-to-all):
* every derived record ``part_of`` the document record,
* records in the same section ``relates_to`` each other (capped),
* deadlines/metrics/requirements ``derived_from`` the clause record of their section,
* entity mentions via ``cie.memory.entities``,
* a contradiction edge when two metric records of the same name in the same
  document disagree on the value.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from cie.core.models import LinkKind, MemoryRecord, RecordType
from cie.memory.records import contradict, link

MAX_SIBLINGS = 4


def autolink(session: Session, document_record: MemoryRecord, records: list[MemoryRecord],
             entities: dict[str, MemoryRecord] | None = None) -> dict[str, int]:
    """``entities``: name -> canonical entity record (created or inherited)."""
    stats = defaultdict(int)
    entities = entities or {}
    by_section: dict[str | None, list[MemoryRecord]] = defaultdict(list)
    for r in records:
        if r.id == document_record.id:
            continue
        link(session, r, document_record, LinkKind.part_of)
        stats["part_of"] += 1
        sec = (r.source_locations or [{}])[0].get("section_id")
        by_section[sec].append(r)
    for recs in by_section.values():
        clause = next((r for r in recs if r.type == RecordType.contract_clause), None)
        for r in recs:
            if clause is not None and r.id != clause.id and r.type in (RecordType.deadline, RecordType.metric, RecordType.requirement, RecordType.risk):
                link(session, r, clause, LinkKind.derived_from)
                stats["derived_from"] += 1
        # sibling relations, capped so a long section does not become a clique
        core = [r for r in recs if r.type not in (RecordType.organization, RecordType.person)][:MAX_SIBLINGS + 1]
        for i, a in enumerate(core):
            for b in core[i + 1:i + 1 + MAX_SIBLINGS]:
                link(session, a, b, LinkKind.relates_to, weight=0.5)
                stats["relates_to"] += 1
    # entity mentions: link every non-entity record whose text names a known entity
    for r in records:
        if r.type in (RecordType.organization, RecordType.person, RecordType.document):
            continue
        text = f"{r.summary} {r.detail}"
        for name, ent in entities.items():
            first = name.split()[0]
            if (name in text or (len(first) > 4 and first in text)) and ent.id != r.id:
                link(session, r, ent, LinkKind.mentions)
                if str(ent.id) not in (r.entity_ids or []):
                    r.entity_ids = list(r.entity_ids or []) + [str(ent.id)]
                stats["mentions"] += 1
    # inherited entities also belong to this document's graph neighbourhood
    for ent in entities.values():
        if ent not in records:
            link(session, document_record, ent, LinkKind.mentions)
    # same-document metric disagreement
    metrics: dict[str, list[MemoryRecord]] = defaultdict(list)
    for r in records:
        if r.type == RecordType.metric and (r.content or {}).get("name") and "value" in (r.content or {}):
            metrics[r.content["name"]].append(r)
    for name, ms in metrics.items():
        if name in ("amount", "percentage"):
            continue
        vals = {float(m.content["value"]) for m in ms}
        if len(vals) > 1 and len(ms) == 2:
            contradict(session, ms[0], ms[1], f"metric '{name}' has conflicting values {sorted(vals)} in the same document",
                       producing_agent="autolink_v1")
            stats["contradictions"] += 1
    return dict(stats)
