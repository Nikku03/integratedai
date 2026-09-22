"""Multi-agent simulation: five specialists under one head on a synthetic
project with planted contradictions and a restricted document.

Produces ``simulation.json`` and ``simulation.md`` with: task DAG, routing
explanations, messages by kind, verification verdicts, contradictions found,
token/latency/cost per agent, and the final synthesis. Deterministic
(extractive strategies, no LLM) unless CIE_LLM_PROVIDER is configured.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from cie.agents import ledger
from cie.agents.head import HeadAgent, create_project
from cie.agents.providers import get_provider
from cie.agents.registry import ensure_default_agents
from cie.core.db import session_scope
from cie.core.models import (
    Agent,
    AgentMessage,
    Metric,
    Permission,
    Principal,
    PrincipalKind,
    RecordType,
    ScopeKind,
    Task,
    Tenant,
)
from cie.extraction.pipeline import run_extraction
from cie.governance.permissions import ensure_role, grant_role
from cie.memory.embeddings import get_embedding_provider
from cie.memory.records import contradict, create_record
from cie.memory.scopes import create_scope
from cie.vault.service import VaultService


def _pdf():
    from cie.eval.synth import CONTRACT_SECTIONS, make_pdf  # reuse the synthetic contract

    amended = CONTRACT_SECTIONS[:3] + [("3. Fees", ["3.1 The Supplier shall be paid a monthly fee of USD 140,000 for the Services after Amendment 1.",
                                                    "3.2 The total fees under this Agreement shall not exceed $4,500,000."])] + CONTRACT_SECTIONS[4:]
    return make_pdf(CONTRACT_SECTIONS), make_pdf(amended)


def run_simulation(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    embedder = get_embedding_provider()
    provider = get_provider()
    with session_scope() as s:
        tenant = Tenant(name=f"sim-{int(time.time())}")
        s.add(tenant)
        s.flush()
        company = create_scope(s, tenant.id, ScopeKind.company, "SimCo")
        legal = create_scope(s, tenant.id, ScopeKind.department, "Legal", company)
        admin = Principal(tenant_id=tenant.id, kind=PrincipalKind.user, name="sim-admin")
        s.add(admin)
        s.flush()
        grant_role(s, tenant_id=tenant.id, principal=admin, role=ensure_role(s, tenant.id, "admin", Permission.admin, 4), scope=company)
        ensure_default_agents(s, tenant.id, company)
        project = create_project(s, tenant_id=tenant.id, parent_scope=legal, name="Northwind renegotiation")
        vault = VaultService()
        v1, v2 = _pdf()
        d1 = vault.ingest(s, tenant_id=tenant.id, data=v1, filename="msa_v1.pdf", scope_id=project.scope_id, doc_type="contract",
                          file_created_at=datetime(2025, 1, 15, tzinfo=UTC)).document
        d2 = vault.ingest(s, tenant_id=tenant.id, data=v2, filename="msa_v2.pdf", scope_id=project.scope_id, doc_type="contract",
                          family_id=d1.family_id, file_created_at=datetime(2025, 9, 1, tzinfo=UTC)).document
        s.commit()
        for d in (d1, d2):
            run_extraction(s, d, vault=vault, embedder=embedder, ocr=None)
        # planted contradiction from an email vs the contract, and a restricted record agents must not see
        a = create_record(s, tenant_id=tenant.id, scope_id=project.scope_id, type=RecordType.deadline, summary="Termination notice period is 90 days",
                          content={"days": 90}, detail="Termination requires 90 days written notice.", source_document_id=d1.id,
                          source_locations=[{"page_no": 3, "quote": "ninety (90) days written notice"}], keywords=["notice", "termination"], embedder=embedder)
        b = create_record(s, tenant_id=tenant.id, scope_id=project.scope_id, type=RecordType.deadline, summary="Termination notice period is 60 days",
                          content={"days": 60}, detail="Supplier email says 60 days notice suffices.", keywords=["notice", "termination"], embedder=embedder)
        contradict(s, a, b, "contract says 90 days, supplier email says 60")
        create_record(s, tenant_id=tenant.id, scope_id=project.scope_id, type=RecordType.fact, summary="Board-restricted walk-away price USD 3,900,000",
                      content={"value": 3900000}, detail="restricted", sensitivity=4, keywords=["walk-away", "price"], embedder=embedder)
        s.commit()
        head = HeadAgent(s, project, embedder=embedder, provider=provider if provider.name != "none" else None)
        objective = ("Plan the renegotiation of the Northwind master services agreement: termination notice and liability clauses, "
                     "monthly fee and penalty exposure, a timeline for the transition and the warehouse automation integration requirements")
        head.start(objective)
        state = head.run(max_steps=20)
        s.commit()
        tasks = list(s.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.created_at)))
        names = {a_.id: a_.name for a_ in s.scalars(select(Agent).where(Agent.tenant_id == tenant.id))}
        msgs = s.execute(select(AgentMessage.kind, func.count(), func.sum(AgentMessage.token_estimate)).where(AgentMessage.project_id == project.id)
                         .group_by(AgentMessage.kind)).all()
        per_agent = {}
        for t in tasks:
            if t.assigned_agent_id and t.metrics:
                pa = per_agent.setdefault(names[t.assigned_agent_id], {"tasks": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0, "cost_usd": 0.0, "packet_items": 0})
                pa["tasks"] += 1
                pa["tokens_in"] += int(t.metrics.get("tokens_in", 0))
                pa["tokens_out"] += int(t.metrics.get("tokens_out", 0))
                pa["latency_ms"] += float(t.metrics.get("latency_ms", 0))
                pa["cost_usd"] += float(t.metrics.get("cost_usd", 0))
                pa["packet_items"] += int(t.metrics.get("packet_items", 0))
        leaked = any("3,900,000" in json.dumps(t.result or {}) for t in tasks)
        report = {
            "objective": objective, "strategy": head.strategy.name, "provider": provider.name, "embedding": getattr(embedder, "name", "?"),
            "wall_seconds": round(time.perf_counter() - t_start, 2),
            "tasks": [{"type": t.task_type, "title": t.title, "status": t.status.value, "agent": names.get(t.assigned_agent_id),
                       "risk": t.risk_level, "decision": (t.assignment_reason or {}).get("decision"),
                       "findings": len((t.result or {}).get("findings", [])), "verification": (t.verification or {}).get("score"),
                       "packet_items": (t.metrics or {}).get("packet_items"), "tokens": int((t.metrics or {}).get("tokens_in", 0)) + int((t.metrics or {}).get("tokens_out", 0))}
                      for t in tasks],
            "messages": [{"kind": k.value, "count": int(c), "tokens": int(tok or 0)} for k, c, tok in msgs],
            "per_agent": per_agent,
            "contradictions_recorded": len(state["contradictions"]),
            "verifications": state["verifications"],
            "restricted_record_leaked_to_agents": leaked,
            "ledger_entries": state["entries"], "ledger_chain_valid": ledger.verify_chain(s, project.id)[0],
            "synthesis": state["synthesis"],
            "metrics_rows": s.scalar(select(func.count(Metric.id)).where(Metric.tenant_id == tenant.id)),
        }
    (out_dir / "simulation.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out_dir / "simulation.md").write_text(md)
    print(md)
    return report


def to_markdown(r: dict) -> str:
    lines = [f"### Multi-agent simulation ({r['strategy']} strategy, provider={r['provider']}, embeddings={r['embedding']}, {r['wall_seconds']}s)", "",
             f"Objective: {r['objective']}", "", "| task | agent | risk | status | findings | verification | packet items | tokens | routing decision |", "|---|---|---|---|---|---|---|---|---|"]
    for t in r["tasks"]:
        lines.append(f"| {t['type']} | {t['agent']} | {t['risk']} | {t['status']} | {t['findings']} | {t['verification']} | {t['packet_items']} | {t['tokens']} | {(t['decision'] or '')[:90]} |")
    lines += ["", "| message kind | count | tokens |", "|---|---|---|"] + [f"| {m['kind']} | {m['count']} | {m['tokens']} |" for m in r["messages"]]
    lines += ["", "| agent | tasks | tokens in | tokens out | latency ms | cost USD |", "|---|---|---|---|---|---|"]
    for a, v in r["per_agent"].items():
        lines.append(f"| {a} | {v['tasks']} | {v['tokens_in']} | {v['tokens_out']} | {v['latency_ms']:.0f} | {v['cost_usd']:.4f} |")
    lines += ["", f"Contradictions recorded in ledger: {r['contradictions_recorded']}. Ledger entries: {r['ledger_entries']} (chain valid: {r['ledger_chain_valid']}).",
              f"Restricted record leaked to agents: **{r['restricted_record_leaked_to_agents']}**.", "",
              f"Synthesis confidence: {r['synthesis']['confidence'] if r['synthesis'] else 'n/a'}; uncertainty items: "
              f"{len(r['synthesis']['uncertainty']) if r['synthesis'] else 0}; citations: {len(r['synthesis']['citations']) if r['synthesis'] else 0}."]
    return "\n".join(lines)
