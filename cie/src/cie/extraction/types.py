"""Extraction data types shared by all extractors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

BBox = list[float]  # [x0, y0, x1, y1] in PDF points (72 dpi) or None-equivalent [0,0,0,0]


@dataclass
class ExtractedBlock:
    kind: str  # text|heading|table|figure|signature|formula|list|header|footer
    bbox: BBox
    text: str = ""
    content: dict[str, Any] = field(default_factory=dict)  # tables: {"rows": [[...]]}
    confidence: float | None = None
    font_size: float | None = None
    bold: bool = False


@dataclass
class ExtractedPage:
    page_no: int  # 1-based
    width: float
    height: float
    blocks: list[ExtractedBlock]
    method: str  # text|ocr|structured
    confidence: float | None = None
    image_png: bytes | None = None  # rendered page for OCR pages (optional)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks if b.text)


@dataclass
class ExtractionMeta:
    extractor: str
    version: str
    page_count: int
    language: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
