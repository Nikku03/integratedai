"""Where an answer gets lost: search, packaging, or the model.

For every EnterpriseRAG-Bench question with gold documents, the benchmark gives the answer as short facts
(``answer_facts``). This audit follows those facts through the memory bank's answer path and puts each question in
the first stage that loses any of them:

1. **Search missed the document.** No gold document is in the evidence packet.
2. **Right document, wrong part.** A gold document is in the packet, but some of the answer's facts are not in the
   packet's text (the passage that holds them was not selected).
3. **Cut before the model.** Every fact is in the packet, but not in the part a small model is given (the best items
   up to ``llm_local_evidence_chars``, as ``retrieval.answer.assisted`` sends them).
4. **Everything reached the model.** Every fact is in what the model reads. A wrong answer here is the model's.

**Fact presence** is a lexical check on one passage at a time (a section, or a record's summary and detail): every
number in the fact appears in the passage as a whole number, and at least ``COVER`` of its content words appear after
English stemming. One passage must hold the fact; words scattered across a 50-passage packet do not count. Each fact
is first checked against the gold documents' own sections. A fact that this check cannot find there is not counted at
all, since the check cannot see it anywhere else either.

The system's own answer is checked too: the extractive answer by default, or, with ``--assisted``, the answer the
configured model composes (``CIE_LLM_PROVIDER``). A question whose facts all reached the model, but whose answer
misses one or declines, is the model's loss.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

COVER = 0.7
_NUM = re.compile(r"\d[\d,.:/\-]*\d|\d")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "by", "at", "from", "as", "is", "are", "was", "were",
         "be", "been", "it", "its", "this", "that", "these", "those", "which", "who", "what", "when", "where", "how", "has", "have",
         "had", "not", "no", "but", "into", "than", "then", "so", "such", "there", "their", "they", "them", "will", "would", "can",
         "could", "should", "may", "also", "per", "each", "any", "all", "both", "via", "about", "after", "before", "over", "under",
         "between", "including", "include", "includes", "new", "one"}

STAGES = ["search_missed_document", "right_document_wrong_part", "cut_before_model", "everything_reached_model"]


def _stems(text: str) -> set[str]:
    from cie.retrieval.bm25 import analyze

    return set(analyze(text or ""))


def fact_terms(fact: str) -> tuple[list[str], list[str]]:
    """(numbers, stemmed content words) of a fact."""
    from cie.retrieval.bm25 import analyze

    nums = [n.strip(".,:/-") for n in _NUM.findall(fact)]
    words = [w for w in re.findall(r"[A-Za-z][A-Za-z0-9_'.\-]*", fact) if w.lower() not in _STOP and len(w) > 2]
    stems = []
    for w in words:
        for s in analyze(w):
            if s not in stems and s not in _STOP:
                stems.append(s)
    return [n for n in nums if n], stems


def _has_number(n: str, low: str) -> bool:
    return re.search(r"(?<![\d.,])" + re.escape(n.lower()) + r"(?![\d])", low) is not None


def present(fact: str, text: str, stems: set[str] | None = None, cover: float = COVER) -> bool:
    nums, words = fact_terms(fact)
    if not nums and not words:
        return False
    low = (text or "").lower()
    if any(not _has_number(n, low) for n in nums):
        return False
    if not words:
        return True
    stems = stems if stems is not None else _stems(text)
    return sum(1 for w in words if w in stems) / len(words) >= cover


def passages(items: list[dict]) -> list[str]:
    return [f"{it.get('summary', '')}\n{it.get('detail', '')}" for it in items]


def model_view(items: list[dict], budget_chars: int | None) -> list[str]:
    """The passages a model is given, as ``answer.assisted`` sends them: each item cut at 1,500 characters, and, for a
    small-context model, items in rank order up to ``budget_chars``."""
    out, used = [], 0
    for body in passages(items):
        size = min(len(body), 1500) + 120
        if budget_chars and out and used + size > budget_chars:
            break
        out.append(body[:1500])
        used += size
    return out


def present_in_one(fact: str, texts: list[tuple[str, set[str]]]) -> bool:
    return any(present(fact, t, st) for t, st in texts)


def classify(facts: list[str], gold_passages: list[str], packet_docs: list[str], gold_docs: set[str], packet_passages: list[str],
             view_passages: list[str], answer_text: str | None = None) -> dict[str, Any]:
    """The first stage that loses an answer fact, for one question."""
    gold = [(t, _stems(t)) for t in gold_passages]
    stem_of = {t: st for t, st in ((t, _stems(t)) for t in set(packet_passages) | set(view_passages))}
    packet = [(t, stem_of[t]) for t in packet_passages]
    view = [(t, stem_of[t]) for t in view_passages]
    checkable = [f for f in facts if present_in_one(f, gold)]
    in_packet = [f for f in checkable if present_in_one(f, packet)]
    in_view = [f for f in checkable if present_in_one(f, view)]
    out: dict[str, Any] = {"facts": len(facts), "checkable": len(checkable), "in_packet": len(in_packet), "in_model_view": len(in_view),
                           "gold_in_packet": bool(gold_docs & set(packet_docs)), "gold_in_top10": bool(gold_docs & set(packet_docs[:10]))}
    if answer_text is not None:
        a_stems = _stems(answer_text)
        out["in_answer"] = len([f for f in checkable if present(f, answer_text, a_stems)])
    if not checkable:
        out["stage"] = None
    elif not out["gold_in_packet"]:
        out["stage"] = STAGES[0]
    elif len(in_packet) < len(checkable):
        out["stage"] = STAGES[1]
    elif len(in_view) < len(checkable):
        out["stage"] = STAGES[2]
    else:
        out["stage"] = STAGES[3]
    return out


def _half(question_id: str) -> str:
    """``odd`` or ``even`` by the question's number: the development half and the test half."""
    return "odd" if int(re.sub(r"\D", "", question_id) or 0) % 2 else "even"


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    judged = [r for r in rows if r["stage"]]
    stages = Counter(r["stage"] for r in judged)
    out: dict[str, Any] = {"questions": len(rows), "judged": len(judged),
                           "unjudged_no_checkable_fact": len(rows) - len(judged),
                           "stages": {s: stages.get(s, 0) for s in STAGES},
                           "facts": sum(r["facts"] for r in judged), "checkable_facts": sum(r["checkable"] for r in judged),
                           "facts_in_packet": sum(r["in_packet"] for r in judged), "facts_in_model_view": sum(r["in_model_view"] for r in judged)}
    if judged and "answer_chars" in judged[0]:
        out["answer_chars_mean"] = round(sum(r["answer_chars"] for r in judged) / len(judged), 1)
        out["answer_chars_max"] = max(r["answer_chars"] for r in judged)
        out["status"] = dict(Counter(r.get("status") for r in judged))
    if judged and "in_answer" in judged[0]:
        out["facts_in_answer"] = sum(r.get("in_answer", 0) for r in judged)
        out["questions_with_every_fact_in_answer"] = sum(1 for r in judged if r.get("in_answer", 0) == r["checkable"])
        full = [r for r in judged if r["stage"] == STAGES[3]]
        out["everything_reached_model_but_answer_missed_a_fact"] = sum(1 for r in full if r["in_answer"] < r["checkable"])
        out["everything_reached_model_and_answer_had_every_fact"] = sum(1 for r in full if r["in_answer"] == r["checkable"])
        out["everything_reached_model_but_answer_declined"] = sum(1 for r in full if r.get("status") == "insufficient_evidence")
    return out


def run(tenant_name: str, root: Path, out: Path, engine: str | None = None, n: int | None = None, assisted: bool = False,
        expand_documents: int | None = None, half: str | None = None, log=print) -> dict[str, Any]:
    """Ask every question with gold documents against a loaded memory bank and audit where its answer facts go."""
    from sqlalchemy import select, text

    from cie.core.db import session_scope
    from cie.core.models import Document, Principal, Section, Tenant
    from cie.core.settings import get_settings
    from cie.memory.embeddings import get_embedding_provider
    from cie.retrieval.pipeline import Retriever

    settings = get_settings()
    provider = None
    if assisted:
        from cie.agents.providers import get_provider

        provider = get_provider(settings)
        if getattr(provider, "name", "none") == "none":
            raise SystemExit("--assisted needs a model: set CIE_LLM_PROVIDER and CIE_LLM_MODEL")
    budget = getattr(provider, "evidence_budget_chars", None) if provider else settings.llm_local_evidence_chars
    qs = [json.loads(line) for line in (root / "questions.jsonl").read_text().splitlines() if line.strip()]
    qs = [q for q in qs if q["expected_doc_ids"]]
    if half:  # odd or even question numbers: a development half and a test half
        qs = [q for q in qs if _half(q["question_id"]) == half]
    qs = qs[: n or None]
    rows = []
    with session_scope() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == tenant_name))
        if tenant is None:
            raise SystemExit(f"no tenant named {tenant_name!r}")
        admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "admin"))
        company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=tenant.id))
        dsid_of = {str(i): e.get("dsid") for i, e in s.execute(select(Document.id, Document.extra).where(Document.tenant_id == tenant.id))}
        doc_of = {v: uuid.UUID(k) for k, v in dsid_of.items() if v}
        r = Retriever(s, settings, embedder=get_embedding_provider(settings))
        for i, q in enumerate(qs):
            gold = set(q["expected_doc_ids"])
            gold_ids = [doc_of[g] for g in gold if g in doc_of]
            gold_passages = [t or "" for t in s.scalars(select(Section.text).where(Section.document_id.in_(gold_ids)))] if gold_ids else []
            result, res = r.answer(q["question"], admin, company, mode="assisted" if provider else "strict", provider=provider,
                                   lexical_engine=engine, expand_documents=expand_documents)
            items = res.packet.items
            docs: list[str] = []
            for it in items:
                d = dsid_of.get(str(it.get("document_id")))
                if d and d not in docs:
                    docs.append(d)
            row = classify(q["answer_facts"], gold_passages, docs, gold, passages(items), model_view(items, budget), result.answer or "")
            row.update({"question_id": q["question_id"], "category": q["question_type"], "status": result.status,
                        "answer_chars": len(result.answer or "")})
            rows.append(row)
            s.rollback()
            if (i + 1) % 100 == 0:
                log(f"  {i + 1}/{len(qs)} questions")
    report = {"tenant": tenant_name, "engine": engine or settings.lexical_engine, "model_view_chars": budget, "half": half or "all",
              "expand_documents": settings.packet_expand_documents if expand_documents is None else expand_documents,
              "expand_sections": settings.packet_expand_sections,
              "answers": f"composed by {getattr(provider, 'model', '?')}" if provider else "extractive (no model)",
              "fact_cover": COVER, "overall": summarise(rows),
              "by_half": {h: summarise([x for x in rows if _half(x["question_id"]) == h]) for h in ("odd", "even")},
              "by_category": {c: summarise([x for x in rows if x["category"] == c]) for c in sorted({x["category"] for x in rows})}}
    out.mkdir(parents=True, exist_ok=True)
    (out / "evidence_audit.json").write_text(json.dumps(report, indent=2))
    (out / "evidence_audit_rows.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n")
    return report


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", required=True)
    ap.add_argument("--root", required=True, help="the EnterpriseRAG-Bench checkout (questions.jsonl)")
    ap.add_argument("--out", default="eval_out/evidence_audit")
    ap.add_argument("--engine", choices=["fts", "bm25"], default=None)
    ap.add_argument("--questions", type=int, default=None)
    ap.add_argument("--assisted", action="store_true", help="answers composed by the configured model (CIE_LLM_PROVIDER)")
    ap.add_argument("--expand-documents", type=int, default=None, help="document expansion: how many documents (0: off; default: the setting)")
    ap.add_argument("--half", choices=["odd", "even"], default=None, help="only odd or even question numbers")
    a = ap.parse_args(argv)
    rep = run(a.tenant, Path(a.root), Path(a.out), a.engine, a.questions, a.assisted, a.expand_documents, a.half)
    print(json.dumps(rep["overall"], indent=2))
    return rep


if __name__ == "__main__":  # pragma: no cover
    main()
