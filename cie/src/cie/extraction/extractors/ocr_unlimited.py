"""Adapter for Baidu's Unlimited-OCR (https://hf.co/baidu/Unlimited-OCR).

The model is a ~6.7 GB vision-language OCR model that needs a GPU. This adapter
talks to an OpenAI-compatible server (vLLM ``vllm/vllm-openai:unlimited-ocr``
image or SGLang) exactly as documented on the model card: one user message
with the prompt ``document parsing.`` and a base64 PNG, temperature 0. The
response contains layout markers of the form::

    <|det|>title [x0, y0, x1, y1]<|/det|>Heading text
    <|det|>text [x0, y0, x1, y1]<|/det|>Paragraph text ...
    <|det|>table [..]<|/det|><table>...</table>

Coordinates are parsed as the model emits them and rescaled to PDF points using
``coord_scale`` (default: normalised 0–1000 grid as in DeepSeek-OCR, from which
Unlimited-OCR derives). If a deployment emits pixel coordinates set
``coord_scale="pixels"``.

STATUS: implemented against the published API; NOT exercised against a live
server in this build (no GPU). ``tests/test_extraction.py`` covers the response
parser with a recorded-format sample. An in-process ``transformers`` path is
deliberately not included: it requires CUDA and a pinned torch stack.
"""

from __future__ import annotations

import base64
import re

import httpx

from cie.extraction.types import ExtractedBlock, ExtractedPage

_DET_RE = re.compile(r"<\|det\|>\s*([a-zA-Z_]+)\s*(\[[^\]]*\])?\s*<\|/det\|>(.*)", re.DOTALL)
_KIND_MAP = {
    "title": "heading",
    "section_header": "heading",
    "text": "text",
    "paragraph": "text",
    "table": "table",
    "figure": "figure",
    "image": "figure",
    "formula": "formula",
    "equation": "formula",
    "signature": "signature",
    "list": "list",
    "header": "header",
    "footer": "footer",
    "page_number": "footer",
}


class UnlimitedOCR:
    name = "unlimited_ocr"
    version = "baidu/Unlimited-OCR"

    def __init__(
        self,
        base_url: str,
        model: str = "Unlimited-OCR",
        timeout: float = 600.0,
        coord_scale: str | float = 1000.0,
        image_mode: str = "gundam",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.coord_scale = coord_scale
        self.image_mode = image_mode
        self.client = httpx.Client(timeout=timeout)

    def available(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/v1/models", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def recognize(self, image_png: bytes, dpi: int) -> ExtractedPage:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(image_png))
        b64 = base64.b64encode(image_png).decode()
        payload = {
            "model": self.model,
            "temperature": 0,
            "skip_special_tokens": False,
            "images_config": {"image_mode": self.image_mode},
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "document parsing."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }
            ],
        }
        r = self.client.post(f"{self.base_url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"]
        page = self.parse(raw, img.width, img.height, dpi)
        return page

    # ------------------------------------------------------------------
    def parse(self, raw: str, px_width: int, px_height: int, dpi: int) -> ExtractedPage:
        """Parse the marker format into blocks. Pure function; unit-tested."""
        scale_pts = 72.0 / dpi
        width_pts, height_pts = px_width * scale_pts, px_height * scale_pts
        blocks: list[ExtractedBlock] = []
        cur: dict | None = None
        for line in raw.splitlines():
            m = _DET_RE.match(line.strip())
            if m:
                if cur:
                    blocks.append(self._finish(cur))
                kind = _KIND_MAP.get(m.group(1).lower(), "text")
                bbox = self._bbox(m.group(2), px_width, px_height, scale_pts)
                cur = {"kind": kind, "bbox": bbox, "lines": [m.group(3).strip()]}
            elif cur is not None:
                cur["lines"].append(line.rstrip())
            elif line.strip():
                cur = {"kind": "text", "bbox": [0, 0, width_pts, height_pts], "lines": [line.rstrip()]}
        if cur:
            blocks.append(self._finish(cur))
        return ExtractedPage(
            page_no=0, width=width_pts, height=height_pts, blocks=blocks, method="ocr",
            confidence=None,  # the model does not report per-token confidence
        )

    def _bbox(self, raw: str | None, w: int, h: int, scale_pts: float) -> list[float]:
        if not raw:
            return [0.0, 0.0, w * scale_pts, h * scale_pts]
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", raw)][:4]
        if len(nums) < 4:
            return [0.0, 0.0, w * scale_pts, h * scale_pts]
        x0, y0, x1, y1 = nums
        if self.coord_scale == "pixels":
            return [x0 * scale_pts, y0 * scale_pts, x1 * scale_pts, y1 * scale_pts]
        s = float(self.coord_scale)
        return [x0 / s * w * scale_pts, y0 / s * h * scale_pts,
                x1 / s * w * scale_pts, y1 / s * h * scale_pts]

    @staticmethod
    def _finish(cur: dict) -> ExtractedBlock:
        text = "\n".join(t for t in cur["lines"] if t is not None).strip()
        content: dict = {}
        if cur["kind"] == "table":
            rows = _html_table_rows(text)
            if rows:
                content = {"rows": rows}
                text = "\n".join(" | ".join(r) for r in rows)
        return ExtractedBlock(cur["kind"], cur["bbox"], text, content=content, confidence=None)


def _html_table_rows(html: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        rows.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    return [r for r in rows if any(r)]
