"""
Add a photo to the site, or swap one of the stand-in photos for your own.

    python3 tools/build_media.py PHOTO.jpg SLUG [--alt "…"] [--focus 0.5,0.4]

Writes assets/img/photos/SLUG-800.webp and SLUG-1600.webp and records the photo in
assets/img/photos/media.json (size, ratio, blurred placeholder, alt text, focus point).

Swapping: use the SLUG of the photo you are replacing (e.g. rest-a-01-dining-room-banquette).
Every page that shows it picks up the new file, and this script also updates the blurred
placeholder baked into those pages. The frame keeps its shape on the page and the new photo is
cropped to fit, centred on --focus (x,y from 0 to 1; 0.5,0.5 is the middle).
Adding: pick a new SLUG, then print the markup for a page with
    python3 tools/media_tag.py SLUG --reveal

Requires Pillow (pip install pillow).
"""
from __future__ import annotations
import argparse, base64, io, json
from fractions import Fraction
from pathlib import Path
from PIL import Image, ImageFilter, ImageOps, ImageStat

SITE = Path(__file__).resolve().parents[1]
OUT = SITE / "assets/img/photos"
SIZES, QUALITY = (800, 1600), {800: 72, 1600: 74}


def build(src: Path, slug: str, alt: str | None, focus: str | None) -> tuple[dict, dict | None]:
    db_path = OUT / "media.json"
    db = json.loads(db_path.read_text())
    old = db.get(slug)
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    w0, h0 = im.size
    rec: dict = {}
    for size in SIZES:
        scale = min(1.0, size / max(w0, h0))
        w, h = max(1, round(w0 * scale)), max(1, round(h0 * scale))
        (im.resize((w, h), Image.LANCZOS) if scale < 1 else im).save(OUT / f"{slug}-{size}.webp", "WEBP", quality=QUALITY[size], method=6)
        rec["w"], rec["h"] = w, h
    f = Fraction(rec["w"], rec["h"]).limit_denominator(20)
    rec["ratio"] = f"{f.numerator}/{f.denominator}"
    t = im.copy(); t.thumbnail((20, 20)); t = t.filter(ImageFilter.GaussianBlur(0.8))
    buf = io.BytesIO(); t.save(buf, "WEBP", quality=45)
    rec["lqip"] = "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    rec["color"] = "#%02x%02x%02x" % tuple(int(c) for c in ImageStat.Stat(im.resize((32, 32))).mean[:3])
    rec["alt"] = alt if alt is not None else (old or {}).get("alt", "")
    if focus:
        fx, fy = (float(v) for v in focus.split(","))
        rec["focus"] = f"{round(fx * 100)}% {round(fy * 100)}%"
    else:
        rec["focus"] = (old or {}).get("focus", "50% 50%")
    db[slug] = rec
    db_path.write_text(json.dumps(db, indent=1, ensure_ascii=False))
    return rec, old


def refresh_pages(old: dict, new: dict) -> int:
    """Swap the old blurred placeholder and focus point for the new ones wherever the photo is used."""
    before = f"--lqip:url({old['lqip']}); --focus:{old.get('focus', '50% 50%')}"
    after = f"--lqip:url({new['lqip']}); --focus:{new['focus']}"
    n = 0
    for page in SITE.rglob("*.html"):
        html = page.read_text()
        out = html.replace(before, after).replace(old["lqip"], new["lqip"])
        if out != html:
            page.write_text(out); n += 1
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo"); ap.add_argument("slug")
    ap.add_argument("--alt"); ap.add_argument("--focus", help="x,y between 0 and 1, e.g. 0.5,0.4")
    a = ap.parse_args()
    rec, old = build(Path(a.photo), a.slug, a.alt, a.focus)
    print(f"{a.slug}: {rec['w']}x{rec['h']} ({rec['ratio']})")
    if old:
        print(f"replaced; updated the placeholder on {refresh_pages(old, rec)} page(s)")
        if not rec["alt"] or a.alt is None:
            print("tip: pass --alt to describe the new photo — the old description was kept")
    else:
        print("new photo; get its markup with: python3 tools/media_tag.py", a.slug, "--reveal")
