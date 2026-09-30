"""Baidu's Unlimited-OCR (https://hf.co/baidu/Unlimited-OCR): a 3.3B-parameter vision-language OCR model, derived from
DeepSeek-OCR, that reads a page image into layout blocks. It needs an NVIDIA GPU.

Two ways to run it, with one parser:

* ``UnlimitedOCR``: an OpenAI-compatible server (vLLM ``vllm/vllm-openai:unlimited-ocr`` or SGLang), as on the model
  card: one user message with the prompt ``document parsing.`` and a base64 PNG, temperature 0.
* ``UnlimitedOCRLocal``: the model loaded in this process with ``transformers`` (``trust_remote_code``), for a single
  GPU machine such as Colab. The model's code is pinned to ``REVISION`` so that what runs is what was reviewed.

The model writes layout markers, one block per marker, with the box on a 0–999 grid (its own drawing code divides
by 999)::

    <|det|>title [x0, y0, x1, y1]<|/det|>Heading text
    <|det|>text [[x0, y0, x1, y1]]<|/det|>Paragraph text ...
    <|ref|>table<|/ref|><|det|>[[x0, y0, x1, y1]]<|/det|><table>...</table>

and separates pages with ``<PAGE>`` when given several. Boxes are rescaled to PDF points. If a deployment emits
pixel coordinates, set ``coord_scale="pixels"``.
"""

from __future__ import annotations

import base64
import io
import re
import tempfile
import threading
from pathlib import Path

import httpx

from cie.extraction.types import ExtractedBlock, ExtractedPage

HF_MODEL = "baidu/Unlimited-OCR"
REVISION = "07dea832e22aefee32ad281d4b80551282e1c168"  # 2026-07-29; the model code this adapter was written against
GRID = 999.0
_EOS = "<｜end▁of▁sentence｜>"
_BOX = r"\[\s*\[?[^\]]*\]?\s*\]"
# <|det|>label [box]<|/det|>content   or   <|ref|>label<|/ref|><|det|>[[box]]<|/det|>content
_DET_RE = re.compile(r"<\|det\|>\s*([^<\s\[]+)\s*(" + _BOX + r")?\s*<\|/det\|>(.*)", re.DOTALL)
_REF_RE = re.compile(r"<\|ref\|>\s*(.*?)\s*<\|/ref\|>\s*<\|det\|>\s*(" + _BOX + r")?\s*<\|/det\|>(.*)", re.DOTALL)
_KIND_MAP = {
    "title": "heading",
    "section_header": "heading",
    "section-header": "heading",
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


def split_pages(raw: str) -> list[str]:
    """The pages of a multi-page reply (``<PAGE>`` between pages); a single-page reply is one page."""
    raw = raw.replace(_EOS, "")
    parts = [p.strip("\n") for p in raw.split("<PAGE>")]
    return [p for p in parts if p.strip()] or [raw]


class _Parser:
    coord_scale: str | float = GRID

    def parse(self, raw: str, px_width: int, px_height: int, dpi: int) -> ExtractedPage:
        """Parse the marker format of one page into blocks. Pure function; unit-tested."""
        raw = raw.replace(_EOS, "")
        scale_pts = 72.0 / dpi
        width_pts, height_pts = px_width * scale_pts, px_height * scale_pts
        blocks: list[ExtractedBlock] = []
        cur: dict | None = None
        for line in raw.splitlines():
            s = line.strip()
            m = _REF_RE.match(s) or _DET_RE.match(s)
            if m:
                if cur:
                    blocks.append(self._finish(cur))
                kind = _KIND_MAP.get(m.group(1).lower(), "text")
                bbox = self._bbox(m.group(2), px_width, px_height, scale_pts)
                cur = {"kind": kind, "bbox": bbox, "lines": [m.group(3).strip()]}
            elif cur is not None:
                cur["lines"].append(line.rstrip())
            elif s:
                cur = {"kind": "text", "bbox": [0, 0, width_pts, height_pts], "lines": [line.rstrip()]}
        if cur:
            blocks.append(self._finish(cur))
        return ExtractedPage(
            page_no=0, width=width_pts, height=height_pts, blocks=[b for b in blocks if b.text or b.kind == "figure"], method="ocr",
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


class UnlimitedOCR(_Parser):
    """Through an OpenAI-compatible server."""

    name = "unlimited_ocr"
    version = HF_MODEL

    def __init__(
        self,
        base_url: str,
        model: str = "Unlimited-OCR",
        timeout: float = 600.0,
        coord_scale: str | float = GRID,
        image_mode: str = "gundam",
        max_tokens: int = 8192,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.coord_scale = coord_scale
        self.image_mode = image_mode
        self.max_tokens = max_tokens
        self.client = httpx.Client(timeout=timeout)

    def available(self) -> bool:
        try:
            r = self.client.get(f"{self.base_url}/v1/models", timeout=5.0)
            return r.status_code == 200
        except Exception:
            return False

    def recognize(self, image_png: bytes, dpi: int) -> ExtractedPage:
        from PIL import Image

        img = Image.open(io.BytesIO(image_png))
        b64 = base64.b64encode(image_png).decode()
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,  # a page that loops is cut here instead of running to the context length
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
        return self.parse(raw, img.width, img.height, dpi)


class UnlimitedOCRLocal(_Parser):
    """The model in this process (``transformers``, bf16 on CUDA), as on the model card: single-image "gundam" mode
    (base 1024, tiles 640, cropping on), no repetition of 35-token n-grams within 128 tokens."""

    name = "unlimited_ocr"
    version = f"{HF_MODEL}@{REVISION[:7]}"

    def __init__(self, model: str = HF_MODEL, revision: str = REVISION, cache_dir: str | None = None, max_length: int = 8192,
                 coord_scale: str | float = GRID):
        self.model_name, self.revision, self.cache_dir = model, revision, cache_dir
        self.max_length = max_length
        self.coord_scale = coord_scale
        self._model = self._tok = None
        self._lock = threading.Lock()

    @staticmethod
    def available() -> bool:
        try:
            import torch
            import transformers  # noqa: F401
        except ImportError:
            return False
        return bool(torch.cuda.is_available())

    def load(self) -> UnlimitedOCRLocal:
        if self._model is None:
            import torch
            from transformers import AutoModel, AutoTokenizer

            kw = {"trust_remote_code": True, "revision": self.revision, "cache_dir": self.cache_dir}
            self._tok = AutoTokenizer.from_pretrained(self.model_name, **kw)
            self._model = AutoModel.from_pretrained(self.model_name, use_safetensors=True, torch_dtype=torch.bfloat16, **kw).eval().cuda()
        return self

    def raw(self, image_png: bytes) -> str:
        """The model's own output for one page image."""
        self.load()
        with self._lock, tempfile.TemporaryDirectory(prefix="cie_ocr_") as tmp:
            path = Path(tmp) / "page.png"
            path.write_bytes(image_png)
            out = self._model.infer(self._tok, prompt="<image>document parsing.", image_file=str(path), output_path=tmp,
                                    base_size=1024, image_size=640, crop_mode=True, eval_mode=True, max_length=self.max_length,
                                    no_repeat_ngram_size=35, ngram_window=128)
        return out if isinstance(out, str) else str(out or "")

    def recognize(self, image_png: bytes, dpi: int) -> ExtractedPage:
        from PIL import Image

        img = Image.open(io.BytesIO(image_png))
        return self.parse(self.raw(image_png), img.width, img.height, dpi)


def _html_table_rows(html: str) -> list[list[str]]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S | re.I):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)
        rows.append([re.sub(r"<[^>]+>", "", c).strip() for c in cells])
    return [r for r in rows if any(r)]
