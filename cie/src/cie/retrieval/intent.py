"""Query intent classification and hint extraction (rule based, LLM optional)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from cie.extraction.facts import DATE_RE, parse_date

UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
CLAUSE_RE = re.compile(r"\b(?:clause|section|article|§)\s*(\d+(?:\.\d+)*)\b", re.I)
QUOTED_RE = re.compile(r"[\"“]([^\"”]{2,80})[\"”]")
TEMPORAL_RE = re.compile(r"\b(as of|before|after|since|until|in (?:19|20)\d\d|current(?:ly)?|latest|previous(?:ly)?|old|superseded|history|changed|was|now)\b", re.I)
COMPARE_RE = re.compile(r"\b(compare|difference|differ|versus|vs\.?|conflict|contradict|disagree|consistent)\b", re.I)
LIST_RE = re.compile(r"\b(list|all|every|which|enumerate|how many)\b", re.I)
WHO_RE = re.compile(r"\b(who|whom|whose|person|people|signed|responsible|owner)\b", re.I)
VALUE_RE = re.compile(r"\b(how much|what is the (?:fee|amount|price|cost|total|cap|limit|penalty|rate|term|deadline|date)|when (?:is|does|must|was)|what date|by when)\b", re.I)
DEFINE_RE = re.compile(r"\b(what does .* mean|define|definition of|meaning of)\b", re.I)
_TYPE_HINTS = {
    "deadline": re.compile(r"\b(deadline|due|by when|expire|terminate|notice period)\b", re.I),
    "metric": re.compile(r"\b(how much|fee|amount|price|cost|total|cap|penalty|rate|percent|%|revenue|budget|salary)\b", re.I),
    "contract_clause": re.compile(r"\b(clause|section|article|agreement|contract|term|liability|indemn)\b", re.I),
    "decision": re.compile(r"\b(decid|approv|resolv|agreed)\w*\b", re.I),
    "requirement": re.compile(r"\b(must|shall|required|obligation|requirement)\b", re.I),
    "risk": re.compile(r"\b(risk|liabilit|penalt|breach|exposure)\w*\b", re.I),
    "person": re.compile(r"\b(who|signed|signatory|officer|manager|director)\b", re.I),
    "organization": re.compile(r"\b(supplier|vendor|company|counterparty|party|customer|client)\b", re.I),
    "open_question": re.compile(r"\b(open question|unresolved|tbd|pending)\b", re.I),
    "task": re.compile(r"\b(task|assigned|blocked|progress)\b", re.I),
}


@dataclass
class Intent:
    kind: str  # exact_id|exact_field|entity|definition|temporal|comparison|list|open
    record_ids: list[uuid.UUID] = field(default_factory=list)
    clause_numbers: list[str] = field(default_factory=list)
    quoted: list[str] = field(default_factory=list)
    type_hints: list[str] = field(default_factory=list)
    as_of: datetime | None = None
    include_history: bool = False
    wants_entities: bool = False


def classify(query: str) -> Intent:
    q = query.strip()
    intent = Intent(kind="open")
    intent.record_ids = [uuid.UUID(m) for m in UUID_RE.findall(q)]
    intent.clause_numbers = CLAUSE_RE.findall(q)
    intent.quoted = QUOTED_RE.findall(q)
    intent.type_hints = [t for t, pat in _TYPE_HINTS.items() if pat.search(q)]
    dates = [parse_date(d) for d in DATE_RE.findall(q)]
    dates = [d for d in dates if d]
    m = re.search(r"\bas of\b", q, re.I)
    if m and dates:
        intent.as_of = dates[0]
    if intent.record_ids:
        intent.kind = "exact_id"
    elif intent.clause_numbers or (VALUE_RE.search(q) and intent.type_hints):
        intent.kind = "exact_field"
    elif DEFINE_RE.search(q):
        intent.kind = "definition"
    elif COMPARE_RE.search(q):
        intent.kind = "comparison"
    elif TEMPORAL_RE.search(q):
        intent.kind = "temporal"
    elif WHO_RE.search(q):
        intent.kind = "entity"
    elif LIST_RE.search(q):
        intent.kind = "list"
    intent.include_history = bool(re.search(r"\b(previous|old|superseded|history|changed|was|before|earlier|original)\b", q, re.I))
    intent.wants_entities = bool(WHO_RE.search(q))
    return intent
