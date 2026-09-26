# Two Squares — Design & Build · website

A static site for a design-and-build studio working on cafés, restaurants, bars and shops.
No framework and no build step: every page is plain HTML, CSS and JavaScript. Upload the `site/`
folder to Netlify (drag and drop) and it works, including the contact form and the old-URL redirects.

> **Prototype.** Project names, quotes, numbers and photographs are stand-ins (licensed stock from
> Pexels, Unsplash and Mixkit, free for commercial use). The café walk-in video is the studio's own.
> See **Before launch** at the end.

## The site

| Page | What's on it |
|---|---|
| `index.html` | Hero reel → **the walk**: one street, three doors. The café (08:00) opens onto the studio's own walk-in clip, scrubbed by scroll; "Take the corner table" runs the café sequence and puts the paper **menu card** on the table (each item opens the contact form, prefilled). The restaurant (14:00) and bar (23:00) doors swing open onto their clips. Then selected work, what we do, how it works, numbers, the quote and a closing CTA. |
| `work.html` | Every project. Filters with counts (`?filter=cafes`, `restaurants`, `bars`, `retail`, kept in the URL), a Rows/Grid toggle, loop videos on hover in the grid. |
| `work/<slug>.html` | Six case studies: hero, facts, brief and "the move", stages delivered, photographs and a loop, details, the build, outcome, owner quote, credits, next project. |
| `services.html` | "The menu": the services set as a printed restaurant menu, each item expanding to what's included and "Order this" (prefills the contact form); the five-step process; FAQ. |
| `studio.html` | The studio, opening on "Studio" as a picture frame (the workshop seen through the letters), principles, one contract, team, numbers, clients, careers. |
| `contact.html` | The enquiry form. Prefilled from the menu card, the services menu and case studies; inline validation; posts to Netlify Forms. |
| `404.html` | "Wrong door." |

## How it's put together

```
site/
├── *.html, work/*.html         the pages (edit them directly)
├── partials/                   shared header, footer, <head> and script tags, and the walk
├── templates/                  case.html (case-study template), page.html (skeleton for a new page)
├── assets/
│   ├── css/base.css            design tokens (colours, type, spacing) and every shared component
│   ├── css/<page>.css          one stylesheet per page, scoped under [data-page="…"]
│   ├── js/motion.js            the motion engine: smooth scroll, reveals, page transitions
│   ├── js/site.js              header, menu overlay, cursor, video manager, toasts
│   ├── js/scrub.js             scroll-scrubbed video
│   ├── js/<page>.js            page behaviour (walk.js is the walk and café sequence)
│   ├── js/vendor/              GSAP 3.15 (ScrollTrigger, SplitText, Flip, CustomEase), Lenis 1.3 — self-hosted
│   ├── data/projects.json      the six projects: copy, facts, which photos and loop each uses
│   ├── img/photos/             photos as <slug>-800.webp / -1600.webp, plus media.json
│   ├── video/                  clips as .webm + .mp4, -sm (4:5, phones) versions, posters/
│   └── fonts/                  Instrument Serif and Instrument Sans (self-hosted)
├── tools/                      small Python scripts (below)
├── _redirects                  Netlify: the old sector pages → work.html?filter=…
├── robots.txt, sitemap.xml
```

### Shared header, footer and menu
Edit `partials/header.html`, `footer.html`, `head.html` or `scripts.html`, then copy them into every page:

```bash
python3 tools/sync_partials.py              # all pages
python3 tools/sync_partials.py index.html   # just one
```

### Projects
All six live in `assets/data/projects.json`. After editing it, regenerate the Work list and the case studies:

```bash
python3 tools/build_work.py
python3 tools/build_case_studies.py
```
To add a project, copy an entry, give it a new `slug`, set `filter` (cafes / restaurants / bars / retail),
add the slug to `order`, point `next` at another project, and run both scripts. Add the new page to `sitemap.xml`.

### Photos
Swap a stand-in for your own photo by keeping its name (the *slug*). Every page that uses it updates:

```bash
python3 tools/build_media.py ~/Photos/our-counter.jpg rest-a-01-dining-room-banquette --alt "The counter at Otla at noon" --focus 0.5,0.45
```
To add a new photo, use a new slug, then print ready-to-paste markup (size reserved, blurred placeholder, lazy loading):
`python3 tools/media_tag.py <slug> --reveal`. Photos should be at least 1600px on the long edge. Needs Pillow (`pip install pillow`).

### Video
```bash
python3 tools/encode_video.py walk-in.mov cafe-walk --scrub --length 10    # a clip that plays as you scroll
python3 tools/encode_video.py pour.mov loop-latte --loop --start 2 --length 8   # an ambient loop
```
Replacing a clip with the same name needs no page edits. Needs ffmpeg. Scrub clips should be a steady,
forward camera move of 8–14s; the walk-ins are `cafe-walk`, `restaurant-walk` and `bar-walk`.

### Motion, briefly
Add attributes, not code: `data-reveal` (fade up), `data-reveal="image"` (curtain reveal on a `.media` figure),
`data-split` (headline lines rise in), `data-parallax="0.15"`, `data-count="64"`, `data-cursor="View"`.
With *reduce motion* switched on in the visitor's system settings, all of it is off and everything is simply shown;
the walk becomes three stills and the café sequence goes straight to the menu card.

## Run it locally

```bash
cd site && python3 -m http.server 8000     # then open http://localhost:8000
```
Some browsers want HTTP range requests to seek video; if the walk's clips don't scrub, use `npx serve site` instead.
The contact form shows its success message locally but only sends once deployed on Netlify.

## Quality checks (at handover)

Every page was tested in Chromium at 1440×900, 1024×1366 and 390×844, and with reduced motion:
0 console errors, 0 failed requests, 0 broken links, 0 overlapping text, 0 horizontal scroll, and no
serious or critical accessibility (axe WCAG 2.1 AA) issues. Layout shift is under 0.01 everywhere. Scrolling holds
60fps on every page, except the walk on large desktop windows in a headless browser *without a GPU*
(slow frames around the restaurant and bar doors). There the cost grows with window size, which points to software
rendering rather than the code; it should be confirmed on real hardware.

## Before launch

- **Photos and video:** replace the stock photos with your own projects (see Photos). Remove
  the "Placeholder" badges (`badge--placeholder`) and the footer's prototype line (`partials/footer.html`).
- **Projects:** real names, places, facts, quotes and credits in `assets/data/projects.json`, then regenerate.
- **Studio:** team names and roles, the numbers (64 venues, 9 cities, founded 2016, 12 people, 18,000 m², 7 in 10
  clients returning), clients and press — all in `studio.html`. Home repeats some numbers in `index.html`.
- **Contact details:** email (`hello@twosquares.studio` everywhere), phone (`+91 [00000 00000]`), address, careers
  email, social links (`href="#"` in `partials/footer.html`). Find them all with `grep -rn "\[" site/*.html partials`.
- **Contact form:** confirm the budget bands (₹ and US$) in `contact.html`; after the first deploy, set the
  notification email under Netlify → Forms.
- **Search:** `robots.txt` blocks search engines while this is a prototype. Open it (`Allow: /`) and put the real
  domain into `sitemap.xml` at launch.
