"""Verification of a task result against original sources and the live state.

Each finding is checked by every method its evidence allows, and the verdict records which ones ran:

* **citation**: the cited record must exist, be current (not deleted or superseded), its quote must appear on
  the cited page (or in the record), and the claim must be lexically supported by it;
* **state**: each live-state record the finding relies on (``state_refs``) must still be at the version the
  finding used, and a stated field value must still be the record's value;
* **recalculation**: a finding with a ``calculation`` (an arithmetic expression over numbers and live-state
  fields) is recomputed from the *current* state with a safe evaluator and must match the stated value.

A finding with none of these has no evidence and fails. State checks read through the verifier's permissions:
a record the verifier may not see cannot support a finding. Failing findings lower the producing agent's
scorecard, and the reviewer asks for changes.
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


def verify_result(session: Session, result: dict[str, Any], *, reader=None) -> Verdict:
    """``reader`` (a ``GraphReader`` with the verifier's permissions) is needed for state and recalculation checks."""
    v = Verdict()
    for f in result.get("findings", []):
        status, why, methods, extra = "verified", [], [], {}
        cites = f.get("citations") or []
        refs = f.get("state_refs") or []
        calc = f.get("calculation")
        if not cites and not refs and not calc:
            status, why = "failed", ["no evidence: no citation, state reference or calculation"]
        if cites:
            methods.append("citation")
            ok, reasons = _check_citations(session, f, cites)
            if not ok:
                status, why = "failed", why + reasons
        if refs:
            methods.append("state")
            reasons = _check_state(reader, refs)
            if reasons:
                status, why = "failed", why + reasons
        if calc:
            methods.append("recalculation")
            reasons, recomputed = _recalculate(reader, calc, f.get("value"))
            extra["recomputed"] = recomputed
            if reasons:
                status, why = "failed", why + reasons
        v.details.append({"claim": f.get("claim"), "status": status, "reasons": why, "methods": methods, **extra})
        if status == "verified":
            v.verified += 1
        else:
            v.failed += 1
    return v


def _check_citations(session: Session, f: dict[str, Any], cites: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    ok, why = True, []
    for c in cites:
        rid = c.get("item_id")
        try:
            rec = session.get(MemoryRecord, uuid.UUID(rid)) if rid else None
        except ValueError:
            rec = None
        if rec is None:
            ok, why = False, why + [f"cited record {rid} not found"]
            continue
        if rec.deleted_at is not None:
            ok, why = False, why + ["cited record deleted"]
        if rec.superseded_by_id is not None:
            ok, why = False, why + ["cited record was superseded by a newer version"]
        quote = _norm(c.get("quote") or "")
        if quote and rec.source_document_id and c.get("page_no"):
            page = session.scalar(select(Page).where(Page.document_id == rec.source_document_id, Page.page_no == c["page_no"])
                                  .order_by(Page.id.desc()))
            if page is not None and quote[:80] not in _norm(page.text) and quote[:80] not in _norm(rec.detail):
                ok, why = False, why + ["quote not found on cited page"]
        claim_words = {w for w in re.findall(r"[a-z0-9]{4,}", _norm(f.get("claim", "")))}
        hay = _norm(f"{rec.summary} {rec.detail} {rec.content}")
        if claim_words and sum(1 for w in claim_words if w in hay) / len(claim_words) < 0.3:
            ok, why = False, why + ["claim not supported by cited record"]
    return ok, why


def _node(reader, ref):
    if reader is None:
        return None
    from cie.state.domain_events import _view

    try:
        return _view(reader, ref)
    except (ValueError, KeyError):
        return None


def _label(ref) -> str:
    return ":".join(str(x) for x in ref) if isinstance(ref, (list, tuple)) else str(ref)


def _check_state(reader, refs: list[dict[str, Any]]) -> list[str]:
    if reader is None:
        return ["state references need a state reader"]
    why = []
    for r in refs:
        ref = r.get("ref") or r.get("id")
        n = _node(reader, ref)
        if n is None:
            why.append(f"record {_label(ref)} not found or not visible to the verifier")
            continue
        if r.get("version") is not None and int(r["version"]) != n.version:
            why.append(f"stale: {n.type}:{n.key} is at version {n.version}; the finding used version {r['version']}")
        if r.get("field") and "value" in r:
            cur = (n.attrs or {}).get(r["field"])
            if str(cur) != str(r["value"]):
                why.append(f"{n.type}:{n.key} {r['field']} is {cur!r}, not {r['value']!r}")
    return why


def _recalculate(reader, calc: dict[str, Any], stated: Any) -> tuple[list[str], float | None]:
    from cie.agents.calc import CalcError, evaluate

    names: dict[str, Any] = {}
    for name, spec in (calc.get("inputs") or {}).items():
        if isinstance(spec, dict) and ("ref" in spec or "id" in spec):
            n = _node(reader, spec.get("ref") or spec.get("id"))
            if n is None:
                return [f"input {name}: record {_label(spec.get('ref') or spec.get('id'))} not found or not visible"], None
            if spec.get("field") not in (n.attrs or {}):
                return [f"input {name}: {n.type}:{n.key} has no {spec.get('field')}"], None
            names[name] = n.attrs[spec["field"]]
        else:
            names[name] = spec
    try:
        got = evaluate(str(calc.get("expression", "")), names)
    except CalcError as e:
        return [f"cannot recalculate: {e}"], None
    target = calc.get("result", stated)
    try:
        want = float(target)
    except (TypeError, ValueError):
        return [f"stated value {target!r} is not a number"], round(got, 6)
    tol = float(calc.get("tolerance", 0.01))
    if abs(got - want) > max(tol, abs(want) * 1e-9):
        return [f"recomputed {round(got, 6)} from the current state; the finding states {want}"], round(got, 6)
    return [], round(got, 6)
