"""
Print correct, CLS-safe markup for a photo in assets/img/photos/media.json.

    python3 tools/media_tag.py SLUG [--sizes "(max-width: 900px) 100vw, 50vw"] [--ratio 4/5]
                                    [--eager] [--reveal] [--class extra] [--alt "…"] [--root ../]

--ratio crops the figure to a different aspect ratio (object-fit: cover, using the
image's focus point); otherwise the image's own ratio is used. --eager is for the
first-viewport image (fetchpriority=high, no lazy). --reveal adds data-reveal="image".
"""
import argparse, json
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
DB = json.loads((SITE / "assets/img/photos/media.json").read_text())

def tag(slug, sizes="(max-width: 900px) 100vw, 60vw", ratio=None, eager=False, reveal=False, cls="", alt=None, root="", indent=""):
    m = DB[slug]
    r = ratio or m["ratio"]
    a = (m["alt"] if alt is None else alt).replace('"', "&quot;")
    base = f"{root}assets/img/photos/{slug}"
    attrs = ' loading="eager" fetchpriority="high"' if eager else ' loading="lazy"'
    klass = "media" + ((" " + cls) if cls else "")
    rev = ' data-reveal="image"' if reveal else ""
    fig = f'{indent}<figure class="{klass}"{rev} style="aspect-ratio:{r}; --lqip:url({m["lqip"]}); --focus:{m["focus"]}">\n'
    fig += (f'{indent}  <img src="{base}-1600.webp" srcset="{base}-800.webp 800w, {base}-1600.webp 1600w" sizes="{sizes}"\n'
            f'{indent}       width="{m["w"]}" height="{m["h"]}" alt="{a}"{attrs} decoding="async">\n')
    fig += f"{indent}</figure>"
    return fig

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("slug"); ap.add_argument("--sizes", default="(max-width: 900px) 100vw, 60vw")
    ap.add_argument("--ratio"); ap.add_argument("--eager", action="store_true"); ap.add_argument("--reveal", action="store_true")
    ap.add_argument("--class", dest="cls", default=""); ap.add_argument("--alt"); ap.add_argument("--root", default="")
    a = ap.parse_args()
    print(tag(a.slug, a.sizes, a.ratio, a.eager, a.reveal, a.cls, a.alt, a.root))
