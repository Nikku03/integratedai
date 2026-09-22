"""Vault service: ingest, version, read-with-verification.

The vault is append-only. Re-ingesting identical bytes returns the existing
document (dedup by sha256); re-ingesting a changed file under an existing
``family_id`` creates the next version.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Blob, Document, Scope
from cie.core.settings import Settings, get_settings
from cie.core.util import sha256_bytes
from cie.extraction.detect import detect_media_type
from cie.vault.backends import Cipher, LocalBackend, S3Backend, VaultBackend


class IntegrityError(RuntimeError):
    pass


@dataclass
class IngestResult:
    document: Document
    created: bool
    deduplicated: bool


class VaultService:
    def __init__(self, settings: Settings | None = None, backend: VaultBackend | None = None):
        self.settings = settings or get_settings()
        self.cipher = Cipher(self.settings.encryption_key or None)
        if backend is not None:
            self.backend = backend
        elif self.settings.vault_backend == "s3":
            self.backend = S3Backend(
                self.settings.s3_bucket,
                self.settings.s3_endpoint,
                self.settings.s3_access_key,
                self.settings.s3_secret_key,
            )
        else:
            self.backend = LocalBackend(self.settings.vault_path)

    # ------------------------------------------------------------------
    def ingest(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        data: bytes,
        filename: str,
        scope_id: uuid.UUID,
        owner_id: uuid.UUID | None = None,
        source: str = "upload",
        original_location: str | None = None,
        title: str | None = None,
        doc_type: str | None = None,
        sensitivity: int = 1,
        acl: dict | None = None,
        retention_policy: str = "default",
        retain_until: datetime | None = None,
        file_created_at: datetime | None = None,
        family_id: uuid.UUID | None = None,
        media_type: str | None = None,
        extra: dict | None = None,
    ) -> IngestResult:
        digest = sha256_bytes(data)
        media_type = media_type or detect_media_type(data, filename)
        blob = session.scalar(
            select(Blob).where(Blob.tenant_id == tenant_id, Blob.sha256 == digest)
        )
        dedup = blob is not None
        if blob is None:
            key = f"{tenant_id}/{digest}"
            uri = self.backend.put(key, self.cipher.encrypt(data))
            blob = Blob(
                tenant_id=tenant_id,
                sha256=digest,
                size_bytes=len(data),
                media_type=media_type,
                storage_uri=uri,
                encrypted=self.cipher.enabled,
            )
            session.add(blob)
            session.flush()

        scope = session.get(Scope, scope_id)
        if scope is None or scope.tenant_id != tenant_id:
            raise ValueError("scope not found in tenant")
        department_id, project_id = _scope_lineage(session, scope)

        # Versioning within a family
        version = 1
        previous_id = None
        if family_id is not None:
            latest = session.scalar(
                select(Document)
                .where(Document.tenant_id == tenant_id, Document.family_id == family_id)
                .order_by(Document.version.desc())
                .limit(1)
            )
            if latest is not None:
                if latest.blob_id == blob.id:
                    return IngestResult(document=latest, created=False, deduplicated=True)
                version = latest.version + 1
                previous_id = latest.id
        else:
            existing = session.scalar(
                select(Document).where(
                    Document.tenant_id == tenant_id,
                    Document.blob_id == blob.id,
                    Document.scope_id == scope_id,
                    Document.original_filename == filename,
                    Document.deleted_at.is_(None),
                )
            )
            if existing is not None:
                return IngestResult(document=existing, created=False, deduplicated=True)
            family_id = uuid.uuid4()

        doc = Document(
            tenant_id=tenant_id,
            blob_id=blob.id,
            family_id=family_id,
            version=version,
            previous_version_id=previous_id,
            title=title or filename,
            original_filename=filename,
            original_location=original_location,
            source=source,
            owner_id=owner_id,
            scope_id=scope_id,
            department_id=department_id,
            project_id=project_id,
            doc_type=doc_type,
            sensitivity=sensitivity,
            acl=acl or {},
            retention_policy=retention_policy,
            retain_until=retain_until,
            file_created_at=file_created_at,
            extra=extra or {},
        )
        session.add(doc)
        session.flush()
        return IngestResult(document=doc, created=True, deduplicated=dedup)

    # ------------------------------------------------------------------
    def read(self, session: Session, document: Document | uuid.UUID) -> bytes:
        doc = document if isinstance(document, Document) else session.get(Document, document)
        if doc is None:
            raise KeyError("document not found")
        blob = session.get(Blob, doc.blob_id)
        assert blob is not None
        raw = self.backend.get(blob.storage_uri)
        data = self.cipher.decrypt(raw) if blob.encrypted else raw
        if sha256_bytes(data) != blob.sha256:
            raise IntegrityError(f"checksum mismatch for blob {blob.id}")
        return data

    def verify(self, session: Session, document: Document) -> bool:
        try:
            self.read(session, document)
            return True
        except IntegrityError:
            return False

    def versions(self, session: Session, family_id: uuid.UUID) -> list[Document]:
        return list(
            session.scalars(
                select(Document).where(Document.family_id == family_id).order_by(Document.version)
            )
        )


def _scope_lineage(session: Session, scope: Scope) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    """Walk up the scope tree and return (department_id, project_id)."""
    department = project = None
    node: Scope | None = scope
    while node is not None:
        if node.kind.value == "project" and project is None:
            project = node.id
        if node.kind.value == "department" and department is None:
            department = node.id
        node = session.get(Scope, node.parent_id) if node.parent_id else None
    return department, project
