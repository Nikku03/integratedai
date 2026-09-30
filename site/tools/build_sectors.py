#!/usr/bin/env python3
"""
Render the four sector pages — cafes.html, restaurants.html, bars.html, retail.html — from one template.

    python3 tools/build_sectors.py                  # every sector
    python3 tools/build_sectors.py cafes bars       # just these
    python3 tools/build_sectors.py --copy PATH      # refresh the deck strings in sectors.json from copy.json first

Data     assets/data/sectors.json     per sector: hero copy (deck: work.filters), the four needs, projects,
                                      services, quote, FAQs, CTA; shared labels, services and FAQs (deck)
         assets/data/projects.json    the projects (name, meta, hero image, quote)
Markup   templates/sector.html        string.Template ($name); the repeating blocks are built here
Images   tools/media_tag.py           CLS-safe <figure class="media"> (aspect-ratio, LQIP, focus)
Chrome   tools/sync_partials.py       head/header/footer/scripts, the venue's build partial and (café) cafe-seq

Pure standard library. The pages are plain HTML afterwards: no build step is needed to deploy them.
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
from media_tag import DB, tag  # noqa: E402

ROOT = ""
TEMPLATE = SITE / "templates" / "sector.html"
DATA = SITE / "assets" / "data" / "sectors.json"
PROJECTS = SITE / "assets" / "data" / "projects.json"

# media.json alt text runs long for a few of these; the same literal voice, shorter
ALT = {
    "rest-c-06-table-detail": "Plates of food and a yellow cocktail on a weathered dark timber table",
    "rest-c-05-dark-stair-bar": "A dark bar under a row of glowing pendants, the stair beyond",
    "people-01-bar-counter-couple": "Guests at a warm-lit bar counter, a bartender working behind it",
    "front-09-shop-pink-facade": "A pink stone shopfront with a dark green panelled door",
    "retailA-03-fitting-corner-rattan": "Fitting corner: terracotta niches, cream curtains to the floor and a rattan chair",
    "retailA-04-cutting-table-fabrics": "A cutting table with open shelves packed with rolls of pink, navy and cream fabric",
    "rest-a-04-green-door-detail": "A sage-green panelled door opening onto the dining room",
    "cafe-b-01-window-bar-stools": "A small café window bar with leather stools and sunlight striping a slatted wall",
    "single-01-green-cafe-stools": "A café window bar with sage-green French doors, a timber ledge and stools",
    "window-01-arched-window-table": "A round marble table and bentwood chairs under a tall arched window",
    "cafe-b-02-timber-counter-cake": "A slice of layered honey cake on a pale timber counter",
    "people-03-dinner-table-warm": "Hands over a timber bistro table with red wine, bread and cheese",
    "rest-b-03-teal-booths": "Teal quilted leather booths under white arched dividers",
    "material-10-slatted-timber-pendants": "Three slatted timber pendants glowing warm against a dark background",
    "bar-a-05-cocktail-banquette": "A crimson cocktail in a cut-glass coupe on a black lacquered ledge",
    "build-01-hand-plane": "A joiner shaping a hardwood plank at the workshop bench",
}
# work.html?filter=<id> ids for the four pages (the Work index's filter chips)
FILTER = {"cafes": "cafes", "restaurants": "restaurants", "bars": "bars", "retail": "retail"}


# ------------------------------------------------------------------ helpers
def esc(s) -> str:
    return html.escape(str(s), quote=False)


def attr(s) -> str:
    return html.escape(str(s), quote=True)


def md(s: str) -> str:
    """escape, then *accent* → <em>accent</em> (one per headline)"""
    return re.sub(r"\*(.+?)\*", r"<em>\1</em>", esc(s))


def plain(s: str) -> str:
    return s.replace("*", "")


def indent(block: str, n: int) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in block.splitlines())


def figure(slug, sizes, *, ratio=None, eager=False, reveal=True, cls="", alt=None, style="", attrs="", ind=0):
    out = tag(slug, sizes, ratio, eager, reveal, cls, ALT.get(slug) if alt is None else alt, ROOT)
    if style:
        out = out.replace(' style="', f' style="{style} ', 1)
    if attrs:
        out = out.replace("<figure ", f"<figure {attrs} ", 1)
    return indent(out, ind)


def qs(**kw) -> str:
    return "&".join(f"{k}={v}" for k, v in kw.items() if v)


def contact(**kw) -> str:
    return f"{ROOT}contact.html?" + qs(**kw)


def meta_line(parts) -> str:
    """segments never break inside; each carries its '·' in front of it, hung in the gap (sector.css), and a
    line that starts with a segment clips its dot — so no line ends on, or starts with, a dangling separator"""
    sep = '<span class="sep" aria-hidden="true">·</span>'
    return " ".join(f'<span class="seg">{sep if i else ""}{esc(x)}</span>' for i, x in enumerate(parts))


def intro_html(text: str) -> str:
    """the hero intro: the first sentence always shows; the rest is tucked away on phones (sector.css keeps it for
    screen readers). The page's "What a … needs" section carries the same points in full."""
    m = re.search(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    if not m or m.start() < 24:
        return esc(text)
    lead, rest = text[:m.start()], text[m.end():]
    return f'{esc(lead)}<span class="sector-hero__more"> {esc(rest)}</span>'


# ------------------------------------------------------------------ blocks
def film_note(s, L):
    if s.get("ownFootage"):
        return ""
    return f'        <span class="t-label sector-hero__note">{esc(L["filmNote"])}</span>\n'


def needs(s):
    out = []
    for i, p in enumerate(s["needs"]["points"]):
        n = i + 1
        if p.get("video"):
            name, vid = p["video"], f"need-film-{n}"
            fig = f"""<figure class="media sector-need__media" data-reveal="image" style="aspect-ratio:4/5">
  <video id="{vid}" data-autoplay data-src="{ROOT}assets/video/{name}-sm"
         poster="{ROOT}assets/video/posters/{name}-sm-poster.jpg"
         muted loop playsinline preload="none" aria-hidden="true"></video>
  <button class="film-toggle film-toggle--sm" type="button" data-video-toggle="#{vid}" aria-pressed="true"><span class="film-toggle__icon" aria-hidden="true"></span><span class="sr-only">Play video</span></button>
</figure>"""
            fig = indent(fig, 8)
        else:
            fig = figure(p["image"], "(max-width: 600px) 100vw, (max-width: 900px) 50vw, 25vw", ratio="4/5",
                         reveal=True, cls="sector-need__media", ind=8)
        out.append(f"""      <li class="sector-need sector-need--{n}">
{fig}
        <div class="sector-need__text" data-float="0.5">
          <p class="t-label sector-need__num" aria-hidden="true">{n:02d}</p>
          <h3 class="t-display-s sector-need__title">{esc(p['title'])}</h3>
          <p class="t-small muted sector-need__body">{esc(p['text'])}</p>
        </div>
      </li>""")
    return "\n".join(out)


def projects(s, by_slug, L):
    slugs = s["projects"]["slugs"]
    one = len(slugs) == 1
    out = []
    for i, slug in enumerate(slugs):
        p = by_slug[slug]
        hero = p["images"]["hero"]
        if one:
            ratio, sizes = "3/2", "(max-width: 900px) 100vw, 62vw"
        else:
            ratio = "3/2" if i == 0 else "4/5"
            sizes = "(max-width: 900px) 100vw, 54vw" if i == 0 else "(max-width: 900px) 100vw, 36vw"
        # decorative: the heading link names the project; the name matches the case hero (shared-element morph)
        fig = figure(hero, sizes, ratio=ratio, cls="sector-project__media", alt="",
                     style=f"view-transition-name:proj-{slug};", attrs='aria-hidden="true"', ind=8)
        meta = meta_line([p["type"], p["city"], p["year"]])
        out.append(f"""      <li class="sector-project sector-project--{i + 1}">
{fig}
        <div class="sector-project__text">
          <p class="t-label sector-project__meta">{meta}</p>
          <h3 class="t-display-m sector-project__name"><a class="sector-project__link" href="{ROOT}work/{slug}.html">{esc(p['name'])}</a></h3>
          <p class="t-body muted sector-project__line">{esc(p['oneLiner'])}</p>
          <p class="sector-project__cta t-small" aria-hidden="true">{esc(L['viewProject'])} <span class="arr">→</span></p>
        </div>
      </li>""")
    return "\n".join(out)


def menu_items(s, services, L):
    out = []
    for sid in s["menu"]["items"]:
        it = services[sid]
        pre = it.get("prefill", {})
        href = contact(venue=s["venue"], service=pre.get("service"), stage=pre.get("stage"), **{"from": "services"}, item=sid)
        out.append(f"""          <li class="sector-menu__item" data-reveal>
            <div class="sector-menu__main">
              <h3 class="t-display-s sector-menu__name">{esc(it['name'])}</h3>
              <p class="t-small muted sector-menu__desc">{esc(it['description'])}</p>
            </div>
            <p class="t-small sector-menu__time"><span class="t-label">{esc(L['duration'])}</span> {esc(it['duration'])}</p>
            <a class="btn btn--sm sector-menu__order" href="{attr(href)}">{esc(L['itemCta'])}<span class="sr-only">: {esc(it['name'])}</span> <span class="arr" aria-hidden="true">→</span></a>
          </li>""")
    return "\n".join(out)


def quote_figure(s):
    return figure(s["quote"]["image"], "(max-width: 900px) 70vw, 32vw", ratio="1/1", cls="blob sector-quote__media", ind=6)


def faq(s, items):
    out = []
    for i, k in enumerate(s["faq"]):
        f = items[k]
        badge = ('<p class="badge badge--placeholder sector-faq__badge"><span class="badge__dot" aria-hidden="true"></span>'
                 '<span>Placeholder</span></p>') if f.get("placeholder") else ""
        out.append(f"""        <details class="sector-faq__item" data-reveal>
          <summary class="sector-faq__q"><span class="t-display-s">{esc(f['q'])}</span><span class="sector-faq__icon" aria-hidden="true"></span></summary>
          <div class="sector-faq__a"><p class="t-body muted">{esc(f['a'])}</p>{badge}</div>
        </details>""")
    return "\n".join(out)


def others(s, all_sectors):
    out = []
    for o in sorted(all_sectors, key=lambda x: x["time"]):          # time-of-day order, as in the nav
        if o["id"] == s["id"]:
            continue
        out.append(f"""        <li><a class="sector-others__link" href="{ROOT}{o['file']}" style="--accent: var(--{o['accent']})">
          <span class="sector-others__thumb"><img src="{ROOT}assets/img/sectors/{o['id']}-thumb.webp" alt="" width="240" height="300" loading="lazy" decoding="async"></span>
          <span class="sector-others__text"><span class="t-label sector-others__time">{esc(o['time'])}</span><span class="sector-others__name">{esc(o['label'])}</span></span>
          <span class="sector-others__arr" aria-hidden="true">→</span>
        </a></li>""")
    return "\n".join(out)


# ------------------------------------------------------------------ page
def render(s, data, by_slug, tpl):
    sh = data["shared"]
    L = sh["labels"]
    q = by_slug[s["quote"]["project"]]
    cafe = s["build"] == "cafe"
    walk = contact(venue=s["venue"], service="feasibility", stage="looking", **{"from": "sector"})
    values = {
        "title": attr(s["seo"]["title"]),
        "description": attr(s["seo"]["description"]),
        "og_image": attr(f"{ROOT}assets/video/posters/{s['video']}-poster.jpg"),
        "id": attr(s["id"]),
        "accent": attr(s["accent"]),
        "video": attr(s["video"]),
        "time": esc(s["time"]),
        "label": esc(s["label"]),
        "film_note": film_note(s, L),
        "headline": md(s["headline"]),
        "intro": intro_html(s["intro"]),
        "walk_href": attr(walk),
        "walk_label": esc(L["walk"]),
        "see_work": esc(L["seeWork"]),
        "needs_label": esc(s["needs"]["label"]),
        "needs_headline": md(s["needs"]["headline"]),
        "needs_lede": esc(L["needsLede"]),
        "needs": needs(s),
        "build": s["build"],
        "cafe_seq": "<!-- @partial:cafe-seq -->\n<!-- /@partial:cafe-seq -->\n" if cafe else "",
        "project_count": str(len(s["projects"]["slugs"])),
        "projects_label": esc(s["projects"]["label"]),
        "projects_headline": md(s["projects"]["headline"]),
        "projects_all": esc(L["projectsAll"]),
        "projects_all_href": attr(f"{ROOT}work.html?filter={FILTER[s['id']]}"),
        "projects": projects(s, by_slug, L),
        "menu_label": esc(L["menuLabel"]),
        "menu_headline": md(s["menu"]["headline"]),
        "menu_lede": esc(s["menu"]["lede"]),
        "menu_all": esc(L["menuAll"]),
        "menu_sheet": esc(L["menuSheet"]),
        "menu_items": menu_items(s, sh["services"], L),
        "quote_figure": quote_figure(s),
        "quote_label": esc(L["quoteLabel"]),
        "quote_text": f"“{esc(q['quote']['text'])}”",
        "quote_by": esc(q["quote"]["attribution"]),
        "quote_href": attr(f"{ROOT}work/{q['slug']}.html"),
        "read_project": esc(L["readProject"]),
        "faq_label": esc(L["faqLabel"]),
        "faq_headline": md(L["faqHeadline"]),
        "faq_all": esc(L["faqAll"]),
        "faq": faq(s, sh["faq"]),
        "cta_headline": md(s["cta"]["headline"]),
        "cta_body": esc(L["ctaBody"]),
        "cta_button": esc(s["cta"]["button"]),
        "cta_href": attr(contact(venue=s["venue"], **{"from": "sector"})),
        "others_label": esc(L["others"]),
        "others": others(s, [x for x in data["sectors"]]),
        "extra_css": '<link rel="stylesheet" href="assets/css/cafe-seq.css">\n' if cafe else "",
        "extra_js": '<script src="assets/js/cafe-seq.js" defer></script>\n' if cafe else "",
    }
    return tpl.substitute(values)


def load_template() -> Template:
    src = TEMPLATE.read_text()
    src = re.sub(r"(<!-- @partial:(\w[\w-]*) -->).*?(<!-- /@partial:\2 -->)", r"\1\n\3", src, flags=re.S)
    return Template(src)


def refresh_from_deck(data, deck_path):
    """copy the deck strings (verbatim) back into sectors.json: hero copy, services and FAQs"""
    deck = json.loads(Path(deck_path).read_text())
    filters = {f["id"]: f for f in deck["work"]["filters"]}
    for s in data["sectors"]:
        f = filters[s["id"]]
        if plain(s["headline"]) != f["headline"]:
            print(f"  note: {s['id']} headline changed in the deck — re-mark its *accent*: {f['headline']}")
            s["headline"] = f["headline"]
        s["intro"], s["cta"]["button"], s["seo"] = f["intro"], f["cta"], f["seo"]
    for sec in deck["services"]["card"]["sections"]:
        for it in sec["items"]:
            if it["id"] in data["shared"]["services"]:
                data["shared"]["services"][it["id"]] = {k: it[k] for k in ("name", "description", "includes", "duration", "prefill")}
    by_q = {v["q"]: k for k, v in data["shared"]["faq"].items()}
    for it in deck["services"]["faq"]["items"]:
        k = by_q.get(it["q"])
        if k:
            data["shared"]["faq"][k] = {"q": it["q"], "a": it["a"], **({"placeholder": True} if it.get("placeholder") else {})}
    data["shared"]["labels"]["ctaBody"] = deck["caseStudyTemplate"]["cta"]["body"]
    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--copy", help="copy.json to refresh the deck strings from")
    a = ap.parse_args()
    data = json.loads(DATA.read_text())
    if a.copy:
        refresh_from_deck(data, a.copy)
    by_slug = {p["slug"]: p for p in json.loads(PROJECTS.read_text())["projects"]}
    by_id = {s["id"]: s for s in data["sectors"]}
    want = a.ids or data["order"]
    unknown = [x for x in want if x not in by_id]
    if unknown:
        raise SystemExit(f"unknown sector(s): {', '.join(unknown)}")
    tpl = load_template()
    written = []
    for sid in want:
        s = by_id[sid]
        page = SITE / s["file"]
        page.write_text(render(s, data, by_slug, tpl))
        written.append(s["file"])
    subprocess.run([sys.executable, str(SITE / "tools" / "sync_partials.py"), *written], cwd=SITE, check=True)
    print(f"wrote {len(written)} sector page(s): {', '.join(written)}")


if __name__ == "__main__":
    main()
