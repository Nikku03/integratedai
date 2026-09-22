"""Divide a page stream into semantic sections with exact provenance.

A section starts at a heading block (or at a hard token limit) and carries
``spans`` — one entry per page it touches with the block ids and the union
bbox on that page — so every section cites page and box exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from cie.core.util import estimate_tokens


@dataclass
class BlockRef:
    block_id: uuid.UUID
    page_no: int
    bbox: list[float]
    kind: str
    text: str
    leading_heading: str | None = None


@dataclass
class SectionDraft:
    title: str | None
    level: int
    blocks: list[BlockRef] = field(default_factory=list)

    @property
    def text(self) -> str:
        body = [b.text for b in self.blocks if b.text and b.kind != "heading"]
        parts = []
        if self.title and not (body and body[0].lstrip().startswith(self.title.strip())):
            parts.append(self.title)
        parts.extend(body)
        return "\n".join(parts).strip()

    @property
    def page_start(self) -> int:
        return min((b.page_no for b in self.blocks), default=1)

    @property
    def page_end(self) -> int:
        return max((b.page_no for b in self.blocks), default=self.page_start)

    def spans(self) -> list[dict]:
        by_page: dict[int, list[BlockRef]] = {}
        for b in self.blocks:
            by_page.setdefault(b.page_no, []).append(b)
        out = []
        for page_no in sorted(by_page):
            bs = by_page[page_no]
            boxes = [b.bbox for b in bs if b.bbox and any(b.bbox)]
            bbox = [min(x[0] for x in boxes), min(x[1] for x in boxes),
                    max(x[2] for x in boxes), max(x[3] for x in boxes)] if boxes else [0, 0, 0, 0]
            out.append({"page_no": page_no, "block_ids": [str(b.block_id) for b in bs], "bbox": bbox})
        return out


def build_sections(blocks: list[BlockRef], target_tokens: int = 400, max_tokens: int = 900) -> list[SectionDraft]:
    """Greedy sectioning: headings open sections; oversize sections split at
    block boundaries; tiny trailing sections merge into the previous one."""
    sections: list[SectionDraft] = []
    cur = SectionDraft(title=None, level=1)
    cur_tokens = 0
    for b in blocks:
        if b.kind in ("header", "footer") and len(b.text) < 80:
            continue
        lead = getattr(b, "leading_heading", None)
        if lead and (cur.blocks or cur.title):
            sections.append(cur)
            cur = SectionDraft(title=lead.strip(), level=_level(lead))
            cur_tokens = 0
        if b.kind == "heading":
            if cur.blocks or cur.title:
                sections.append(cur)
            cur = SectionDraft(title=b.text.strip(), level=_level(b.text))
            cur.blocks.append(b)
            cur_tokens = estimate_tokens(b.text)
            continue
        t = estimate_tokens(b.text)
        if cur_tokens + t > max_tokens and cur.blocks:
            sections.append(cur)
            cur = SectionDraft(title=cur.title, level=cur.level)
            cur_tokens = 0
        cur.blocks.append(b)
        cur_tokens += t
    if cur.blocks or cur.title:
        sections.append(cur)

    # merge tiny sections forward so a lone heading does not become a section
    merged: list[SectionDraft] = []
    for s in sections:
        if merged and estimate_tokens(s.text) < target_tokens // 6 and not s.title:
            merged[-1].blocks.extend(s.blocks)
        else:
            merged.append(s)
    return [s for s in merged if s.text]


def _level(title: str) -> int:
    import re

    m = re.match(r"^(\d+(?:\.\d+)*)", title.strip())
    if m:
        return min(m.group(1).count(".") + 1, 6)
    if title.isupper():
        return 1
    return 2
