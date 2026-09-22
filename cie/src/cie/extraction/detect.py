"""Media type and language detection."""

from __future__ import annotations

import mimetypes
import re
from collections import Counter

try:
    import magic  # python-magic (libmagic)
except Exception:  # pragma: no cover
    magic = None

_EXT_OVERRIDES = {
    ".md": "text/markdown",
    ".eml": "message/rfc822",
    ".py": "text/x-python",
    ".ts": "text/x-typescript",
    ".js": "text/javascript",
    ".json": "application/json",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".vtt": "text/vtt",
    ".srt": "text/plain",
}


def detect_media_type(data: bytes, filename: str = "") -> str:
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    sniffed = None
    if magic is not None:
        try:
            sniffed = magic.from_buffer(data[:8192], mime=True)
        except Exception:
            sniffed = None
    if sniffed and sniffed not in ("application/octet-stream", "text/plain", "application/zip"):
        return sniffed
    if ext in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[ext]
    guess, _ = mimetypes.guess_type(filename)
    if guess:
        return guess
    if sniffed:
        return sniffed
    return "application/octet-stream"


_STOPWORDS = {
    "en": {"the", "and", "of", "to", "in", "is", "that", "for", "with", "shall", "this", "by"},
    "de": {"der", "die", "und", "das", "ist", "nicht", "mit", "für", "von", "den", "ein"},
    "fr": {"le", "la", "les", "et", "des", "est", "pour", "dans", "une", "que", "pas"},
    "es": {"el", "la", "los", "las", "y", "de", "que", "para", "con", "una", "por"},
    "pt": {"o", "a", "os", "as", "e", "de", "que", "para", "com", "uma", "não"},
    "it": {"il", "la", "e", "di", "che", "per", "con", "una", "non", "sono", "del"},
}


def detect_language(text: str) -> str:
    """Cheap stopword-ratio detector. Returns ISO 639-1 code or 'und'."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())
    if len(words) < 20:
        return "und"
    counts = Counter(words)
    best, best_score = "und", 0.0
    for lang, sw in _STOPWORDS.items():
        score = sum(counts[w] for w in sw) / len(words)
        if score > best_score:
            best, best_score = lang, score
    return best if best_score > 0.02 else "und"


def is_pdf(media_type: str) -> bool:
    return media_type == "application/pdf"


def is_image(media_type: str) -> bool:
    return media_type.startswith("image/")
