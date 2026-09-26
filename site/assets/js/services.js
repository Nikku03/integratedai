/*!
 * Two Squares — services.html ("The menu")
 * · menu items and FAQ: accessible disclosures (button + aria-expanded/-controls,
 *   hidden="until-found" so find-in-page still reaches them), opened and closed
 *   with a FLIP: only transform, opacity and clip-path animate, never height.
 * · deep links (#whole-venue …) open their item.
 * · Motion.page: the sheet straightens as it arrives, reveals, the course
 *   index scroll-spy, and the process stage (CSS-sticky media, no pin) that
 *   swaps a loop per step while the texts scroll past.
 * Works without GSAP: disclosures just open and close.
 */
(function (w, d) {
  "use strict";
  const root = d.documentElement;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const mq = (q) => w.matchMedia(q).matches;
  const reduce = () => mq("(prefers-reduced-motion: reduce)");
  const animOK = () => !!(w.gsap && root.classList.contains("js-motion") && !reduce());
  const ease = () => (w.Motion && w.Motion.EASE) || "power3.out";

  /* ================================================================ disclosures */
  function Disclosures(group, opts) {
    const items = $$(opts.item, group).map((el) => {
      const btn = $(opts.button, el);
      const panel = d.getElementById(btn.getAttribute("aria-controls"));
      return { el, btn, panel, inner: panel.firstElementChild };
    });
    const isOpen = (it) => it.btn.getAttribute("aria-expanded") === "true";
    const setState = (it, open) => { it.btn.setAttribute("aria-expanded", String(open)); it.el.classList.toggle("is-open", open); };
    // a collapsed panel is not rendered (content-visibility: hidden); the class tells
    // the QA overlap checker to skip its (unpainted) text boxes
    const hide = (it) => {
      it.panel.setAttribute("hidden", "until-found");
      it.panel.classList.add("qa-ignore-overlap");
      it.panel.style.cssText = "";
      if (w.gsap) w.gsap.set(it.inner, { clearProps: "clipPath,opacity" });
    };

    const show = (it) => {
      it.panel.style.cssText = "";
      it.panel.removeAttribute("hidden");
      it.panel.classList.remove("qa-ignore-overlap");
    };

    function toggle(it, want, instant) {
      const open = want == null ? !isOpen(it) : want;
      if (open === isOpen(it)) return;
      const closing = open ? (opts.single ? items.filter((o) => o !== it && isOpen(o)) : []) : [it];
      const opening = open ? it : null;
      if (instant || !animOK()) {
        closing.forEach((o) => { setState(o, false); if (w.gsap) w.gsap.killTweensOf(o.inner); hide(o); });
        if (opening) { setState(opening, true); if (w.gsap) w.gsap.killTweensOf(opening.inner); show(opening); }
        return;
      }
      flip(opening, closing);
    }

    // FLIP: measure every block, change the layout once, then animate each block
    // from where it was (transform only). A closing panel leaves the flow at once
    // but stays on screen, absolutely placed, and is wiped up in step with the
    // blocks that slide over it; an opening panel is wiped down in step with the
    // blocks it pushes. Same duration and ease, so the edges track.
    function flip(opening, closing) {
      const gsap = w.gsap, D = 0.72, E = ease();
      const blocks = $$("[data-flip]", opts.flipRoot || group);
      const cur = blocks.map((b) => +gsap.getProperty(b, "y") || 0);
      const before = blocks.map((b) => b.getBoundingClientRect().top);
      const paper = opts.paper, sheet = paper && paper.parentElement;
      const h0 = sheet ? sheet.offsetHeight * (+gsap.getProperty(paper, "scaleY") || 1) : 0;

      closing.forEach((o) => {
        setState(o, false);
        gsap.killTweensOf(o.inner);
        if (o.panel.style.position !== "absolute") {
          const top = o.panel.offsetTop;
          o.panel.style.cssText = `position:absolute;left:0;right:0;top:${top}px`;
        }
      });
      if (opening) {
        setState(opening, true);
        gsap.killTweensOf(opening.inner);
        show(opening);
      }

      const vh = innerHeight;
      const near = (y) => y > -vh && y < vh * 2;
      blocks.forEach((b, i) => {
        const now = b.getBoundingClientRect().top - cur[i];
        const dy = before[i] - now;
        if (Math.abs(dy) < 0.5 || (!near(before[i]) && !near(now))) { if (cur[i]) gsap.set(b, { clearProps: "transform" }); return; }
        gsap.fromTo(b, { y: dy }, { y: 0, duration: D, ease: E, overwrite: "auto", clearProps: "transform" });
      });
      if (sheet) {
        const h1 = sheet.offsetHeight;
        if (Math.abs(h1 - h0) > 0.5) gsap.fromTo(paper, { scaleY: h0 / h1 }, { scaleY: 1, duration: D, ease: E, overwrite: true, clearProps: "transform" });
      }

      closing.forEach((o) => {
        if (!o.inner.style.clipPath) gsap.set(o.inner, { clipPath: "inset(0% 0% 0% 0%)" });
        gsap.to(o.inner, { clipPath: "inset(0% 0% 100% 0%)", duration: D, ease: E });
        gsap.to(o.inner, { opacity: 0, duration: D * 0.6, ease: "power1.in", onComplete: () => { if (!isOpen(o)) hide(o); } });
      });
      if (opening) {
        const inner = opening.inner;
        if (!inner.style.clipPath) gsap.set(inner, { clipPath: "inset(0% 0% 100% 0%)", opacity: 0 });
        gsap.to(inner, { clipPath: "inset(0% 0% 0% 0%)", duration: D, ease: E, clearProps: "clipPath" });
        gsap.to(inner, { opacity: 1, duration: D * 0.7, ease: "power1.out", delay: D * 0.12, clearProps: "opacity" });
      }
    }

    // back/forward: remember which items were open in this history entry, so
    // returning from contact.html lands on the same (open) item
    function persist() {
      if (!opts.key) return;
      try {
        const st = Object.assign({}, history.state || {});
        st[opts.key] = items.filter(isOpen).map((o) => o.el.id || o.btn.id);
        history.replaceState(st, "");
      } catch (_) { /* sandboxed history */ }
    }
    function restore() {
      if (!opts.key) return;
      let ids = null;
      try {
        const nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
        if (nav && nav.type === "back_forward" && history.state) ids = history.state[opts.key];
      } catch (_) { /* ignore */ }
      if (!Array.isArray(ids)) return;
      items.forEach((o) => { if (ids.includes(o.el.id || o.btn.id)) toggle(o, true, true); });
    }

    items.forEach((it) => {
      it.btn.addEventListener("click", () => { toggle(it); persist(); });
      // find-in-page reveals a collapsed panel: keep the button state in sync
      it.panel.addEventListener("beforematch", () => {
        if (opts.single) items.forEach((o) => { if (o !== it && isOpen(o)) toggle(o, false, true); });
        setState(it, true);
        show(it);
        persist();
      });
      if (opts.clickable) {
        const extra = $(opts.clickable, it.el);
        if (extra) extra.addEventListener("click", () => it.btn.click());
      }
    });
    restore();
    return { items, toggle, isOpen, persist };
  }

  const sheet = $("[data-menu-sheet]");
  const menu = sheet && Disclosures(sheet, {
    item: "[data-menu-item]", button: ".menu-item__toggle", paper: $(".menu-sheet__paper", sheet),
    clickable: ".menu-item__desc", key: "svcMenuOpen",
  });
  const faqList = $("[data-faq]");
  const faq = faqList && Disclosures(faqList, { item: ".faq-item", button: ".faq-item__q button", single: true, key: "svcFaqOpen" });

  // deep links: services.html#whole-venue opens that item (other pages link to them)
  function openFromHash(instant) {
    const id = decodeURIComponent(location.hash.slice(1));
    if (!id || !menu) return;
    const target = d.getElementById(id);
    const it = target && menu.items.find((m) => m.el === target || m.el.contains(target));
    if (it) { menu.toggle(it, true, instant); menu.persist(); }
  }
  openFromHash(true);
  w.addEventListener("hashchange", () => openFromHash(false));

  /* ================================================================ motion */
  const M = w.Motion;
  if (!M || !M.page) return;

  M.page("services", (env) => {
    const gsap = w.gsap, ST = w.ScrollTrigger;
    const offs = [];

    // ---- course index scroll-spy (wide screens show it; cheap everywhere)
    const links = new Map($$("[data-course-link]").map((a) => [a.dataset.courseLink, a]));
    $$("[data-course]").forEach((c) => {
      ST.create({
        trigger: c, start: "top 45%", end: "bottom 45%",
        onToggle: (self) => {
          const a = links.get(c.id);
          if (!a) return;
          if (self.isActive) { links.forEach((l) => l.removeAttribute("aria-current")); a.setAttribute("aria-current", "true"); }
          else if (a.getAttribute("aria-current")) a.removeAttribute("aria-current");
        },
      });
    });
    offs.push(() => links.forEach((l) => l.removeAttribute("aria-current")));

    // reduced motion: no reveals, no scrubs; the process falls back to stacked stills (CSS)
    if (!env.motion) return () => offs.forEach((f) => f());

    const DRIFT = M.DRIFT || "power3.out";
    const mm = gsap.matchMedia();
    offs.push(() => mm.revert());

    // ---- hero copy: a timed intro after the headline's line reveal (above the fold on
    // every viewport, so it must not wait for a scroll trigger); opacity + y only
    const heroIn = $$("[data-hero-in]");
    if (heroIn.length) {
      gsap.fromTo(heroIn, { opacity: 0, y: 24 }, {
        opacity: 1, y: 0, duration: 1, ease: DRIFT, stagger: 0.08,
        delay: (M.introDelay || 0) + 0.3, clearProps: "transform",
      });
      offs.push(() => gsap.set(heroIn, { clearProps: "opacity,transform" }));
    }

    // ---- the sheet: masthead wipe, then courses and items rise as they arrive
    if (sheet) {
      const logo = $(".menu-sheet__title .logo", sheet);
      if (logo) {
        gsap.fromTo(logo, { clipPath: "inset(0% 100% 0% 0%)" }, {
          clipPath: "inset(0% 0% 0% 0%)", duration: 1.2, ease: "ts.cut",
          scrollTrigger: { trigger: logo, start: "top 88%", once: true },
          onComplete: () => gsap.set(logo, { clearProps: "clipPath" }),
        });
      }
      const rise = $$(".menu-sheet__sub, .menu-sheet__rule, .menu-sheet__course-head, .menu-item, .menu-sheet__foot", sheet);
      gsap.set(rise, { opacity: 0, y: 22 });
      ST.batch(rise, {
        start: "top 92%", once: true,
        onEnter: (batch) => gsap.to(batch, { opacity: 1, y: 0, duration: 1, ease: DRIFT, stagger: 0.07, overwrite: "auto", clearProps: "opacity,transform" }),
      });
      offs.push(() => gsap.set(rise, { clearProps: "opacity,transform" }));

      // desktop flourish: the sheet lies slightly askew and straightens as it scrolls into view
      mm.add("(min-width: 901px)", () => {
        gsap.fromTo(sheet, { rotation: -1.6, y: 56 }, {
          rotation: 0, y: 0, ease: "none",
          scrollTrigger: {
            trigger: sheet, start: "top bottom", end: "top 30%", scrub: true,
            // its own layer only while it turns (a tall sheet repainted per frame is costly)
            onToggle: (self) => { sheet.style.willChange = self.isActive ? "transform" : ""; },
          },
        });
        return () => { sheet.style.willChange = ""; };
      });
    }

    // ---- hero: the small plate drifts against the long table (desktop)
    const side = $(".svc-hero__side");
    if (side) {
      mm.add("(min-width: 1181px)", () => {
        gsap.fromTo(side, { yPercent: 6 }, {
          yPercent: -10, ease: "none",
          scrollTrigger: { trigger: ".svc-hero", start: "top top", end: "bottom top", scrub: true },
        });
      });
    }

    // ---- FAQ items rise in (opacity only: the buttons stay focusable)
    const qs = $$(".faq-item");
    if (qs.length) {
      gsap.set(qs, { opacity: 0, y: 16 });
      ST.batch(qs, {
        start: "top 92%", once: true,
        onEnter: (batch) => gsap.to(batch, { opacity: 1, y: 0, duration: 0.9, ease: DRIFT, stagger: 0.06, overwrite: "auto", clearProps: "opacity,transform" }),
      });
      offs.push(() => gsap.set(qs, { clearProps: "opacity,transform" }));
    }

    // ---- process: sticky media, one layer per step, only the active loop plays
    mm.add("(min-width: 901px)", () => processStage());

    return () => offs.forEach((f) => f());
  });

  function processStage() {
    const gsap = w.gsap, ST = w.ScrollTrigger;
    const stage = $("[data-process]");
    if (!stage) return;
    const layers = $$(".svc-process__layer", stage);
    const steps = $$(".svc-step", stage);
    const list = $(".svc-process__steps", stage);
    const vids = layers.map((l) => $("video", l));
    const nEl = $("[data-process-n]", stage), nameEl = $("[data-process-name]", stage);
    const fill = $(".svc-process__progress span", stage);
    const pause = $("[data-process-pause]", stage);
    const names = steps.map((s) => $(".svc-step__name", s).textContent.trim());
    let active = 0, inView = false, userPaused = false;

    const srcFor = (v) => (w.TS && w.TS.pickVideoSrc ? w.TS.pickVideoSrc(v)
      : v.dataset.src + (v.canPlayType('video/webm; codecs="vp9"') ? ".webm" : ".mp4"));
    const load = (i) => {
      const v = vids[i];
      if (!v || v.dataset.loaded) return;
      v.dataset.loaded = "1"; v.muted = true; v.src = srcFor(v);
    };
    const sync = () => {
      vids.forEach((v, i) => {
        if (!v) return;
        if (i === active && inView && !userPaused && !d.hidden) { load(i); const p = v.play(); if (p && p.catch) p.catch(() => {}); }
        else if (!v.paused) v.pause();
      });
    };
    const paint = (i) => {
      steps.forEach((s, k) => s.classList.toggle("is-active", k === i));
      nEl.textContent = steps[i].dataset.n; nameEl.textContent = names[i];
    };

    layers.forEach((l, k) => { l.classList.remove("is-active"); l.style.visibility = k === 0 ? "visible" : "hidden"; l.style.zIndex = k === 0 ? 2 : 0; });
    paint(0);

    function setActive(i, dir) {
      if (i === active) return;
      const prev = active;
      active = i;
      paint(i);
      // a fast scroll can switch again mid-wipe: finish the outgoing wipe at once,
      // so the layer underneath the new one is always whole (no ground showing through)
      gsap.killTweensOf(layers[prev]);
      gsap.set(layers[prev], { clearProps: "clipPath" });
      layers.forEach((l, k) => { l.style.zIndex = k === i ? 2 : k === prev ? 1 : 0; l.style.visibility = k === i || k === prev ? "visible" : "hidden"; });
      const L = layers[i], media = L.firstElementChild;
      gsap.fromTo(L, { clipPath: dir < 0 ? "inset(0% 0% 100% 0%)" : "inset(100% 0% 0% 0%)" }, {
        clipPath: "inset(0% 0% 0% 0%)", duration: 0.95, ease: "ts.cut", overwrite: true,
        onComplete: () => { layers.forEach((l, k) => { if (k !== active) l.style.visibility = "hidden"; }); gsap.set(L, { clearProps: "clipPath" }); },
      });
      gsap.fromTo(media, { scale: 1.1 }, { scale: 1, duration: 1.3, ease: ease(), overwrite: true, clearProps: "transform" });
      load(i); load(i + 1);
      sync();
    }

    steps.forEach((s, i) => ST.create({
      trigger: s, start: "top 55%", end: "bottom 55%",
      onToggle: (self) => { if (self.isActive) setActive(i, self.direction); },
    }));
    gsap.fromTo(fill, { scaleX: 0 }, { scaleX: 1, ease: "none", scrollTrigger: { trigger: list, start: "top 55%", end: "bottom 55%", scrub: true } });
    ST.create({
      trigger: stage, start: "top bottom", end: "bottom top",
      onToggle: (self) => { inView = self.isActive; if (inView) { load(active); load(active + 1); } sync(); },
    });
    // warm the first two loops a screen early
    ST.create({ trigger: stage, start: "top 200%", once: true, onEnter: () => { load(0); load(1); } });

    const onVis = () => sync();
    d.addEventListener("visibilitychange", onVis);
    const onPause = () => {
      userPaused = !userPaused;
      pause.setAttribute("aria-pressed", String(userPaused));
      $(".sr-only", pause).textContent = userPaused ? "Play video" : "Pause video";
      sync();
    };
    pause && pause.addEventListener("click", onPause);

    return () => {
      d.removeEventListener("visibilitychange", onVis);
      pause && pause.removeEventListener("click", onPause);
      vids.forEach((v) => v && v.pause());
      steps.forEach((s, k) => s.classList.toggle("is-active", k === 0));
      layers.forEach((l, k) => { l.style.cssText = l.style.cssText.replace(/(visibility|z-index|clip-path)[^;]*;?/g, ""); l.classList.toggle("is-active", k === 0); });
      active = 0;
    };
  }
})(window, document);
