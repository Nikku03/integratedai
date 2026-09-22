"""Small shared utilities: ids, hashing, token estimation, time."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import BinaryIO


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utcnow() -> datetime:
    return datetime.now(UTC)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_stream(fh: BinaryIO, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    while True:
        b = fh.read(chunk)
        if not b:
            break
        h.update(b)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Approximate LLM token count.

    Real counts come from the provider's usage report after a call; this
    estimate (roughly 4 characters per token for English, adjusted for
    whitespace-separated words) is used for budgeting before a call. It is
    labelled as an estimate wherever it is surfaced.
    """
    if not text:
        return 0
    words = len(text.split())
    chars = len(text)
    return max(1, int(0.75 * words + chars / 6))
