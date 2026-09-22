"""Tesseract OCR engine returning blocks with bounding boxes and confidences."""

from __future__ import annotations

import io
import shutil

from PIL import Image

from cie.extraction.types import ExtractedBlock, ExtractedPage


class TesseractOCR:
    name = "tesseract"

    def __init__(self, lang: str = "eng", psm: int = 3):
        import pytesseract

        self._pt = pytesseract
        self.lang = lang
        self.psm = psm
        self.version = str(pytesseract.get_tesseract_version()) if shutil.which("tesseract") else "missing"

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None

    def recognize(self, image_png: bytes, dpi: int) -> ExtractedPage:
        img = Image.open(io.BytesIO(image_png))
        scale = 72.0 / dpi  # pixels -> PDF points
        data = self._pt.image_to_data(
            img, lang=self.lang, config=f"--psm {self.psm}", output_type=self._pt.Output.DICT
        )
        groups: dict[tuple[int, int], dict] = {}
        n = len(data["text"])
        for i in range(n):
            word = data["text"][i]
            if not word or not word.strip():
                continue
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if conf < 0:
                continue
            key = (int(data["block_num"][i]), int(data["par_num"][i]))
            g = groups.setdefault(key, {"words": [], "confs": [], "boxes": [], "lines": {}})
            x, y, w, h = (data["left"][i], data["top"][i], data["width"][i], data["height"][i])
            g["words"].append(word)
            g["confs"].append(conf)
            g["boxes"].append((x, y, x + w, y + h))
            line_key = int(data["line_num"][i])
            g["lines"].setdefault(line_key, []).append(word)
        blocks: list[ExtractedBlock] = []
        all_conf: list[float] = []
        for key in sorted(groups):
            g = groups[key]
            xs0 = min(b[0] for b in g["boxes"])
            ys0 = min(b[1] for b in g["boxes"])
            xs1 = max(b[2] for b in g["boxes"])
            ys1 = max(b[3] for b in g["boxes"])
            text = "\n".join(" ".join(g["lines"][k]) for k in sorted(g["lines"]))
            conf = sum(g["confs"]) / len(g["confs"]) / 100.0
            all_conf.extend(g["confs"])
            blocks.append(
                ExtractedBlock(
                    "text",
                    [xs0 * scale, ys0 * scale, xs1 * scale, ys1 * scale],
                    text,
                    confidence=conf,
                )
            )
        page_conf = (sum(all_conf) / len(all_conf) / 100.0) if all_conf else 0.0
        return ExtractedPage(
            page_no=0,
            width=img.width * scale,
            height=img.height * scale,
            blocks=blocks,
            method="ocr",
            confidence=page_conf,
        )
