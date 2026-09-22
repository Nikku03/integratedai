"""Connectors: pull files from external sources into the vault.

``LocalFolderConnector`` is implemented (recursive scan, content-hash dedup,
version detection by path). IMAP, Google Drive, SharePoint, Slack and Git
connectors are NOT implemented in this build; their classes raise
``NotImplementedError`` so nothing pretends to sync.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from cie.core.models import Document
from cie.vault.service import IngestResult, VaultService
from cie.workers import queue


@dataclass
class SourceFile:
    path: str
    data: bytes
    modified_at: datetime


class Connector(Protocol):
    name: str

    def scan(self) -> Iterator[SourceFile]: ...


class LocalFolderConnector:
    name = "connector:folder"

    def __init__(self, root: Path, patterns: tuple[str, ...] = ("*.pdf", "*.docx", "*.xlsx", "*.pptx", "*.eml", "*.txt", "*.md",
                                                                  "*.csv", "*.html", "*.json", "*.png", "*.jpg")):
        self.root = Path(root)
        self.patterns = patterns

    def scan(self) -> Iterator[SourceFile]:
        for pat in self.patterns:
            for p in sorted(self.root.rglob(pat)):
                if p.is_file():
                    yield SourceFile(str(p.relative_to(self.root)), p.read_bytes(),
                                     datetime.fromtimestamp(p.stat().st_mtime, tz=UTC))


def sync(session: Session, connector: Connector, *, vault: VaultService, tenant_id: uuid.UUID, scope_id: uuid.UUID,
         owner_id: uuid.UUID | None = None, enqueue_jobs: bool = True) -> list[IngestResult]:
    """Ingest every file; a changed file at a known path becomes a new version."""
    results = []
    for f in connector.scan():
        location = f"{connector.name}:{f.path}"
        existing = session.scalar(select(Document).where(Document.tenant_id == tenant_id, Document.original_location == location,
                                                         Document.deleted_at.is_(None)).order_by(Document.version.desc()))
        res = vault.ingest(session, tenant_id=tenant_id, data=f.data, filename=Path(f.path).name, scope_id=scope_id, owner_id=owner_id,
                           source=connector.name, original_location=location, file_created_at=f.modified_at,
                           family_id=existing.family_id if existing else None)
        if res.created and enqueue_jobs:
            queue.enqueue(session, tenant_id, "extract_document", {"document_id": str(res.document.id)})
        results.append(res)
    return results


class ImapConnector:  # pragma: no cover
    name = "connector:imap"

    def __init__(self, *a, **kw):
        raise NotImplementedError("IMAP connector is not implemented in this build (docs/ROADMAP.md)")


class GoogleDriveConnector:  # pragma: no cover
    name = "connector:gdrive"

    def __init__(self, *a, **kw):
        raise NotImplementedError("Google Drive connector is not implemented in this build (docs/ROADMAP.md)")


class GitRepoConnector:  # pragma: no cover
    name = "connector:git"

    def __init__(self, *a, **kw):
        raise NotImplementedError("Git connector is not implemented in this build (docs/ROADMAP.md)")
