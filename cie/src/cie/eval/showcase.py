"""A walk-through of the Company Intelligence Engine on a loaded EnterpriseRAG-Bench memory bank, for showing.

**Part A, ask.** Example benchmark questions are asked of the memory bank. Each answer cites the documents it comes
from (source system, title, the quoted words). The benchmark's own expected answer is shown beside it, with how many of
its facts the answer holds (the evidence audit's lexical check). With a model configured (``CIE_LLM_PROVIDER``), the
model composes the answer from the evidence; otherwise the answer quotes the evidence.

The default questions were picked to show the answer path working on different sources and question types. They
are examples, not a measurement: the measured results are in ``docs/BENCHMARKS.md``.

**Part B, answers stay true.** A FICTIONAL, GENERATED set of projects (milestones, orders, suppliers, stock, budgets;
``cie.eval.bench_loop``) is added to the same memory bank. A task asks of every project "Can it deliver every
milestone on time and within budget?", and an analyst answers it from the live records, with findings that cite the
record versions they used. Then a supplier announces a delay. The change is routed to the tasks whose answers used
the delayed order; they are reopened and answered again, and verification checks the new figures before they are
published. Without routing, the old answer would stay published.

Writes ``showcase.json`` and a self-contained ``showcase.html``.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# picked from the 5,000-document memory bank: different sources and question types, answers that hold the facts
DEFAULT_QUESTIONS = ["qst_0044", "qst_0279", "qst_0306", "qst_0436", "qst_0237", "qst_0458"]
DEFAULT_SEED = 409  # a world whose first change is a supplier delay that turns one project's answer from yes to no


def _documents(session, ids: list[str]) -> dict[str, dict]:
    from sqlalchemy import select

    from cie.core.models import Document

    want = [uuid.UUID(i) for i in ids if i]
    if not want:
        return {}
    rows = session.execute(select(Document.id, Document.title, Document.extra).where(Document.id.in_(want))).all()
    return {str(i): {"title": t, "source": (e or {}).get("source") or "document"} for i, t, e in rows}


def ask(session, retriever, admin, company_id, q: dict, provider=None) -> dict[str, Any]:
    """One question through the whole answer path; the record of what was asked, answered and cited."""
    from cie.eval.evidence_audit import present

    t0 = time.perf_counter()
    result, res = retriever.answer(q["question"], admin, company_id, mode="assisted" if provider else "strict", provider=provider)
    ms = (time.perf_counter() - t0) * 1000
    docs = _documents(session, [c.get("document_id") for c in result.citations])
    cites = []
    for c in result.citations:
        d = docs.get(str(c.get("document_id")), {})
        cites.append({"n": c["n"], "source": d.get("source", "document"), "title": d.get("title") or c.get("summary") or "",
                      "quote": re.sub(r"\s+", " ", c.get("quote") or "").strip()[:240]})
    facts = q.get("answer_facts") or []
    found = [f for f in facts if present(f, result.answer or "")]
    session.rollback()
    return {"question_id": q["question_id"], "question": q["question"], "type": q.get("question_type"), "answer": result.answer,
            "status": result.status, "mode": result.mode, "model": result.model, "citations": cites, "expected": q.get("gold_answer"),
            "facts": len(facts), "facts_found": len(found), "seconds": round(ms / 1000, 2),
            "evidence_items": len(res.packet.items), "documents_in_evidence": len({it.get("document_id") for it in res.packet.items})}


def ask_question(tenant_name: str, question: str) -> dict[str, Any]:
    """Any question, asked of a loaded memory bank, with the configured model (or quotes without one)."""
    from sqlalchemy import select, text

    from cie.core.db import session_scope
    from cie.core.models import Principal, Tenant
    from cie.core.settings import get_settings
    from cie.memory.embeddings import get_embedding_provider
    from cie.retrieval.pipeline import Retriever

    settings = get_settings()
    provider = _provider(settings)
    with session_scope() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == tenant_name))
        if tenant is None:
            raise SystemExit(f"no tenant named {tenant_name!r}")
        admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "admin"))
        company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=tenant.id))
        r = Retriever(s, settings, embedder=get_embedding_provider(settings))
        return ask(s, r, admin, company, {"question_id": "yours", "question": question, "question_type": "your question"}, provider)


def _provider(settings):
    """The configured model, or None (answers quote the evidence)."""
    if settings.llm_provider in (None, "", "none"):
        return None
    from cie.agents.providers import NoProvider, get_provider

    p = get_provider(settings)
    return None if isinstance(p, NoProvider) else p


def change_story(factory, host_name: str, embedder, settings, seed: int = DEFAULT_SEED, run_tag: str | None = None,
                 log=print) -> dict[str, Any]:
    """Part B: a fictional world in the memory bank, its project tasks answered, then the first supplier delay that
    turns a project's answer from yes to no, routed and answered again."""
    from cie.core.models import Task
    from cie.eval.bench_loop import LoopWorld, Run

    tag = run_tag or f"show{uuid.uuid4().hex[:5]}"
    probe = LoopWorld(seed, 20)
    pick = None
    for j, ev in enumerate(probe.events):
        if ev["kind"] != "supplier_delay":
            continue
        flips = [pk for pk in probe.base.projects if probe.oracle(j, pk)["feasible"] and not probe.oracle(j + 1, pk)["feasible"]]
        if flips:
            pick = (j, flips[0])
            break
    if pick is None:
        raise SystemExit(f"world {seed} has no supplier delay that turns a project's answer: choose another --seed")
    j, pk = pick
    lw = LoopWorld(seed, j + 1, tag=tag)  # the world up to and including that change
    with factory() as s:
        r = Run(s, lw, "loop-relied", host_name, embedder, settings)
        log(f"  fictional projects loaded into {host_name}: {len(lw.base.projects)} projects, {r.docs} documents")
        t0 = time.perf_counter()
        r.start()
        first_answers_s = time.perf_counter() - t0
        for k in range(j):  # earlier changes, applied as they came
            r.apply(k, lw.events[k])
        task_id = r.tasks[pk]
        before = dict(s.get(Task, task_id).result or {})
        routed0, affected0 = r.c["routed"], r.c["affected"]
        ev = lw.events[j]
        r.apply(j, ev)
        s.commit()
        after = dict(s.get(Task, task_id).result or {})
        clean = lambda t: re.sub(rf"\s*\[{tag}\]|{tag}-", "", t or "")  # noqa: E731 - the run's tag keeps worlds apart, not for reading
        name = lw.base.projects[pk]["name"]
        task_title = clean(s.get(Task, task_id).title)
        raw = lw.events[j]["payload"]
        notice = next((op.get("summary") for op in raw.get("ops", []) if op.get("type") == "passage"), None)
        orders = sorted({op["dst"][1] for op in raw.get("ops", []) if op.get("op") == "upsert_edge" and op.get("dst", [None])[0] == "order"})
        oracle_before, oracle_after = lw.oracle(j, pk), lw.oracle(j + 1, pk)
        out = {
            "label": "FICTIONAL, GENERATED project data", "seed": seed, "projects": len(lw.base.projects), "project": name,
            "task": task_title, "first_answers_seconds": round(first_answers_s, 1),
            "before": {"summary": clean(before.get("summary")), "claims": [clean(f["claim"]) for f in before.get("findings", [])],
                       "matches_expected": r._same(before["answer"], oracle_before) if before.get("answer") else False},
            "change": {"kind": "supplier delay", "notice": notice, "supplier": lw.base.suppliers.get(raw.get("supplier"), raw.get("supplier")),
                       "product": lw.base.products.get(raw.get("product"), raw.get("product")), "new_date": str(raw.get("new_date"))[:10],
                       "orders": orders},
            "after": {"summary": clean(after.get("summary")), "claims": [clean(f["claim"]) for f in after.get("findings", [])],
                      "matches_expected": r._same(after["answer"], oracle_after) if after.get("answer") else False},
            "tasks_reopened": r.c["routed"] - routed0, "projects_affected": r.c["affected"] - affected0,
            "projects_missed": r.c["missed"], "change_to_refreshed_answer_seconds": round(r.m["reaction_ms"][-1] / 1000, 2),
            "without_routing": clean(before.get("summary")),
        }
        s.commit()
    return out


# ------------------------------------------------------------------------------------------------ html
_CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--card:#ffffff;--line:#e4e2dc;--accent:#2f5bd3;--good:#1f7a4d;--bad:#b3261e;--chip:#eef1fb}
@media (prefers-color-scheme: dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#a3a29c;--card:#1d1d1b;--line:#33332f;--accent:#8aa8ff;--good:#6fd39f;--bad:#ff8a80;--chip:#232838}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:36px 0 6px}
.sub{color:var(--muted);margin:0 0 18px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}
.q{font-weight:600;margin:0 0 8px}.meta{color:var(--muted);font-size:13px}.ans{white-space:pre-wrap;margin:8px 0}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 9px;font-size:12px;margin-right:6px;color:var(--fg)}
ol.src{margin:6px 0 0 18px;padding:0;font-size:13.5px}ol.src li{margin:3px 0}.src .t{font-weight:600}.src .qt{color:var(--muted)}
details{margin-top:8px}summary{cursor:pointer;color:var(--accent);font-size:13.5px}.good{color:var(--good);font-weight:600}.bad{color:var(--bad);font-weight:600}
.flow{display:grid;grid-template-columns:1fr;gap:10px}.step{border-left:3px solid var(--line);padding:6px 0 6px 14px}.step.now{border-color:var(--accent)}
.kpi{display:flex;flex-wrap:wrap;gap:10px;margin:10px 0}.kpi div{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13px}
.kpi b{display:block;font-size:18px}.note{color:var(--muted);font-size:13px}
"""


def _e(x: Any) -> str:
    return html.escape(str(x if x is not None else ""))


def to_html(rep: dict[str, Any]) -> str:
    a = rep.get("ask", [])
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Company brain showcase</title><style>{_CSS}</style></head><body><main>",
             "<h1>Company brain: ask, cite, stay true</h1>",
             f"<p class='sub'>Memory bank <b>{_e(rep['tenant'])}</b>: {rep['documents']:,} documents from EnterpriseRAG-Bench "
             f"(Slack, Gmail, Drive, Linear, GitHub, Jira, HubSpot, Confluence, Fireflies). Answers: {_e(rep['answers'])}. "
             f"Run {_e(rep['at'])}.</p>"]
    if a:
        found = sum(x["facts_found"] for x in a)
        total = sum(x["facts"] for x in a)
        secs = sorted(x["seconds"] for x in a)
        parts.append("<h2>A. Ask the company's documents</h2><p class='sub'>Example questions from the benchmark. Every answer "
                     "cites where it comes from; the benchmark's expected answer is below it.</p>"
                     f"<div class='kpi'><div><b>{len(a)}</b>questions</div><div><b>{found} of {total}</b>expected facts in the answers</div>"
                     f"<div><b>{secs[len(secs) // 2]:.1f} s</b>median time per answer</div></div>")
        for x in a:
            ok = x["facts"] and x["facts_found"] == x["facts"]
            docs = list(dict.fromkeys((c["source"], c["title"]) for c in x["citations"]))  # one line per document
            src = "".join(f"<li><span class='chip'>{_e(sc)}</span><span class='t'>{_e(t)}</span></li>"
                          for sc, t in docs)  # the answer itself quotes the words; the list names the documents
            parts.append(f"<div class='card'><p class='q'>{_e(x['question'])}</p>"
                         f"<div class='meta'><span class='chip'>{_e(x['type'])}</span>{x['seconds']:.1f} s · "
                         f"{x['documents_in_evidence']} documents in the evidence · <span class='{'good' if ok else 'bad'}'>"
                         f"{x['facts_found']} of {x['facts']} expected facts</span></div>"
                         f"<div class='ans'>{_e(x['answer'])}</div><ol class='src'>{src}</ol>"
                         f"<details><summary>The benchmark's expected answer</summary><p>{_e(x['expected'])}</p></details></div>")
    b = rep.get("change")
    if b:
        parts.append("<h2>B. Answers stay true when the company changes</h2>"
                     f"<p class='sub'>{_e(b['label'])}: {b['projects']} projects added to the same memory bank. A task asks of each: "
                     "can it deliver every milestone on time and within budget?</p>"
                     f"<div class='flow'><div class='step'><div class='meta'>Before</div><p class='q'>{_e(b['task'])}</p>"
                     f"<p>{_e(b['before']['summary'])} <span class='{'good' if b['before']['matches_expected'] else 'bad'}'>"
                     f"({'matches' if b['before']['matches_expected'] else 'does not match'} the expected answer)</span></p></div>"
                     f"<div class='step now'><div class='meta'>A change arrives: an email from the supplier</div>"
                     f"<p>{_e(b['change']['notice'] or (str(b['change']['supplier']) + ' delays ' + str(b['change']['product'])))}</p>"
                     f"<p class='meta'>It touches {len(b['change']['orders'])} open purchase orders: {_e(', '.join(b['change']['orders']))}</p></div>"
                     f"<div class='step now'><div class='meta'>Routed in {b['change_to_refreshed_answer_seconds']:.1f} s: "
                     f"{b['tasks_reopened']} task(s) reopened, {b['projects_missed']} missed</div>"
                     f"<p>{_e(b['after']['summary'])} <span class='{'good' if b['after']['matches_expected'] else 'bad'}'>"
                     f"({'matches' if b['after']['matches_expected'] else 'does not match'} the expected answer)</span></p>"
                     + "".join(f"<p class='meta'>• {_e(c)}</p>" for c in b["after"]["claims"] if "at risk" in c) +
                     f"</div><div class='step'><div class='meta'>Without change routing</div><p>The published answer would still say: "
                     f"<span class='bad'>{_e(b['without_routing'])}</span></p></div></div>")
    m = rep.get("measured")
    if m:
        parts.append("<h2>Measured, not picked</h2><div class='kpi'>" + "".join(f"<div><b>{_e(v)}</b>{_e(k)}</div>" for k, v in m.items())
                     + "</div><p class='note'>Pre-registered tests on the 5,000-document memory bank; details in the repository's docs.</p>")
    parts.append("</main></body></html>")
    return "".join(parts)


MEASURED_5K = {  # pre-registered tests on the local 5,000-document memory bank (docs/*_RESULTS.md, docs/benchmarks)
    "answer documents in the top 10": "88%",
    "questions where every answer fact reaches the model": "72%",
    "answer facts in the evidence-only answer": "2.7x the old answer",
    "stale answers served after 60 changes": "0 (410 without routing)",
    "affected projects reached by a change": "119 of 119",
    "search time, p95": "0.9 s",
}


def run(tenant_name: str, root: Path, out: Path, question_ids: list[str] | None = None, seed: int = DEFAULT_SEED,
        change: bool = True, log=print) -> dict[str, Any]:
    from sqlalchemy import func, select, text

    from cie.core.db import session_scope
    from cie.core.models import Document, Principal, Tenant
    from cie.core.settings import get_settings
    from cie.memory.embeddings import get_embedding_provider
    from cie.retrieval.pipeline import Retriever

    settings = get_settings()
    provider = _provider(settings)
    embedder = get_embedding_provider(settings)
    qs = {json.loads(x)["question_id"]: json.loads(x) for x in (root / "questions.jsonl").read_text().splitlines() if x.strip()}
    ids = question_ids or DEFAULT_QUESTIONS
    rep: dict[str, Any] = {"tenant": tenant_name, "at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                           "answers": f"composed by {getattr(provider, 'model', 'a model')} from the evidence" if provider
                           else "quoted from the evidence (no model)", "ask": [], "measured": MEASURED_5K}
    with session_scope() as s:
        tenant = s.scalar(select(Tenant).where(Tenant.name == tenant_name))
        if tenant is None:
            raise SystemExit(f"no tenant named {tenant_name!r}")
        rep["documents"] = s.scalar(select(func.count()).select_from(Document).where(Document.tenant_id == tenant.id))
        admin = s.scalar(select(Principal).where(Principal.tenant_id == tenant.id, Principal.name == "admin"))
        company = s.scalar(select(text("id")).select_from(text("scopes")).where(text("tenant_id = :t AND parent_id IS NULL")).params(t=tenant.id))
        retriever = Retriever(s, settings, embedder=embedder)
        retriever.answer("warm up", admin, company)  # the first question would otherwise pay for loading the models
        s.rollback()
        log("A. ask")
        for qid in ids:
            if qid not in qs:
                log(f"  {qid}: not in the benchmark's questions; skipped")
                continue
            x = ask(s, retriever, admin, company, qs[qid], provider)
            rep["ask"].append(x)
            log(f"  {qid} ({x['type']}): {x['facts_found']} of {x['facts']} expected facts, {x['seconds']:.1f} s, "
                f"{len(x['citations'])} sources\n    Q: {x['question']}\n    A: {(x['answer'] or '')[:400]}")
    if change:
        log("B. answers stay true (FICTIONAL, GENERATED projects)")
        rep["change"] = change_story(session_scope, tenant_name, embedder, settings, seed=seed, log=log)
        c = rep["change"]
        log(f"  before: {c['before']['summary']}\n  change: {c['change']['notice']}\n  after ({c['change_to_refreshed_answer_seconds']} s, {c['tasks_reopened']} task(s) reopened): "
            f"{c['after']['summary']}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "showcase.json").write_text(json.dumps(rep, indent=2, default=str))
    (out / "showcase.html").write_text(to_html(rep))
    log(f"wrote {out / 'showcase.html'}")
    return rep


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tenant", required=True, help="a loaded EnterpriseRAG-Bench memory bank (load.json names it)")
    ap.add_argument("--root", required=True, help="the EnterpriseRAG-Bench checkout (questions.jsonl)")
    ap.add_argument("--out", default="eval_out/showcase")
    ap.add_argument("--questions", default=None, help="comma-separated question ids (default: the examples above)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="the fictional world for part B")
    ap.add_argument("--no-change", action="store_true", help="part A only")
    a = ap.parse_args(argv)
    ids = [x.strip() for x in a.questions.split(",") if x.strip()] if a.questions else None
    return run(a.tenant, Path(a.root), Path(a.out), ids, a.seed, not a.no_change)


if __name__ == "__main__":  # pragma: no cover
    main()
