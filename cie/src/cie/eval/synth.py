"""Synthetic document builders shared by the evaluation corpus, the simulation and the tests."""

from __future__ import annotations

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def make_pdf(sections: list[tuple[str, list[str]]], tables: dict[int, list[list[str]]] | None = None,
             page_breaks: bool = True) -> bytes:
    """``sections``: [(heading, [paragraphs])]. ``tables``: {section_index: rows}."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, title="synthetic")
    styles = getSampleStyleSheet()
    flow = []
    for i, (heading, paras) in enumerate(sections):
        flow.append(Paragraph(heading, styles["Heading2"]))
        for p in paras:
            flow.append(Paragraph(p, styles["BodyText"]))
            flow.append(Spacer(1, 6))
        if tables and i in tables:
            t = Table(tables[i])
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]))
            flow.append(t)
        if page_breaks and i < len(sections) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    return buf.getvalue()


def rasterize_pdf(pdf: bytes, dpi: int = 150, noise: float = 0.0) -> bytes:
    """Turn a born-digital PDF into an image-only PDF (a 'scan')."""
    import pymupdf

    src = pymupdf.open(stream=pdf, filetype="pdf")
    out = pymupdf.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        if noise > 0:
            import random

            samples = bytearray(pix.samples)
            rnd = random.Random(page.number)
            for i in range(0, len(samples), max(1, int(1 / noise))):
                samples[i] = max(0, min(255, samples[i] + rnd.randint(-90, 90)))
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pix.width, pix.height, bytes(samples), False)
        png = pix.tobytes("png")
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, stream=png)
    return out.tobytes()


CONTRACT_SECTIONS = [
    ("MASTER SERVICES AGREEMENT", [
        "This Master Services Agreement (the \"Agreement\") is entered into on January 15, 2025 between Acme Robotics Inc. (the \"Company\") and Northwind Logistics Ltd. (the \"Supplier\").",
        "The parties agree as follows.",
    ]),
    ("1. Definitions", [
        "\"Services\" means the warehouse automation services described in Schedule A.",
        "\"Effective Date\" means January 15, 2025.",
    ]),
    ("2. Term and Termination", [
        "2.1 The initial term of this Agreement is thirty-six (36) months from the Effective Date.",
        "2.2 Either party may terminate this Agreement for convenience by giving no later than ninety (90) days written notice, and in any case on or before December 31, 2027.",
        "2.3 The Company must pay all undisputed invoices within 45 days of receipt.",
    ]),
    ("3. Fees", [
        "3.1 The Supplier shall be paid a monthly fee of USD 125,000 for the Services.",
        "3.2 The total fees under this Agreement shall not exceed $4,500,000 without written approval of the Company.",
        "3.3 A late payment penalty of 1.5% per month applies to overdue amounts.",
    ]),
    ("4. Liability", [
        "4.1 The Supplier's aggregate liability shall be limited to the fees paid in the twelve months preceding the claim.",
        "4.2 Neither party shall be liable for indirect or consequential loss, and the risk of force majeure events is excluded.",
    ]),
    ("5. Signatures", [
        "By: Jane Whitfield, Chief Operating Officer, Acme Robotics Inc.",
        "By: Marcus Lindqvist, Managing Director, Northwind Logistics Ltd.",
    ]),
]
