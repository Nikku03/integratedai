"""Verification of a task result against original sources.

For every finding: the cited record must exist and be readable, the quote
must appear in the cited page's stored text (or the record's own source
quote must match), and the claim must be lexically supported by the record.
Produces a verdict with per-finding status; failing findings lower the
producing agent's scorecard and, if any fail hard, the task needs human review.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import MemoryRecord, Page


@dataclass
class Verdict:
    verified: int = 0
    failed: int = 0
    details: list[dict[str, Any]] = field(default_factory=list)

    @property
    def score(self) -> float:
        n = self.verified + self.failed
        return round(self.verified / n, 3) if n else 1.0

    @property
    def passed(self) -> bool:
        return self.failed == 0

    def as_dict(self) -> dict[str, Any]:
        return {"verified": self.verified, "failed": self.failed, "score": self.score, "passed": self.passed, "details": self.details}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def verify_result(session: Session, result: dict[str, Any]) -> Verdict:
    v = Verdict()
    for f in result.get("findings", []):
        status, why = "verified", []
        cites = f.get("citations") or []
        if not cites:
            status, why = "failed", ["no citation"]
        for c in cites:
            rid = c.get("item_id")
            rec = session.get(MemoryRecord, uuid.UUID(rid)) if rid else None
            if rec is None:
                status, why = "failed", why + [f"cited record {rid} not found"]
                continue
            if rec.deleted_at is not None:
                status, why = "failed", why + ["cited record deleted"]
            quote = _norm(c.get("quote") or "")
            if quote and rec.source_document_id and c.get("page_no"):
                page = session.scalar(select(Page).where(Page.document_id == rec.source_document_id, Page.page_no == c["page_no"])
                                      .order_by(Page.id.desc()))
                if page is not None and quote[:80] not in _norm(page.text) and quote[:80] not in _norm(rec.detail):
                    status, why = "failed", why + ["quote not found on cited page"]
            claim_words = {w for w in re.findall(r"[a-z0-9]{4,}", _norm(f.get("claim", "")))}
            hay = _norm(f"{rec.summary} {rec.detail} {rec.content}")
            if claim_words and sum(1 for w in claim_words if w in hay) / len(claim_words) < 0.3:
                status, why = "failed", why + ["claim not supported by cited record"]
        v.details.append({"claim": f.get("claim"), "status": status, "reasons": why})
        if status == "verified":
            v.verified += 1
        else:
            v.failed += 1
    return v
