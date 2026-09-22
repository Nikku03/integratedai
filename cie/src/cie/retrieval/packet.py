"""Evidence packet: the compact, reproducible set of records handed to a model."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from cie.core.models import EvidencePacket, MemoryRecord, Section
from cie.core.util import estimate_tokens
from cie.governance.scanners import redact_injections
from cie.retrieval.rerank import Candidate


def record_item(r: MemoryRecord, c: Candidate | None, conflicts: dict, detail_chars: int = 600) -> dict[str, Any]:
    return {
        "id": str(r.id), "kind": "record", "type": r.type.value, "summary": r.summary,
        "detail": redact_injections((r.detail or "")[:detail_chars]), "content": r.content,
        "document_id": str(r.source_document_id) if r.source_document_id else None,
        "citations": [{**loc, "quote": redact_injections(loc.get("quote") or "")} for loc in (r.source_locations or [])],
        "confidence": float(r.confidence),
        "verification": r.verification.value, "superseded": r.superseded_by_id is not None,
        "superseded_by": str(r.superseded_by_id) if r.superseded_by_id else None,
        "valid_from": r.valid_from.isoformat() if r.valid_from else None,
        "valid_to": r.valid_to.isoformat() if r.valid_to else None,
        "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
        "conflicts_with": [str(x) for x in conflicts.get(r.id, [])],
        "score": round(c.final, 4) if c else None, "support": c.support if c else None, "reasons": c.reasons if c else {},
        "horizon": c.horizon if c else 0, "via": c.via if c else None,
        "glyph": r.glyph, "scope_id": str(r.scope_id),
    }


def section_item(s: Section, c: Candidate | None, text_chars: int = 1200) -> dict[str, Any]:
    return {
        "id": str(s.id), "kind": "section", "type": "section", "summary": s.title or (s.text[:80] + "…"),
        "detail": redact_injections(s.text[:text_chars]), "document_id": str(s.document_id),
        "citations": [{"page_no": sp["page_no"], "bbox": sp["bbox"], "section_id": str(s.id),
                       "quote": redact_injections(s.text[:200])} for sp in (s.spans or [])],
        "page_start": s.page_start, "page_end": s.page_end,
        "score": round(c.final, 4) if c else None, "support": c.support if c else None, "reasons": c.reasons if c else {},
        "scope_id": str(s.scope_id),
    }


def build(session: Session, *, tenant_id: uuid.UUID, principal_id: uuid.UUID | None, query: str, intent: str,
          scope_ids: list[uuid.UUID], filters: dict, ranked: list[Candidate], conflicts: dict, min_records: int,
          max_records: int, token_budget: int, trace: dict, latency_ms: float) -> EvidencePacket:
    items: list[dict[str, Any]] = []
    used = 0
    for c in ranked:
        item = record_item(c.record, c, conflicts) if c.record is not None else section_item(c.section, c)
        t = estimate_tokens(item["summary"] + " " + item["detail"])
        if len(items) >= max_records:
            break
        if used + t > token_budget and len(items) >= min_records:
            break
        items.append(item)
        used += t
    packet = EvidencePacket(tenant_id=tenant_id, principal_id=principal_id, query=query, intent=intent,
                            scope_ids=[str(s) for s in scope_ids], filters=filters, items=items, trace=trace,
                            token_estimate=used, latency_ms=latency_ms)
    session.add(packet)
    session.flush()
    return packet
