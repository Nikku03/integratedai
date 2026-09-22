"""Ingestion-time scanners: secrets, PII, prompt injection.

These produce flags, not guarantees. Retrieved document text is always
handed to models as untrusted data regardless of what the scanners found.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SECRET_PATTERNS = {
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "generic_api_key": re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}", re.I),
    "github_token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
}
_PII_PATTERNS = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s-]?)?(?:\(\d{2,4}\)[\s-]?)?\d{3,4}[\s-]\d{3,4}(?:[\s-]\d{2,4})?(?!\d)"),
    "ssn_us": re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "dob": re.compile(r"\b(?:date of birth|DOB)\b[:\s]*\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", re.I),
}
_INJECTION_PATTERNS = [
    re.compile(p, re.I) for p in (
        r"ignore (?:all |any |the )?(?:previous|prior|above|earlier) (?:instructions|prompts|rules)",
        r"disregard (?:all |any |the )?(?:previous|prior|above) (?:instructions|rules)",
        r"you are now (?:a|an|the) ",
        r"\bsystem prompt\b",
        r"\bas an ai\b.*\b(?:must|should)\b",
        r"do not (?:tell|inform|reveal to) the user",
        r"\bassistant:\s",
        r"<\s*/?\s*(?:system|instruction|prompt)\s*>",
        r"\bexfiltrat\w+\b",
        r"send (?:this|the) (?:data|document|contents?) to ",
        r"\bBEGIN (?:HIDDEN|SECRET) INSTRUCTIONS?\b",
        r"when (?:you|the model) (?:read|see|process) this",
        r"reply with only",
        r"override (?:your|all) (?:safety|instructions|guidelines)",
    )
]


@dataclass
class Flag:
    kind: str  # secret|pii|injection
    label: str
    page_no: int | None
    excerpt: str

    def as_dict(self) -> dict:
        return {"kind": self.kind, "label": self.label, "page_no": self.page_no, "excerpt": self.excerpt}


def _luhn(s: str) -> bool:
    digits = [int(c) for c in s if c.isdigit()]
    if len(digits) < 13:
        return False
    total, alt = 0, False
    for d in reversed(digits):
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def scan_text(text: str, page_no: int | None = None, max_flags: int = 50) -> list[Flag]:
    flags: list[Flag] = []
    for label, pat in _SECRET_PATTERNS.items():
        for m in pat.finditer(text):
            flags.append(Flag("secret", label, page_no, _redact(m.group(0))))
            if len(flags) >= max_flags:
                return flags
    for label, pat in _PII_PATTERNS.items():
        for m in pat.finditer(text):
            if label == "card" and not _luhn(m.group(0)):
                continue
            if label == "phone" and sum(c.isdigit() for c in m.group(0)) < 8:
                continue
            flags.append(Flag("pii", label, page_no, _redact(m.group(0))))
            if len(flags) >= max_flags:
                return flags
    for pat in _INJECTION_PATTERNS:
        for m in pat.finditer(text):
            start = max(0, m.start() - 40)
            flags.append(Flag("injection", pat.pattern[:40], page_no, text[start:m.end() + 40].replace("\n", " ")))
            if len(flags) >= max_flags:
                return flags
    return flags


def _redact(s: str) -> str:
    if len(s) <= 6:
        return "***"
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


def wrap_untrusted(text: str, source: str) -> str:
    """Envelope for any retrieved text passed to a model: data, never instructions."""
    safe = text.replace("</untrusted_document>", "</untrusted_document >")
    return f'<untrusted_document source="{source}">\n{safe}\n</untrusted_document>'
