"""Completeness and confidence checks for an extraction."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompletenessReport:
    expected_pages: int
    extracted_pages: int
    empty_pages: list[int] = field(default_factory=list)
    low_confidence_pages: list[int] = field(default_factory=list)
    duplicate_pages: list[tuple[int, int]] = field(default_factory=list)
    mean_confidence: float | None = None
    ocr_pages: int = 0
    text_pages: int = 0
    passed: bool = True
    issues: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "expected_pages": self.expected_pages,
            "extracted_pages": self.extracted_pages,
            "empty_pages": self.empty_pages,
            "low_confidence_pages": self.low_confidence_pages,
            "duplicate_pages": self.duplicate_pages,
            "mean_confidence": self.mean_confidence,
            "ocr_pages": self.ocr_pages,
            "text_pages": self.text_pages,
            "passed": self.passed,
            "issues": self.issues,
        }


def check_completeness(
    expected_pages: int,
    pages: list[tuple[int, str, float | None, str, str]],
    low_conf_threshold: float = 0.6,
) -> CompletenessReport:
    """``pages``: (page_no, text, confidence, method, text_sha256)."""
    rep = CompletenessReport(expected_pages=expected_pages, extracted_pages=len(pages))
    seen: dict[str, int] = {}
    confs = []
    got = set()
    for page_no, text, conf, method, sha in pages:
        got.add(page_no)
        if method == "ocr":
            rep.ocr_pages += 1
        else:
            rep.text_pages += 1
        if not text.strip():
            rep.empty_pages.append(page_no)
        if conf is not None:
            confs.append(conf)
            if conf < low_conf_threshold:
                rep.low_confidence_pages.append(page_no)
        if text.strip():
            if sha in seen:
                rep.duplicate_pages.append((seen[sha], page_no))
            else:
                seen[sha] = page_no
    missing = sorted(set(range(1, expected_pages + 1)) - got)
    if missing:
        rep.passed = False
        rep.issues.append(f"missing pages: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    if rep.extracted_pages != expected_pages:
        rep.passed = False
        rep.issues.append(f"page count mismatch: expected {expected_pages}, got {rep.extracted_pages}")
    if confs:
        rep.mean_confidence = round(sum(confs) / len(confs), 4)
    if rep.empty_pages:
        rep.issues.append(f"{len(rep.empty_pages)} empty page(s) flagged for review")
    if rep.low_confidence_pages:
        rep.issues.append(f"{len(rep.low_confidence_pages)} low-confidence page(s) flagged for review")
    return rep
