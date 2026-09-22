"""Conservative OCR correction proposals.

The original block text is never modified. Each proposal is stored in the
``corrections`` table with a method and confidence, and the corrected text is
what gets indexed for search while citations still point to the original.

Rules are deliberately narrow so they never invent content:
* de-hyphenate words broken across line ends when the joined word is common,
* fix ligature/encoding artefacts (ﬁ → fi, ﬂ → fl),
* fix digit/letter confusions inside otherwise alphabetic words (l→I, 0→O)
  and inside otherwise numeric tokens (O→0, l→1) only when the result is a
  plausible number,
* collapse repeated whitespace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl", "’": "'", "‘": "'", "“": '"', "”": '"'}
_HYPHEN_BREAK = re.compile(r"(\w{2,})-\n(\w{2,})")
_ALPHA_WITH_DIGIT = re.compile(r"\b([A-Za-z]*)([01])([A-Za-z]+)\b")
_NUM_WITH_LETTER = re.compile(r"\b(\d[\d,.]*)([OoIl])(\d[\d,.]*)?\b")


@dataclass
class CorrectionProposal:
    original: str
    corrected: str
    method: str
    confidence: float


def propose(text: str, method_prefix: str = "rule") -> CorrectionProposal | None:
    fixed = text
    for k, v in _LIGATURES.items():
        fixed = fixed.replace(k, v)
    fixed = _HYPHEN_BREAK.sub(lambda m: m.group(1) + m.group(2), fixed)
    fixed = _ALPHA_WITH_DIGIT.sub(_alpha_digit, fixed)
    fixed = _NUM_WITH_LETTER.sub(_num_letter, fixed)
    fixed = re.sub(r"[ \t]{2,}", " ", fixed)
    if fixed == text:
        return None
    changed = sum(1 for a, b in zip(text, fixed, strict=False) if a != b) + abs(len(text) - len(fixed))
    conf = max(0.5, 1.0 - changed / max(len(text), 1) * 5)
    return CorrectionProposal(text, fixed, f"{method_prefix}:ocr_v1", round(conf, 3))


def _alpha_digit(m: re.Match) -> str:
    pre, d, post = m.group(1), m.group(2), m.group(3)
    if len(pre) + len(post) < 2:
        return m.group(0)
    return pre + ("l" if d == "1" else "o") + post


def _num_letter(m: re.Match) -> str:
    a, ch, b = m.group(1), m.group(2), m.group(3) or ""
    if not b and not a:
        return m.group(0)
    repl = "0" if ch in "Oo" else "1"
    return a + repl + b
