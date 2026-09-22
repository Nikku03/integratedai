"""Extractors for Word, Excel, PowerPoint, text, markdown, HTML, email, CSV,
code, transcripts and JSON/database exports.

These formats have no page geometry. "Pages" are logical units (a DOCX page
break group, a worksheet, a slide, or a chunk of ~60 lines) and block bboxes
are ``[0, 0, 0, 0]`` with the logical location stored in ``content``:
``{"paragraph": i}``, ``{"sheet": name, "range": "A1:D20"}``, ``{"slide": n}``,
``{"line_start": a, "line_end": b}``. Citations therefore remain exact.
"""

from __future__ import annotations

import csv
import html as html_lib
import io
import json
import re
from collections.abc import Iterator
from email import policy
from email.parser import BytesParser

from cie.extraction.types import ExtractedBlock, ExtractedPage, ExtractionMeta

NOBOX = [0.0, 0.0, 0.0, 0.0]
LINES_PER_PAGE = 60


class _Base:
    name = "structured"
    version = "1"

    def meta(self, data: bytes) -> ExtractionMeta:
        pages = list(self.extract(data))
        return ExtractionMeta(self.name, self.version, len(pages))

    def page_count(self, data: bytes) -> int:
        return sum(1 for _ in self.extract(data))


class TextExtractor(_Base):
    """Plain text, markdown, code, transcripts (.vtt/.srt), JSON, SQL dumps."""

    name = "text"

    def __init__(self, media_type: str = "text/plain"):
        self.media_type = media_type

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        text = data.decode("utf-8", errors="replace")
        if self.media_type == "application/json":
            try:
                text = json.dumps(json.loads(text), indent=1, ensure_ascii=False)
            except Exception:
                pass
        lines = text.splitlines()
        is_md = self.media_type == "text/markdown"
        is_code = self.media_type.startswith("text/x-") or self.media_type in ("text/javascript",)
        page_no = 0
        for start in range(0, max(len(lines), 1), LINES_PER_PAGE):
            page_no += 1
            if pages is not None and (page_no - 1) not in pages:
                continue
            chunk = lines[start:start + LINES_PER_PAGE]
            blocks: list[ExtractedBlock] = []
            para: list[str] = []
            para_start = start
            for i, line in enumerate(chunk, start=start):
                if line.strip() == "" and para and not is_code:
                    blocks.append(_para_block(para, para_start, i - 1, is_md))
                    para, para_start = [], i + 1
                    continue
                if not para:
                    para_start = i
                para.append(line)
            if para:
                blocks.append(_para_block(para, para_start, start + len(chunk) - 1, is_md))
            if is_code:
                for b in blocks:
                    b.kind = "text"
                    b.content["language"] = self.media_type
            yield ExtractedPage(page_no, 0, 0, blocks, "structured", confidence=1.0)


def _para_block(lines: list[str], a: int, b: int, is_md: bool) -> ExtractedBlock:
    text = "\n".join(lines).strip()
    kind = "text"
    if is_md and text.startswith("#"):
        kind = "heading"
        text = text.lstrip("# ").strip()
    elif is_md and text.startswith("|") and "\n" in text:
        kind = "table"
        rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in text.splitlines()
                if not re.match(r"^\|?\s*:?-{2,}", ln)]
        return ExtractedBlock(kind, NOBOX, text, content={"rows": rows, "line_start": a, "line_end": b})
    return ExtractedBlock(kind, NOBOX, text, content={"line_start": a, "line_end": b}, confidence=1.0)


class HtmlExtractor(_Base):
    name = "html"

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        raw = data.decode("utf-8", errors="replace")
        raw = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", raw)
        raw = re.sub(r"(?i)<br\s*/?>", "\n", raw)
        raw = re.sub(r"(?i)</(p|div|tr|li|h[1-6]|table)>", "\n\n", raw)
        raw = re.sub(r"(?i)<h([1-6])[^>]*>", lambda m: "\n\n#" * 1 + " ", raw)
        text = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        yield from TextExtractor("text/markdown").extract(text.encode(), pages)


class EmailExtractor(_Base):
    name = "email"

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        msg = BytesParser(policy=policy.default).parsebytes(data)
        headers = {k: str(msg.get(k, "")) for k in ("From", "To", "Cc", "Date", "Subject", "Message-ID")}
        body = msg.get_body(preferencelist=("plain", "html"))
        text = ""
        if body is not None:
            text = body.get_content()
            if body.get_content_type() == "text/html":
                text = "\n".join(p.text for pg in HtmlExtractor().extract(text.encode()) for p in pg.blocks)
        blocks = [ExtractedBlock("header", NOBOX, "\n".join(f"{k}: {v}" for k, v in headers.items() if v),
                                 content=headers, confidence=1.0)]
        attachments = [p.get_filename() for p in msg.iter_attachments()]
        for pg in TextExtractor().extract(text.encode()):
            blocks.extend(pg.blocks)
        if attachments:
            blocks.append(ExtractedBlock("text", NOBOX, "Attachments: " + ", ".join(a for a in attachments if a),
                                         content={"attachments": attachments}))
        yield ExtractedPage(1, 0, 0, blocks, "structured", confidence=1.0)


class CsvExtractor(_Base):
    name = "csv"

    def __init__(self, delimiter: str = ","):
        self.delimiter = delimiter

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        text = data.decode("utf-8", errors="replace")
        rows = list(csv.reader(io.StringIO(text), delimiter=self.delimiter))
        header = rows[0] if rows else []
        page_no = 0
        for start in range(1 if header else 0, max(len(rows), 1), LINES_PER_PAGE):
            page_no += 1
            if pages is not None and (page_no - 1) not in pages:
                continue
            chunk = rows[start:start + LINES_PER_PAGE]
            table = [header] + chunk if header else chunk
            txt = "\n".join(" | ".join(r) for r in table)
            yield ExtractedPage(page_no, 0, 0, [
                ExtractedBlock("table", NOBOX, txt, content={"rows": table, "line_start": start,
                                                             "line_end": start + len(chunk) - 1}, confidence=1.0)
            ], "structured", confidence=1.0)


class DocxExtractor(_Base):
    name = "docx"

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        import docx  # python-docx

        d = docx.Document(io.BytesIO(data))
        blocks: list[ExtractedBlock] = []
        page_no, count = 1, 0
        body = d.element.body
        para_idx = 0
        table_idx = 0
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        for child in body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                p = Paragraph(child, d)
                text = p.text.strip()
                style = (p.style.name if p.style is not None else "") or ""
                if text:
                    kind = "heading" if style.lower().startswith(("heading", "title")) else "text"
                    blocks.append(ExtractedBlock(kind, NOBOX, text, content={"paragraph": para_idx, "style": style},
                                                 confidence=1.0))
                    count += len(text)
                para_idx += 1
                if child.xpath(".//w:br[@w:type='page']") or count > 3000:
                    if pages is None or (page_no - 1) in pages:
                        yield ExtractedPage(page_no, 0, 0, blocks, "structured", confidence=1.0)
                    page_no, count, blocks = page_no + 1, 0, []
            elif tag == "tbl":
                t = Table(child, d)
                rows = [[c.text.strip() for c in r.cells] for r in t.rows]
                txt = "\n".join(" | ".join(r) for r in rows)
                blocks.append(ExtractedBlock("table", NOBOX, txt, content={"rows": rows, "table": table_idx},
                                             confidence=1.0))
                table_idx += 1
        if blocks and (pages is None or (page_no - 1) in pages):
            yield ExtractedPage(page_no, 0, 0, blocks, "structured", confidence=1.0)


class XlsxExtractor(_Base):
    name = "xlsx"

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        page_no = 0
        for ws in wb.worksheets:
            rows = []
            for r in ws.iter_rows(values_only=True):
                if any(c is not None for c in r):
                    rows.append(["" if c is None else str(c) for c in r])
            for start in range(0, max(len(rows), 1), LINES_PER_PAGE):
                page_no += 1
                if pages is not None and (page_no - 1) not in pages:
                    continue
                chunk = rows[start:start + LINES_PER_PAGE]
                txt = "\n".join(" | ".join(r) for r in chunk)
                yield ExtractedPage(page_no, 0, 0, [
                    ExtractedBlock("table", NOBOX, txt, content={
                        "rows": chunk, "sheet": ws.title,
                        "range": f"A{start + 1}:{_col(max((len(r) for r in chunk), default=1))}{start + len(chunk)}"},
                        confidence=1.0)
                ], "structured", confidence=1.0)


def _col(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s or "A"


class PptxExtractor(_Base):
    name = "pptx"

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
        for i, slide in enumerate(prs.slides, start=1):
            if pages is not None and (i - 1) not in pages:
                continue
            blocks: list[ExtractedBlock] = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    kind = "heading" if shape == getattr(slide.shapes, "title", None) else "text"
                    bbox = [float(shape.left or 0) / 12700, float(shape.top or 0) / 12700,
                            float((shape.left or 0) + (shape.width or 0)) / 12700,
                            float((shape.top or 0) + (shape.height or 0)) / 12700]  # EMU -> points
                    blocks.append(ExtractedBlock(kind, bbox, shape.text_frame.text.strip(),
                                                 content={"slide": i}, confidence=1.0))
                if getattr(shape, "has_table", False) and shape.has_table:
                    rows = [[c.text.strip() for c in r.cells] for r in shape.table.rows]
                    blocks.append(ExtractedBlock("table", NOBOX, "\n".join(" | ".join(r) for r in rows),
                                                 content={"rows": rows, "slide": i}, confidence=1.0))
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
                blocks.append(ExtractedBlock("text", NOBOX, slide.notes_slide.notes_text_frame.text.strip(),
                                             content={"slide": i, "notes": True}))
            yield ExtractedPage(i, float(prs.slide_width or 0) / 12700, float(prs.slide_height or 0) / 12700,
                                blocks, "structured", confidence=1.0)


class ImageExtractor(_Base):
    """A standalone image (scan/photo) goes straight to the OCR engine."""

    name = "image"

    def __init__(self, ocr, dpi: int = 200):
        self.ocr = ocr
        self.dpi = dpi

    def extract(self, data: bytes, pages: range | None = None) -> Iterator[ExtractedPage]:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("L")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page = self.ocr.recognize(buf.getvalue(), self.dpi)
        page.page_no = 1
        page.image_png = buf.getvalue()
        yield page
