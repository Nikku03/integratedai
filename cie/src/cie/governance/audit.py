"""Append-only audit log."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from cie.core.models import AuditLog


def audit(session: Session, *, tenant_id: uuid.UUID, principal_id: uuid.UUID | None, action: str,
          resource_kind: str | None = None, resource_id: Any = None, details: dict | None = None,
          outcome: str = "ok") -> AuditLog:
    row = AuditLog(tenant_id=tenant_id, principal_id=principal_id, action=action, resource_kind=resource_kind,
                   resource_id=str(resource_id) if resource_id is not None else None,
                   details=details or {}, outcome=outcome)
    session.add(row)
    session.flush()
    return row
