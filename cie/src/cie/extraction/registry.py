"""Choose an extractor for a media type; wire the OCR engine from settings."""

from __future__ import annotations

from cie.core.settings import Settings, get_settings
from cie.extraction.extractors import Extractor, OCREngine
from cie.extraction.extractors.office import (
    CsvExtractor,
    DocxExtractor,
    EmailExtractor,
    HtmlExtractor,
    ImageExtractor,
    PptxExtractor,
    TextExtractor,
    XlsxExtractor,
)
from cie.extraction.extractors.pdf import PdfExtractor


class NoOCR:
    """Explicit stand-in when no OCR engine is configured. Never fakes text."""

    name = "none"
    version = "0"

    def recognize(self, image_png: bytes, dpi: int):  # pragma: no cover
        raise RuntimeError("No OCR engine configured (CIE_OCR_BACKEND)")


def build_ocr(settings: Settings | None = None) -> OCREngine | None:
    settings = settings or get_settings()
    backend = settings.ocr_backend
    if backend == "unlimited_ocr" or (backend == "auto" and settings.unlimited_ocr_url):
        from cie.extraction.extractors.ocr_unlimited import UnlimitedOCR

        if settings.unlimited_ocr_url:
            engine = UnlimitedOCR(settings.unlimited_ocr_url, settings.unlimited_ocr_model)
            if backend == "unlimited_ocr" or engine.available():
                return engine
    if backend in ("auto", "tesseract"):
        from cie.extraction.extractors.ocr_tesseract import TesseractOCR

        if TesseractOCR.available():
            return TesseractOCR()
        if backend == "tesseract":
            raise RuntimeError("tesseract binary not found")
    return None


def extractor_for(media_type: str, settings: Settings | None = None, ocr: OCREngine | None = None) -> Extractor:
    settings = settings or get_settings()
    if ocr is None:
        ocr = build_ocr(settings)
    mt = media_type.lower()
    if mt == "application/pdf":
        return PdfExtractor(ocr=ocr, ocr_dpi=settings.ocr_dpi, min_chars=settings.ocr_min_chars_per_page)
    if mt.startswith("image/"):
        if ocr is None:
            raise RuntimeError("image ingestion requires an OCR engine")
        return ImageExtractor(ocr, settings.ocr_dpi)
    if mt.endswith("wordprocessingml.document"):
        return DocxExtractor()
    if mt.endswith("spreadsheetml.sheet"):
        return XlsxExtractor()
    if mt.endswith("presentationml.presentation"):
        return PptxExtractor()
    if mt == "message/rfc822":
        return EmailExtractor()
    if mt == "text/html":
        return HtmlExtractor()
    if mt == "text/csv":
        return CsvExtractor(",")
    if mt == "text/tab-separated-values":
        return CsvExtractor("\t")
    if mt.startswith("text/") or mt in ("application/json", "application/sql", "application/x-sql"):
        return TextExtractor(mt)
    raise ValueError(f"unsupported media type: {media_type}")
