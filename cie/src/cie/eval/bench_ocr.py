"""OCR benchmark: how accurately, and how fast, an OCR engine reads scanned company documents.

**Pages.** A seeded sample of EnterpriseRAG-Bench documents (real enterprise text: tickets, threads, wiki pages, CRM
notes) is typeset as letter-size pages at 200 dpi in an 11-point sans-serif font, at most ``max_pages`` pages per
document. Every page is then degraded at two levels (``LEVELS``):
- ``scan``, an office scan: a rotation of up to 1 degree, a slight blur, grain, JPEG at quality 60;
- ``hard``, a poor copy: up to 3 degrees, scanned at 75% resolution and scaled back, a stronger blur and grain, JPEG
  at quality 35.
The text typeset on a page is its ground truth. Pages are typeset in ASCII (curly quotes and dashes become straight
ones; other characters are dropped), so that the ground truth is exactly what the page shows.

**Measures,** per engine and page:
- character error rate (CER): edit distance divided by the reference length, on text normalised the same way for
  every engine (markdown emphasis and heading marks removed, whitespace collapsed);
- word error rate (WER);
- numbers kept: the share of the reference's numbers (amounts, dates, identifiers) found verbatim in the output. The
  memory bank's figures come from them;
- seconds per page on the machine it ran on, and the time to load the engine.

``--ingest N`` also puts the first N scanned documents through the memory bank's own pipeline (vault, extraction with
the engine, sections, typed records) in a new tenant, and reports what it built and which numbers survived.

What this does not show: scans of real paper differ (stamps, handwriting, photos taken at an angle, tables, forms).
This measures typeset text under controlled noise.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import re
import statistics
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Any

PAGE_IN = (8.5, 11.0)
MARGIN_IN = 0.75
FONT_PT = 11
LINE = 1.35
_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
          "/usr/share/fonts/truetype/freefont/FreeSans.ttf"]
_ASCII = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...", " ": " ",
          "•": "-", "→": "->", "×": "x"}
_NUM = re.compile(r"\d[\d,.:/\-]*\d|\d")
LEVELS = {"scan": {"rotate": 1.0, "scale": 1.0, "blur": 0.6, "grain": 8.0, "jpeg": 60},
          "hard": {"rotate": 3.0, "scale": 0.75, "blur": 1.0, "grain": 16.0, "jpeg": 35}}


# ------------------------------------------------------------------ pages
def _font(px: int):
    from PIL import ImageFont

    for f in _FONTS:
        if Path(f).exists():
            return ImageFont.truetype(f, px)
    return ImageFont.load_default(size=px)


def ascii_text(s: str) -> str:
    s = "".join(_ASCII.get(c, c) for c in s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return "\n".join(re.sub(r"[ \t]+", " ", line).rstrip() for line in s.splitlines())


def typeset(text: str, dpi: int = 200, max_pages: int = 2) -> list[tuple[Any, str]]:
    """The text as page images (white background, black type) with each page's ground truth."""
    from PIL import Image, ImageDraw

    w, h = int(PAGE_IN[0] * dpi), int(PAGE_IN[1] * dpi)
    margin = int(MARGIN_IN * dpi)
    font = _font(round(FONT_PT * dpi / 72))
    line_h = round(FONT_PT * dpi / 72 * LINE)
    per_page = (h - 2 * margin) // line_h
    lines: list[str] = []
    for para in ascii_text(text).split("\n"):
        words, cur = para.split(), ""
        if not words:
            if lines and lines[-1]:
                lines.append("")
            continue
        for word in words:
            cand = f"{cur} {word}".strip()
            if font.getlength(cand) <= w - 2 * margin or not cur:
                cur = cand
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    pages = []
    for p in range(max_pages):
        chunk = lines[p * per_page:(p + 1) * per_page]
        if not any(chunk):
            break
        img = Image.new("L", (w, h), 255)
        d = ImageDraw.Draw(img)
        for i, line in enumerate(chunk):
            d.text((margin, margin + i * line_h), line, fill=0, font=font)
        pages.append((img, "\n".join(chunk).strip()))
    return pages


def degrade(img, rng: random.Random, level: str = "scan"):
    """The page as a scan at ``level`` (``LEVELS``). Returns PNG bytes of the same size as the page."""
    import numpy as np
    from PIL import Image, ImageFilter

    lv = LEVELS[level]
    out = img.rotate(rng.uniform(-lv["rotate"], lv["rotate"]), resample=Image.BICUBIC, fillcolor=255)
    if lv["scale"] != 1.0:
        w, h = out.size
        out = out.resize((round(w * lv["scale"]), round(h * lv["scale"])), Image.BILINEAR).resize((w, h), Image.BILINEAR)
    out = out.filter(ImageFilter.GaussianBlur(lv["blur"]))
    arr = np.asarray(out, dtype=np.float32)
    arr += np.random.default_rng(rng.randrange(1 << 30)).normal(0, lv["grain"], arr.shape)
    out = Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=lv["jpeg"])
    buf.seek(0)
    png = io.BytesIO()
    Image.open(buf).convert("L").save(png, "PNG")
    return png.getvalue()


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ------------------------------------------------------------------ measures
def normalise(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")  # table markup the model may emit
    s = re.sub(r"(?m)^\s*#+\s*", "", s)
    s = s.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", s).strip()


def cer(ref: str, hyp: str) -> float:
    from rapidfuzz.distance import Levenshtein

    r, h = normalise(ref), normalise(hyp)
    return Levenshtein.distance(r, h) / max(len(r), 1)


def wer(ref: str, hyp: str) -> float:
    from rapidfuzz.distance import Levenshtein

    r, h = normalise(ref).split(), normalise(hyp).split()
    return Levenshtein.distance(r, h) / max(len(r), 1)


def numbers_kept(ref: str, hyp: str) -> tuple[int, int]:
    """(numbers of the reference found verbatim in the output, numbers in the reference)."""
    nums = _NUM.findall(normalise(ref))
    h = normalise(hyp)
    return sum(1 for n in nums if n in h), len(nums)


def _p(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4)


# ------------------------------------------------------------------ engines
def build_engine(name: str, ocr_url: str | None = None):
    from cie.core.settings import get_settings

    if name == "tesseract":
        from cie.extraction.extractors.ocr_tesseract import TesseractOCR

        if not TesseractOCR.available():
            raise RuntimeError("tesseract binary not found")
        return TesseractOCR()
    if name == "unlimited_ocr":
        from cie.extraction.extractors.ocr_unlimited import UnlimitedOCR, UnlimitedOCRLocal

        s = get_settings()
        url = ocr_url or s.unlimited_ocr_url
        if url:
            return UnlimitedOCR(url, s.unlimited_ocr_model, max_tokens=s.unlimited_ocr_max_tokens)
        if not UnlimitedOCRLocal.available():
            raise RuntimeError("Unlimited-OCR needs a server (--ocr-url) or a CUDA GPU with torch and transformers")
        return UnlimitedOCRLocal(cache_dir=str(s.model_cache), max_length=s.unlimited_ocr_max_tokens)
    raise ValueError(f"unknown engine {name!r}")


def run_engine(engine, pages: list[dict], dpi: int, log=print) -> dict[str, Any]:
    t = time.perf_counter()
    if hasattr(engine, "load"):
        engine.load()
    load_s = time.perf_counter() - t
    rows, failed = [], 0
    for i, pg in enumerate(pages):
        t = time.perf_counter()
        try:
            out = engine.recognize(pg["png"], dpi)
            text = "\n".join(b.text for b in out.blocks if b.text)
        except Exception as e:  # noqa: BLE001 - a page the engine cannot read is a result
            failed += 1
            text = ""
            log(f"  [{engine.name}] page {i} failed: {type(e).__name__}: {e}"[:300])
        secs = time.perf_counter() - t
        kept, total = numbers_kept(pg["truth"], text)
        rows.append({"doc": pg["doc"], "page": pg["page"], "level": pg["level"], "cer": round(cer(pg["truth"], text), 4), "wer": round(wer(pg["truth"], text), 4),
                     "numbers": total, "numbers_kept": kept, "seconds": round(secs, 3), "chars": len(pg["truth"]), "text": text})
        if (i + 1) % 10 == 0:
            log(f"  [{engine.name}] {i + 1}/{len(pages)} pages, median CER so far {_p([r['cer'] for r in rows], 0.5)}")
    nums = sum(r["numbers"] for r in rows)
    by_level = {}
    for lv in sorted({r["level"] for r in rows}):
        rs = [r for r in rows if r["level"] == lv]
        n = sum(r["numbers"] for r in rs)
        by_level[lv] = {"pages": len(rs), "cer_median": _p([r["cer"] for r in rs], 0.5), "cer_mean": round(statistics.mean(r["cer"] for r in rs), 4),
                        "wer_median": _p([r["wer"] for r in rs], 0.5), "numbers_kept": round(sum(r["numbers_kept"] for r in rs) / n, 4) if n else None,
                        "seconds_per_page_p50": _p([r["seconds"] for r in rs], 0.5)}
    return {"engine": engine.name, "version": getattr(engine, "version", "?"), "pages": len(rows), "failed_pages": failed, "by_level": by_level,
            "cer_median": _p([r["cer"] for r in rows], 0.5), "cer_mean": round(statistics.mean(r["cer"] for r in rows), 4) if rows else None,
            "cer_p90": _p([r["cer"] for r in rows], 0.9), "wer_median": _p([r["wer"] for r in rows], 0.5),
            "numbers_kept": round(sum(r["numbers_kept"] for r in rows) / nums, 4) if nums else None, "numbers": nums,
            "seconds_per_page_p50": _p([r["seconds"] for r in rows], 0.5), "seconds_per_page_p95": _p([r["seconds"] for r in rows], 0.95),
            "load_seconds": round(load_s, 1), "per_page": rows}


# ------------------------------------------------------------------ memory bank
def ingest(engine, docs: list[dict], dpi: int, log=print) -> dict[str, Any]:
    """The scanned documents through the memory bank's pipeline, in a new tenant."""
    from collections import Counter

    from PIL import Image
    from sqlalchemy import select

    from cie.core.db import session_scope
    from cie.core.models import MemoryRecord, Section
    from cie.eval.bench_enterprise import new_tenant
    from cie.extraction.pipeline import run_extraction
    from cie.memory.embeddings import get_embedding_provider
    from cie.vault.service import VaultService

    tenant_id, company_id, _ = new_tenant(f"ocr-{engine.name}-{uuid.uuid4().hex[:6]}")
    vault, embedder = VaultService(), get_embedding_provider()
    t = time.perf_counter()
    kept = total = 0
    types: Counter = Counter()
    n_sec = 0
    for d in docs:
        imgs = [Image.open(io.BytesIO(p)).convert("RGB") for p in d["scans"]]
        buf = io.BytesIO()
        imgs[0].save(buf, "PDF", resolution=dpi, save_all=True, append_images=imgs[1:])
        with session_scope() as s:
            doc = vault.ingest(s, tenant_id=tenant_id, data=buf.getvalue(), filename=f"{d['dsid']}.pdf", scope_id=company_id,
                               title=d["title"][:200], doc_type="scan").document
            s.commit()
            run_extraction(s, doc, vault=vault, embedder=embedder, ocr=engine)
            secs = list(s.scalars(select(Section.text).where(Section.document_id == doc.id)))
            n_sec += len(secs)
            types.update(t_.value for t_ in s.scalars(select(MemoryRecord.type).where(MemoryRecord.source_document_id == doc.id)))
            k, n = numbers_kept("\n".join(d["truths"]), "\n".join(secs))
            kept, total = kept + k, total + n
    out = {"tenant_id": str(tenant_id), "documents": len(docs), "sections": n_sec, "records_by_type": dict(types),
           "numbers_kept_in_sections": round(kept / total, 4) if total else None, "seconds": round(time.perf_counter() - t, 1)}
    log(f"  [{engine.name}] memory bank from {len(docs)} scanned documents: {out}")
    return out


# ------------------------------------------------------------------ run
def sample_docs(root: Path, n: int, seed: int, cache: Path | None, min_chars: int = 600) -> list[dict]:
    from cie.eval.bench_enterprise import build_index, read_doc

    index = build_index(root / "generated_data" / "sources", cache=cache)
    rng = random.Random(seed)
    ids = sorted(index)
    rng.shuffle(ids)
    out = []
    for dsid in ids:
        d = read_doc(root / "generated_data" / "sources" / index[dsid])
        text = f"{d['title']}\n\n{d['content']}".strip()
        if len(ascii_text(text)) >= min_chars:
            out.append({"dsid": dsid, "title": d["title"] or dsid, "text": text})
        if len(out) >= n:
            break
    return out


def run(root: Path, out: Path, n_docs: int = 30, engines: list[str] | None = None, max_pages: int = 2, dpi: int = 200, seed: int = 11,
        ingest_docs: int = 0, ocr_url: str | None = None, log=print) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    docs = sample_docs(root, n_docs, seed, out / "index.json")
    pages = []
    for d in docs:
        d["scans"], d["truths"] = [], []
        for pno, (img, truth) in enumerate(typeset(d["text"], dpi, max_pages), start=1):
            for level in LEVELS:
                png = degrade(img, rng, level)
                if level == "scan":  # the memory-bank step reads the office scans
                    d["scans"].append(png)
                    d["truths"].append(truth)
                pages.append({"doc": d["dsid"], "page": pno, "level": level, "png": png, "truth": truth})
    log(f"{len(docs)} documents typeset into {len(pages) // len(LEVELS)} pages at {dpi} dpi, each scanned at {len(LEVELS)} levels")
    for pg in pages[:len(LEVELS)]:
        (out / f"sample_page_{pg['level']}.png").write_bytes(pg["png"])
    report: dict[str, Any] = {"benchmark": "OCR of typeset EnterpriseRAG-Bench documents with scan degradation", "documents": len(docs),
                              "pages": len(pages), "levels": LEVELS, "dpi": dpi, "max_pages": max_pages, "seed": seed, "engines": {}}
    for name in engines or ["tesseract", "unlimited_ocr"]:
        try:
            engine = build_engine(name, ocr_url)
        except Exception as e:  # noqa: BLE001 - an engine that is not installed here is reported, not fatal
            report["engines"][name] = {"error": f"{type(e).__name__}: {e}"}
            log(f"[{name}] not run: {e}")
            continue
        log(f"[{name}] reading {len(pages)} pages ...")
        res = run_engine(engine, pages, dpi, log)
        (out / f"pages_{name}.jsonl").write_text("\n".join(json.dumps(r) for r in res.pop("per_page")) + "\n")
        if ingest_docs:
            res["memory_bank"] = ingest(engine, docs[:ingest_docs], dpi, log)
        report["engines"][name] = res
        log(f"[{name}] median CER {res['cer_median']}, numbers kept {res['numbers_kept']}, {res['seconds_per_page_p50']} s/page")
    (out / "bench_ocr.json").write_text(json.dumps(report, indent=2, default=str))
    md = to_markdown(report)
    (out / "bench_ocr.md").write_text(md)
    print(md)
    return report


def to_markdown(rep: dict[str, Any]) -> str:
    lines = [f"### OCR benchmark: {rep['documents']} EnterpriseRAG-Bench documents typeset at {rep['dpi']} dpi, {rep['pages']} scanned pages "
             f"({', '.join(rep.get('levels', {'scan': 0}))} levels; seed {rep['seed']})", "",
             "| engine | level | pages | median CER | mean CER | median WER | numbers kept | s/page p50 |",
             "|---|---|---|---|---|---|---|---|"]
    for name, e in rep["engines"].items():
        if "error" in e:
            lines.append(f"| {name} | not run: {e['error']} | | | | | | |")
            continue
        for lv, x in e.get("by_level", {}).items():
            lines.append(f"| {name} ({e['version']}) | {lv} | {x['pages']} | {x['cer_median']} | {x['cer_mean']} | {x['wer_median']} | "
                         f"{x['numbers_kept']} | {x['seconds_per_page_p50']} |")
    lines += ["", "| engine | all pages: median CER | p90 CER | numbers kept | s/page p50 / p95 | load s | failed pages |", "|---|---|---|---|---|---|---|"]
    for name, e in rep["engines"].items():
        if "error" not in e:
            lines.append(f"| {name} | {e['cer_median']} | {e['cer_p90']} | {e['numbers_kept']} of {e['numbers']:,} | "
                         f"{e['seconds_per_page_p50']} / {e['seconds_per_page_p95']} | {e['load_seconds']} | {e['failed_pages']} |")
    for name, e in rep["engines"].items():
        mb = e.get("memory_bank") if isinstance(e, dict) else None
        if mb:
            lines += ["", f"Memory bank from {mb['documents']} scanned documents read by {name}: {mb['sections']} sections, "
                      f"records {mb['records_by_type']}, numbers kept in the sections {mb['numbers_kept_in_sections']}, {mb['seconds']} s."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", required=True, help="the EnterpriseRAG-Bench checkout (generated_data/sources)")
    ap.add_argument("--out", default="eval_out/ocr")
    ap.add_argument("--docs", type=int, default=30)
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--engines", default="tesseract,unlimited_ocr")
    ap.add_argument("--ingest", type=int, default=0, help="also build a memory bank from the first N scanned documents with each engine")
    ap.add_argument("--ocr-url", default=None, help="an Unlimited-OCR server; default: CIE_UNLIMITED_OCR_URL, else the model on this GPU")
    a = ap.parse_args(argv)
    return run(Path(a.root), Path(a.out), a.docs, [e.strip() for e in a.engines.split(",") if e.strip()], a.max_pages, a.dpi, a.seed,
               a.ingest, a.ocr_url)


if __name__ == "__main__":  # pragma: no cover
    main()
