# Atelier Nord — website

A static portfolio site for a hospitality & retail interior design studio.
No build step, no framework: open `index.html` in a browser and it works.
Upload the folder to any host (Netlify, Vercel, GitHub Pages, cPanel) and it works there too.

```
site/
├── index.html          Home — hero with floating cards, ticker, pinned "story" section, drifting project grid
├── restaurants.html    Sector page — restaurants (orange accent)
├── bars.html           Sector page — bars (violet accent), with the "7pm / 10pm / 1am" pinned chapter
├── retail.html         Sector page — shops (sage accent)
├── studio.html         About / team / services
├── contact.html        Enquiry form + studio details
├── project.html        Template for a single project case study (duplicate per project)
├── assets/
│   ├── css/site.css    All styling. Colours + type live in the :root block at the top.
│   ├── js/app.js       All scroll / motion effects (see "How the effects work")
│   └── img/*.svg       Placeholder "renders". Replace with your photos.
└── tools/make_placeholders.py   Regenerates the placeholder images (optional)
```

---

## 1. Make it yours (15 minutes)

### Studio name, email, phone
Everything is a plain-text placeholder. From inside the `site/` folder:

```bash
# macOS / Linux
grep -rl "Atelier Nord" . | xargs sed -i '' 's/Atelier Nord/YOUR STUDIO NAME/g'
grep -rl "hello@ateliernord.com" . | xargs sed -i '' 's/hello@ateliernord.com/you@yourdomain.com/g'
grep -rl "+00 000 000 000" . | xargs sed -i '' 's/+00 000 000 000/+91 98765 43210/g'
```
(On Linux drop the `''` after `-i`. Or just use Find & Replace in any editor across the folder.)

Also update on `contact.html`: the studio address block, and on every page: the Instagram / Pinterest / LinkedIn links in the footer (search for `href="#"`).

### Photos
Every image is referenced by filename in `assets/img/`. Drop in your own photo with the **same name** and it appears everywhere that image is used:

| File | Where it's used |
|---|---|
| `hero-01/02/03.svg` | Sector cards on the home page; page headers for restaurants / bars / shops |
| `rest-*.svg` | Restaurant projects |
| `bar-*.svg` | Bar projects |
| `shop-*.svg` | Shop projects |
| `studio-team.svg`, `studio-process.svg` | Studio page |

You can use `.jpg` / `.webp` instead of `.svg` — just update the `src="..."` in the HTML to match.
Recommended: 1600px wide, under 400 KB each (use [squoosh.app](https://squoosh.app) to compress).
Portrait images (4:5) look best in the project grids; landscape (16:10) for the page headers.

### Projects
Project cards appear in three places — copy an existing block and change the text:

- **Floating grid** (`.float-grid` → `.proj`) — the drifting collage. `data-speed="1.2"` makes a card lead the scroll; `0.85` makes it lag. Keep values between 0.8 and 1.3.
- **Location index** (`.index__row`) — the hover-to-preview list on the sector pages. `data-img="..."` is the thumbnail that follows the cursor.
- **Drag rail** (`.hscroll` → `.hcard`) — the horizontal "by location" strip.

For a full case study, duplicate `project.html` → `ember.html`, `velvet-room.html`, etc., and point the cards' `href` at them.

### Colours & fonts
Top of `assets/css/site.css`:

```css
--bg: #0e0d0c;      /* page background */
--ink: #f3ede4;     /* text */
--brass: #c9a36b;   /* default accent */
--rest: #d47a3a;    /* restaurants accent */
--bar: #8b6cff;     /* bars accent */
--retail: #a6b37a;  /* shops accent */
```
Each sector page sets `<html data-sector="restaurant|bar|retail">` and picks up its accent automatically.
Fonts are Google Fonts (Fraunces + Inter) loaded in each page's `<head>`; swap the `<link>` and the `--font-display` / `--font-body` variables to change them.

---

## 2. Make the contact form send

The form currently shows a thank-you message but doesn't send anything (there's no server). Two free options:

**Formspree** (works on any host)
1. Sign up at formspree.io, create a form, copy your endpoint.
2. In `contact.html`, change `<form class="form" data-demo ...>` to
   `<form class="form" action="https://formspree.io/f/YOUR_ID" method="POST" ...>` — i.e. remove `data-demo`, add `action` and `method`.

**Netlify Forms** (if hosting on Netlify)
1. Change `<form class="form" data-demo ...>` to `<form class="form" netlify name="enquiry" ...>`.
2. Submissions show up in the Netlify dashboard and can be emailed to you.

---

## 3. Put it online

**Netlify Drop (easiest, free, ~2 minutes)** — go to app.netlify.com/drop and drag the `site` folder onto the page. You get a live URL immediately; connect your own domain in the settings.

**Vercel** — `npx vercel site` from the repo root, or import the repo and set the root directory to `site`.

**GitHub Pages** — Pages serves from the repo root or `/docs`, so either move the contents of `site/` to a `docs/` folder on a dedicated branch, or use a "deploy static site to Pages" GitHub Action pointed at `site/`.

**Any traditional host (cPanel, FTP)** — upload the *contents* of `site/` into `public_html`.

---

## 4. How the effects work

All motion is in `assets/js/app.js` and is switched on with data-attributes, so you can add effects to new content without touching JavaScript:

| Attribute / class | Effect |
|---|---|
| `data-reveal` (`="left"`, `"right"`, `"scale"`) | Fades and rises into view. Add `style="--d:200"` to delay by 200 ms for staggering. |
| `class="split"` on a heading | Each line slides up from behind a mask. |
| `class="wipe"` around an image | Curtain wipe reveal + slow zoom. |
| `data-parallax="0.2"` | Drifts at 20% of scroll speed (negative values go the other way). |
| `data-float` | Gentle continuous bobbing. Tune with `--float-dur`, `--float-amp`, `--float-rot`. |
| `data-tilt="1.5"` | Follows the mouse in 3D (used on the hero cards). |
| `data-speed="1.2"` on a `.proj` in `.float-grid` | Cards drift past each other while scrolling. |
| `class="chapter"` section | Sticky pinned story: the background image swaps as each `.chapter__step` scrolls past. |
| `class="hscroll"` | Drag-to-scroll horizontal rail with progress bar. |
| `data-count="64" data-suffix="%"` | Number counts up when it enters view. |
| `class="marquee"` | Infinite ticker; speeds up when you scroll fast. |

Also built in: page-transition curtain between pages, nav that hides on scroll-down and blurs when scrolled, cursor glow on desktop, magnetic buttons, and a mobile full-screen menu.

Everything respects the OS "reduce motion" setting: with it on, the site renders fully static.

---

## 5. Regenerating placeholder images

Only needed if you want different placeholder art before real photos arrive:

```bash
python3 site/tools/make_placeholders.py
```
Edit the `PROJECTS` list in that file to change names and colour palettes.
