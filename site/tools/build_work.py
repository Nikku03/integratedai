"""
Render the Work index (work.html) from assets/data/projects.json and the copy deck.
The list is plain, static HTML: it is crawlable, works without JS and reserves its
space before anything loads (zero CLS). work.js only filters, toggles and animates it.

    python3 tools/build_work.py                       # rewrite the generated blocks in work.html
    python3 tools/build_work.py --check               # exit 1 if work.html is out of date
    python3 tools/build_work.py --copy …/copy.json    # re-read the work.* strings from the copy deck

Generated blocks (everything between each pair of markers is replaced):
    <!-- @gen:work-head -->  restore ?filter= and the saved view before first paint, per-filter titles
    <!-- @gen:work-hero -->  headline / intro / CTA variants, stacked in one grid cell (one visible)
    <!-- @gen:work-bar -->   filter radios with counts, and the project count
    <!-- @gen:work -->       the project list (Rows and Grid markup) and the empty state
Images come from tools/media_tag.py (aspect-ratio, width/height, LQIP, focus point).
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SITE / "tools"))
from media_tag import DB as MEDIA, tag as media_tag  # noqa: E402

PAGE = SITE / "work.html"
DATA = SITE / "assets/data/projects.json"
VIEW_KEY = "ts-work-view"

# work.* from the copy deck (research/copy/copy.json), verbatim. Refresh with --copy.
WORK_COPY = json.loads(r'''{
 "seo": {
  "title": "Work — Two Squares Design & Build",
  "description": "Cafés, restaurants, bars and shops designed and built by Two Squares in Bengaluru, Gurugram, Mumbai, New Delhi, Lisbon and Dubai."
 },
 "hero": {
  "eyebrow": "Work",
  "headline": "Every room here has survived a Saturday.",
  "intro": "Designed and built by the same team, then tested by the only people who count: the ones who come back. Filter by what you’re opening."
 },
 "filterLabel": "Show",
 "filters": [
  {
   "id": "all",
   "label": "All",
   "headline": "Every room here has survived a Saturday.",
   "intro": "Cafés that earn their living before ten. Dining rooms that turn tables without rushing anyone. Bars built for 1am, and shops you walk slower in. Every project here was drawn and built by the same team, which is why they look like the drawings and why they’re still holding up.",
   "seo": {
    "title": "Work — Two Squares Design & Build",
    "description": "Cafés, restaurants, bars and shops designed and built by Two Squares in Bengaluru, Gurugram, Mumbai, New Delhi, Lisbon and Dubai."
   }
  },
  {
   "id": "cafes",
   "label": "Cafés",
   "headline": "Cafés that earn their living before ten.",
   "intro": "A café is judged at 08:15, with the queue at the door. We plan the counter first — order, make, pick-up, bin — so two baristas can do the work of three. Then the room: seats for laptops and for prams, daylight on the pastry case, power where people actually sit, and a corner table someone will claim every morning.",
   "cta": "Talk about your café",
   "seo": {
    "title": "Café design & build — Two Squares",
    "description": "Cafés, bakeries and espresso bars designed and built by Two Squares: counters planned for the morning rush, rooms that hold the afternoon."
   }
  },
  {
   "id": "restaurants",
   "label": "Restaurants",
   "headline": "Dining rooms with a pulse.",
   "intro": "We walk the service before we choose a finish: host to table, table to pass, pass to wash-up. Every metre a server saves is a metre of calm in the room. Then we make it warm: acoustics you can talk over at full covers, banquettes worth waiting for, and light that flatters the food and the faces.",
   "cta": "Talk about your restaurant",
   "seo": {
    "title": "Restaurant design & build — Two Squares",
    "description": "Restaurants designed and built by Two Squares: plans drawn around the service, acoustics for full covers and light that flatters food and faces."
   }
  },
  {
   "id": "bars",
   "label": "Bars",
   "headline": "Rooms built for late.",
   "intro": "Everything in a bar faces one way. We design the back-bar as the stage and the room as the audience, draw the stations with your head bartender, and put the lighting on scenes so the room changes without anyone touching a switch. Finishes are chosen for citrus, sugar and 2am.",
   "cta": "Talk about your bar",
   "seo": {
    "title": "Bar design & build — Two Squares",
    "description": "Cocktail bars and late rooms designed and built by Two Squares: back-bars lit as the stage, stations drawn with your bartenders, finishes that last."
   }
  },
  {
   "id": "retail",
   "label": "Retail",
   "headline": "Retail you walk slower in.",
   "intro": "A shopfront gets about three seconds with someone walking past at 4 km/h. We design for those three seconds, then for the walk to the back wall, then for the till. Fixtures that disappear, light that renders colour truthfully, and kits of parts that travel to the next city.",
   "cta": "Talk about your shop",
   "seo": {
    "title": "Retail design & build — Two Squares",
    "description": "Shops, flagships and roll-out formats designed and built by Two Squares: shopfronts that stop people, fixtures that disappear, colour-true light."
   }
  }
 ],
 "cardMeta": "{type} · {city} · {year}",
 "cardCta": "View project",
 "count": {
  "many": "{n} projects",
  "one": "1 project"
 },
 "empty": {
  "text": "Nothing to show here yet. Ask us about the ones we can’t publish.",
  "link": "Ask us"
 },
 "bottomCta": {
  "headline": "Don’t see your kind of room?",
  "body": "Hotel lobbies, bakeries, kiosks, a counter in a food hall. If people eat, drink or shop in it, we’d like to see the plan.",
  "button": "Start a project"
 }
}''')

# One italic accent per headline (DESIGN §2). The words stay verbatim; only the emphasis is ours.
EMPHASIS = {
    "all": "Saturday",
    "cafes": "before ten",
    "restaurants": "pulse",
    "bars": "late",
    "retail": "slower",
    "bottom": "kind of room",
}
# contact.html prefill (COPY.md: /contact?venue=&service=&stage=&from=)
VENUE = {"cafes": "cafe", "restaurants": "restaurant", "bars": "bar", "retail": "shop"}
ALIASES = {"cafe": "cafes", "café": "cafes", "cafés": "cafes", "restaurant": "restaurants",
           "bar": "bars", "shop": "retail", "shops": "retail", "store": "retail", "stores": "retail"}
DOT = {"all": "var(--green)", "cafes": "var(--cafe)", "restaurants": "var(--restaurant)",
       "bars": "var(--bar)", "retail": "var(--retail)"}

esc = lambda s: html.escape(s, quote=True)


def emphasise(text: str, phrase: str | None) -> str:
    out = esc(text)
    if phrase and phrase in text:
        p = esc(phrase)
        out = out.replace(p, f"<em>{p}</em>", 1)
    return out


def nobreak(markup: str) -> str:
    """Keep hyphenated words (pick-up, back-bar) on one line. SplitText measures whole words,
    so a word the browser breaks at its hyphen would wrap differently while split and jump on revert."""
    return re.sub(r"(?<![\w-])(\w+(?:-\w+)+)(?![\w-])", r'<span class="work-nb">\1</span>', markup)


def ratio(slug: str) -> float:
    m = MEDIA[slug]
    return m["w"] / m["h"]


def count_text(n: int) -> str:
    c = WORK_COPY["count"]
    return c["one"] if n == 1 else c["many"].replace("{n}", str(n))


def short_alt(slug: str) -> str:
    """media.json alts are literal and sometimes long; keep one clause under 125 characters (altText.rules)."""
    a = MEDIA[slug]["alt"].strip()
    if len(a) <= 125:
        return a
    cut = a[:125]
    for sep in ("; ", ", "):
        i = cut.rfind(sep)
        if i > 40:
            return cut[:i]
    return cut[: cut.rfind(" ")]


def figure(slug, *, sizes, cls, eager=False, high=False, ratio_override=None, style_extra="", alt=None, indent=""):
    """media_tag.py markup + page hooks (class, reveal, extra custom properties)."""
    alt = short_alt(slug) if alt is None else alt
    fig = media_tag(slug, sizes=sizes, ratio=ratio_override, eager=eager, reveal=True, cls=cls, alt=alt, indent=indent)
    if eager and not high:
        fig = fig.replace(' fetchpriority="high"', "")
    if style_extra:
        fig = fig.replace('style="', f'style="{style_extra}; ', 1)
    return fig


def rows_sizes(rs: list[float], i: int) -> str:
    tot = sum(rs)
    desk = max(8, round(69 * rs[i] / tot) + 1)
    tab = max(10, round(92 * rs[i] / tot) + 1)
    phone = 100 if i == 0 else max(20, round(90 * rs[i] / (tot - rs[0])) + 1)
    return f"(max-width: 600px) {phone}vw, (max-width: 1199px) {tab}vw, {desk}vw"


def item(p: dict, idx: int, first: bool) -> str:
    slug, name, url = p["slug"], p["name"], p["url"]
    meta = WORK_COPY["cardMeta"].replace("{type}", p["type"]).replace("{city}", p["city"]).replace("{year}", p["year"])
    rows = p["images"]["rows"]
    rs = [ratio(s) for s in rows]
    I = "      "
    figs = []
    for i, s in enumerate(rows):
        extra = f"--r:{rs[i]:.4f}"
        cls = "work-item__img"
        if i == 0:
            cls += " work-item__lead"
            extra += f"; view-transition-name:proj-{slug}"
        figs.append(figure(s, sizes=rows_sizes(rs, i), cls=cls, eager=first, high=first and i == 0,
                           style_extra=extra, indent=I + "    "))
    loop = p.get("loop")
    video = ""
    if loop:
        video = (f'{I}    <video class="work-item__loop" muted loop playsinline preload="none" aria-hidden="true" tabindex="-1"\n'
                 f'{I}           data-src="assets/video/{loop}-sm" data-poster="assets/video/posters/{loop}-sm-poster.jpg"></video>\n')
    cover = figure(p["images"]["cover"], sizes="(max-width: 600px) 92vw, (max-width: 900px) 46vw, 30vw",
                   cls="work-item__cover", ratio_override="4/5", indent=I + "  ")
    cover = cover.replace("\n" + I + "  </figure>", "\n" + video + I + "  </figure>") if video else cover
    accent = p.get("accent") or p["filter"]
    return f'''  <li class="work-item" data-filter="{esc(p["filter"])}" data-slug="{esc(slug)}" style="--accent:var(--{esc(accent)})">
    <article class="work-item__inner" aria-labelledby="work-{esc(slug)}">
      <div class="work-item__text" data-reveal-group>
        <p class="work-item__index t-label" data-reveal><span class="work-item__num">{idx:02d}</span><span class="work-item__tick" aria-hidden="true"></span><span class="work-item__sector">{esc(p["sector"])}</span></p>
        <h2 class="work-item__name" id="work-{esc(slug)}" data-reveal><a class="work-item__link" href="{esc(url)}" data-cursor="View">{esc(name)}</a></h2>
        <p class="work-item__meta" data-reveal>{esc(meta)}</p>
        <p class="work-item__line" data-reveal>{esc(p["oneLiner"])}</p>
        <p class="work-item__cta" aria-hidden="true" data-reveal><span class="work-item__cta-txt">{esc(WORK_COPY["cardCta"])}</span> <span class="arr">→</span></p>
      </div>
      <a class="work-item__media" href="{esc(url)}" tabindex="-1" aria-hidden="true" data-cursor="View">
        <div class="work-item__strip" data-reveal-group>
{chr(10).join(figs)}
        </div>
{cover}
      </a>
    </article>
  </li>'''


def build(copy: dict, data: dict) -> dict[str, str]:
    order = data["order"]
    by = {p["slug"]: p for p in data["projects"]}
    projects = [by[s] for s in order if s in by]
    filters = copy["filters"]
    ids = [f["id"] for f in filters]
    counts = {f["id"]: (len(projects) if f["id"] == "all" else sum(p["filter"] == f["id"] for p in projects)) for f in filters}

    # ---- head: restore before first paint
    titles = {f["id"]: f["seo"]["title"] for f in filters}
    seo = {f["id"]: {"title": f["seo"]["title"], "description": f["seo"]["description"], "label": f["label"],
                     "countText": count_text(counts[f["id"]])} for f in filters}
    head = f'''<script>
/* work: restore ?filter= and the saved Rows/Grid view before first paint (no layout shift). Generated by tools/build_work.py */
(function (d, w) {{
  var r = d.documentElement, T = {json.dumps(titles, ensure_ascii=False)},
      A = {json.dumps(ALIASES, ensure_ascii=False)}, f = "all", v = "rows", q;
  try {{ q = (new URLSearchParams(w.location.search).get("filter") || "").toLowerCase(); q = A[q] || q; if (T[q]) f = q; }} catch (e) {{}}
  try {{ if (w.localStorage.getItem("{VIEW_KEY}") === "grid") v = "grid"; }} catch (e) {{}}
  r.setAttribute("data-work-filter", f); r.setAttribute("data-work-view", v);
  if (f !== "all") d.title = T[f];
}})(document, window);
</script>
<script type="application/json" id="work-seo">{json.dumps(seo, ensure_ascii=False)}</script>'''

    # ---- hero variants
    t, i, c = [], [], []
    for f in filters:
        fid = f["id"]
        t.append(f'        <span class="work-swap__v" data-f="{fid}">{nobreak(emphasise(f["headline"], EMPHASIS.get(fid)))}</span>')
        i.append(f'          <p class="work-swap__v" data-f="{fid}">{nobreak(esc(f["intro"]))}</p>')
        if f.get("cta"):
            href = f"contact.html?venue={VENUE.get(fid, '')}&amp;from=work"
            c.append(f'          <p class="work-swap__v" data-f="{fid}"><a class="work-hero__cta-link" href="{href}">'
                     f'<span>{esc(f["cta"])}</span> <span class="arr" aria-hidden="true">→</span></a></p>')
    hero = f'''<h1 class="work-hero__title t-display-l work-swap" id="work-title" data-swap="title">
{chr(10).join(t)}
      </h1>
      <div class="work-hero__side" data-reveal data-delay="0.2">
        <div class="work-hero__intro t-body work-swap" data-swap="intro">
{chr(10).join(i)}
        </div>
        <div class="work-hero__cta work-swap" data-swap="cta">
{chr(10).join(c)}
        </div>
      </div>'''

    # ---- bar: filters + count
    radios = []
    for f in filters:
        fid, n = f["id"], counts[f["id"]]
        checked = " checked" if fid == "all" else ""
        radios.append(
            f'    <label class="work-filter" data-f="{fid}" style="--dot:{DOT.get(fid, "var(--green)")}">'
            f'<input class="work-filter__input" type="radio" name="work-filter" value="{fid}" autocomplete="off"{checked}>'
            f'<span class="work-filter__txt"><span class="work-filter__dot" aria-hidden="true"></span>{esc(f["label"])}'
            f'<sup class="work-filter__n" aria-hidden="true">{n:02d}</sup></span>'
            f'<span class="sr-only qa-ignore-overlap">, {esc(count_text(n))}</span></label>')
    cnt = [f'    <span class="work-swap__v" data-f="{fid}">{esc(count_text(counts[fid]))}</span>' for fid in ids]
    bar = f'''<div class="work-filters" role="radiogroup" aria-labelledby="work-filters-label">
    <span class="work-filters__label t-label" id="work-filters-label">{esc(copy["filterLabel"])}</span>
{chr(10).join(radios)}
  </div>
  <p class="work-count t-label work-swap" data-swap="count" aria-hidden="true">
{chr(10).join(cnt)}
  </p>'''

    # ---- list
    items = [item(p, n + 1, n == 0) for n, p in enumerate(projects)]
    empty = copy["empty"]
    text = empty["text"]
    lst = f'''<ol class="work-list" id="work-list" aria-label="Projects">
{chr(10).join(items)}
</ol>
<div class="work-empty" id="work-empty">
  <p class="work-empty__text t-display-s">{esc(text)}</p>
  <a class="work-empty__link btn" href="contact.html?from=work">{esc(empty["link"])} <span class="arr" aria-hidden="true">→</span></a>
</div>'''
    # ---- bottom CTA
    b = copy["bottomCta"]
    cta = f'''<section class="work-cta section on-sand" aria-labelledby="work-cta-title">
    <div class="wrap grid work-cta__grid">
      <h2 class="work-cta__title t-display-l" id="work-cta-title" data-split>{emphasise(b["headline"], EMPHASIS.get("bottom"))}</h2>
      <div class="work-cta__side" data-float="0.6">
        <p class="t-lede" data-reveal>{esc(b["body"])}</p>
        <a class="btn btn--solid" href="contact.html?from=work" data-reveal>{esc(b["button"])} <span class="arr" aria-hidden="true">→</span></a>
      </div>
    </div>
  </section>'''
    return {"work-head": head, "work-hero": hero, "work-bar": bar, "work": lst, "work-cta": cta}


MARK = re.compile(r"(<!-- @gen:(work[\w-]*) -->)(.*?)(<!-- /@gen:\2 -->)", re.S)


def render(src: str, blocks: dict[str, str]) -> str:
    seen = set()

    def repl(m):
        name = m.group(2)
        if name not in blocks:
            raise SystemExit(f"work.html: unknown block '{name}'")
        seen.add(name)
        return f"{m.group(1)}\n{blocks[name]}\n{m.group(4)}"

    out = MARK.sub(repl, src)
    missing = set(blocks) - seen
    if missing:
        raise SystemExit(f"work.html: missing markers for {sorted(missing)}")
    return out


def main():
    global WORK_COPY
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--copy", help="path to the copy deck's copy.json (reads its work.* strings)")
    a = ap.parse_args()
    if a.copy:
        WORK_COPY = json.loads(Path(a.copy).read_text())["work"]
    data = json.loads(DATA.read_text())
    blocks = build(WORK_COPY, data)
    src = PAGE.read_text()
    out = render(src, blocks)
    if a.check:
        print("work.html is up to date" if out == src else "work.html is OUT OF DATE: run tools/build_work.py")
        sys.exit(0 if out == src else 1)
    if out != src:
        PAGE.write_text(out)
    n = len(data["order"])
    print(f"  work.html  {n} projects · blocks: {', '.join(blocks)}")


if __name__ == "__main__":
    main()
