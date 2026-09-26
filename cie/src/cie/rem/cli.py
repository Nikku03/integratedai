"""``cie rem ...`` commands: ingest, query, change, replay, demo, bench."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select


def _tenant(s, name: str, create: bool = False):
    from cie.core.models import Tenant

    t = s.scalar(select(Tenant).where(Tenant.name == name))
    if t is None and create:
        t = Tenant(name=name)
        s.add(t)
        s.flush()
    if t is None:
        raise SystemExit(f"unknown tenant {name!r}")
    return t


def ingest(args) -> dict[str, Any]:
    from cie.core.db import session_scope
    from cie.memory.embeddings import get_embedding_provider
    from cie.rem.ingest import ingest_bundle
    from cie.vault.service import VaultService

    bundle = json.loads(Path(args.bundle).read_text())
    with session_scope() as s:
        t = _tenant(s, args.tenant, create=True)
        return ingest_bundle(s, t.id, bundle, vault=VaultService(), embedder=get_embedding_provider(), name=Path(args.bundle).stem)


def query(args) -> dict[str, Any]:
    from cie.core.db import session_scope
    from cie.core.models import Principal
    from cie.governance.permissions import visible_scopes
    from cie.memory.embeddings import get_embedding_provider
    from cie.rem.query import QueryRequest, run_query

    with session_scope() as s:
        t = _tenant(s, args.tenant)
        p = s.scalar(select(Principal).where(Principal.tenant_id == t.id, Principal.name == args.principal))
        if p is None:
            raise SystemExit(f"unknown principal {args.principal!r}")
        req = QueryRequest(question=args.question, policy=args.policy, limits=json.loads(args.limits),
                           project_keys=[x for x in args.projects.split(",") if x])
        return run_query(s, t.id, visible_scopes(s, p), req, embedder=get_embedding_provider(), principal_id=p.id)


def change(args) -> dict[str, Any]:
    from cie.core.db import session_scope
    from cie.memory.embeddings import get_embedding_provider
    from cie.rem.change import process_event, submit_event
    from cie.workers import queue

    payload = json.loads(Path(args.payload).read_text())
    with session_scope() as s:
        t = _tenant(s, args.tenant)
        ev, created = submit_event(s, t.id, kind=args.kind, payload=payload, idempotency_key=args.key)
        if not created:
            return {"event_id": str(ev.id), "created": False, "status": ev.status}
        if args.queue:
            job = queue.enqueue(s, t.id, "rem_change", {"event_id": str(ev.id)})
            return {"event_id": str(ev.id), "created": True, "job_id": str(job.id)}
        return {"event_id": str(ev.id), "created": True, **process_event(s, ev.id, embedder=get_embedding_provider())}


def replay(args) -> dict[str, Any]:
    """Re-apply every processed event of a tenant, in sequence order, into a fresh tenant with the same scope tree,
    and compare each event's impacts by (target key, impact, rule). Identical output means processing is deterministic."""
    from cie.core.db import session_scope
    from cie.core.models import Scope
    from cie.memory.embeddings import get_embedding_provider
    from cie.rem.change import process_event, submit_event
    from cie.rem.models import RemEvent, RemImpact, RemNode

    with session_scope() as s:
        src = _tenant(s, args.tenant)
        dst = _tenant(s, args.into or f"{args.tenant}-replay-{uuid.uuid4().hex[:6]}", create=True)
        scopes = s.scalars(select(Scope).where(Scope.tenant_id == src.id)).all()
        by_id = {sc.id: sc for sc in scopes}
        made: dict[uuid.UUID, Scope] = {}

        def clone(sc: Scope):
            if sc.id in made:
                return made[sc.id]
            from cie.memory.scopes import create_scope

            parent = clone(by_id[sc.parent_id]) if sc.parent_id else None
            made[sc.id] = create_scope(s, dst.id, sc.kind, sc.name, parent)
            return made[sc.id]

        for sc in scopes:
            clone(sc)
        emb = get_embedding_provider()
        diffs, n = [], 0
        for ev in s.scalars(select(RemEvent).where(RemEvent.tenant_id == src.id, RemEvent.status == "done").order_by(RemEvent.seq)):
            new, _ = submit_event(s, dst.id, kind=ev.kind, payload=ev.payload, idempotency_key=ev.idempotency_key)
            process_event(s, new.id, embedder=emb)
            n += 1

            def keyed(event_id):
                rows = s.execute(select(RemNode.type, RemNode.key, RemImpact.impact, RemImpact.rule_id)
                                 .join(RemNode, RemNode.id == RemImpact.target_id).where(RemImpact.event_id == event_id)).all()
                return sorted(tuple(r) for r in rows)

            a, b = keyed(ev.id), keyed(new.id)
            if a != b:
                diffs.append({"event": ev.idempotency_key, "original": a, "replayed": b})
        return {"source": src.name, "replayed_into": dst.name, "events": n, "identical": not diffs, "differences": diffs}


def demo(args) -> None:
    from cie.eval import rem_demo

    raise SystemExit(rem_demo.main(["--out", args.out]))


def bench(args) -> None:
    from cie.eval import bench_rem

    raise SystemExit(bench_rem.main(args))
