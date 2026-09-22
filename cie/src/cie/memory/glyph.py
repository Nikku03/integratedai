"""Glyph: a compact, typed, machine-readable memory card.

Built deterministically from a record and its graph edges. It is a retrieval
and navigation structure that always points back to evidence; it is never a
replacement for the record or the raw source. Stored as JSONB in
``memory_records.glyph``; ``cie.eval.bench_glyph`` measures alternative
encodings of the same content.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvidencePointer(BaseModel):
    document_id: str | None = None
    page_no: int | None = None
    bbox: list[float] | None = None
    block_id: str | None = None
    section_id: str | None = None
    quote: str | None = None


class Glyph(BaseModel):
    v: int = 1  # glyph schema version
    id: str
    type: str
    what: str  # what happened / the claim
    who: list[str] = Field(default_factory=list)  # entities it concerns
    why: str | None = None  # why it matters
    project: str | None = None
    department: str | None = None
    time: dict[str, Any] = Field(default_factory=dict)  # {event, valid_from, valid_to, recorded}
    status: str = "current"  # current|superseded|disputed|rejected
    dependencies: list[str] = Field(default_factory=list)  # record ids
    consequences: list[str] = Field(default_factory=list)  # record ids (causes ->)
    contradictions: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    verification: str = "unverified"
    evidence: list[EvidencePointer] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    def to_compact(self) -> dict[str, Any]:
        """Drop empty fields; this is what is stored."""
        d = self.model_dump()
        return {k: v for k, v in d.items() if v not in (None, [], {}, "")}


_WHY_BY_TYPE = {
    "deadline": "A dated obligation; missing it has consequences.",
    "requirement": "A binding obligation that constrains work.",
    "decision": "Changes what the organization will do.",
    "risk": "Potential loss or liability.",
    "contract_clause": "Governs rights and duties under the agreement.",
    "metric": "A measured quantity used for decisions.",
    "contradiction": "Two records disagree; one or both may be wrong.",
    "open_question": "Unresolved; blocks certainty downstream.",
    "failure": "Something did not work; do not repeat it.",
    "result": "Outcome of a test or task.",
    "hypothesis": "A claim awaiting test.",
}


def build_glyph(record: Any, edges: list[Any], scope_names: dict[str, str | None]) -> dict[str, Any]:
    """``record``: MemoryRecord; ``edges``: RecordLink rows touching it."""
    deps, cons, contras = [], [], []
    for e in edges:
        k = e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        if e.src_id == record.id and k in ("depends_on", "part_of"):
            deps.append(str(e.dst_id))
        elif e.src_id == record.id and k == "causes":
            cons.append(str(e.dst_id))
        elif k == "contradicts":
            other = e.dst_id if e.src_id == record.id else e.src_id
            contras.append(str(other))
    status = "current"
    if record.superseded_by_id is not None:
        status = "superseded"
    elif record.verification.value == "disputed" or contras:
        status = "disputed"
    elif record.verification.value == "rejected":
        status = "rejected"
    who = list(record.content.get("parties", [])) if isinstance(record.content, dict) else []
    for key in ("name", "party", "owner", "assignee"):
        v = record.content.get(key) if isinstance(record.content, dict) else None
        if isinstance(v, str) and v not in who:
            who.append(v)
    g = Glyph(
        id=str(record.id),
        type=record.type.value,
        what=record.summary,
        who=who[:8],
        why=_WHY_BY_TYPE.get(record.type.value),
        project=scope_names.get("project"),
        department=scope_names.get("department"),
        time={k: v for k, v in {
            "event": record.event_time.isoformat() if record.event_time else None,
            "valid_from": record.valid_from.isoformat() if record.valid_from else None,
            "valid_to": record.valid_to.isoformat() if record.valid_to else None,
            "recorded": record.recorded_at.isoformat() if record.recorded_at else None,
        }.items() if v},
        status=status,
        dependencies=deps[:16],
        consequences=cons[:16],
        contradictions=contras[:16],
        confidence=round(float(record.confidence), 3),
        verification=record.verification.value,
        evidence=[EvidencePointer(**{"document_id": str(record.source_document_id) if record.source_document_id else None,
                                     **{k: v for k, v in loc.items() if k in EvidencePointer.model_fields}})
                  for loc in (record.source_locations or [])[:4]],
        keywords=list(record.keywords or [])[:12],
    )
    return g.to_compact()
