"""Pluggable extractors. Register new ones in ``registry``."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from cie.extraction.types import ExtractedPage, ExtractionMeta


class Extractor(Protocol):
    name: str
    version: str

    def page_count(self, data: bytes) -> int: ...

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        """Yield pages lazily so 300+ page files never sit in memory at once."""
        ...

    def meta(self, data: bytes) -> ExtractionMeta: ...


class OCREngine(Protocol):
    """Recognises text in a rendered page image and returns blocks with boxes."""

    name: str
    version: str

    def recognize(self, image_png: bytes, dpi: int) -> ExtractedPage: ...
