"""API dependencies: database session, authenticated principal, services."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.db import session_factory
from cie.core.models import Principal
from cie.core.settings import Settings, get_settings
from cie.governance.permissions import Visibility, visible_scopes


def db() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@dataclass
class Auth:
    principal: Principal
    visibility: Visibility

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.principal.tenant_id


def current_auth(request: Request, session: Session = Depends(db), x_api_key: str | None = Header(default=None),
                 settings: Settings = Depends(get_settings)) -> Auth:
    key = x_api_key or request.query_params.get("api_key")
    if not key:
        raise HTTPException(401, "missing X-API-Key")
    p = session.scalar(select(Principal).where(Principal.api_key_hash == hash_key(key)))
    if p is None:
        raise HTTPException(401, "invalid API key")
    return Auth(principal=p, visibility=visible_scopes(session, p))


def require_scope_read(auth: Auth, scope_id: uuid.UUID) -> None:
    if scope_id not in auth.visibility.scope_ids:
        raise HTTPException(403, "no access to scope")


def require_scope_write(auth: Auth, scope_id: uuid.UUID) -> None:
    if not auth.visibility.can_write(scope_id):
        raise HTTPException(403, "write access required on scope")
