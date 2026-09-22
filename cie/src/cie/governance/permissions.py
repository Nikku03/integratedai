"""RBAC + ABAC resolution.

A principal sees a resource iff some grant gives it a role on the resource's
scope or an ancestor, the role's clearance covers the resource's sensitivity,
and the resource ACL does not deny it. ``visible_scopes`` returns the scope-id
set and per-scope clearance so every retrieval query filters in SQL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Grant, Permission, Principal, Role, Scope

_LEVEL = {Permission.read: 1, Permission.write: 2, Permission.admin: 3}


@dataclass
class Visibility:
    principal_id: uuid.UUID
    tenant_id: uuid.UUID
    clearance_by_scope: dict[uuid.UUID, int] = field(default_factory=dict)  # scope -> max sensitivity
    level_by_scope: dict[uuid.UUID, int] = field(default_factory=dict)  # scope -> permission level
    is_admin: bool = False

    @property
    def scope_ids(self) -> set[uuid.UUID]:
        return set(self.clearance_by_scope)

    def can_read(self, scope_id: uuid.UUID, sensitivity: int, acl: dict | None = None) -> bool:
        if scope_id not in self.clearance_by_scope:
            return False
        if self.clearance_by_scope[scope_id] < sensitivity:
            return False
        return _acl_allows(acl, self.principal_id)

    def can_write(self, scope_id: uuid.UUID) -> bool:
        return self.level_by_scope.get(scope_id, 0) >= 2

    def sql_filter(self, scope_col, sens_col):
        """SQL predicate: scope in visible set AND sensitivity <= clearance(scope)."""
        from sqlalchemy import and_, or_

        by_clearance: dict[int, list[uuid.UUID]] = {}
        for sid, clr in self.clearance_by_scope.items():
            by_clearance.setdefault(clr, []).append(sid)
        clauses = [and_(scope_col.in_(ids), sens_col <= clr) for clr, ids in by_clearance.items()]
        if not clauses:
            return scope_col.is_(None)  # nothing visible
        return or_(*clauses)


def _acl_allows(acl: dict | None, principal_id: uuid.UUID) -> bool:
    if not acl:
        return True
    pid = str(principal_id)
    if pid in set(acl.get("deny", [])):
        return False
    allow = acl.get("allow")
    return not allow or pid in set(allow)


def visible_scopes(session: Session, principal: Principal) -> Visibility:
    vis = Visibility(principal_id=principal.id, tenant_id=principal.tenant_id)
    grants = list(session.execute(
        select(Grant, Role).join(Role, Role.id == Grant.role_id)
        .where(Grant.principal_id == principal.id, Grant.tenant_id == principal.tenant_id)
    ))
    if not grants:
        return vis
    all_scopes = list(session.scalars(select(Scope).where(Scope.tenant_id == principal.tenant_id)))
    for grant, role in grants:
        root = next((s for s in all_scopes if s.id == grant.scope_id), None)
        if root is None:
            continue
        if role.permission == Permission.admin and root.parent_id is None:
            vis.is_admin = True
        for s in all_scopes:
            if s.id == root.id or s.path.startswith(root.path + "/"):
                vis.clearance_by_scope[s.id] = max(vis.clearance_by_scope.get(s.id, -1), role.max_sensitivity)
                vis.level_by_scope[s.id] = max(vis.level_by_scope.get(s.id, 0), _LEVEL[role.permission])
    return vis


def grant_role(session: Session, *, tenant_id: uuid.UUID, principal: Principal, role: Role, scope: Scope,
               granted_by: uuid.UUID | None = None) -> Grant:
    existing = session.scalar(select(Grant).where(Grant.principal_id == principal.id, Grant.role_id == role.id,
                                                  Grant.scope_id == scope.id))
    if existing:
        return existing
    g = Grant(tenant_id=tenant_id, principal_id=principal.id, role_id=role.id, scope_id=scope.id, granted_by=granted_by)
    session.add(g)
    session.flush()
    return g


def ensure_role(session: Session, tenant_id: uuid.UUID, name: str, permission: Permission, max_sensitivity: int) -> Role:
    r = session.scalar(select(Role).where(Role.tenant_id == tenant_id, Role.name == name))
    if r:
        return r
    r = Role(tenant_id=tenant_id, name=name, permission=permission, max_sensitivity=max_sensitivity)
    session.add(r)
    session.flush()
    return r


class AccessDenied(PermissionError):
    pass
