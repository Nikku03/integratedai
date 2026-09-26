"""
Copy the shared chrome into every page.

    python3 tools/sync_partials.py              # every page
    python3 tools/sync_partials.py index.html   # just these pages

Each page marks where a partial goes with a pair of comments:
    <!-- @partial:header -->  …anything…  <!-- /@partial:header -->
Everything between the markers is replaced by partials/<name>.html, with
{{root}} set to the relative path back to the site root ("" or "../").
Pages stay plain HTML — no build step is needed to deploy them.
"""
from __future__ import annotations
import re
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
PARTIALS = {p.stem: p.read_text() for p in (SITE / "partials").glob("*.html")}
MARK = re.compile(r"(<!-- @partial:(\w[\w-]*) -->)(.*?)(<!-- /@partial:\2 -->)", re.S)

def sync(page: Path) -> int:
    depth = len(page.relative_to(SITE).parts) - 1
    root = "../" * depth
    html = page.read_text()
    n = 0
    def repl(m):
        nonlocal n
        name = m.group(2)
        if name not in PARTIALS:
            raise SystemExit(f"{page}: unknown partial '{name}'")
        n += 1
        body = PARTIALS[name].replace("{{root}}", root).rstrip("\n")
        return f"{m.group(1)}\n{body}\n{m.group(4)}"
    out = MARK.sub(repl, html)
    if out != html:
        page.write_text(out)
    return n

def main():
    import sys
    if sys.argv[1:]:
        pages = [(SITE / a).resolve() if not Path(a).is_absolute() else Path(a) for a in sys.argv[1:]]
    else:
        pages = [p for p in SITE.rglob("*.html") if "partials" not in p.parts and "tools" not in p.parts]
    for p in sorted(pages):
        n = sync(p)
        print(f"  {str(p.relative_to(SITE)):<32} {n} partial(s)")

if __name__ == "__main__":
    main()
