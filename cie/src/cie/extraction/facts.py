"""Deterministic derivation of typed memory records from sections.

This is the rule-based strategy. It never invents content: every record quotes
the sentence it came from and points to the page, block and bbox. Confidence
is capped at 0.8 for rule extraction; an LLM strategy (``cie.agents.providers``)
can add richer records with its own ``producing_agent`` tag.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cie.extraction.sectioning import BlockRef, SectionDraft

PRODUCER = "rule_extractor_v1"

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
DATE_RE = re.compile(
    rf"\b((?:{_MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}|\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})\b"
)
MONEY_RE = re.compile(r"(?:(USD|EUR|GBP|INR|\$|€|£|₹)\s?)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s*(million|billion|thousand|m|bn|k)?\b", re.I)
PCT_RE = re.compile(r"\b(\d{1,3}(?:\.\d+)?)\s?%")
DEADLINE_RE = re.compile(r"\b(no later than|on or before|by|within\s+\d+\s+(?:business\s+)?days|deadline|due (?:on|by)|expires? on|terminat\w+ on)\b", re.I)
DURATION_RE = re.compile(r"\b(\d{1,3})\s+(?:\(\d+\)\s+)?(?:business\s+|calendar\s+)?days\b", re.I)
REQ_RE = re.compile(r"\b(shall|must|is required to|are required to|shall not|must not|may not)\b", re.I)
DECISION_RE = re.compile(r"\b(decided|approved|resolved|agreed to|resolution|hereby approves|the board approved|elected to)\b", re.I)
RISK_RE = re.compile(r"\b(risk|liabilit\w+|penalt\w+|indemnif\w+|breach|default|force majeure|terminat\w+ for cause|dispute)\b", re.I)
QUESTION_RE = re.compile(r"\b(TBD|to be determined|to be confirmed|TBC|pending confirmation|open question|unresolved)\b|\[\s*\]", re.I)
ORG_RE = re.compile(r"\b([A-Z][A-Za-z0-9&'\-]+(?:\s+[A-Z][A-Za-z0-9&'\-]+){0,4}\s+(?:Inc\.?|Ltd\.?|LLC|L\.L\.C\.|GmbH|Corp\.?|Corporation|Limited|plc|PLC|S\.A\.|B\.V\.|AG|Co\.))")
DEFINED_RE = re.compile(r"\(\s*(?:the\s+|hereinafter\s+)?[\"“]([A-Z][A-Za-z ]{1,40})[\"”]\s*\)")
PERSON_RE = re.compile(r"\b(?:Mr\.|Ms\.|Mrs\.|Dr\.|Prof\.)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b|\bBy:\s*(?:/s/\s*)?([A-Z][a-z]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-z]+){1,2})\b|\bName:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b")
CLAUSE_TITLE_RE = re.compile(r"^(?:(?:Section|Article|Clause|Schedule|Exhibit)\s+)?(\d+(?:\.\d+)*|[IVXLC]+)[.):]?\s+(.{3,100})$", re.I)
SENT_SPLIT = re.compile(r"(?<=[.;!?])\s+(?=[A-Z(\"“]|\d+(?:\.\d+)+\s)")
METRIC_KEY_RE = re.compile(r"\b(revenue|net income|EBITDA|headcount|budget|cost|fee|price|total|amount|penalty|cap|limit|term|salary|margin|growth|churn)\b", re.I)


@dataclass
class RecordDraft:
    type: str
    summary: str
    content: dict[str, Any]
    detail: str
    source_locations: list[dict[str, Any]]
    keywords: list[str] = field(default_factory=list)
    confidence: float = 0.7
    event_time: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    entity_names: list[str] = field(default_factory=list)


def parse_date(s: str) -> datetime | None:
    s = s.strip().replace(",", "")
    for fmt in ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%b. %d %Y", "%Sept %d %Y"):
        try:
            return datetime.strptime(s.replace(".", ""), fmt.replace(".", "")).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT_SPLIT.split(text.replace("\n", " ")) if len(s.strip()) > 12]


def _locate(sentence: str, blocks: list[BlockRef], section_id: str | None) -> list[dict[str, Any]]:
    probe = sentence[:60].replace("\n", " ")
    for b in blocks:
        if probe in b.text.replace("\n", " "):
            return [{"page_no": b.page_no, "bbox": b.bbox, "block_id": str(b.block_id),
                     "section_id": section_id, "quote": sentence[:300]}]
    if blocks:
        b = blocks[0]
        return [{"page_no": b.page_no, "bbox": b.bbox, "block_id": str(b.block_id),
                 "section_id": section_id, "quote": sentence[:300]}]
    return [{"page_no": None, "bbox": None, "block_id": None, "section_id": section_id, "quote": sentence[:300]}]


def _money(m: re.Match) -> dict[str, Any]:
    cur = m.group(1).upper()
    cur = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}.get(cur, cur)
    val = float(m.group(2).replace(",", "") + ("." + m.group(3) if m.group(3) else ""))
    mult = (m.group(4) or "").lower()
    val *= {"million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}.get(mult, 1)
    return {"value": val, "currency": cur, "raw": m.group(0)}


def keywords_for(text: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-]{2,}", text)
    stop = {"the", "and", "for", "that", "with", "this", "from", "shall", "will", "are", "was", "were",
            "have", "has", "not", "any", "all", "such", "under", "into", "their", "its", "which", "other",
            "than", "each", "upon", "may", "also", "been", "between", "here", "there", "these", "those"}
    freq: dict[str, int] = {}
    for w in words:
        lw = w.lower()
        if lw in stop:
            continue
        freq[lw] = freq.get(lw, 0) + (2 if w[0].isupper() else 1)
    return [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:limit]]


def derive_records(
    sections: list[tuple[str, SectionDraft]],
    *,
    document_title: str,
    doc_type: str | None,
    max_per_type_per_section: int = 6,
) -> list[RecordDraft]:
    """``sections``: list of (section_id, draft)."""
    drafts: list[RecordDraft] = []
    orgs_seen: set[str] = set()
    people_seen: set[str] = set()
    for section_id, sec in sections:
        add = _Adder(drafts, max_per_type_per_section)
        # header/footer blocks (page furniture, email headers) never join body sentences
        body_blocks = [b for b in sec.blocks if b.kind not in ("header", "footer")]
        text = "\n".join(([sec.title] if sec.title else []) + [b.text for b in body_blocks if b.text and b.kind != "heading"]).strip()
        for hb in sec.blocks:
            if hb.kind == "header" and hb.text.startswith(("From:", "Subject:", "To:")):
                meta = dict(line.split(":", 1) for line in hb.text.splitlines() if ":" in line)
                meta = {k.strip(): v.strip() for k, v in meta.items()}
                when = parse_date(meta.get("Date", "")[5:16].replace(",", "")) if meta.get("Date") else None
                add(RecordDraft("fact", f"Email from {meta.get('From', '?')} to {meta.get('To', '?')}: {meta.get('Subject', '')}"[:180],
                                {"email": meta}, hb.text, _locate(hb.text, sec.blocks, section_id), keywords_for(hb.text, 6), 0.9,
                                event_time=when))

        # Contract clause per numbered section
        if sec.title:
            m = CLAUSE_TITLE_RE.match(sec.title.strip())
            if m and (doc_type in (None, "contract", "agreement", "policy") or re.search(r"agreement|contract|terms", document_title, re.I)):
                first = _sentences(text)[:1]
                add(RecordDraft(
                    type="contract_clause",
                    summary=f"Clause {m.group(1)}: {m.group(2).strip()}",
                    content={"clause_number": m.group(1), "title": m.group(2).strip(), "document": document_title},
                    detail=text[:2000],
                    source_locations=_locate(sec.title, sec.blocks, section_id),
                    keywords=keywords_for(text),
                    confidence=0.8,
                ))
                first = first  # noqa: F841 (kept for readability)

        for sent in _sentences(text):
            locs = _locate(sent, sec.blocks, section_id)
            dates = [parse_date(d) for d in DATE_RE.findall(sent)]
            dates = [d for d in dates if d]
            first_date = dates[0] if dates else None

            duration = DURATION_RE.search(sent)
            if DEADLINE_RE.search(sent) and (first_date or duration):
                content: dict[str, Any] = {"trigger": DEADLINE_RE.search(sent).group(0)}
                if first_date:
                    content["date"] = first_date.isoformat()
                if duration:
                    content["duration_days"] = int(duration.group(1))
                add(RecordDraft("deadline", _short(sent), content, sent, locs, keywords_for(sent, 6), 0.75, event_time=first_date))
            if REQ_RE.search(sent):
                add(RecordDraft("requirement", _short(sent), {"modal": REQ_RE.search(sent).group(0).lower()},
                                sent, locs, keywords_for(sent, 6), 0.7, event_time=first_date))
            if DECISION_RE.search(sent):
                add(RecordDraft("decision", _short(sent), {"marker": DECISION_RE.search(sent).group(0).lower()},
                                sent, locs, keywords_for(sent, 6), 0.65, event_time=first_date, valid_from=first_date))
            if RISK_RE.search(sent) and len(sent) < 600:
                add(RecordDraft("risk", _short(sent), {"marker": RISK_RE.search(sent).group(0).lower()},
                                sent, locs, keywords_for(sent, 6), 0.6))
            for mm in MONEY_RE.finditer(sent):
                money = _money(mm)
                key = METRIC_KEY_RE.search(sent)
                add(RecordDraft("metric", _short(sent), {**money, "name": (key.group(0).lower() if key else "amount")},
                                sent, locs, keywords_for(sent, 6), 0.75, event_time=first_date, valid_from=first_date))
            for pm in PCT_RE.finditer(sent):
                key = METRIC_KEY_RE.search(sent)
                add(RecordDraft("metric", _short(sent), {"value": float(pm.group(1)), "unit": "%", "name": (key.group(0).lower() if key else "percentage"), "raw": pm.group(0)},
                                sent, locs, keywords_for(sent, 6), 0.7, event_time=first_date, valid_from=first_date))
            if QUESTION_RE.search(sent):
                add(RecordDraft("open_question", _short(sent), {"marker": QUESTION_RE.search(sent).group(0)},
                                sent, locs, keywords_for(sent, 6), 0.6))
            for om in ORG_RE.finditer(sent):
                name = om.group(1).strip()
                if name not in orgs_seen:
                    orgs_seen.add(name)
                    add(RecordDraft("organization", name, {"name": name, "context": _short(sent)}, sent, locs,
                                    keywords_for(name, 4), 0.7, entity_names=[name]))
            for pmn in PERSON_RE.finditer(sent):
                name = next(g for g in pmn.groups() if g)
                if name not in people_seen:
                    people_seen.add(name)
                    signatory = bool(re.match(r"\s*By:", sent)) or "signatur" in sent.lower()
                    detail = (f"Signed by {name} (signatory). {sent}" if signatory else sent)
                    add(RecordDraft("person", name, {"name": name, "context": _short(sent), "role": "signatory" if signatory else None},
                                    detail, locs, keywords_for(name, 3) + (["signed", "signatory"] if signatory else []), 0.65,
                                    entity_names=[name]))
            for dm in DEFINED_RE.finditer(sent):
                term = dm.group(1).strip()
                add(RecordDraft("fact", f'Defined term "{term}"', {"defined_term": term, "definition": _short(sent)},
                                sent, locs, keywords_for(term + " " + sent, 6), 0.75))
    return drafts


class _Adder:
    """Appends drafts with a per-type cap for one section."""

    def __init__(self, drafts: list[RecordDraft], cap: int):
        self.drafts, self.cap, self.counts = drafts, cap, {}

    def __call__(self, d: RecordDraft) -> None:
        if self.counts.get(d.type, 0) >= self.cap:
            return
        self.counts[d.type] = self.counts.get(d.type, 0) + 1
        self.drafts.append(d)


def _short(s: str, n: int = 180) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"
