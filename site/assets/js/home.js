/*!
 * Two Squares — home page (index.html). Loads after motion.js, site.js, cafe-seq.js, then corridor.js (index.html) or build.js (index-build.html).
 *
 * Plain behaviour (works with reduced motion and even if GSAP failed to load):
 *   · "Walk in ↓" cue → scrolls to #walk
 *   · Selected work: hover / focus picks the image, dims the other names,
 *     and hands the image a view-transition-name on click (case-study hero morph)
 * Motion (registered with Motion.page, only when motion is allowed):
 *   1 hero intro + scroll drift   4 frame reveal, names rise, touch auto-advance
 *   5 media drift (desktop)       6 process rail draws with scroll
 *   8 CTA: a lit window opens to full-bleed green, then the headline rises
 */
(function (w, d) {
  "use strict";
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));
  const reduced = () => w.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const plainClick = (e) => !(e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey);

  /* ================================================================ walk-in cue */
  (function cue() {
    const a = $("[data-walk-in]");
    if (!a) return;
    a.addEventListener("click", (e) => {
      if (!plainClick(e)) return;
      const walk = d.getElementById("walk");
      if (!walk) return;
      e.preventDefault();
      const M = w.Motion;
      const y = walk.getBoundingClientRect().top + w.scrollY;
      if (M && M.scrollTo) M.scrollTo(y, { duration: 1.5 });
      else w.scrollTo({ top: y, behavior: reduced() ? "auto" : "smooth" });
      // keyboard / screen-reader users continue from the walk
      if (!walk.hasAttribute("tabindex")) walk.setAttribute("tabindex", "-1");
      walk.focus({ preventScroll: true });
    });
  })();

  /* ================================================================ selected work: image index */
  const work = (function initWork() {
    const sec = $("[data-home-work]");
    if (!sec) return null;
    const list = $("[data-work-list]", sec);
    const links = $$(".home-work__link", list);
    const slides = {};
    $$(".home-work__slide", sec).forEach((s) => { slides[s.dataset.slug] = s; });
    const metaEl = $("[data-work-meta]", sec), countEl = $("[data-work-count]", sec);
    const pad = (n) => String(n).padStart(2, "0");
    let active = (links[0] && links[0].dataset.slug) || null;

    const api = {
      sec, list, links, index: 0,
      set(slug, opts = {}) {
        const next = slides[slug];
        const i = links.findIndex((a) => a.dataset.slug === slug);
        if (!next || i < 0) return;
        api.index = i;
        links.forEach((a) => a.classList.toggle("is-current", a === links[i]));
        if (metaEl) metaEl.textContent = links[i].dataset.meta || "";
        if (countEl) countEl.textContent = pad(i + 1) + " / " + pad(links.length);
        if (opts.instant) next.classList.add("is-instant");
        if (slug === active) return;
        Object.values(slides).forEach((s) => s.classList.remove("is-prev"));
        const prev = slides[active];
        if (prev) { prev.classList.remove("is-active"); prev.classList.add("is-prev"); }
        next.classList.add("is-active");
        active = slug;
      },
      dim(on) { list.classList.toggle("is-dim", !!on); },
    };

    links.forEach((a) => {
      const slug = a.dataset.slug;
      a.addEventListener("pointerenter", (e) => { if (e.pointerType !== "mouse") return; api.set(slug); api.dim(true); });
      a.addEventListener("focus", () => { api.set(slug); api.dim(true); });
      a.addEventListener("click", (e) => {
        if (!plainClick(e)) return;
        // the clicked project's image is the one on screen, and it carries the
        // shared name so the case-study hero grows out of it (cross-document VT)
        api.set(slug, { instant: true });
        Object.values(slides).forEach((s) => { s.style.viewTransitionName = ""; });
        const s = slides[slug];
        if (s) { s.style.viewTransitionName = "proj-" + slug; s.style.setProperty("view-transition-class", "proj"); }
      });
    });
    list.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") api.dim(false); });
    list.addEventListener("focusout", (e) => { if (!list.contains(e.relatedTarget)) api.dim(false); });
    // back/forward cache: drop the shared name and any instant state
    w.addEventListener("pageshow", () => {
      Object.values(slides).forEach((s) => {
        s.style.viewTransitionName = ""; s.style.removeProperty("view-transition-class"); s.classList.remove("is-instant");
      });
    });
    // decode the hidden slides ahead of the first hover (no hitch on the first crossfade)
    if ("IntersectionObserver" in w) {
      const io = new IntersectionObserver((es) => {
        if (!es.some((e) => e.isIntersecting)) return;
        io.disconnect();
        // one image per idle slot, so six big decodes never land in the same frame
        const queue = $$(".home-work__slide > img", sec);
        const idle = w.requestIdleCallback || ((f) => setTimeout(f, 120));
        const next = () => {
          const img = queue.shift();
          if (!img) return;
          const dec = () => { (img.decode ? img.decode() : Promise.resolve()).catch(() => {}).then(() => idle(next)); };
          if (img.complete && img.naturalWidth) dec(); else { img.loading = "eager"; img.addEventListener("load", dec, { once: true }); img.addEventListener("error", () => idle(next), { once: true }); }
        };
        idle(next);
      }, { rootMargin: "100% 0px" });
      io.observe(sec);
    }
    return api;
  })();

  /* ================================================================ motion */
  const M = w.Motion;
  if (!M || !M.page) return;

  // masked line reveal for [data-home-split] (same look as motion.js data-split). aria "none" keeps
  // the text itself readable, so it also works on a <p> (which may not carry an aria-label)
  function splitLines(el, trigger, opts = {}) {
    const gsap = w.gsap;
    if (!el) return;
    if (!w.SplitText) {
      gsap.fromTo(el, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 1, ease: M.DRIFT, delay: opts.delay || 0, scrollTrigger: trigger });
      return;
    }
    w.SplitText.create(el, {
      type: "lines", mask: "lines", linesClass: "line", autoSplit: true,
      aria: el.matches("h1,h2,h3,h4,h5,h6") ? "auto" : "none",
      onSplit(self) {
        gsap.set(el, { opacity: 1 });
        self.masks.forEach((m) => m.classList.add("line-mask"));
        return gsap.fromTo(self.lines, { yPercent: 120 }, { yPercent: 0, duration: 1.1, stagger: 0.09, ease: M.DRIFT, delay: opts.delay || 0, scrollTrigger: trigger });
      },
    });
  }

  M.page("home", (env) => {
    if (!env.motion) return;                       // reduced motion: CSS shows every section as plain, readable content
    const gsap = w.gsap, ST = w.ScrollTrigger;
    const EASE = M.EASE, DRIFT = M.DRIFT;
    const offs = [];

    /* ---------------------------------------------------------- 1 · hero */
    const hero = $(".home-hero");
    if (hero) {
      const delay = M.introDelay || 0;
      const video = $(".home-hero__video", hero), media = $(".home-hero__media", hero);
      const content = $(".home-hero__content", hero), rule = $(".home-hero__rule", hero);
      // the room settles as the lights come up; the headline lines rise (data-split, +0.2s),
      // then the statement, the rule, the facts and the controls, in that order
      const intro = gsap.timeline({ delay, defaults: { ease: DRIFT, duration: 1 } });
      intro.fromTo(video, { scale: 1.12 }, { scale: 1, duration: 2.6, ease: EASE }, 0)
        .fromTo($(".home-hero__eyebrow", hero), { autoAlpha: 0, y: 16 }, { autoAlpha: 1, y: 0, clearProps: "transform" }, 0.1)
        .fromTo($(".home-hero__body", hero), { autoAlpha: 0, y: 24 }, { autoAlpha: 1, y: 0, clearProps: "transform" }, 0.72)
        .fromTo(rule, { scaleX: 0 }, { scaleX: 1, duration: 1.4, ease: "ts.cut" }, 0.82)
        .fromTo($$(".home-hero__fact", hero), { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, stagger: 0.08, clearProps: "transform" }, 0.95)
        .fromTo($(".home-hero__controls", hero), { autoAlpha: 0, y: 20 }, { autoAlpha: 1, y: 0, clearProps: "transform" }, 1.2);
      // scroll away: the room pushes in, the words drift up and fade (transform + opacity only)
      gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true, invalidateOnRefresh: true },
      })
        .fromTo(media, { scale: 1 }, { scale: 1.08, duration: 1 }, 0)
        .fromTo(content, { y: 0 }, { y: () => -0.16 * w.innerHeight, duration: 1 }, 0)
        .fromTo(content, { opacity: 1 }, { opacity: 0, duration: 0.62 }, 0);
    }

    /* ---------------------------------------------------------- 4 · selected work */
    if (work) {
      const { sec, list } = work;
      const stack = $(".home-work__stack", sec);
      const small = () => w.innerWidth <= 900;
      // the street ends at night, so the index arrives full bleed under it (dark to dark, no paper
      // gap between them); without the walk, the frame opens out of the paper as before
      const fromStreet = !!d.querySelector("[data-corridor], [data-build]");
      const openClip = () => (fromStreet ? "inset(0% 0% 0% 0%)" : small() ? "inset(5% 4% 0% 4%)" : "inset(9% 6% 0% 6%)");
      // paper → green: the frame opens out to full bleed as it arrives, and closes back as it leaves
      gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: {
          trigger: sec, start: "top bottom", end: "bottom top", scrub: true, invalidateOnRefresh: true,
          onToggle: (self) => { stack.style.willChange = self.isActive ? "transform" : ""; },
        },
      })
        .fromTo(sec, { clipPath: openClip },
          { clipPath: "inset(0% 0% 0% 0%)", duration: 0.5, ease: "power2.out" }, 0)
        .fromTo(stack, { scale: 1.16 }, { scale: 1, duration: 0.5, ease: "power1.out" }, 0)
        .to(sec, { clipPath: () => (small() ? "inset(0% 4% 5% 4%)" : "inset(0% 6% 9% 6%)"), duration: 0.38, ease: "power2.in" }, 0.62)
        .to(stack, { scale: 1.06, duration: 0.38 }, 0.62);

      // the names rise into place, one after another (masked), once
      const items = $$(".home-work__item", list), rises = $$(".home-work__rise", list);
      items.forEach((li) => li.classList.add("is-masked"));
      gsap.fromTo(rises, { yPercent: 118 }, {
        yPercent: 0, duration: 1.15, stagger: 0.075, ease: DRIFT,
        scrollTrigger: { trigger: list, start: "top 80%", once: true },
        onComplete: () => items.forEach((li) => li.classList.remove("is-masked")),
      });
      offs.push(() => { items.forEach((li) => li.classList.remove("is-masked")); stack.style.willChange = ""; });
      gsap.fromTo($$("[data-work-in]", sec), { opacity: 0, y: 16 }, {
        opacity: 1, y: 0, duration: 1, stagger: 0.08, ease: DRIFT, delay: 0.45, clearProps: "transform",
        scrollTrigger: { trigger: list, start: "top 80%", once: true },
      });

      // touch: no hover, so the index turns over by itself while it's on screen
      if (!env.fine) {
        let timer = null;
        const tick = () => {
          const next = work.links[(work.index + 1) % work.links.length];
          work.set(next.dataset.slug);
          timer = gsap.delayedCall(3.5, tick);
        };
        const start = () => { if (timer) return; list.classList.add("is-auto"); timer = gsap.delayedCall(3.5, tick); };
        const stop = () => { if (timer) { timer.kill(); timer = null; } list.classList.remove("is-auto"); };
        ST.create({ trigger: sec, start: "top 70%", end: "bottom 30%", onToggle: (self) => (self.isActive ? start() : stop()) });
        offs.push(stop);
      }
    }

    /* ---------------------------------------------------------- 5 · what we do: media drift against the text (desktop) */
    const mm = gsap.matchMedia();
    offs.push(() => mm.revert());
    mm.add("(min-width: 901px)", () => {
      $$(".home-what [data-drift]").forEach((el) => {
        const a = parseFloat(el.dataset.drift) || 50;
        gsap.fromTo(el, { y: a * 0.3 }, {
          y: -a * 0.7, ease: "none",
          scrollTrigger: { trigger: el.closest(".home-what__row") || el, start: "top bottom", end: "bottom top", scrub: true },
        });
      });
    });

    /* ---------------------------------------------------------- 6 · how it works: the rail draws, each step arrives as it's reached */
    const rail = $("[data-process]");
    if (rail) {
      mm.add({ wide: "(min-width: 901px)", narrow: "(max-width: 900px)" }, (c) => {
        const wide = c.conditions.wide;
        const fill = $(".home-process__fill", rail);
        const steps = $$(".home-process__step", rail);
        const tl = gsap.timeline({
          defaults: { ease: "none" },
          scrollTrigger: wide
            ? { trigger: rail, start: "top 86%", end: "top 50%", scrub: true }
            : { trigger: rail, start: "top 78%", end: "bottom 58%", scrub: true },
        });
        tl.fromTo(fill, wide ? { scaleX: 0 } : { scaleY: 0 }, wide ? { scaleX: 1, duration: 1 } : { scaleY: 1, duration: 1 }, 0);
        steps.forEach((s, i) => {
          const at = i / steps.length;                // where the fill reaches this step's marker
          tl.fromTo($(".home-process__mark > span", s), { scale: 0 }, { scale: 1, duration: 0.05, ease: "power2.out" }, at);
          tl.fromTo([...s.children].filter((el) => !el.classList.contains("home-process__mark")),
            { autoAlpha: 0, y: 18 }, { autoAlpha: 1, y: 0, duration: 0.12, stagger: 0.025, ease: "power2.out" }, at);
        });
        tl.to({}, { duration: 0.05 });                // a little rest after the last step
      });
    }

    /* ---------------------------------------------------------- 7 · quote: the lines rise, then the attribution */
    splitLines($(".home-quote [data-home-split]"), { trigger: ".home-quote", start: "top 82%", once: true });

    /* ---------------------------------------------------------- 8 · CTA: the window opens, then the headline rises */
    const cta = $("[data-home-cta]");
    if (cta) {
      const stage = $(".home-cta__stage", cta), video = $(".home-cta__video", cta);
      const title = $("[data-cta-title]", cta), rule = $("[data-cta-rule]", cta);
      const bits = $$("[data-cta-in]", cta).concat($$(".home-cta__toggle", cta));
      // a lit, door-shaped window centred on the stage
      const windowClip = () => {
        const W = w.innerWidth, H = w.innerHeight;
        const ww = W < H ? W * 0.62 : Math.min(W * 0.28, H * 0.5);
        const wh = W < H ? H * 0.48 : H * 0.62;
        const x = ((W - ww) / 2 / W) * 100, y = ((H - wh) / 2 / H) * 100;
        return `inset(${y.toFixed(2)}% ${x.toFixed(2)}% ${y.toFixed(2)}% ${x.toFixed(2)}%)`;
      };
      gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: { trigger: cta, start: "top 88%", end: "top -38%", scrub: true, invalidateOnRefresh: true },
      })
        .fromTo(stage, { clipPath: windowClip }, { clipPath: "inset(0% 0% 0% 0%)", duration: 1, ease: "power2.inOut" }, 0)
        .fromTo(video, { scale: 1.32 }, { scale: 1, duration: 1, ease: "power1.out" }, 0);

      const reveal = { trigger: cta, start: "top -24%", once: true };
      splitLines(title, reveal, { delay: 0.1 });
      const [eyebrow, ...rest] = bits;
      gsap.fromTo(eyebrow, { autoAlpha: 0, y: 18 }, { autoAlpha: 1, y: 0, duration: 0.9, ease: DRIFT, clearProps: "transform", scrollTrigger: reveal });
      gsap.fromTo(rest, { autoAlpha: 0, y: 22 }, { autoAlpha: 1, y: 0, duration: 1, stagger: 0.08, ease: DRIFT, delay: 0.5, clearProps: "transform", scrollTrigger: reveal });
      gsap.fromTo(rule, { scaleX: 0 }, { scaleX: 1, duration: 1.3, ease: "ts.cut", delay: 0.35, scrollTrigger: reveal });
    }

    return () => offs.forEach((f) => f());
  });
})(window, document);
