"""PDF extractor built on PyMuPDF.

Born-digital pages come from the text layer with block bounding boxes, font
sizes (for heading detection), tables (``page.find_tables``), images (figure
blocks) and a signature heuristic. Pages whose text layer is empty or tiny are
rendered and passed to the configured OCR engine, one page at a time.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

import pymupdf

from cie.extraction.extractors import OCREngine
from cie.extraction.types import ExtractedBlock, ExtractedPage, ExtractionMeta

_SIG_RE = re.compile(r"\b(signature|signed|by:|authori[sz]ed signatory|/s/)\b", re.I)
_FORMULA_RE = re.compile(r"[∑∫√≤≥≠±×÷∞∂∆πλσ]|\\frac|\^\{|\b[a-z]\s*=\s*[a-z0-9(]", re.I)


class PdfExtractor:
    name = "pymupdf"
    version = pymupdf.VersionBind

    def __init__(self, ocr: OCREngine | None = None, ocr_dpi: int = 200, min_chars: int = 25):
        self.ocr = ocr
        self.ocr_dpi = ocr_dpi
        self.min_chars = min_chars

    def page_count(self, data: bytes) -> int:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return doc.page_count

    def meta(self, data: bytes) -> ExtractionMeta:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            return ExtractionMeta(
                extractor=self.name,
                version=self.version,
                page_count=doc.page_count,
                stats={"metadata": {k: v for k, v in (doc.metadata or {}).items() if v}},
            )

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            rng = pages if pages is not None else range(doc.page_count)
            for idx in rng:
                if idx >= doc.page_count:
                    break
                yield self._extract_page(doc[idx], idx + 1)

    # ------------------------------------------------------------------
    def _extract_page(self, page: pymupdf.Page, page_no: int) -> ExtractedPage:
        width, height = page.rect.width, page.rect.height
        blocks = self._text_blocks(page)
        chars = sum(len(b.text) for b in blocks)
        if chars < self.min_chars:
            if self.ocr is None:
                return ExtractedPage(page_no, width, height, blocks, "text", confidence=None)
            pix = page.get_pixmap(dpi=self.ocr_dpi, colorspace=pymupdf.csGRAY)
            png = pix.tobytes("png")
            ocr_page = self.ocr.recognize(png, self.ocr_dpi)
            ocr_page.page_no = page_no
            ocr_page.width, ocr_page.height = width, height
            ocr_page.image_png = png
            return ocr_page

        blocks.extend(self._tables(page))
        blocks.extend(self._images(page))
        blocks.sort(key=lambda b: (round(b.bbox[1] / 8), b.bbox[0]))
        return ExtractedPage(page_no, width, height, blocks, "text", confidence=1.0)

    def _text_blocks(self, page: pymupdf.Page) -> list[ExtractedBlock]:
        out: list[ExtractedBlock] = []
        d = page.get_text("dict", flags=pymupdf.TEXT_PRESERVE_LIGATURES)
        sizes: list[float] = []
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            for line in b.get("lines", []):
                for span in line.get("spans", []):
                    if span.get("text", "").strip():
                        sizes.append(span.get("size", 0))
        body = _median(sizes) if sizes else 10.0
        for b in d.get("blocks", []):
            if b.get("type") != 0:
                continue
            lines_text = []
            max_size, bold = 0.0, False
            for line in b.get("lines", []):
                spans = [s for s in line.get("spans", []) if s.get("text")]
                lines_text.append("".join(s["text"] for s in spans))
                for s in spans:
                    max_size = max(max_size, s.get("size", 0))
                    if s.get("flags", 0) & 16 and s["text"].strip():
                        bold = True
            text = "\n".join(t.rstrip() for t in lines_text).strip()
            if not text:
                continue
            kind = "text"
            if _is_heading(text, max_size, body, bold):
                kind = "heading"
            elif _SIG_RE.search(text) and len(text) < 200:
                kind = "signature"
            elif _FORMULA_RE.search(text) and len(text) < 300:
                kind = "formula"
            elif page.rect.height and (b["bbox"][3] < page.rect.height * 0.06):
                kind = "header"
            elif page.rect.height and (b["bbox"][1] > page.rect.height * 0.94):
                kind = "footer"
            out.append(
                ExtractedBlock(kind, list(b["bbox"]), text, confidence=1.0,
                               font_size=max_size, bold=bold)
            )
        return out

    def _tables(self, page: pymupdf.Page) -> list[ExtractedBlock]:
        out: list[ExtractedBlock] = []
        try:
            tabs = page.find_tables()
        except Exception:
            return out
        for t in tabs.tables:
            try:
                rows = t.extract()
            except Exception:
                continue
            clean = [[(c or "").strip() for c in r] for r in rows if any(c for c in r)]
            if not clean:
                continue
            text = "\n".join(" | ".join(r) for r in clean)
            out.append(
                ExtractedBlock("table", list(t.bbox), text, content={"rows": clean}, confidence=0.9)
            )
        return out

    def _images(self, page: pymupdf.Page) -> list[ExtractedBlock]:
        out: list[ExtractedBlock] = []
        for info in page.get_image_info():
            bbox = list(info.get("bbox", (0, 0, 0, 0)))
            if (bbox[2] - bbox[0]) < 20 or (bbox[3] - bbox[1]) < 20:
                continue
            out.append(ExtractedBlock("figure", bbox, "", content={"width": info.get("width"),
                                                                    "height": info.get("height")}))
        return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    return s[len(s) // 2]


_NUMBERED = re.compile(r"^(\d+(\.\d+)*|[A-Z]|[IVXLC]+|Article\s+\w+|Section\s+\w+|Schedule\s+\w+)[.):]?\s+\S")


def _is_heading(text: str, size: float, body: float, bold: bool) -> bool:
    if "\n" in text.strip() or len(text) > 120:
        return False
    if size >= body * 1.15:
        return True
    if bold and len(text) < 80:
        return True
    if _NUMBERED.match(text) and len(text) < 100 and not text.endswith("."):
        return True
    if text.isupper() and 3 < len(text) < 80:
        return True
    return False
