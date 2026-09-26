/*!
 * Two Squares: case-study pages (work/<slug>.html).
 * Registers with the motion core; every tween and ScrollTrigger lives inside
 * the Motion.page context (or a nested matchMedia that the cleanup reverts).
 *   hero      image settles in (unless it just morphed in via the view transition),
 *             then scales gently as the page scrolls away from it
 *   stages    the ticks draw in, one after another
 *   gallery   full-bleed photographs drift inside their clipped frames (desktop)
 *   details   the sticky photo column swaps as each callout passes the middle (desktop)
 * Reduced motion / no GSAP: nothing here runs; the CSS lays everything out as stills.
 */
(function (w, d) {
  "use strict";
  const M = w.Motion;
  if (!M || !M.page) return;
  const $ = (s, r = d) => r.querySelector(s);
  const $$ = (s, r = d) => Array.from(r.querySelectorAll(s));

  // Runs before the motion core boots (DOMContentLoaded). Where the sticky details column is used, the inline
  // copies of the detail photos are display:none and never seen, so they don't get a reveal there.
  const MOTION_OK = w.matchMedia("(prefers-reduced-motion: no-preference)").matches;
  if (MOTION_OK && w.matchMedia("(min-width: 901px) and (orientation: landscape)").matches) {
    $$(".case-details__inline[data-reveal]").forEach((f) => f.removeAttribute("data-reveal"));
  }
  // Workaround for the core image reveal (SP/build/requests/case.md #1). motion.js builds
  // [data-reveal="image"] as a gsap.timeline with a scrollTrigger; a timeline's trigger is refreshed lazily,
  // so its end is still undefined when the next reveal is created. When the page boots scrolled down
  // (history back / forward restores the position) the next trigger's init refreshes those lazy ones, they are
  // already past and `once` kills them mid-loop, ScrollTrigger throws ("reading 'end'") and the rest of boot
  // never runs: every reveal below stays hidden. Until the core uses tweens, this page runs the same reveal
  // (same values) with plain tweens. Remove this block and the one in Motion.page once motion.js is patched.
  const takeover = MOTION_OK ? $$('[data-reveal="image"]') : [];
  takeover.forEach((f) => { f.removeAttribute("data-reveal"); f.setAttribute("data-case-reveal", "image"); });

  M.page("case", (env) => {
    if (!env.motion) return;
    const gsap = w.gsap, ST = w.ScrollTrigger;
    const CUT = "ts.cut", EASE = M.EASE;
    const offs = [];

    /* ---- hero ------------------------------------------------------------ */
    const hero = $(".case-hero");
    const fig = hero && $(".case-hero__media", hero);
    const img = fig && fig.querySelector("img");
    if (img && !w.__vt) {
      // arriving directly (no shared-element morph): a slow settle, timed with the title
      gsap.fromTo(img, { scale: 1.07 }, { scale: 1, duration: 2, ease: EASE, delay: M.introDelay, clearProps: "transform" });
    }
    // scrubbed layers get their own compositor layer only while they are on screen (no repaint per frame)
    const layer = (el) => (self) => { el.style.willChange = self.isActive ? "transform" : ""; };
    if (fig) {
      gsap.to(fig, {
        scale: 1.06, yPercent: 5, ease: "none",
        scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true, onToggle: layer(fig) },
      });
    }
    // meta line + placeholder tag follow the title's line reveal (they sit below the 88% reveal line, so no ScrollTrigger)
    const heroIntro = hero ? $$(".case-hero__meta, .case-hero__badge", hero) : [];
    if (heroIntro.length) {
      gsap.fromTo(heroIntro, { autoAlpha: 0, y: 16 }, {
        autoAlpha: 1, y: 0, duration: 1, ease: M.DRIFT, stagger: 0.08, delay: M.introDelay + 0.45, clearProps: "transform",
      });
    }

    /* ---- image reveals (the core's curtain + settle, as tweens: see the workaround note above) ---- */
    $$('[data-case-reveal="image"]').forEach((el) => {
      const r = el.getBoundingClientRect();
      const delay = r.top < innerHeight && r.bottom > 0 ? M.introDelay : 0;
      const im = el.querySelector(":scope > img, :scope > picture > img, :scope > video");
      const st = () => ({ trigger: el, start: "top 88%", once: true });
      gsap.fromTo(el, { clipPath: "inset(8% 8% 8% 8%)" }, {
        clipPath: "inset(0% 0% 0% 0%)", duration: 1.2, ease: M.DRIFT, delay, scrollTrigger: st(),
        onComplete: () => gsap.set(el, { clipPath: "none" }),
      });
      if (im) gsap.fromTo(im, { scale: 1.12 }, { scale: 1, duration: 1.4, ease: EASE, delay, clearProps: "transform", scrollTrigger: st() });
    });

    /* ---- paragraph line reveals ------------------------------------------ */
    // Like the core [data-split], but aria "none": a line split keeps the words as real text,
    // so no aria-label is needed (aria-label on a <p> is prohibited ARIA).
    const splits = $$("[data-case-split]");
    if (w.SplitText) {
      splits.forEach((el) => {
        const r = el.getBoundingClientRect();
        const delay = r.top < innerHeight && r.bottom > 0 ? M.introDelay : 0;
        const s = w.SplitText.create(el, {
          type: "lines", mask: "lines", linesClass: "line", autoSplit: true, aria: "none",
          onSplit(self) {
            gsap.set(el, { visibility: "visible" });
            self.masks.forEach((m) => m.classList.add("line-mask"));
            return gsap.from(self.lines, {
              yPercent: 120, duration: 1.1, stagger: 0.09, ease: M.DRIFT, delay,
              scrollTrigger: { trigger: el, start: "top 90%", once: true },
            });
          },
        });
        offs.push(() => s.revert());
      });
    } else {
      gsap.set(splits, { visibility: "visible" });
    }

    /* ---- what we did: ticks draw in after their rows arrive ---------------- */
    const ticks = $$(".case-stages__item.is-done .case-stages__tick");
    if (ticks.length) {
      gsap.fromTo(ticks, { clipPath: "inset(0% 100% 0% 0%)" }, {
        clipPath: "inset(0% 0% 0% 0%)", duration: 0.7, ease: CUT, stagger: 0.07, delay: 0.35,
        scrollTrigger: { trigger: ".case-stages", start: "top 85%", once: true },
        onComplete: () => gsap.set(ticks, { clearProps: "clipPath" }),
      });
    }

    /* ---- desktop only: parallax + the sticky details swap ------------------ */
    const mm = gsap.matchMedia();
    mm.add("(min-width: 901px)", () => {
      $$("[data-case-parallax]").forEach((el) => {
        const s = parseFloat(el.dataset.caseParallax) || 0.06;
        gsap.fromTo(el, { yPercent: -s * 100 }, {
          yPercent: s * 100, ease: "none",
          scrollTrigger: { trigger: el.parentElement, start: "top bottom", end: "bottom top", scrub: true, onToggle: layer(el) },
        });
      });
      return () => $$("[data-case-parallax]").forEach((el) => { el.style.willChange = ""; });
    });
    // the sticky details column: landscape desktops only (matches case.css)
    mm.add("(min-width: 901px) and (orientation: landscape)", () => {
      const sec = $(".case-details");
      if (!sec) return;
      const figs = $$(".case-details__fig", sec);
      const items = $$(".case-details__item", sec);
      const now = $(".case-details__now", sec);
      if (!figs.length || figs.length !== items.length) return;
      let cur = 0;
      gsap.set(figs, { zIndex: (i) => (i === 0 ? 2 : 0) });
      const show = (i, dir) => {
        if (i === cur) return;
        const prev = figs[cur], next = figs[i];
        cur = i;
        figs.forEach((f) => { if (f !== prev && f !== next) gsap.set(f, { zIndex: 0 }); });
        gsap.set(prev, { zIndex: 1 });
        gsap.set(next, { zIndex: 2 });
        gsap.fromTo(next, { clipPath: dir < 0 ? "inset(0% 0% 100% 0%)" : "inset(100% 0% 0% 0%)" },
          { clipPath: "inset(0% 0% 0% 0%)", duration: 0.9, ease: CUT, overwrite: true });
        const im = next.querySelector("img");
        if (im) gsap.fromTo(im, { scale: 1.12 }, { scale: 1, duration: 1.3, ease: EASE, overwrite: true });
        figs.forEach((f, k) => f.classList.toggle("is-active", k === i));
        items.forEach((it, k) => it.classList.toggle("is-active", k === i));
        if (now) now.textContent = String(i + 1).padStart(2, "0");
      };
      items.forEach((it, i) => {
        ST.create({
          trigger: it, start: "top 55%", end: "bottom 55%",
          onToggle: (self) => { if (self.isActive) show(i, self.direction); },
        });
      });
      return () => {
        figs.forEach((f, k) => f.classList.toggle("is-active", k === 0));
        items.forEach((it, k) => it.classList.toggle("is-active", k === 0));
        if (now) now.textContent = "01";
      };
    });

    offs.push(() => mm.revert());
    return () => offs.forEach((f) => f());
  });
})(window, document);
