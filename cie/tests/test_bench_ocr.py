"""The OCR benchmark's pages and measures (no database, no model)."""

from __future__ import annotations

import random

from cie.eval import bench_ocr as b


def test_typeset_pages_carry_their_ground_truth_in_ascii():
    text = "Invoice “Q3” – total EUR 12,480.00 due 2026-10-15…\n\n" + " ".join(f"word{i}" for i in range(2500))
    pages = b.typeset(text, dpi=100, max_pages=2)
    assert len(pages) == 2
    img, truth = pages[0]
    assert img.size == (850, 1100) and truth.startswith('Invoice "Q3" - total EUR 12,480.00 due 2026-10-15...')
    assert all(ord(c) < 128 for _, t in pages for c in t)
    png = b.degrade(img, random.Random(3))
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_error_rates_and_numbers_kept():
    ref = "Total due: EUR 12,480.00 by 2026-10-15.\nRef PO-4471"
    assert b.cer(ref, ref) == 0.0 and b.wer(ref, ref) == 0.0
    assert b.cer(ref, "## **Total due:** EUR 12,480.00 by 2026-10-15. Ref PO-4471") == 0.0, "markdown and layout are not errors"
    assert 0 < b.cer(ref, "Tota1 due: EUR 12,48O.00 by 2026-10-15. Ref PO-4471") < 0.1
    assert b.numbers_kept(ref, "EUR 12,480.00 by 2026-1O-15 PO-4471") == (2, 3)
    assert b.cer(ref, "") == 1.0
