"""
Regenerate index-build.html (Version B of the walk: the rooms build themselves) from index.html
(Version A: the corridor). The two pages differ only in the walk section, its stylesheet and scripts,
so edit index.html and run:

    python3 tools/build_variants.py
"""
import re, subprocess
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]

s = (SITE / "index.html").read_text()
s = re.sub(r"<!-- @partial:corridor -->.*?<!-- /@partial:corridor -->", "<!-- @partial:build -->\n<!-- /@partial:build -->", s, flags=re.S)
s = s.replace('<link rel="stylesheet" href="assets/css/corridor.css">', '<link rel="stylesheet" href="assets/css/build.css">')
s = s.replace('<script src="assets/js/corridor.js" defer></script>', '<script src="assets/js/build.js" defer></script>')
s = s.replace('<script src="assets/js/scrub.js" defer></script>\n', "")          # no scrubbed video in the build
s = s.replace('data-variant="corridor"', 'data-variant="build"', 1)
if '<meta name="robots"' not in s:                                                 # one version in search results
    s = s.replace("</title>", '</title>\n<meta name="robots" content="noindex">', 1)
for needle in ("@partial:build", "build.css", "build.js", "@partial:cafe-seq", "cafe-seq.js", 'data-variant="build"'):
    assert needle in s, f"index.html no longer has what index-build.html needs: {needle}"
(SITE / "index-build.html").write_text(s)
subprocess.run(["python3", str(SITE / "tools/sync_partials.py"), "index.html", "index-build.html"], check=True)
