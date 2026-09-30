# Two Squares — Design & Build · website

A static site for a design-and-build studio working on cafés, restaurants, bars and shops.
No framework and no build step: every page is plain HTML, CSS and JavaScript. Upload the `site/`
folder to Netlify (drag and drop) and it works, including the contact form and the old-URL redirects.

> **Prototype.** Project names, quotes, numbers and photographs are stand-ins (licensed stock from
> Pexels, Unsplash and Mixkit, free for commercial use). The café walk-in video is the studio's own.
> See **Before launch** at the end.

The look: olive and beige, soft rounded edges, and a "liquid" feel. Images and text columns float slowly
as you scroll, a few feature images sit in shapes that gently change, and dark bands are rounded panels
set just in from the edge of the screen.

## The site

One home page, four sector pages, and the usual pages around them.

| Page | What's on it |
|---|---|
| `index.html` | **Home.** The hero reel. Then **the build**: a restaurant builds itself as you scroll. The plan draws itself and becomes a pencil sketch. It rises as a white model, takes its joinery, then its finishes, and the lights come on over the real photograph. At each of the seven stages a short **note** pops up beside the build: a number, a promise, a client's words, or "Book a free site walk". It ends on "See the dining rooms" and "Start a project". Next comes **Pick your room**: four floating doorways (café 08:00, shop 11:00, restaurant 14:00, bar 23:00), each opening its sector page. After that: selected work, what we do, how it works, the numbers and a quote, and the closing CTA. |
| `cafes.html` | **Cafés.** The hero plays the studio's own walk-in clip. Below it: what a café needs, and the café build with its notes. The build ends at the corner table, where "Take the corner table" puts the paper **menu card** on the table; each item opens the contact form, prefilled. Then the café projects, the services to order, the client's words, questions and a CTA. |
| `restaurants.html`, `bars.html`, `retail.html` | The same layout for restaurants, bars and shops (retail is labelled **Shops**). Each has its own walk-in clip, its own build, and its own notes, projects, services and questions. |
| `work.html` | Every project. Filters with counts (`?filter=cafes`, `restaurants`, `bars`, `retail`, kept in the URL), a Rows/Grid toggle, loop videos on hover in the grid. |
| `work/<slug>.html` | Six case studies. Each has a hero, facts, the brief and "the move", the stages delivered, photographs and a loop, details, the build, the outcome, an owner quote, credits and the next project. |
| `services.html` | "The menu": the services set as a printed restaurant menu, each item expanding to what's included and "Order this" (prefills the contact form); the five-step process; FAQ. |
| `studio.html` | The studio, opening on "Studio" as a picture frame (the workshop seen through the letters), principles, one contract, team, numbers, clients, careers. |
| `contact.html` | The enquiry form. Prefilled from the menu card, the services menu, the build's notes, the sector pages and case studies, with a one-line banner saying where the visitor came from ("From the café you watched being built"); inline validation; posts to Netlify Forms. |
| `404.html` | "Wrong door." |

The header's **Sectors** button opens a small panel with the four sector pages. The Index overlay and the footer list them too.

## How it's put together

```
site/
├── *.html, work/*.html         the pages (edit index.html and the case-study template directly; the others below are generated)
├── partials/                   shared header, footer, <head> and script tags;
│                               build-cafe|restaurant|bar|retail (one build per venue, generated); cafe-seq (the corner table)
├── templates/                  case.html (case studies), sector.html (sector pages), page.html (skeleton for a new page)
├── assets/
│   ├── css/base.css            design tokens (colours, radii, shadows, type, spacing) and every shared component
│   ├── css/<page>.css          one stylesheet per page, scoped under [data-page="…"]; build.css, cafe-seq.css
│   ├── js/motion.js            the motion engine: smooth scroll, reveals, the liquid float, page transitions
│   ├── js/site.js              header, Sectors panel, menu overlay, cursor, video manager, toasts
│   ├── js/build.js             the build (any page with a build partial)
│   ├── js/cafe-seq.js          the corner table and the menu card (cafes.html)
│   ├── js/<page>.js            page behaviour (home.js, work.js, …)
│   ├── js/vendor/              GSAP 3.15 (ScrollTrigger, SplitText, Flip, CustomEase), Lenis 1.3 — self-hosted
│   ├── data/projects.json      the six projects: copy, facts, which photos and loop each uses
│   ├── data/build.json         the four builds: source photo, regions, plan, site diary, the seven notes, end links
│   ├── data/sectors.json       the four sector pages: headline, points, projects, services, questions
│   ├── img/photos/             photos as <slug>-800.webp / -1600.webp, plus media.json
│   ├── img/build/              the build's rendered layers (sketch, shell, model, dim, lit) per venue
│   ├── video/                  clips as .webm + .mp4, -sm (4:5, phones) versions, posters/
│   └── fonts/                  Instrument Serif and Instrument Sans (self-hosted)
├── tools/                      small Python scripts (below)
├── _redirects                  Netlify: old URLs → their new pages
├── robots.txt, sitemap.xml
```

### Shared header, footer and menu
Edit `partials/header.html`, `footer.html`, `head.html` or `scripts.html`, then copy them into every page:

```bash
python3 tools/sync_partials.py              # all pages
python3 tools/sync_partials.py index.html   # just one
```
A page marks where a partial goes with `<!-- @partial:name -->` … `<!-- /@partial:name -->`. The same command
drops the build partials into the home and sector pages.

### Projects
All six live in `assets/data/projects.json`. After editing it, regenerate the Work list, the case studies and the
sector pages (they list each sector's projects):

```bash
python3 tools/build_work.py
python3 tools/build_case_studies.py
python3 tools/build_sectors.py
```
To add a project, copy an entry, give it a new `slug`, set `filter` (cafes / restaurants / bars / retail),
add the slug to `order`, point `next` at another project, and run the three scripts. Add the new page to `sitemap.xml`.

### Sector pages
`cafes.html`, `restaurants.html`, `bars.html` and `retail.html` are generated from one template
(`templates/sector.html`) and one data file (`assets/data/sectors.json`). The data file holds, per sector, the hero
copy, the four "what a … needs" points, the projects, services, quote, questions and CTA. The project details come from
`projects.json`, and the build comes from the venue's partial. Edit the data or the template, then:

```bash
python3 tools/build_sectors.py                # all four (it also syncs their partials)
python3 tools/build_sectors.py cafes bars     # just these
```
Don't edit the four pages by hand: the next run overwrites them.

### The build
Each venue's build is rendered from **one finished photograph**: a pencil sketch, the empty white shell, the white
model with its joinery, the finishes before the lights, and the lit room. So every stage lines up with the real room.
The regions, plan, site-diary captions, the seven notes, and the end links are in `assets/data/build.json`.

```bash
BUILD_SRC=~/Photos/originals python3 tools/build_layers.py images restaurant   # render the layers (Pillow + numpy)
python3 tools/build_layers.py html restaurant                                # write partials/build-restaurant.html
python3 tools/build_layers.py preview restaurant                             # overlays, for placing the regions
python3 tools/sync_partials.py index.html restaurants.html                   # put it into the pages that use it
```
To use one of your own projects, point the venue's `src` at your photograph (2400px on the long edge, shot straight
on, no people). Redraw its regions using the preview, then run the four commands. The home page uses the restaurant.
Each sector page uses its own venue.

**The notes** (`copy.pops` per venue in `build.json`) are one short line and a label each. Some have an action. Stage
04 always offers "Book a free site walk" (the contact form, prefilled). Keep their numbers in step with `studio.html`
and the home page. To hide a note, delete its entry; the stage still plays.

### Photos
Swap a stand-in for your own photo by keeping its name (the *slug*). Every page that uses it updates:

```bash
python3 tools/build_media.py ~/Photos/our-counter.jpg rest-a-01-dining-room-banquette --alt "The counter at Otla at noon" --focus 0.5,0.45
```
To add a new photo, use a new slug, then print ready-to-paste markup (size reserved, blurred placeholder, lazy loading):
`python3 tools/media_tag.py <slug> --reveal`. Photos should be at least 1600px on the long edge. Needs Pillow (`pip install pillow`).

### Video
```bash
python3 tools/encode_video.py our-cafe.mov hero-cafe --loop --length 9            # a sector page's hero film
python3 tools/encode_video.py pour.mov loop-latte --loop --start 2 --length 8     # an ambient loop
```
Replacing a clip with the same name needs no page edits. Needs ffmpeg. Add `--grade "<ffmpeg filters>"` to use your
own colour grade, and `--out DIR` to compare before replacing. The sector heroes are `hero-cafe` (cut from the studio's
own café walk-in), `hero-restaurant`, `hero-bar` and `hero-retail`: seamless loops whose last second crossfades into the
first. The best replacement for each is your own steady 10–14s walk into a finished room, chosen so its end and start
look alike. (`--scrub` encodes, with a keyframe every 8 frames, are for film that plays as you scroll.)

### Motion, briefly
Add attributes, not code:
- `data-reveal`: fade up.
- `data-reveal="image"`: a rounded curtain reveal on a `.media` figure.
- `data-split`: headline lines rise in.
- `data-parallax="0.15"`.
- `data-count="64"`.
- `data-cursor="View"`.

**Floating.** Every `.media` image floats on its own. Put `data-float` on a text column to make it float too
(`"0.5"` is calmer, `"1.4"` livelier), or `data-float="off"` to stop it. For a slowly changing liquid shape on a
feature image, add `class="blob"`; the home page's doorways use a variant of it. Use it on a few images at most.

With *reduce motion* switched on in the visitor's system settings, all of it is off and everything is simply shown.
The builds become three stills with their notes as a list, and the café sequence goes straight to the menu card.

## Run it locally

```bash
cd site && python3 -m http.server 8000     # then open http://localhost:8000
```
Some browsers want HTTP range requests to seek video. If the clips don't play, use `npx serve site` instead.
The contact form shows its success message locally but only sends once deployed on Netlify.

## Quality checks (at handover)

Every page was tested in Chromium at 1440×900, 1024×1366 and 390×844, and with reduced motion. The results:
- 0 console errors, 0 failed requests, 0 broken links;
- 0 overlapping text, 0 horizontal scroll;
- no serious or critical accessibility issues (axe, WCAG 2.1 AA);
- layout shift under 0.01 everywhere.

Scrolling holds 60fps on phones. On large desktop windows, in a headless browser *without a GPU*, the builds drop a
few frames in their middle stages, where several layers are masked at once. This should be confirmed on real hardware.

## Before launch

- **Photos and video:** replace the stock photos with your own projects (see Photos) and the walk-in clips with your
  own (see Video). Remove the "Placeholder" badges (`badge--placeholder`) and the footer's prototype line
  (`partials/footer.html`).
- **The builds:** each is drawn from a stock photograph. Rebuild them from your own finished rooms (see The build),
  and rewrite the site-diary captions in `build.json`. The dates and figures in them (weeks, m², lux, K) are
  stand-ins.
- **The notes:** check every note in `build.json` is true for the studio: the numbers, the promises (fixed price after
  detail design, one contract, own workshop, dated programme, the 90-day return visit, licences and approvals), and
  the client quotes (from `projects.json`).
- **Projects:** real names, places, facts, quotes and credits in `assets/data/projects.json`, then regenerate.
- **Sector pages:** the points, services and questions in `assets/data/sectors.json`, then run `tools/build_sectors.py`.
- **Studio:** team names and roles, the numbers (64 venues, 9 cities, founded 2016, 12 people, 18,000 m², 7 in 10
  clients returning), clients and press. They're all in `studio.html`. The home page repeats the numbers in
  `index.html`, and the build's notes repeat some in `build.json`.
- **Home:** the four "Pick your room" photos (`index.html`, section 3) and the selected work.
- **Contact details:** email (`hello@twosquares.studio` everywhere), phone (`+91 [00000 00000]`), address, careers
  email, social links (`href="#"` in `partials/footer.html`). Find them all with `grep -rn "\[" site/*.html partials`.
- **Contact form:** confirm the budget bands (₹ and US$) in `contact.html`. After the first deploy, set the
  notification email under Netlify → Forms.
- **Search:** `robots.txt` blocks search engines while this is a prototype. Open it (`Allow: /`) and put the real
  domain into `sitemap.xml` at launch.
