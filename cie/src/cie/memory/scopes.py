"""Scope tree (company > department > project > agent > task)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Scope, ScopeKind

_ORDER = [ScopeKind.company, ScopeKind.department, ScopeKind.project, ScopeKind.agent, ScopeKind.task]


def create_scope(session: Session, tenant_id: uuid.UUID, kind: ScopeKind | str, name: str,
                 parent: Scope | uuid.UUID | None = None, attributes: dict | None = None) -> Scope:
    kind = ScopeKind(kind)
    parent_obj = parent if isinstance(parent, Scope) or parent is None else session.get(Scope, parent)
    if kind != ScopeKind.company and parent_obj is None:
        raise ValueError(f"{kind.value} scope requires a parent")
    if parent_obj is not None and _ORDER.index(kind) <= _ORDER.index(parent_obj.kind) and kind != ScopeKind.task:
        # allow agent under project or department, task under anything below company
        if not (kind == ScopeKind.agent and parent_obj.kind in (ScopeKind.department, ScopeKind.company)):
            raise ValueError(f"cannot nest {kind.value} under {parent_obj.kind.value}")
    existing = session.scalar(select(Scope).where(
        Scope.tenant_id == tenant_id, Scope.name == name,
        Scope.parent_id == (parent_obj.id if parent_obj else None)))
    if existing:
        return existing
    scope = Scope(tenant_id=tenant_id, kind=kind, name=name,
                  parent_id=parent_obj.id if parent_obj else None, path="", attributes=attributes or {})
    session.add(scope)
    session.flush()
    scope.path = (parent_obj.path + "/" if parent_obj else "/") + str(scope.id)
    session.flush()
    return scope


def ancestors(session: Session, scope_id: uuid.UUID) -> list[Scope]:
    out: list[Scope] = []
    node = session.get(Scope, scope_id)
    while node is not None:
        out.append(node)
        node = session.get(Scope, node.parent_id) if node.parent_id else None
    return out  # self first, root last


def descendants(session: Session, scope: Scope) -> list[Scope]:
    return list(session.scalars(select(Scope).where(Scope.tenant_id == scope.tenant_id,
                                                    Scope.path.like(scope.path + "/%"))))


def addressable_scope_ids(session: Session, scope_id: uuid.UUID) -> set[uuid.UUID]:
    """Scopes whose records a query at ``scope_id`` may address: self, all
    descendants (project sees its tasks/agents) and all ancestors (inherited
    company/department memory)."""
    scope = session.get(Scope, scope_id)
    if scope is None:
        return set()
    ids = {s.id for s in ancestors(session, scope_id)}
    ids |= {s.id for s in descendants(session, scope)}
    return ids
