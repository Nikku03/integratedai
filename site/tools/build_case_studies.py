#!/usr/bin/env python3
"""
Render the case-study pages, work/<slug>.html, from one template.

    python3 tools/build_case_studies.py                 # every project
    python3 tools/build_case_studies.py ember otla      # just these
    python3 tools/build_case_studies.py --copy PATH     # re-read the labels from the copy deck (copy.json)

Data    assets/data/projects.json   projects[] (copy + images + loop + accent + next) and stagesMaster
Labels  LABELS below, verbatim from copy.json → caseStudyTemplate (--copy refreshes them)
Markup  templates/case.html         string.Template ($name); the repeating blocks are built here
Images  tools/media_tag.py          CLS-safe <figure class="media"> (aspect-ratio, LQIP, focus), root "../"
Chrome  tools/sync_partials.py      run on each generated page (head/header/footer/scripts with ../ links)

Pure standard library. Pages are plain HTML afterwards: no build step is needed to deploy them.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from string import Template

SITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SITE / "tools"))
from media_tag import DB, tag  # noqa: E402  (the one place figure markup is made)

ROOT = "../"                     # pages live in work/, one level down
OUT_DIR = SITE / "work"
TEMPLATE = SITE / "templates" / "case.html"
DATA = SITE / "assets" / "data" / "projects.json"

# copy.json → caseStudyTemplate (verbatim). "What we did" is not in the deck; written in its voice.
LABELS = {
    "backLink": "All work",
    "factLabels": {
        "location": "Location", "type": "Type", "size": "Size", "seats": "Covers / seats",
        "scope": "Scope", "duration": "Duration", "opened": "Opened",
    },
    "sectionHeadings": {
        "brief": "The brief", "move": "The move", "details": "The details", "build": "The build",
        "outcome": "The outcome", "quote": "In their words", "credits": "Credits",
    },
    "creditLabels": {"photography": "Photography", "designAndBuild": "Design & build", "collaborators": "With"},
    "nextLabel": "Next project",
    "placeholderBanner": "Placeholder project. The name, quote and photographs stand in for real work.",
    "cta": {
        "headline": "Opening something like this?",
        "body": "Send us the floor plan and the opening date. We’ll come back with how the room could work.",
        "button": "Start a project",
    },
}
SCOPE_HEADING = "What we did"
FILM_LABEL, FILM_NOTE = "Film", "Placeholder stock footage"

# work.html?filter=<filter> → contact.html?venue=<venue>
VENUE = {"cafes": "cafe", "restaurants": "restaurant", "bars": "bar", "retail": "shop"}

# media.json alt text is a literal description, but some entries run past the 125-character rule
# (cut mid-word at 150) and one is an editing note. Case-study overrides, same literal voice.
ALT = {
    "bar-a-01-red-lounge-wide": "Cocktail bar with oxblood-red walls, black lacquered frames, a chandelier, high timber tables and chesterfield banquettes",
    "bar-a-02-arch-fireplace": "Black walls and a red-lined arch framing a white marble fireplace, velvet ottomans and timber tables on glossy boards",
    "bar-a-04-red-room-bar": "A red room with the bar counter and chandelier in the distance and leather lounge seating in front",
    "material-08-marble-counter-edge": "A long cream marble counter with warm-grey veining running towards a window",
    "cafe-a-01-window-seating-wide": "Cream plaster café with tall black steel glazing, a woven rattan drum table and a peacock-back rattan chair",
    "hero-03-plant-hall-cafe": "Converted-warehouse café: white timber-truss roof, exposed brick, a black steel stair and hanging plants",
    "material-13-travertine-marble-dish": "A dark marble bowl on unfilled travertine beside a stack of linen-bound books",
    "rest-c-01-bookcase-long-table": "Heritage dining room: a carved timber bookcase against grey plaster, bulb pendants and a long set table",
    "retailA-01-boutique-rail-plants": "A bright atelier boutique: garments on a long rail between potted trees on a pale floor",
    "retailA-02-fitting-curtains": "Fitting area with terracotta-pink niches behind heavy cream linen curtains, a rattan chair and a ficus",
    "retailA-06-atelier-workroom": "Atelier workroom: a timber thread-rack wall, white cutting tables and an oak table with sewing chairs",
    "retailA-03-fitting-corner-rattan": "Fitting corner with terracotta niches, cream curtains, a rattan lounge chair and a ficus on a pale lilac floor",
    "retailA-05-haberdashery-wall": "A wall of thread spools on timber rails, a pothos in macramé and the workroom beyond",
    "retailA-04-cutting-table-fabrics": "A white cutting table on a brass-toned frame, its open shelves packed with pink, navy and cream fabric rolls",
    "rest-a-01-dining-room-banquette": "Bright heritage bistro: white panelling, green shutters, a long black tufted leather banquette and bentwood chairs",
    "rest-a-06-veranda-green-shutters": "Veranda with saffron walls, deep-green louvred shutters, a cast-iron column and cream wicker chairs on checker tiles",
    "window-01-arched-window-table": "A round marble-top table and bentwood chairs under a tall arched window, ivy outside, herringbone parquet",
    "cafe-c-01-counter-shelves-window": "Dark-timber coffee bar: open shelves of glassware, an espresso machine and grinders by a shuttered window",
    "cafe-b-01-window-bar-stools": "Small café: a white slatted wall striped with sunlight, a reclaimed-timber window ledge and leather bar stools",
    "cafe-c-02-window-desk-nook": "Dark stained timber nook with a small desk under a window, a linen curtain and pools of sunlight",
}


# ------------------------------------------------------------------ helpers
def esc(s: str) -> str:
    return html.escape(str(s), quote=False)


def attr(s: str) -> str:
    return html.escape(str(s), quote=True)


def ratio_of(slug: str) -> float:
    m = DB[slug]
    return m["w"] / m["h"]


def orient(slug: str) -> str:
    r = ratio_of(slug)
    return "portrait" if r < 0.95 else "landscape" if r > 1.05 else "square"


def indent(block: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in block.splitlines())


def figure(slug, sizes, *, ratio=None, eager=False, reveal=True, cls="", alt=None, style="", attrs="", ind=0):
    """media_tag.tag() plus page-specific extras (a class, style additions, data attributes)."""
    out = tag(slug, sizes, ratio, eager, reveal, cls, ALT.get(slug) if alt is None else alt, ROOT)
    if style:
        out = out.replace(' style="', f' style="{style} ', 1)
    if attrs:
        out = out.replace("<figure ", f"<figure {attrs} ", 1)
    return indent(out, ind)


def meta_line(parts) -> str:
    """'Cocktail bar · Connaught Place, New Delhi · 2026': each part stays on one line when the row wraps,
    and the dot travels with the part before it, so a wrapped line never starts with one."""
    sep = '<span class="sep" aria-hidden="true">·</span>'
    return " ".join(f'<span class="seg">{esc(x)}{sep if i < len(parts) - 1 else ""}</span>' for i, x in enumerate(parts))


def keep_dots(s: str) -> str:
    """'Concept · Interior design · …': a wrapped line never starts with the dot (no-break space before it)."""
    return s.replace(" · ", "\u00a0· ")


def fact(label: str, value: str, wide: bool = False) -> str:
    klass = "case-facts__item" + (" case-facts__item--wide" if wide else "")
    value = keep_dots(esc(value))
    return (f'<div class="{klass}" data-reveal><dt class="t-label">{esc(label)}</dt>'
            f"<dd>{value}</dd></div>")


# ------------------------------------------------------------------ blocks
def hero_figure(p):
    slug = p["images"]["hero"]
    m = DB[slug]
    # object-fit: cover on a 100svh frame: on tall screens the photo is drawn wider than the viewport
    sizes = f"(max-aspect-ratio: {m['w']}/{m['h']}) calc(100vh * {m['w'] / m['h']:.3f}), 100vw"
    return figure(slug, sizes, eager=True, reveal=False, cls="case-hero__media",
                  style=f"view-transition-name:proj-{p['slug']};", ind=4)


def facts(p):
    L = LABELS["factLabels"]
    size = p["sizeM2"] + (f" · {p['keyFigure']}" if p.get("keyFigure") else "")
    seats = p.get("seats")
    rows = [
        fact(L["location"], f"{p['neighbourhood']}, {p['city']}, {p['country']}"),
        fact(L["type"], p["type"]),
        fact(L["size"], size, wide=not seats),          # no seats (a shop): size takes the fourth cell
    ]
    if seats:
        rows.append(fact(L["seats"], seats))
    rows += [
        fact(L["scope"], " · ".join(p["scope"]), wide=True),
        fact(L["duration"], p["duration"]),
        fact(L["opened"], p["opened"]),
    ]
    return indent("\n".join(rows), 8)


def stages(p, master):
    scope = p["scope"]
    items = [(s, s in scope) for s in master] + [(s, True) for s in scope if s not in master]
    out = []
    for name, done in items:
        if done:
            out.append(f'<li class="case-stages__item is-done" data-reveal><span class="case-stages__tick" aria-hidden="true"></span>'
                       f'<span class="case-stages__name">{esc(name)}</span></li>')
        else:
            # not part of this job: the rest of the menu, ghosted at 30%. Decorative: the delivered stages
            # (and the Scope fact) carry the information, so the name is drawn by CSS from data-label and
            # the row is hidden from assistive tech.
            out.append(f'<li class="case-stages__item is-off" aria-hidden="true" data-reveal><span class="case-stages__tick"></span>'
                       f'<span class="case-stages__name" data-label="{attr(name)}"></span></li>')
    return indent("\n".join(out), 10)


def inset_figure(p):
    g = next(x for x in p["images"]["gallery"] if x["layout"] == "inset")
    slug = g["slugs"][0]
    o = orient(slug)
    ratio = "4/5" if o == "portrait" else None
    sizes = "(max-width: 900px) 100vw, 45vw" if o != "portrait" else "(max-width: 900px) 100vw, 38vw"
    return figure(slug, sizes, ratio=ratio, cls="case-scope__media", ind=6), o


def gallery(p):
    """inset (placed with 'What we did') → full → loop → pair → full, in the order the data gives."""
    blocks, fulls = [], 0
    loop_done = False
    for g in p["images"]["gallery"]:
        lay = g["layout"]
        if lay == "inset":
            continue
        if lay == "full":
            fulls += 1
            f = figure(g["slugs"][0], "100vw", cls="case-full__media", attrs='data-case-parallax="0.06"', ind=2)
            blocks.append(f'<div class="case-full case-full--{fulls}">\n{f}\n</div>')
            if fulls == 1 and p.get("loop"):
                blocks.append(loop(p))
                loop_done = True
        elif lay == "pair":
            a, b = g["slugs"]
            both_portrait = orient(a) == "portrait" and orient(b) == "portrait"
            ratio = "3/4" if both_portrait else "3/2" if orient(a) == orient(b) == "landscape" else "4/5"
            sizes = "(max-width: 900px) 50vw, 46vw"
            fa = figure(a, sizes, ratio=ratio, cls="case-pair__a", ind=4)
            fb = figure(b, sizes, ratio=ratio, cls="case-pair__b", ind=4)
            blocks.append(f'<div class="wrap">\n  <div class="case-pair case-pair--{"portrait" if both_portrait else "landscape"}">\n{fa}\n{fb}\n  </div>\n</div>')
    if p.get("loop") and not loop_done:
        blocks.append(loop(p))
    return indent("\n".join(blocks), 4)


def loop(p):
    name, vid = p["loop"], f"loop-{p['slug']}"
    base = f"{ROOT}assets/video/{name}"
    poster = f"{ROOT}assets/video/posters/{name}"
    return f"""<div class="wrap grid case-loop">
  <figure class="media case-loop__media" data-reveal="image">
    <video id="{vid}" data-autoplay data-src="{base}" data-src-sm="{base}-sm"
           poster="{poster}-poster.jpg" data-poster-sm="{poster}-sm-poster.jpg"
           muted loop playsinline preload="none" aria-hidden="true"></video>
  </figure>
  <div class="case-loop__side" data-float="0.6">
    <p class="case-loop__note"><span class="t-label">{esc(FILM_LABEL)}</span><span class="t-small">{esc(FILM_NOTE)}</span></p>
    <button class="case-loop__toggle" type="button" data-video-toggle="#{vid}" aria-pressed="true"><span class="case-loop__icon" aria-hidden="true"></span><span class="case-loop__word" aria-hidden="true"></span><span class="sr-only">Play video</span></button>
  </div>
</div>"""


def details(p):
    imgs, items = p["images"]["details"], p["details"]
    n = len(items)
    # one frame shape for the sticky column: portrait unless most detail photos are landscape
    land = sum(orient(s) == "landscape" for s in imgs)
    frame_ratio, frame_r = ("5/4", 1.25) if land * 2 > len(imgs) else ("4/5", 0.8)
    stage, lst = [], []
    for i, (d, slug) in enumerate(zip(items, imgs)):
        stage.append(figure(slug, "(max-width: 900px) 1px, 40vw", ratio=frame_ratio, reveal=False,
                            cls="case-details__fig" + (" is-active" if i == 0 else ""), attrs=f'data-i="{i}"', ind=12))
        inline = figure(slug, "(max-width: 600px) 100vw, (max-width: 900px) 50vw, 32vw", ratio=frame_ratio,
                        cls="case-details__inline", ind=10)
        lst.append(f"""        <li class="case-details__item{' is-active' if i == 0 else ''}" data-i="{i}">
{inline}
          <div class="case-details__text">
            <h3 class="t-label case-details__name"><span class="case-details__num">{i + 1:02d}</span>{esc(d['label'])}</h3>
            <p class="t-lede" data-reveal>{esc(d['text'])}</p>
          </div>
        </li>""")
    return "\n".join(stage), "\n".join(lst), frame_ratio, frame_r, f"{n:02d}"


def outcome(p):
    return indent("\n".join(f'<p class="t-display-m case-outcome__line" data-case-split>{esc(s)}</p>' for s in p["outcome"]), 10)


def credits(p):
    L = LABELS["creditLabels"]
    c = p["credits"]
    rows = [f'<div class="case-credits__item" data-reveal><dt class="t-label">{esc(L[k])}</dt><dd>{keep_dots(esc(c[k]))}</dd></div>'
            for k in ("photography", "designAndBuild", "collaborators") if c.get(k)]
    return indent("\n".join(rows), 10)


def next_figure(n):
    # decorative here (the link text names the project); its view-transition name matches the next page's hero
    return figure(n["images"]["hero"], "100vw", reveal=False, cls="case-next__media", alt="",
                  style=f"view-transition-name:proj-{n['slug']};", attrs='aria-hidden="true"', ind=6)


# ------------------------------------------------------------------ page
def render(p, by_slug, master, tpl):
    H = LABELS["sectionHeadings"]
    n = by_slug[p["next"]]
    inset, inset_o = inset_figure(p)
    stage_figs, detail_items, frame_ratio, frame_r, total = details(p)
    back = f"{ROOT}work.html?filter={p['filter']}"
    hero_img = p["images"]["hero"]
    values = {
        "root": ROOT,
        "title": attr(p["seo"]["title"]),
        "description": attr(p["seo"]["description"]),
        "og_image": attr(f"{ROOT}assets/img/photos/{hero_img}-1600.webp"),
        "slug": attr(p["slug"]),
        "accent": attr(p["accent"]),
        "hero_figure": hero_figure(p),
        "back_href": attr(back),
        "back_label": esc(LABELS["backLink"]),
        "name": esc(p["name"]),
        "hero_meta": meta_line([p["type"], f'{p["neighbourhood"]}, {p["city"]}', p["year"]]),
        "placeholder": esc(LABELS["placeholderBanner"]),
        "one_liner": esc(p["oneLiner"]),
        "facts": facts(p),
        "h_brief": esc(H["brief"]), "brief": esc(p["brief"]),
        "h_move": esc(H["move"]), "move_title": esc(p["move"]["title"]), "move_text": esc(p["move"]["text"]),
        "h_scope": esc(SCOPE_HEADING), "stages": stages(p, master),
        "inset_figure": inset, "inset_orient": inset_o,
        "gallery": gallery(p),
        "h_details": esc(H["details"]), "stage_figures": stage_figs, "details": detail_items,
        "frame_ratio": frame_ratio, "frame_r": frame_r, "details_total": total,
        "frame_orient": "landscape" if frame_r > 1 else "portrait",
        "h_build": esc(H["build"]), "build": esc(p["build"]),
        "h_outcome": esc(H["outcome"]), "outcome": outcome(p),
        "h_quote": esc(H["quote"]), "quote_text": f"“{esc(p['quote']['text'])}”", "quote_by": esc(p["quote"]["attribution"]),
        "h_credits": esc(H["credits"]), "credits": credits(p),
        "next_label": esc(LABELS["nextLabel"]), "next_href": attr(f"{n['slug']}.html"),
        "next_figure": next_figure(n), "next_name": esc(n["name"]),
        "next_meta": meta_line([n["type"], n["city"]]),
        "cta_headline": esc(LABELS["cta"]["headline"]), "cta_body": esc(LABELS["cta"]["body"]),
        "cta_button": esc(LABELS["cta"]["button"]),
        "cta_href": attr(f"{ROOT}contact.html?venue={VENUE[p['filter']]}&from=case-study&item={p['slug']}"),
    }
    return tpl.substitute(values)


def load_template() -> Template:
    src = TEMPLATE.read_text()
    # if someone ran sync_partials over templates/, drop the filled chrome: pages get it fresh below
    src = re.sub(r"(<!-- @partial:(\w[\w-]*) -->).*?(<!-- /@partial:\2 -->)", r"\1\n\3", src, flags=re.S)
    return Template(src)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--copy", help="copy.json to read caseStudyTemplate labels from")
    a = ap.parse_args()
    if a.copy:
        LABELS.update(json.loads(Path(a.copy).read_text())["caseStudyTemplate"])
    data = json.loads(DATA.read_text())
    by_slug = {p["slug"]: p for p in data["projects"]}
    order = [s for s in data.get("order", by_slug) if s in by_slug]
    want = a.slugs or order
    unknown = [s for s in want if s not in by_slug]
    if unknown:
        raise SystemExit(f"unknown project(s): {', '.join(unknown)}")
    tpl = load_template()
    OUT_DIR.mkdir(exist_ok=True)
    written = []
    for slug in want:
        page = OUT_DIR / f"{slug}.html"
        page.write_text(render(by_slug[slug], by_slug, data["stagesMaster"], tpl))
        written.append(str(page.relative_to(SITE)))
    subprocess.run([sys.executable, str(SITE / "tools" / "sync_partials.py"), *written], cwd=SITE, check=True)
    print(f"wrote {len(written)} case stud{'y' if len(written) == 1 else 'ies'}: {', '.join(written)}")


if __name__ == "__main__":
    main()
