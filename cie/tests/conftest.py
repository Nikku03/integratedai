"""Test fixtures. Tests marked ``db`` need PostgreSQL with pgvector at
CIE_TEST_DATABASE_URL (default postgresql+psycopg://cie:cie@localhost:5432/cie_test)."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

os.environ.setdefault("CIE_EMBEDDING_PROVIDER", "hashed")
os.environ.setdefault("CIE_VAULT_PATH", tempfile.mkdtemp(prefix="cie-vault-"))
os.environ.setdefault("CIE_LLM_PROVIDER", "none")

from cie.core import db as dbmod  # noqa: E402
from cie.core.models import (  # noqa: E402
    Base,
    Permission,
    Principal,
    PrincipalKind,
    ScopeKind,
    Tenant,
)
from cie.core.settings import get_settings  # noqa: E402
from cie.governance.permissions import ensure_role, grant_role  # noqa: E402
from cie.memory.embeddings import HashedEmbedding  # noqa: E402
from cie.memory.scopes import create_scope  # noqa: E402
from cie.vault.backends import LocalBackend  # noqa: E402
from cie.vault.service import VaultService  # noqa: E402

TEST_URL = os.environ.get("CIE_TEST_DATABASE_URL", get_settings().test_database_url)


def _db_available() -> bool:
    try:
        eng = dbmod.get_engine(TEST_URL)
        with eng.connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def engine():
    if not _db_available():
        pytest.skip("PostgreSQL test database not available")
    eng = dbmod.get_engine(TEST_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(eng)
    # create_all does not add values to an enum type that already exists; keep the test database in step with the models
    from cie.core.models import LinkKind

    with eng.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for kind in LinkKind:
            conn.execute(text(f"ALTER TYPE link_kind ADD VALUE IF NOT EXISTS '{kind.value}'"))
    return eng


@pytest.fixture
def session(engine):
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    factory = dbmod.session_factory()
    s = factory()
    try:
        yield s
        s.commit()
    finally:
        s.close()


@pytest.fixture
def vault(tmp_path: Path):
    settings = get_settings()
    return VaultService(settings, backend=LocalBackend(tmp_path / "vault"))


@pytest.fixture
def embedder():
    return HashedEmbedding(384)


class World:
    """A tenant with company/department/project scopes and an admin principal."""

    def __init__(self, session):
        self.session = session
        self.tenant = Tenant(name=f"acme-{uuid.uuid4().hex[:6]}")
        session.add(self.tenant)
        session.flush()
        self.company = create_scope(session, self.tenant.id, ScopeKind.company, "Acme")
        self.legal = create_scope(session, self.tenant.id, ScopeKind.department, "Legal", self.company)
        self.finance = create_scope(session, self.tenant.id, ScopeKind.department, "Finance", self.company)
        self.project = create_scope(session, self.tenant.id, ScopeKind.project, "Project Atlas", self.legal)
        self.project2 = create_scope(session, self.tenant.id, ScopeKind.project, "Project Borealis", self.finance)
        self.admin = Principal(tenant_id=self.tenant.id, kind=PrincipalKind.user, name="admin", attributes={})
        self.analyst = Principal(tenant_id=self.tenant.id, kind=PrincipalKind.user, name="analyst", attributes={})
        self.outsider = Principal(tenant_id=self.tenant.id, kind=PrincipalKind.user, name="outsider", attributes={})
        session.add_all([self.admin, self.analyst, self.outsider])
        session.flush()
        admin_role = ensure_role(session, self.tenant.id, "admin", Permission.admin, 4)
        reader = ensure_role(session, self.tenant.id, "reader", Permission.read, 2)
        grant_role(session, tenant_id=self.tenant.id, principal=self.admin, role=admin_role, scope=self.company)
        grant_role(session, tenant_id=self.tenant.id, principal=self.analyst, role=reader, scope=self.legal)
        grant_role(session, tenant_id=self.tenant.id, principal=self.outsider, role=reader, scope=self.finance)
        session.flush()


@pytest.fixture
def world(session):
    return World(session)
