/*!
 * Two Squares — site chrome. Runs on every page, after motion.js.
 * Header states · overlay nav · cursor · preloader · lazy images · ambient
 * video manager · toast · copy-to-clipboard · prefetch · contact venue memory ·
 * touch press feedback + haptics.
 * Everything here works without motion (reduced motion, or GSAP failed to load):
 * motion-only parts are registered with Motion.global() and receive env.motion.
 */
(function (w, d) {
  "use strict";
  const root = d.documentElement;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const reduce = () => w.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fine = () => w.matchMedia("(hover: hover) and (pointer: fine)").matches;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) {} },
    sget(k) { try { return sessionStorage.getItem(k); } catch (_) { return null; } },
    sset(k, v) { try { sessionStorage.setItem(k, v); } catch (_) {} },
  };
  const TS = (w.TS = w.TS || {});
  TS.store = store;

  /* ---------------------------------------------------------------- nav: current page */
  (function markCurrent() {
    const here = location.pathname.replace(/index\.html$/, "").replace(/\/$/, "") || "/";
    $$(".site-header__nav a[href], .nav-overlay a[href]").forEach((a) => {
      const u = new URL(a.getAttribute("href"), location.href);
      const p = u.pathname.replace(/index\.html$/, "").replace(/\/$/, "") || "/";
      const section = d.body.dataset.section;           // e.g. "work" on case studies
      if (p === here || (section && a.dataset.section === section)) a.setAttribute("aria-current", "page");
    });
  })();

  /* ---------------------------------------------------------------- lazy images: fade in on decode */
  // Once the photo has faded in, the LQIP background is dropped (.media.is-ready): a CSS
  // background image makes a floating (moving) layer repaint on every frame.
  function wireImages(scope = d) {
    $$(".media > img, .media > picture > img", scope).forEach((img) => {
      if (img.dataset.wired) return;
      img.dataset.wired = "1";
      const fig = img.closest(".media");
      const done = () => {
        img.classList.add("is-loaded");
        if (fig && img.naturalWidth) setTimeout(() => fig.classList.add("is-ready"), 650);
      };
      if (img.complete && img.naturalWidth) done();
      else { img.addEventListener("load", done, { once: true }); img.addEventListener("error", done, { once: true }); }
    });
  }
  // video figures: the poster covers the LQIP once it has loaded (same URL, so it comes from cache)
  function wirePosters(scope = d) {
    $$(".media > video[poster]", scope).forEach((v) => {
      if (v.dataset.posterWired) return;
      v.dataset.posterWired = "1";
      const fig = v.parentElement;
      const url = v.getAttribute("poster");            // the poster on screen now (the browser loads it anyway)
      if (!url || !fig) return;
      const im = new Image();
      im.onload = () => fig.classList.add("is-ready");
      im.src = url;
    });
  }
  TS.wireImages = (scope) => { wireImages(scope); wirePosters(scope); };
  wireImages();
  wirePosters();

  /* ---------------------------------------------------------------- toast */
  let toastEl, toastTimer;
  TS.toast = (msg) => {
    if (!toastEl) { toastEl = d.createElement("div"); toastEl.className = "toast"; toastEl.setAttribute("role", "status"); toastEl.setAttribute("aria-live", "polite"); d.body.appendChild(toastEl); }
    toastEl.textContent = msg;
    requestAnimationFrame(() => toastEl.classList.add("is-in"));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove("is-in"), 2400);
  };

  /* ---------------------------------------------------------------- copy to clipboard: [data-copy="text"] */
  d.addEventListener("click", (e) => {
    const b = e.target.closest && e.target.closest("[data-copy]");
    if (!b) return;
    e.preventDefault();
    const text = b.dataset.copy;
    const ok = () => TS.toast(b.dataset.copied || "Copied");
    if (navigator.clipboard && w.isSecureContext) navigator.clipboard.writeText(text).then(ok, () => fallback());
    else fallback();
    function fallback() {
      const t = d.createElement("textarea"); t.value = text; t.setAttribute("readonly", ""); t.style.position = "fixed"; t.style.opacity = "0";
      d.body.appendChild(t); t.select(); try { d.execCommand("copy"); ok(); } catch (_) { location.href = "mailto:" + text; } t.remove();
    }
  });

  /* ---------------------------------------------------------------- prefetch internal pages on intent */
  (function prefetch() {
    const seen = new Set();
    const go = (a) => {
      if (!a || a.target === "_blank") return;
      const u = new URL(a.href, location.href);
      if (u.origin !== location.origin || u.pathname === location.pathname || seen.has(u.pathname)) return;
      seen.add(u.pathname);
      const l = d.createElement("link"); l.rel = "prefetch"; l.href = u.pathname; d.head.appendChild(l);
    };
    d.addEventListener("pointerover", (e) => go(e.target.closest && e.target.closest("a[href]")), { passive: true });
    d.addEventListener("focusin", (e) => go(e.target.closest && e.target.closest("a[href]")));
  })();

  /* ---------------------------------------------------------------- contact: the room arrives already selected */
  // A sector page (body[data-sector]) or a case study (body[data-project]) remembers its room for the
  // session. Every contact.html link that doesn't name a venue — the header's "Start a project", the
  // Index's Contact, the footer's Contact, the services "Order this" links — then carries it, so the
  // form opens with that venue chip selected and the "From the … page / project" banner (contact.js).
  // Keys (sessionStorage): ts-venue (cafe|restaurant|bar|shop), ts-venue-from (sector|case-study|work),
  // ts-venue-item (the project slug, case studies only). contact.js reads ts-venue as a fallback.
  // The latest choice wins: a work filter tap (from=work) replaces the room, and every link is rebuilt
  // from its author's href with the memory as it is now (on load, on each change, and at the moment of use).
  // Page code that changes the room: TS.venue.set(venue, from, item) / TS.venue.restore(from), or write
  // the keys and dispatch "ts:venue" on document.
  (function venueMemory() {
    const SECTOR = { cafes: "cafe", restaurants: "restaurant", bars: "bar", retail: "shop" };
    const PROJECT = { "common-hours": "cafe", tilt: "cafe", ember: "restaurant", otla: "restaurant", stillroom: "bar", dhaaga: "shop" };
    const KEYS = ["ts-venue", "ts-venue-from", "ts-venue-item"];
    const get = () => KEYS.map((k) => store.sget(k) || "");            // [venue, from, item]
    function put(venue, from, item) {
      if (venue) { store.sset(KEYS[0], venue); store.sset(KEYS[1], from || "sector"); store.sset(KEYS[2], item || ""); }
      else KEYS.forEach((k) => { try { sessionStorage.removeItem(k); } catch (_) {} });
    }
    const b = d.body, sector = b.dataset.sector, project = b.dataset.project;
    if (sector && SECTOR[sector]) put(SECTOR[sector], "sector", "");
    else if (project) {
      // unknown slug: the page's own prefilled contact link names the room
      let v = PROJECT[project] || "";
      if (!v) { const a = $('a[href*="contact.html"][href*="venue="]'); v = a ? new URL(a.href).searchParams.get("venue") || "" : ""; }
      if (v) put(v, "case-study", project);
    }
    // the room this page opened with, before any of its own controls changed it
    const base = get();
    let all = () => {};
    const changed = () => all();
    TS.venue = {
      get() { const m = get(); return m[0] ? { venue: m[0], from: m[1], item: m[2] } : null; },
      set(venue, from, item) { put(venue, from, item); changed(); },
      // the page's own choice is undone (the work index's "All"): back to the room it opened with, unless
      // that room was this same page's earlier choice, in which case no room is chosen now
      restore(from) { if (base[0] && base[1] !== from) put(base[0], base[1], base[2]); else put(""); changed(); },
    };
    if (b.dataset.page === "contact") return;               // the form itself: nothing to carry
    const CONTACT = /(^|\/)contact\.html(?=$|[?#])/;
    // sources whose banner is worded from the room itself (contact.js ROOMS): a link like the work index's
    // own "Start a project" (?from=work, no room while All is on) only takes a room remembered from that
    // same source; otherwise it is left as it is, and contact.js picks the remembered room up with the
    // banner that says where it came from ("Picked up from the Cafés page", not "From the café projects")
    const ROOM_FROM = /^(work|sector|build)$/i;
    const own = new WeakMap();                               // link -> { href: the author's, out: what we wrote }
    function carry(a) {
      const cur = a && a.getAttribute("href");
      if (!cur) return;
      const seen = own.get(a);
      // rebuild from the author's href; page code that rewrote the link since (work.js) set a new one
      const href = seen && seen.out === cur ? seen.href : cur;
      if (!CONTACT.test(href) || /^[a-z]+:/i.test(href)) { own.delete(a); return; }   // relative links to our own form only
      const [venue, from, item] = get();
      const hashAt = href.indexOf("#"), hash = hashAt >= 0 ? href.slice(hashAt) : "";
      const noHash = hashAt >= 0 ? href.slice(0, hashAt) : href;
      const qAt = noHash.indexOf("?"), path = qAt >= 0 ? noHash.slice(0, qAt) : noHash;
      const q = new URLSearchParams(qAt >= 0 ? noHash.slice(qAt + 1) : "");
      const src = (q.get("from") || "").toLowerCase();
      let out = href;
      // the author's link names its room, or its source words the banner from another room: leave it;
      // no room remembered: the author's link as written
      if (venue && !q.has("venue") && !(src && !q.has("item") && ROOM_FROM.test(src) && src !== from)) {
        q.set("venue", venue);
        if (!q.has("from")) {
          q.set("from", from || "sector");
          if (from === "case-study" && item) q.set("item", item);
        }
        out = path + "?" + q.toString() + hash;
      }
      if (out !== cur) a.setAttribute("href", out);
      if (out !== href) own.set(a, { href, out }); else own.delete(a);
    }
    all = () => $$('a[href*="contact.html"]').forEach(carry);
    all();
    // page scripts that run after this one (work.js on work.html?filter=…) may already have set a room
    d.addEventListener("DOMContentLoaded", all, { once: true });
    // links added later (build pop-ups, menus): carry the room at the moment of use
    // A tap also leaves the link's query for the form to read once: the preview host can drop a query string on
    // the way (contact.html prefers the URL's own)
    const onUse = (e) => {
      const a = e.target.closest && e.target.closest('a[href*="contact.html"]');
      if (!a) return;
      carry(a);
      if (e.type === "click" && !e.defaultPrevented && e.button === 0 && !(e.metaKey || e.ctrlKey || e.shiftKey || e.altKey)) {
        store.sset("ts-contact-q", new URL(a.href, location.href).search);
      }
    };
    d.addEventListener("click", onUse, true);
    d.addEventListener("pointerdown", onUse, true);
    d.addEventListener("focusin", onUse, true);
    d.addEventListener("ts:venue", changed);
    // back/forward cache: another page may have changed the room since (or "Start from scratch" cleared it)
    w.addEventListener("pageshow", (e) => { if (e.persisted) all(); });
    // the work index: its filter (html[data-work-filter], work.js) is the visitor's latest choice of room.
    // A sector filter is that room; going from one back to "All" undoes the page's own choice
    // (TS.venue.restore). Opening the page on All (work.js re-sets the attribute at init) keeps the room.
    if (b.dataset.page === "work" && w.MutationObserver) {
      let last = root.dataset.workFilter;                  // set before first paint by the <head> script
      new MutationObserver(() => {
        const f = root.dataset.workFilter, was = last, m = get();
        last = f;
        if (f === was) changed();
        else if (SECTOR[f]) { if (m[0] !== SECTOR[f] || m[1] !== "work") put(SECTOR[f], "work", ""); changed(); }
        else if (f === "all" && SECTOR[was] && m[1] === "work") TS.venue.restore("work");
        else changed();
      }).observe(root, { attributes: true, attributeFilter: ["data-work-filter"] });
    }
  })();

  /* ---------------------------------------------------------------- placeholder links (footer socials until the real URLs exist) */
  d.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest('a[data-placeholder][href="#"]');
    if (!a) return;
    e.preventDefault();
    TS.toast && TS.toast("That link goes live with the site.");
  });

  /* ---------------------------------------------------------------- touch press: squish + spring, and a haptic tick */
  // Touch and pen only (the mouse has the liquid cursor). The squish is a Web Animation on the
  // individual `scale` property, so it composes with any transform, float or GSAP tween on the
  // element and never fights a page's own transition. It waits 60ms so a finger that starts a
  // scroll on a card doesn't flash it (the browser cancels the pointer), but a quick tap still
  // gets the full squish. The haptic fires on the click, i.e. only for a real tap:
  // navigator.vibrate(10) where it exists (Android); on iOS 18+ Safari, which has no vibrate API,
  // an invisible, unfocusable <input type=checkbox switch> label is clicked inside the tap's own
  // click handler, which plays the system tick. Anything unsupported fails silently.
  // Nothing moves or buzzes under reduced motion.
  // A label is a press target when it names its control (label[for]) or wraps a radio or checkbox
  // (the work filters, form chips). A label that wraps a text field is not: the field gets the caret.
  const TOGGLE = /^(radio|checkbox)$/;
  const pressLabel = (lab) => !!lab.htmlFor || !!(lab.control && TOGGLE.test(lab.control.type));
  TS.pressLabel = pressLabel;
  (function press() {
    const SEL = 'a[href], button, .chip, summary, [role="button"], label, input[type="submit"], input[type="button"], [data-press]:not([data-press="off"])';
    const state = new WeakMap();                               // el → { anim, amt, inline }
    let lastType = "", lastDown = 0, timer = 0, cur = null, pressedAt = 0, lastBuzz = 0;
    const pick = (e) => {
      const t = e.target;
      let el = t && t.closest && t.closest(SEL);
      // a label around a text field: look further out (a card link, say), never at the label
      while (el && el.tagName === "LABEL" && !el.matches(".chip") && !pressLabel(el)) el = el.parentElement && el.parentElement.closest(SEL);
      if (!el || el.closest('[data-press="off"], [disabled], [aria-disabled="true"]')) return null;
      return el;
    };
    const play = (el, frames, opts) => {
      const st = state.get(el), a = el.animate(frames, opts);
      if (st.anim) st.anim.cancel();                           // the new one starts from an explicit frame: no jump
      st.anim = a;
      return a;
    };
    function squish(el) {
      pressedAt = performance.now();
      if (reduce() || !el.animate) return;
      const r = el.getBoundingClientRect();
      const inline = getComputedStyle(el).display === "inline";   // transforms skip inline boxes: dim those instead
      // ≈ 12px of travel at most: a button gets .97, a tall card a gentler squeeze
      const amt = 1 - Math.min(0.03, 12 / Math.max(r.width, r.height, 1));
      const st = state.get(el) || {};
      st.amt = amt; st.inline = inline; state.set(el, st);
      play(el, inline ? [{ opacity: 1 }, { opacity: 0.55 }] : [{ scale: "1" }, { scale: String(amt) }],
        { duration: 110, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" });
    }
    function release(el, wait) {
      const st = el && state.get(el);
      if (!st || !st.anim || !el.animate) return;
      const pressAnim = st.anim;
      setTimeout(() => {
        if (st.anim !== pressAnim) return;                     // pressed again meanwhile
        const back = play(el, st.inline ? [{ opacity: 0.55 }, { opacity: 1 }] : [{ scale: String(st.amt) }, { scale: "1" }],
          { duration: st.inline ? 260 : 520, easing: st.inline ? "ease-out" : "cubic-bezier(.34,1.56,.64,1)" });
        back.onfinish = () => { back.cancel(); if (st.anim === back) st.anim = null; };
      }, Math.max(0, wait));
    }
    d.addEventListener("pointerdown", (e) => {
      lastType = e.pointerType; lastDown = performance.now();
      if (e.pointerType === "mouse" || !e.isPrimary) return;
      clearTimeout(timer);
      if (cur) release(cur, 0);
      cur = pick(e); pressedAt = 0;
      const el = cur;
      if (el) timer = setTimeout(() => { if (cur === el) squish(el); }, 60);
    }, { passive: true, capture: true });
    d.addEventListener("pointerup", (e) => {
      if (!cur || e.pointerType === "mouse") return;
      clearTimeout(timer);
      const el = cur; cur = null;
      if (!pressedAt) squish(el);                               // a quick tap: squish now, spring back after a beat
      release(el, 90 - (performance.now() - pressedAt));
    }, { passive: true, capture: true });
    d.addEventListener("pointercancel", () => {                 // the finger turned into a scroll
      clearTimeout(timer);
      if (cur) release(cur, 0);
      cur = null;
    }, { passive: true, capture: true });

    const canVibrate = typeof navigator.vibrate === "function";
    const iOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
    let busy = false;
    function haptic() {
      if (reduce() || busy) return;
      const now = performance.now();
      if (now - lastBuzz < 150) return;                         // a label and its input fire two clicks
      lastBuzz = now;
      busy = true;
      try {
        if (canVibrate) { navigator.vibrate(10); return; }
        if (!iOS) return;
        // iOS 18+: clicking the label of an <input type=checkbox switch> plays the system tick. It is
        // never rendered (display:none, in <head>), aria-hidden, unfocusable, and gone right after.
        // Older iOS just toggles an invisible checkbox: harmless.
        const lab = d.createElement("label"), i = d.createElement("input");
        lab.setAttribute("aria-hidden", "true"); lab.style.display = "none";
        i.type = "checkbox"; i.setAttribute("switch", ""); i.tabIndex = -1;
        lab.appendChild(i); d.head.appendChild(lab);
        lab.click();
        lab.remove();
      } catch (_) { /* no haptics on this device: fine */ } finally { busy = false; }
    }
    // only a real tap (a trusted click that followed a touch / pen press) ticks
    d.addEventListener("click", (e) => {
      if (busy || !e.isTrusted) return;
      if ((lastType !== "touch" && lastType !== "pen") || performance.now() - lastDown > 1200) return;
      if (pick(e)) haptic();
    }, true);
    TS.haptic = haptic;
  })();

  /* ---------------------------------------------------------------- overlay nav (works without motion) */
  (function overlay() {
    const ov = $(".nav-overlay"), toggle = $(".nav-toggle");
    if (!ov || !toggle) return;
    const close = $(".nav-overlay__close", ov);
    let lastFocus = null;
    const focusables = () => $$('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])', ov).filter((el) => el.offsetParent !== null);
    function open() {
      const r = toggle.getBoundingClientRect();
      ov.style.setProperty("--ox", ((r.left + r.width / 2) / innerWidth) * 100 + "%");
      ov.style.setProperty("--oy", ((r.top + r.height / 2) / innerHeight) * 100 + "%");
      lastFocus = d.activeElement;
      ov.hidden = false; ov.removeAttribute("inert");
      requestAnimationFrame(() => ov.classList.add("is-open"));
      toggle.setAttribute("aria-expanded", "true");
      root.classList.add("nav-open");
      w.Motion && w.Motion.stop && w.Motion.stop();
      if (w.gsap && !reduce()) {
        w.gsap.fromTo($$(".nav-overlay__link span, .nav-overlay__foot > *", ov), { yPercent: 60, autoAlpha: 0 },
          { yPercent: 0, autoAlpha: 1, duration: 0.9, ease: w.Motion && w.Motion.DRIFT || "power3.out", stagger: 0.06, delay: 0.25 });
      }
      setTimeout(() => (focusables()[0] || close).focus({ preventScroll: true }), 60);
    }
    function shut() {
      ov.classList.remove("is-open");
      setTimeout(() => { if (!ov.classList.contains("is-open")) { ov.scrollTop = 0; ov.classList.remove("is-scrolled"); } }, 850);
      toggle.setAttribute("aria-expanded", "false");
      root.classList.remove("nav-open");
      ov.setAttribute("inert", "");
      w.Motion && w.Motion.start && w.Motion.start();
      if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
    }
    TS.closeNav = shut;
    // the top bar gets a fill once the overlay itself scrolls (small landscape phones)
    ov.addEventListener("scroll", () => ov.classList.toggle("is-scrolled", ov.scrollTop > 4), { passive: true });
    ov.setAttribute("inert", "");
    toggle.addEventListener("click", () => (ov.classList.contains("is-open") ? shut() : open()));
    close && close.addEventListener("click", shut);
    ov.addEventListener("click", (e) => { const a = e.target.closest("a[href]"); if (a && new URL(a.href).pathname === location.pathname) shut(); });
    d.addEventListener("keydown", (e) => {
      if (!ov.classList.contains("is-open")) return;
      if (e.key === "Escape") { e.preventDefault(); shut(); }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && d.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && d.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    });
    w.addEventListener("resize", () => { if (innerWidth > 900 && ov.classList.contains("is-open")) shut(); });
  })();

  /* ---------------------------------------------------------------- header states (scroll position only; no layout reads per frame) */
  (function header() {
    const h = $(".site-header");
    if (!h) return;
    const firstDark = d.querySelector("main > [data-header='dark']:first-child, main > :first-child[data-header='dark']");
    let lastY = w.scrollY, ticking = false, forced = 0;
    // the hero is an inset panel (margin-top: --panel-inset): measure to its bottom edge
    const heroH = () => (firstDark ? firstDark.offsetTop + firstDark.offsetHeight : 0);
    let heroBottom = heroH();
    w.addEventListener("resize", () => { heroBottom = heroH(); }, { passive: true });
    function update() {
      ticking = false;
      const y = w.scrollY;
      const overDark = firstDark && y < heroBottom - h.offsetHeight;
      root.dataset.headerOver = overDark ? "dark" : "light";
      h.classList.toggle("is-solid", y > 80 && !overDark);
      const dy = y - lastY;
      if (!root.classList.contains("nav-open")) {
        if (forced > 0) h.classList.add("is-hidden");
        else if (y > innerHeight * 0.3 && dy > 8) h.classList.add("is-hidden");
        else if (dy < -8 || y < innerHeight * 0.3) h.classList.remove("is-hidden");
      }
      if (Math.abs(dy) > 8 || y < 10) lastY = y;
    }
    // sections can force the header out of the way (e.g. the pinned walk)
    TS.hideHeader = (on) => { forced = Math.max(0, forced + (on ? 1 : -1)); update(); };
    w.addEventListener("scroll", () => { if (!ticking) { ticking = true; requestAnimationFrame(update); } }, { passive: true });
    h.addEventListener("focusin", () => h.classList.remove("is-hidden"));
    update();
  })();

  /* ---------------------------------------------------------------- ambient video manager: <video data-autoplay data-src="base" [data-src-sm="base-sm"]> */
  const pickExt = (v) => {
    const isSafari = /^((?!chrome|android|crios|fxios).)*safari/i.test(navigator.userAgent);
    return !isSafari && v.canPlayType('video/webm; codecs="vp9"') === "probably" ? "webm" : "mp4";
  };
  // The -sm files are 4:5 portrait crops. They suit a portrait phone or tablet only: a phone held
  // sideways (844×390, say) gets the 16:9 master and its poster, or it would stretch a thin band of
  // a portrait crop across a wide panel.
  const SMALL_Q = "(max-width: 900px) and (orientation: portrait)";
  TS.videoSmall = (v) => !!v.dataset.srcSm && w.matchMedia(SMALL_Q).matches;
  TS.pickVideoSrc = (v) => {
    const small = TS.videoSmall(v);
    if (v.dataset.posterSm) {
      if (v.dataset.posterLg == null) v.dataset.posterLg = v.getAttribute("poster") || "";
      const want = small ? v.dataset.posterSm : v.dataset.posterLg;
      if (want && v.getAttribute("poster") !== want) v.poster = want;
    }
    return (small ? v.dataset.srcSm : v.dataset.src) + "." + pickExt(v);
  };
  (function videos() {
    const vids = $$("video[data-autoplay]");
    if (!vids.length) return;
    // the phone turned: loaded films switch file (keeping their place), the rest just their poster
    const mqSmall = w.matchMedia(SMALL_Q);
    const turned = () => vids.forEach((v) => {
      if (!v.dataset.srcSm) return;
      if (!v.dataset.loaded) { if (v.dataset.posterSm) TS.pickVideoSrc(v); return; }
      const next = TS.pickVideoSrc(v);
      if (v.getAttribute("src") === next) return;
      const wasPlaying = !v.paused, t = v.currentTime || 0;
      v.src = next;
      if (t) v.addEventListener("loadedmetadata", () => { try { v.currentTime = v.duration ? t % v.duration : t; } catch (_) {} }, { once: true });
      if (wasPlaying && !reduce()) { const p = v.play(); if (p && p.catch) p.catch(() => {}); }
    });
    if (mqSmall.addEventListener) mqSmall.addEventListener("change", turned); else if (mqSmall.addListener) mqSmall.addListener(turned);
    const setSrc = (v) => {
      if (v.dataset.loaded) return;
      v.dataset.loaded = "1";
      v.muted = true; v.playsInline = true; v.setAttribute("muted", ""); v.setAttribute("playsinline", "");
      v.src = TS.pickVideoSrc(v);
      v.addEventListener("error", () => v.classList.add("is-failed"), { once: true });
    };
    const play = (v) => {
      if (reduce() || v.dataset.paused === "user") return;
      setSrc(v);
      const p = v.play(); if (p && p.catch) p.catch(() => {});
    };
    const near = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) setSrc(e.target); }), { rootMargin: "100% 0px 100% 0px" });
    const vis = new IntersectionObserver((es) => es.forEach((e) => (e.isIntersecting ? play(e.target) : e.target.pause())), { threshold: 0.15 });
    vids.forEach((v) => {
      if (v.hasAttribute("data-eager")) setSrc(v);
      near.observe(v); vis.observe(v);
    });
    d.addEventListener("visibilitychange", () => vids.forEach((v) => (d.hidden ? v.pause() : null)));
    // pause/play toggles: <button data-video-toggle="#id">
    $$("[data-video-toggle]").forEach((b) => {
      const v = $(b.dataset.videoToggle); if (!v) return;
      const sync = () => { b.setAttribute("aria-pressed", String(v.paused)); b.querySelector(".sr-only") && (b.querySelector(".sr-only").textContent = v.paused ? "Play video" : "Pause video"); };
      b.addEventListener("click", () => { if (v.paused) { v.dataset.paused = ""; setSrc(v); v.play().catch(() => {}); } else { v.dataset.paused = "user"; v.pause(); } });
      v.addEventListener("play", sync); v.addEventListener("pause", sync); sync();
    });
  })();

  /* ---------------------------------------------------------------- footer year */
  $$("[data-year]").forEach((el) => (el.textContent = new Date().getFullYear()));

  /* ================================================================ motion-only chrome */
  const M = w.Motion;
  if (!M || !M.global) return;

  // the preloader must hold intros that are already on screen
  const pre = $(".preloader");
  const runPreloader = pre && !root.classList.contains("no-preload") && !reduce();
  if (runPreloader) M.config.introDelay = 1.25;

  M.global((env) => {
    const gsap = w.gsap;
    const offs = [];

    /* ---- preloader: logo wipes in, label rises, the panel lifts (≤1.4s, any input skips) */
    if (pre) {
      if (!env.motion || root.classList.contains("no-preload")) { pre.remove(); }
      else {
        store.sset("ts-intro", "1");
        const logo = $(".logo", pre), label = $(".t-label", pre);
        const tl = gsap.timeline({ onComplete: () => pre.remove() });
        tl.to(logo, { clipPath: "inset(0 0% 0 0)", duration: 0.75, ease: "ts.cut" })
          .to(label, { autoAlpha: 1, y: 0, duration: 0.45, ease: "ts.out" }, "-=0.25")
          .to(pre, { clipPath: "inset(0 0 100% 0)", duration: 0.7, ease: "ts.cut" }, "+=0.12");
        const skip = () => { if (tl.progress() < 1) tl.progress(1); };
        ["wheel", "touchstart", "keydown", "pointerdown"].forEach((ev) => w.addEventListener(ev, skip, { once: true, passive: true }));
      }
    }

    /* ---- cursor (fine pointers, motion only): a small liquid blob. No ring, no text.
       It trails the pointer with a little lag and stretches along its direction of travel
       (squash and stretch from velocity), grows softly and turns translucent over anything
       interactive (data-cursor still counts as interactive; its label is never shown), and on
       press gives "haptic" feedback: a quick squish, an elastic spring back and a small liquid
       ripple where you pressed. Hidden over text fields (the caret shows) and when the pointer
       leaves the window. One gsap.ticker callback, transforms only, and it writes nothing
       while it is at rest. */
    if (env.fine && env.motion) {
      const c = d.createElement("div");
      c.className = "cursor"; c.setAttribute("aria-hidden", "true");
      c.innerHTML = '<span class="cursor__blob"><span class="cursor__fill"></span></span>';
      const blob = c.firstChild;
      const rip = d.createElement("div");
      rip.className = "cursor-ripple"; rip.setAttribute("aria-hidden", "true");
      d.body.append(c, rip);
      const INTERACTIVE = 'a[href], button:not([disabled]), [role="button"], .chip, label[for], summary, select, [data-cursor]:not([data-cursor="none"]), [data-press]:not([data-press="off"])';
      const TEXT = 'input:not([type="radio"]):not([type="checkbox"]):not([type="range"]):not([type="submit"]):not([type="button"]):not([type="reset"]):not([type="file"]):not([type="color"]), textarea, [contenteditable=""], [contenteditable="true"], iframe, [data-cursor="none"]';
      const DARK = '.on-dark, .nav-overlay, [data-header="dark"], [data-theme="dark"], [data-cursor-dark]';
      const BASE = 0.42, HOVER = 1;                     // blob scale: ~20px at rest, 48px over a target
      let tx = 0, ty = 0, x = 0, y = 0, vx = 0, vy = 0, ang = 0, str = 0, size = BASE, sizeTo = BASE;
      let shown = false, awake = true;
      const press = { v: 1 };
      const move = (e) => {
        if (e.pointerType && e.pointerType !== "mouse") return;
        tx = e.clientX; ty = e.clientY;
        if (!shown) { shown = true; x = tx; y = ty; c.classList.add("is-visible"); }
        awake = true;
      };
      const over = (e) => {
        const t = e.target;
        if (!t || !t.closest) return;
        c.classList.toggle("is-hidden", !!t.closest(TEXT));
        const lab = t.closest("label");
        const hot = !!t.closest(INTERACTIVE) || (!!lab && pressLabel(lab));
        c.classList.toggle("is-hover", hot);
        const dark = !!t.closest(DARK);
        c.classList.toggle("is-dark", dark); rip.classList.toggle("is-dark", dark);
        sizeTo = hot ? HOVER : BASE; awake = true;
      };
      const down = (e) => {
        if (e.pointerType !== "mouse" || e.button !== 0) return;
        gsap.to(press, { v: 0.7, duration: 0.12, ease: "power2.out", overwrite: true });
        gsap.fromTo(rip, { x: e.clientX, y: e.clientY, scale: 0.25, opacity: 0.9 },
          { scale: 1.5, opacity: 0, duration: 0.7, ease: "power2.out", overwrite: true });
        awake = true;
      };
      const up = (e) => {
        if (e.pointerType !== "mouse") return;
        gsap.to(press, { v: 1, duration: 0.9, ease: "elastic.out(1.1, 0.32)", overwrite: true });
        awake = true;
      };
      const hide = () => c.classList.remove("is-visible");
      const show = () => { if (shown) c.classList.add("is-visible"); };
      const out = (e) => { if (!e.relatedTarget) hide(); };        // the pointer left the window
      const tick = (time, dt) => {
        if (!shown || (!awake && press.v === 1)) return;
        const f = Math.min(dt, 50) / 16.667;                        // frames at 60 fps
        const k = 1 - Math.pow(1 - 0.2, f);                         // the trail
        const px = x, py = y;
        x += (tx - x) * k; y += (ty - y) * k;
        vx = (x - px) / Math.max(f, 0.25); vy = (y - py) / Math.max(f, 0.25);
        const speed = Math.hypot(vx, vy);
        const want = Math.min(speed / 38, 0.5);                     // stretch 0 … 50 %
        str += (want - str) * (1 - Math.pow(1 - 0.3, f));
        if (speed > 0.6) {                                          // turn toward the travel, the short way round
          let a = Math.atan2(vy, vx) * 57.2958, dA = a - ang;
          dA = ((dA + 540) % 360) - 180;
          ang += dA * (1 - Math.pow(1 - 0.35, f));
        }
        size += (sizeTo - size) * (1 - Math.pow(1 - 0.18, f));
        const p = press.v, sq = 1 + (1 - p) * 0.45;                 // squish: flatter and a little wider
        c.style.transform = `translate3d(${x.toFixed(2)}px, ${y.toFixed(2)}px, 0)`;
        blob.style.transform = `rotate(${ang.toFixed(2)}deg) scale(${(size * p * sq * (1 + str)).toFixed(4)}, ${(size * p * (1 - str * 0.45)).toFixed(4)})`;
        // at rest: stop writing until something changes
        if (Math.abs(tx - x) < 0.1 && Math.abs(ty - y) < 0.1 && str < 0.002 && Math.abs(sizeTo - size) < 0.002) awake = false;
      };
      gsap.ticker.add(tick);
      w.addEventListener("pointermove", move, { passive: true });
      d.addEventListener("pointerover", over, { passive: true });
      d.addEventListener("pointerdown", down, { passive: true });
      w.addEventListener("pointerup", up, { passive: true });
      d.addEventListener("mouseout", out, { passive: true });
      d.documentElement.addEventListener("pointerenter", show);
      w.addEventListener("blur", hide);
      offs.push(() => {
        gsap.ticker.remove(tick);
        w.removeEventListener("pointermove", move); d.removeEventListener("pointerover", over);
        d.removeEventListener("pointerdown", down); w.removeEventListener("pointerup", up);
        d.removeEventListener("mouseout", out); d.documentElement.removeEventListener("pointerenter", show);
        w.removeEventListener("blur", hide);
        gsap.killTweensOf([press, rip]);
        c.remove(); rip.remove();
      });
    }

    /* ---- overlay shapes drift slowly (only while the overlay is open is it visible, but it's cheap) */
    $$(".nav-overlay__shape").forEach((s, i) => {
      const tw = gsap.to(s, { x: i ? 24 : -30, y: i ? -18 : 22, rotation: "+=6", duration: 9 + i * 3, ease: "sine.inOut", yoyo: true, repeat: -1 });
      offs.push(() => tw.kill());
    });

    return () => offs.forEach((f) => f());
  });
})(window, document);
