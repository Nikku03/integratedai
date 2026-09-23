"""``SourceDoc`` -> ``DocMemory``: everything the memory bank keeps about one document,
computed without a database so it can run in worker processes.

* sections: one run of chunks per body field, titled with the field ("Root cause",
  "Acceptance criteria"); short fields are gathered into one "Details" section; the
  first section carries a metadata header for lexical search;
* an extractive summary: the document's own summary field when it has one, otherwise
  the sentences most central to its vocabulary, with a position prior;
* tags: the system's own labels and categorical fields plus the document's key phrases;
* typed records: items of structured list fields (action items, decisions, risks, open
  questions, acceptance criteria, root cause, resolution) and the rule extractor's
  deadlines, decisions, requirements, risks, metrics and open questions over the body;
* the document record (a memory card: summary, tags, people, company, project, dates);
* numeric sentences, kept for cross-document contradiction detection.

Nothing is generated: every summary sentence, tag and record quotes the document.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cie.extraction.facts import DATE_RE, derive_records, keywords_for, parse_date
from cie.extraction.sectioning import BlockRef, SectionDraft
from cie.ingest.sources import SourceDoc, as_list, person_name, tag, text_of

CHUNK = 1000
OVERLAP = 120
SHORT_FIELD = 300
SUMMARY_FIELDS = ("summary", "plain_text_summary", "investigation_summary", "use_case_summary", "requirements_summary", "tldr", "overview")
TYPED_FIELDS: dict[str, tuple[str, str]] = {
    "action_items": ("task", "Action item"), "next_steps": ("task", "Next step"), "next_step": ("task", "Next step"),
    "tasks": ("task", "Task"), "follow_up_actions": ("task", "Follow-up"), "post_release_actions": ("task", "Post-release action"),
    "decisions": ("decision", "Decision"),
    "risks": ("risk", "Risk"), "blockers": ("risk", "Blocker"), "technical_blockers": ("risk", "Technical blocker"),
    "known_issues": ("risk", "Known issue"),
    "open_questions": ("open_question", "Open question"), "questions": ("open_question", "Open question"),
    "acceptance_criteria": ("requirement", "Acceptance criterion"), "technical_requirements": ("requirement", "Requirement"),
    "root_cause": ("fact", "Root cause"), "investigation_summary": ("fact", "Investigation"), "impact": ("fact", "Impact"),
    "resolution": ("result", "Resolution"), "resolution_notes": ("result", "Resolution"), "workaround": ("result", "Workaround"),
    "mitigations_applied": ("result", "Mitigation"), "merge_outcome": ("result", "Merge outcome"),
}
RULE_CAPS = {"deadline": 3, "decision": 3, "requirement": 3, "risk": 2, "metric": 4, "open_question": 2, "fact": 1}
MAX_FIELD_ITEMS = 6
MAX_RECORDS = 30
STOP = set("""a an the and or but if then else of to in on at by for with from into over under about as is are was were be been being
this that these those it its it's we our you your they their them he she his her i me my us not no yes so do does did done can could
should would will shall may might must have has had having also just than too very more most less least any all each every some such
per via etc e.g i.e vs re fyi pls please thanks thank hi hey ok okay yeah new one two three use using used get got see need needs
what when where who which how why there here out up down off only own same other both few many much well still even back after before""".split())
_WORD = re.compile(r"[a-z][a-z0-9\-]{2,}")
_SPEAKER = re.compile(r"^\s*[\w .'()\-]{1,40}:\s+(?=\S)")
_HEADER_LINE = re.compile(r"^\s*(from|to|cc|bcc|date|subject|sent|re|fwd)\s*:", re.I)
_MD = re.compile(r"[#*_`>|]+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_QUOTE_ATTRIBUTION = re.compile(r"^\s*On\b.{5,160}\bwrote:?\s*$")
_OWNER = re.compile(r"^\s*(?:owner\s*[:=]\s*)?([A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,2})\s*(?:[-–—:]|\()\s*")
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"“(])")


@dataclass
class RecOut:
    type: str
    summary: str
    detail: str
    content: dict[str, Any]
    keywords: list[str]
    confidence: float
    embed: str
    section: int | None = None
    event_time: datetime | None = None
    mentions: list[str] = field(default_factory=list)  # entity names (people, companies) the record names


@dataclass
class DocMemory:
    dsid: str | None
    source: str
    rel: str
    title: str
    display_title: str
    summary: str
    tags: list[str]
    sections: list[tuple[str, str, str]]  # (title, stored text, embedding text)
    records: list[RecOut]  # records[0] is the document record
    people: list[tuple[str, str]]
    orgs: list[str]
    project: str | None
    keys: list[str]
    refs: list[tuple[str, str]]
    created: datetime | None
    updated: datetime | None
    sensitivity: int
    numeric: list[str]  # sentences with numbers, for cross-document contradiction detection
    meta_extra: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------ text helpers
def chunk(text: str, size: int = CHUNK, overlap: int = OVERLAP) -> list[str]:
    """Chunks of about ``size`` characters cut at line or sentence boundaries, with a small overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out = []
    i = 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = max(text.rfind("\n", i + size // 2, j), text.rfind(". ", i + size // 2, j))
            if cut > i:
                j = cut + 1
        out.append(text[i:j].strip())
        if j >= len(text):
            break
        i = max(j - overlap, i + 1)
    return [c for c in out if c]


def clean_line(s: str) -> str:
    s = _MD.sub(" ", s)
    s = _SPEAKER.sub("", s, count=1)
    return re.sub(r"\s+", " ", s).strip(" -–—:")


def is_header(line: str) -> bool:
    """An e-mail header or quote-attribution line, also when a list bullet or quote marker precedes it
    (a message list renders as '- From: ...')."""
    raw = _BULLET.sub("", line).lstrip("> ")
    return bool(_HEADER_LINE.match(raw) or _QUOTE_ATTRIBUTION.match(raw))


def sentences(text: str, limit: int = 400) -> list[str]:
    out = []
    for line in text.splitlines():
        if not line.strip() or is_header(line) or line.strip().startswith(("---", "===", "```")):
            continue
        line = clean_line(_BULLET.sub("", line))
        for s in _SENT.split(line):
            s = s.strip()
            if 30 <= len(s):
                out.append(s[:320])
                if len(out) >= limit:
                    return out
    return out


def words(s: str) -> list[str]:
    return [w for w in _WORD.findall(s.lower()) if w not in STOP]


def short(s: str, n: int = 200) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def pretty(field_name: str) -> str:
    return field_name.replace("_", " ").strip().capitalize()


# ------------------------------------------------------------------ summary and tags
def summarize(doc: SourceDoc, max_chars: int = 320) -> str:
    fields = dict(doc.fields)
    for f in SUMMARY_FIELDS:
        v = fields.get(f) or (text_of(doc.meta.get(f)) if doc.meta.get(f) else "")
        if v and len(v) > 40:
            ss = sentences(v, 3) or [clean_line(v)]
            return short(" ".join(ss[:2]), max_chars)
    body = "\n".join(t for f, t in doc.fields if f not in TYPED_FIELDS)[:8000] or doc.body[:8000]
    ss = sentences(body, 80)
    if not ss:
        return short(clean_line(body), max_chars)
    tf = Counter(w for s in ss for w in words(s))
    title_words = set(words(doc.title))
    scored = []
    for i, s in enumerate(ss):
        ws = set(words(s))
        if not ws:
            continue
        centrality = sum(tf[w] for w in ws) / (len(ws) + 4)
        scored.append((centrality + 2.0 * len(ws & title_words) + 3.0 / (1 + i), i, s))
    best = sorted(sorted(scored, reverse=True)[:2], key=lambda x: x[1])
    out = ""
    for _, _, s in best:
        if len(out) + len(s) > max_chars and out:
            break
        out = (out + " " + s).strip()
    return short(out, max_chars)


_URLISH = re.compile(r"\S+@\S+|https?://\S+|\b[\w.-]+\.(?:com|io|ai|net|org)\b", re.I)


def keyphrases(doc: SourceDoc, n: int = 6) -> list[str]:
    title_words = set(words(doc.title))
    toks = words(_URLISH.sub(" ", " ".join(sentences(doc.body[:12000], 200))))
    uni = Counter(toks)
    bi = Counter(f"{a}-{b}" for a, b in zip(toks, toks[1:], strict=False) if a != b)
    scored = [(c + (3 if all(p in title_words for p in k.split("-")) else 0), k) for k, c in bi.items() if c >= 2]
    scored += [(0.5 * c + (3 if k in title_words else 0), k) for k, c in uni.items() if c >= 3 and len(k) > 3]
    out: list[str] = []
    for _, k in sorted(scored, reverse=True):
        t = tag(k)
        if t and t not in out and not any(t in o or o in t for o in out):
            out.append(t)
        if len(out) >= n:
            break
    return out


# ------------------------------------------------------------------ records
def _items(value: Any) -> list[str]:
    """Items of a structured list field: list entries, else bullet lines, else the first sentences."""
    if isinstance(value, str) and value.strip().startswith("["):
        value = as_list(value)
    if isinstance(value, list):
        items = [text_of(x) for x in value]
    else:
        text = text_of(value)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        bullets = [_BULLET.sub("", ln).strip() for ln in lines if _BULLET.match(ln)]
        items = bullets if len(bullets) >= 2 else (lines if len(lines) >= 2 and all(len(ln) < 300 for ln in lines) else sentences(text, 3) or [text])
    items = [i.replace("-", " ") if " " not in i.strip() and "-" in i else i for i in items]  # CRM-style slugs
    return [short(clean_line(i), 400) for i in items if i and len(i.strip()) > 8][:MAX_FIELD_ITEMS]


def _owner_due(item: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = _OWNER.match(item)
    if m:
        n = person_name(m.group(1))
        if n:
            out["owner"] = n
    d = DATE_RE.search(item)
    if d:
        when = parse_date(d.group(0))
        if when:
            out["due"] = when.isoformat()
    return out


def _prose(line: str) -> bool:
    """A line of prose rather than code, JSON, a table row or a log line."""
    t = line.strip()
    if not t or t.startswith(("{", "}", "[", "|", "```", "$ ", "> ")) or '":' in t or t.count("|") >= 2:
        return False
    letters = sum(ch.isalpha() or ch == " " for ch in t)
    return letters / len(t) > 0.72


def _mentions(text: str, names: list[str]) -> list[str]:
    low = text.lower()
    return [n for n in names if n.lower() in low]


def _norm(text: str) -> str:
    return " ".join(clean_line(ln) for ln in text.splitlines() if ln.strip())


def _section_of(text: str, candidates: list[int] | None, sections: list[tuple[str, str, str]], norm: list[str] | None = None) -> int | None:
    """The section that holds ``text``: searched among the field's own sections first, then all of them (on cleaned
    text, the form rule records quote). A field that has no section (metadata only) gives None, not section 0."""
    if not candidates:
        return None
    probe = re.sub(r"\s+", " ", clean_line(text))[:50]
    if probe:
        for i in candidates:
            if probe in (norm[i] if norm else _norm(sections[i][1])):
                return i
        if norm:
            for i, st in enumerate(norm):
                if probe in st:
                    return i
    return candidates[0]


def build(doc: SourceDoc) -> DocMemory:
    display = doc.title
    if doc.source == "slack" or len(doc.title.split()) <= 2:
        first = next(iter(sentences(doc.body, 1)), "")
        display = f"#{doc.title}: {short(first, 110)}" if doc.source == "slack" and first else doc.title
    summary = summarize(doc)
    tags = list(dict.fromkeys(doc.tags + keyphrases(doc)))[:30]
    people_names = [n for n, _ in doc.people]
    names = people_names + doc.orgs

    # sections
    header_bits = [f"source: {doc.source}"]
    if doc.project:
        header_bits.append(f"project: {doc.project}")
    if doc.orgs:
        header_bits.append(f"company: {', '.join(doc.orgs[:3])}")
    if doc.people:
        header_bits.append("people: " + ", ".join(f"{n} ({r})" for n, r in doc.people[:8]))
    for k in ("status", "priority", "severity", "stage", "key", "channel", "space", "team", "repo", "issue_type", "call_type", "thread_type"):
        v = doc.meta.get(k)
        if v not in (None, "", []) and not isinstance(v, list | dict):
            header_bits.append(f"{k}: {v}")
    if doc.tags:
        header_bits.append("tags: " + ", ".join(doc.tags[:12]))
    header = " | ".join(header_bits)
    sections: list[tuple[str, str, str]] = []
    field_secs: dict[str, list[int]] = {}  # body field -> the sections holding its text
    details: list[tuple[str, str]] = []
    main_field = doc.fields[0][0] if doc.fields else None
    for f, text in doc.fields:
        if not text:
            continue
        if len(text) < SHORT_FIELD and f != main_field:
            details.append((f, f"{pretty(f)}: {text}"))
            continue
        sec_title = doc.title if f == main_field else f"{doc.title} — {pretty(f)}"
        for c in chunk(text):
            field_secs.setdefault(f, []).append(len(sections))
            sections.append((sec_title[:300], c, f"{sec_title}\n{c}"))
    if details:
        body = "\n".join(t for _, t in details)
        first_detail = len(sections)
        for c in chunk(body):
            sections.append((f"{doc.title} — Details"[:300], c, f"{doc.title} — Details\n{c}"))
        for f, t in details:
            probe = t[:60]
            at = next((i for i in range(first_detail, len(sections)) if probe in sections[i][1]), first_detail)
            field_secs.setdefault(f, []).append(at)
    if not sections:
        sections.append((doc.title[:300], doc.title, doc.title))
    t0, s0, e0 = sections[0]
    sections[0] = (t0, f"{header}\n\n{s0}", e0)

    records: list[RecOut] = []
    # document record: the memory card
    card_lines = [f"Summary: {summary}", f"Tags: {', '.join(tags)}"]
    if doc.people:
        card_lines.append("People: " + ", ".join(f"{n} ({r})" for n, r in doc.people[:10]))
    if doc.orgs:
        card_lines.append("Company: " + ", ".join(doc.orgs[:4]))
    if doc.project:
        card_lines.append(f"Project: {doc.project}")
    if doc.keys:
        card_lines.append("Identifiers: " + ", ".join(k.split(":", 1)[-1] for k in doc.keys[:4]))
    if doc.created:
        card_lines.append(f"Created: {doc.created.date().isoformat()}" + (f"; updated: {doc.updated.date().isoformat()}" if doc.updated else ""))
    opening = "\n".join(s for _, s, _ in sections[:2])[:1500]
    records.append(RecOut(
        type="document", summary=short(f"{doc.source}: {display} — {summary}", 400),
        detail="\n".join(card_lines) + "\n\n" + opening,
        content={"dsid": doc.dsid, "source": doc.source, "title": doc.title, "summary": summary, "tags": tags, "project": doc.project,
                 "companies": doc.orgs[:6], "people": [{"name": n, "role": r} for n, r in doc.people[:12]],
                 "identifiers": doc.keys[:8], "created": doc.created.isoformat() if doc.created else None},
        keywords=tags[:24], confidence=0.9, embed=f"{display}\n{summary}\nTags: {', '.join(tags[:12])}", section=0,
        event_time=doc.created, mentions=names))

    # typed records from structured fields (body or metadata)
    seen: set[str] = set()
    field_values: dict[str, Any] = {**{k: v for k, v in doc.meta.items() if k in TYPED_FIELDS}, **{f: t for f, t in doc.fields if f in TYPED_FIELDS}}
    for f, value in field_values.items():
        rtype, label = TYPED_FIELDS[f]
        for item in _items(value):
            key = item.lower()[:80]
            if key in seen:
                continue
            seen.add(key)
            extra = _owner_due(item) if rtype == "task" else {}
            when = parse_date(extra["due"][:10]) if extra.get("due") else None
            summ = short(item if rtype in ("task", "decision", "risk", "open_question", "requirement") else f"{label}: {item}", 220)
            records.append(RecOut(
                type=rtype, summary=summ, detail=f"{label} ({doc.title}): {item}",
                content={"field": f, "label": label, **extra}, keywords=keywords_for(item, 6), confidence=0.85,
                embed=f"{label}: {item}", section=_section_of(item, field_secs.get(f), sections), event_time=when,
                mentions=_mentions(item, names) + ([extra["owner"]] if extra.get("owner") and extra["owner"] not in names else [])))
            if len(records) >= MAX_RECORDS:
                break

    # rule-extracted records over sentence-aligned paragraphs of the body (never over overlapping chunks, whose
    # first sentence is a fragment); code and data snippets are not prose and are skipped
    counts: Counter = Counter()
    norm_secs: list[str] = []
    for f, text in doc.fields:
        if len(records) >= MAX_RECORDS or f in TYPED_FIELDS:
            continue
        paras = [clean_line(ln) for ln in text.splitlines() if ln.strip() and not is_header(ln) and _prose(ln)]
        if not norm_secs:
            norm_secs = [_norm(st) for _t, st, _e in sections]
        block = BlockRef(block_id=None, page_no=1, bbox=None, kind="paragraph", text="\n".join(paras)[:12000])
        for d in derive_records([(f, SectionDraft(title=None, level=1, blocks=[block]))], document_title=doc.title, doc_type=None):
            if d.type not in RULE_CAPS or counts[d.type] >= RULE_CAPS[d.type]:
                continue
            si = _section_of(d.detail, field_secs.get(f), sections, norm=norm_secs)
            key = d.detail.lower()[:80]
            if key in seen or any(key[:40] in s for s in seen):
                continue
            seen.add(key)
            counts[d.type] += 1
            records.append(RecOut(type=d.type, summary=d.summary, detail=d.detail, content=dict(d.content), keywords=d.keywords,
                                  confidence=d.confidence, embed=d.detail[:500], section=si, event_time=d.event_time,
                                  mentions=_mentions(d.detail, names)))
            if len(records) >= MAX_RECORDS:
                break

    numeric = [s for s in sentences(doc.body, 200) if re.search(r"\d", s)][:16]
    return DocMemory(dsid=doc.dsid, source=doc.source, rel=doc.rel, title=doc.title, display_title=display, summary=summary, tags=tags,
                     sections=sections, records=records, people=doc.people, orgs=doc.orgs, project=doc.project, keys=doc.keys,
                     refs=doc.refs, created=doc.created, updated=doc.updated, sensitivity=doc.sensitivity, numeric=numeric,
                     meta_extra={k: str(v)[:200] for k, v in doc.meta.items() if isinstance(v, str | int | float) and len(str(v)) < 200})
