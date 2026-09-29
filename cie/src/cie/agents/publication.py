"""The publication gate: an agent's findings reach shared project memory only after verification.

1. **Stage.** While a task runs, its findings are written to the agent's workspace for that project: a scope of
   kind ``agent`` under the project, so project readers can inspect it but default retrieval does not address it
   (``cie.memory.scopes.addressable_scope_ids``). Workspace records are ``unverified`` and carry the highest
   clearance of the records they cite, never lower.
2. **Publish.** When the task completes, each finding is published to the project scope only if it passed
   verification: the reviewing agent's verdict when there was one, a person's approval, or otherwise a
   verification run at publication. A published record is ``verified``, names who verified it and by which
   methods, and links back to its workspace record. A finding that fails stays in the workspace, marked blocked,
   with the reasons.
3. **Withdraw.** When a completed task is reopened because an input changed, its published findings are marked
   ``disputed`` with the reason, until the task completes again and republishes.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import (
    Agent,
    LinkKind,
    MemoryRecord,
    Permission,
    Principal,
    Project,
    RecordType,
    Scope,
    ScopeKind,
    Task,
    TaskStatus,
    VerificationStatus,
)
from cie.memory.records import create_record, link


def workspace_scope(session: Session, agent: Agent, project: Project) -> Scope:
    """The agent's workspace in this project (created on first use); the agent may write it."""
    from cie.governance.permissions import ensure_role, grant_role
    from cie.memory.scopes import create_scope

    parent = session.get(Scope, project.scope_id)
    name = f"agent:{agent.name}@{project.id.hex[:8]}"
    scope = session.scalar(select(Scope).where(Scope.tenant_id == project.tenant_id, Scope.parent_id == parent.id, Scope.name == name))
    if scope is None:
        scope = create_scope(session, project.tenant_id, ScopeKind.agent, name, parent)
        grant_role(session, tenant_id=project.tenant_id, principal=session.get(Principal, agent.principal_id),
                   role=ensure_role(session, project.tenant_id, "agent_writer", Permission.write, 2), scope=scope)
    return scope


def _clearance(session: Session, citations: list[dict[str, Any]]) -> int:
    ids = []
    for c in citations or []:
        try:
            ids.append(uuid.UUID(str(c.get("item_id"))))
        except ValueError:
            continue
    if not ids:
        return 1
    return max([r.sensitivity for r in session.scalars(select(MemoryRecord).where(MemoryRecord.id.in_(ids)))] or [1])


def stage(session: Session, task: Task, agent: Agent, project: Project, result: dict[str, Any], *, embedder=None,
          limit: int = 8) -> list[MemoryRecord]:
    ws = workspace_scope(session, agent, project)
    out = []
    for i, f in enumerate((result.get("findings") or [])[:limit]):
        cites = f.get("citations") or []
        doc = cites[0].get("document_id") if cites else None
        out.append(create_record(
            session, tenant_id=project.tenant_id, scope_id=ws.id, type=RecordType.result, summary=f"[{agent.name}] {f['claim'][:160]}",
            content={"task_id": str(task.id), "finding": i, "task_revision": task.revision, "kind": f.get("kind"), "value": f.get("value"),
                     "stage": "workspace"},
            detail=f["claim"], source_document_id=uuid.UUID(doc) if doc else None, source_locations=cites, producing_agent=agent.name,
            confidence=float(f.get("confidence", 0.5)), sensitivity=_clearance(session, cites), embedder=embedder, dedup=False))
    return out


def _staged(session: Session, task: Task) -> list[MemoryRecord]:
    rows = session.scalars(select(MemoryRecord).join(Scope, Scope.id == MemoryRecord.scope_id).where(
        MemoryRecord.tenant_id == task.tenant_id, Scope.kind == ScopeKind.agent, MemoryRecord.type == RecordType.result,
        MemoryRecord.deleted_at.is_(None), MemoryRecord.content["task_id"].astext == str(task.id)))
    latest: dict[int, MemoryRecord] = {}

    def when(r: MemoryRecord) -> tuple:
        return (int((r.content or {}).get("task_revision", 0)), r.recorded_at)

    for r in rows:  # a re-run stages again: the latest staging of each finding counts
        i = int((r.content or {}).get("finding", -1))
        if i not in latest or when(r) >= when(latest[i]):
            latest[i] = r
    return [latest[i] for i in sorted(latest)]


def publish(session: Session, task: Task, *, verifier: str, reader=None, embedder=None, human: bool = False) -> dict[str, Any]:
    """Publish the verified findings of a completed task to its project scope."""
    from cie.agents.verification import verify_result

    if task.status != TaskStatus.completed:
        raise ValueError("only a completed task's findings are published")
    project = session.get(Project, task.project_id)
    findings = (task.result or {}).get("findings") or []
    review = task.verification or {}
    reviewed = {d.get("claim"): d for d in review.get("details", [])} if review.get("by") else {}
    published, blocked = [], []
    for ws in _staged(session, task):
        i = int(ws.content.get("finding", -1))
        if (ws.content or {}).get("publication", {}).get("status") == "published" or not 0 <= i < len(findings):
            continue
        f = findings[i]
        if human:
            detail, by = {"status": "verified", "reasons": [], "methods": ["human"]}, verifier
        elif f.get("claim") in reviewed:
            detail, by = reviewed[f["claim"]], review.get("by", verifier)
        else:
            detail, by = verify_result(session, {"findings": [f]}, reader=reader).details[0], verifier
        if detail["status"] != "verified":
            ws.content = {**ws.content, "publication": {"status": "blocked", "reasons": detail.get("reasons", []), "by": by}}
            blocked.append(str(ws.id))
            continue
        rec = create_record(
            session, tenant_id=task.tenant_id, scope_id=project.scope_id, type=RecordType.result, summary=ws.summary,
            content={"task_id": str(task.id), "finding": i, "kind": f.get("kind"), "value": f.get("value"), "workspace_record_id": str(ws.id),
                     "verified_by": by, "methods": detail.get("methods", []), "task_revision": task.revision},
            detail=ws.detail, source_document_id=ws.source_document_id, source_locations=ws.source_locations,
            producing_agent=ws.producing_agent, confidence=ws.confidence, verification=VerificationStatus.verified,
            sensitivity=ws.sensitivity, embedder=embedder, dedup=False)
        link(session, rec, ws, LinkKind.derived_from)
        for old in session.scalars(select(MemoryRecord).where(  # an earlier publication of this finding, withdrawn on reopening
                MemoryRecord.tenant_id == task.tenant_id, MemoryRecord.scope_id == project.scope_id, MemoryRecord.id != rec.id,
                MemoryRecord.superseded_by_id.is_(None), MemoryRecord.content["task_id"].astext == str(task.id),
                MemoryRecord.content["finding"].astext == str(i), MemoryRecord.content.has_key("workspace_record_id"))):
            old.superseded_by_id = rec.id
        ws.content = {**ws.content, "publication": {"status": "published", "record_id": str(rec.id), "by": by}}
        published.append(str(rec.id))
    session.flush()
    return {"published": published, "blocked": blocked}


def withdraw(session: Session, task_id: uuid.UUID, reason: str) -> int:
    """A reopened task's published findings are disputed until it completes and publishes again."""
    n = 0
    for r in session.scalars(select(MemoryRecord).join(Scope, Scope.id == MemoryRecord.scope_id).where(
            Scope.kind != ScopeKind.agent, MemoryRecord.type == RecordType.result, MemoryRecord.deleted_at.is_(None),
            MemoryRecord.verification == VerificationStatus.verified, MemoryRecord.content["task_id"].astext == str(task_id),
            MemoryRecord.content.has_key("workspace_record_id"))):
        r.verification = VerificationStatus.disputed
        r.content = {**(r.content or {}), "withdrawn": reason[:500]}
        n += 1
    session.flush()
    return n
