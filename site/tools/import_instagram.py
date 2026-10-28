"""
Bring the studio's own Instagram posts into the site.

1. Download them from Instagram: Accounts Centre → Your information and permissions → Download your
   information → the studio's account → Some of your information → Content (posts, reels) →
   format JSON, media quality High. Instagram emails a link to a .zip.
2. See what's in it. This writes a catalogue (catalog.json: every post's date, caption and files) and
   contact sheets to choose from. Nothing on the site changes:

       python3 tools/import_instagram.py list ~/Downloads/instagram-twosquares.toronto.zip --out ~/ig-review

3. Add the posts you want, by the ids in the catalogue. Photos become site photos
   (assets/img/photos/ig-<post>-<n>), videos become loops (assets/video/ig-<post>-v<n>):

       python3 tools/import_instagram.py add ~/Downloads/instagram-….zip 20240512-1830 20240601-0915

   Then use them like any other photo or clip: name them in assets/data/projects.json, or print the
   markup with python3 tools/media_tag.py ig-20240512-1830-1 --reveal.

A plain folder of photos and videos works too: each folder that holds them is one post (its name is
the post id), and a caption.txt beside them is used as the caption.
Needs Pillow; videos need ffmpeg (or FFMPEG=/path/to/ffmpeg).
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, shutil, subprocess, sys, tempfile, unicodedata, zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
IMG = {".jpg", ".jpeg", ".png", ".webp"}
VID = {".mp4", ".mov", ".m4v", ".webm"}
FFPROBE = os.environ.get("FFPROBE", shutil.which("ffprobe") or "ffprobe")


def fix(s: str) -> str:
    """Instagram's JSON writes UTF-8 text as Latin-1 escapes ('â\\x80\\x99' for ’): undo that."""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()   # café → cafe
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "post"


def open_export(path: Path) -> tuple[Path, Path | None]:
    """The export's root folder, and a temporary folder to delete afterwards (for a .zip)."""
    if path.is_dir():
        return path, None
    tmp = Path(tempfile.mkdtemp(prefix="ig-export-"))
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp)                        # extractall drops absolute paths and '..' parts
    kids = [p for p in tmp.iterdir() if not p.name.startswith(("__MACOSX", "."))]
    return (kids[0] if len(kids) == 1 and kids[0].is_dir() else tmp), tmp


def duration(p: Path) -> float:
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                             capture_output=True, text=True, check=True).stdout
        return round(float(out.strip()), 1)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return 0.0


def read_posts(root: Path) -> list[dict]:
    """Every post and reel, newest first: {id, date, kind, caption, files}."""
    media = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMG | VID]
    by_name = {p.name: p for p in media}
    resolve = lambda uri: (root / uri) if (root / uri).is_file() else by_name.get(Path(uri).name)
    posts: list[dict] = []
    sources = sorted(root.rglob("posts_*.json")) + sorted(root.rglob("reels.json"))
    for f in sources:
        data = json.loads(f.read_text("utf-8"))
        items = data.get("ig_reels_media", []) if isinstance(data, dict) else data
        for it in items:
            ms = it.get("media") or []
            ts = it.get("creation_timestamp") or (ms[0].get("creation_timestamp", 0) if ms else 0)
            caption = fix(it.get("title") or (ms[0].get("title", "") if ms else ""))
            files = [p for p in (resolve(m.get("uri", "")) for m in ms) if p and p.suffix.lower() in IMG | VID]
            if files:
                posts.append({"ts": ts, "kind": "reel" if f.name == "reels.json" else "post", "caption": caption, "files": files})
    if not sources:                              # a plain folder of photos and videos
        for d in sorted({p.parent for p in media}):
            files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMG | VID)
            cap = d / "caption.txt"
            posts.append({"id": slugify(d.name if d != root else root.name), "kind": "folder",
                          "ts": int(min(p.stat().st_mtime for p in files)),
                          "caption": cap.read_text("utf-8").strip() if cap.is_file() else "", "files": files})
    posts.sort(key=lambda p: p["ts"], reverse=True)
    seen: dict[str, int] = {}
    for p in posts:
        p["date"] = dt.datetime.fromtimestamp(p["ts"], dt.timezone.utc).strftime("%Y-%m-%d")
        base = p.get("id") or dt.datetime.fromtimestamp(p["ts"], dt.timezone.utc).strftime("%Y%m%d-%H%M")
        seen[base] = seen.get(base, 0) + 1
        p["id"] = base if seen[base] == 1 else f"{base}-{seen[base]}"
    return posts


def alt_from(caption: str, date: str) -> str:
    """A starting point for the alt text: the caption's first sentence, without hashtags, handles or emoji."""
    s = re.sub(r"[#@][\w.]+", "", caption)
    s = "".join(ch for ch in s if ord(ch) < 0x2190 or 0x2E80 <= ord(ch) < 0x1F000)
    s = " ".join(re.split(r"(?<=[.!?])\s+|\n+", s.strip())[0].split()).strip(" -–—|·:")
    return s[:120] if len(s) >= 12 else f"A Two Squares project, from the studio's Instagram ({date})"


def thumb(p: Path, size: int):
    from PIL import Image, ImageOps
    if p.suffix.lower() in VID:
        ff = os.environ.get("FFMPEG", shutil.which("ffmpeg") or "ffmpeg")
        with tempfile.TemporaryDirectory() as t:
            out = Path(t) / "f.jpg"
            subprocess.run([ff, "-v", "error", "-y", "-ss", "1", "-i", str(p), "-frames:v", "1", str(out)], capture_output=True)
            if not out.is_file():
                return Image.new("RGB", (size, size), (90, 90, 80))
            im = Image.open(out).convert("RGB")
    else:
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
    return ImageOps.fit(im, (size, size))


def contact_sheets(posts: list[dict], out: Path, per: int = 30, cols: int = 6, size: int = 300) -> list[Path]:
    """Every photo and video as a square tile, labelled with its post id and number (▶ = video)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 15)
    except OSError:
        font = ImageFont.load_default()
    tiles = [(p["id"], n, f) for p in posts for n, f in enumerate(p["files"], 1)]
    sheets = []
    for s in range(0, len(tiles), per):
        chunk = tiles[s:s + per]
        rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * size, rows * (size + 24)), (242, 236, 223))
        draw = ImageDraw.Draw(sheet)
        for i, (pid, n, f) in enumerate(chunk):
            x, y = (i % cols) * size, (i // cols) * (size + 24)
            sheet.paste(thumb(f, size - 6), (x + 3, y + 3))
            draw.text((x + 6, y + size), f"{pid} #{n}{'  ▶ video' if f.suffix.lower() in VID else ''}", fill=(42, 42, 29), font=font)
        dst = out / f"sheet-{s // per + 1:02d}.jpg"
        sheet.save(dst, "JPEG", quality=78)
        sheets.append(dst)
    return sheets


def cmd_list(a) -> None:
    root, tmp = open_export(Path(a.export).expanduser())
    try:
        posts = read_posts(root)
        out = Path(a.out).expanduser()
        out.mkdir(parents=True, exist_ok=True)
        catalog = [{"id": p["id"], "date": p["date"], "kind": p["kind"], "caption": p["caption"],
                    "photos": sum(f.suffix.lower() in IMG for f in p["files"]),
                    "videos": [duration(f) for f in p["files"] if f.suffix.lower() in VID],
                    "files": [str(f.relative_to(root)) for f in p["files"]]} for p in posts]
        (out / "catalog.json").write_text(json.dumps(catalog, indent=1, ensure_ascii=False))
        sheets = contact_sheets(posts, out) if not a.no_sheets else []
        n_img = sum(c["photos"] for c in catalog); n_vid = sum(len(c["videos"]) for c in catalog)
        print(f"{len(catalog)} posts · {n_img} photos · {n_vid} videos → {out / 'catalog.json'}"
              + (f" and {len(sheets)} contact sheet(s)" if sheets else ""))
        for c in catalog[: a.show]:
            print(f"  {c['id']}  {c['kind']:<5} {c['photos']}p {len(c['videos'])}v  {' '.join(c['caption'].split())[:70]}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def cmd_add(a) -> None:
    import build_media, encode_video
    root, tmp = open_export(Path(a.export).expanduser())
    try:
        posts = {p["id"]: p for p in read_posts(root)}
        missing = [i for i in a.ids if i not in posts]
        if missing:
            sys.exit(f"not in this export: {', '.join(missing)} (run `list` for the ids)")
        for pid in a.ids:
            p = posts[pid]
            alt = alt_from(p["caption"], p["date"])
            for n, f in enumerate(p["files"], 1):
                if f.suffix.lower() in IMG:
                    if a.videos_only:
                        continue
                    slug = f"ig-{pid}-{n}"
                    rec, old = build_media.build(f, slug, alt, None)
                    print(f"  photo {slug}: {rec['w']}x{rec['h']} ({rec['ratio']})"
                          + (f", placeholder updated on {build_media.refresh_pages(old, rec)} page(s)" if old else ""))
                elif not a.photos_only:
                    name = f"ig-{pid}-v{n}"
                    length = min(duration(f) or a.length, a.length)
                    print(f"  video {name}: {length}s")
                    encode_video.encode(str(f), name, False, None, length, True)
        print("done. Alt text starts from each caption: check it in assets/img/photos/media.json.")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list", help="catalogue the export and draw contact sheets (changes nothing)")
    l.add_argument("export", help="the Instagram .zip, its unzipped folder, or a plain folder of photos and videos")
    l.add_argument("--out", default="instagram-review", help="where catalog.json and the sheets go")
    l.add_argument("--show", type=int, default=40, help="how many posts to print")
    l.add_argument("--no-sheets", action="store_true")
    l.set_defaults(run=cmd_list)
    d = sub.add_parser("add", help="add posts to the site by id")
    d.add_argument("export"); d.add_argument("ids", nargs="+")
    d.add_argument("--length", type=float, default=12, help="longest loop, in seconds (default 12)")
    g = d.add_mutually_exclusive_group()
    g.add_argument("--photos-only", action="store_true"); g.add_argument("--videos-only", action="store_true")
    d.set_defaults(run=cmd_add)
    a = ap.parse_args()
    a.run(a)
