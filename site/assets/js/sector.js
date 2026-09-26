/*!
 * Two Squares — sector pages (cafes / restaurants / bars / retail .html).
 * Most of the page runs on the shared effects (data-split, data-reveal, the liquid float) and on
 * build.js (the venue build) + site.js (the video manager, the film toggles). This adds:
 *   · the hero film settling in, and sinking behind its panel as you scroll on (scrubbed);
 *   · the big clock in the closing panel drifting against the scroll;
 *   · FAQ: one question open at a time is NOT enforced (owners compare answers); opening one
 *     refreshes ScrollTrigger so the triggers below it stay true.
 * Motion only for the tweens; nothing here is needed for the page to work.
 */
(function (w, d) {
  "use strict";
  const M = w.Motion;
  const $ = (s, r = d) => r.querySelector(s);

  // FAQ: keep ScrollTrigger's measurements true after an answer opens or closes (motion or not)
  d.addEventListener("toggle", (e) => {
    if (e.target && e.target.classList && e.target.classList.contains("sector-faq__item") && w.ScrollTrigger) {
      requestAnimationFrame(() => w.ScrollTrigger.refresh());
    }
  }, true);

  if (!M || !M.page) return;
  // reduced motion (or the engine failing) never hides the hero: its pre-state is .js-motion only
  M.page("sector", (env) => {
    if (!env.motion) return;
    const gsap = w.gsap;
    const hero = $(".sector-hero");
    const film = hero && $(".sector-hero__media > video", hero);
    const inner = hero && $(".sector-hero__inner", hero);
    const small = w.matchMedia("(max-width: 900px)").matches;
    const offs = [];

    // hero intro: label → (headline lines, data-split) → intro → actions → film control
    const ins = hero ? [...hero.querySelectorAll("[data-hero-in]")] : [];
    ins.forEach((el) => {
      gsap.fromTo(el, { opacity: 0, y: 22 }, {
        opacity: 1, y: 0, duration: 1.1, ease: M.DRIFT, clearProps: "transform",
        delay: (M.introDelay || 0) + (parseFloat(el.dataset.heroIn) || 0),
      });
    });
    if (film) {
      // the film settles as the page arrives (after the page transition has uncovered it)
      gsap.fromTo(film, { scale: 1.1 }, { scale: 1.04, duration: 2.2, ease: M.EASE, delay: M.introDelay || 0 });
      // …and sinks behind the panel as it scrolls away (scale stays > 1, so no edge shows)
      gsap.fromTo(film, { yPercent: 0 }, {
        yPercent: small ? 6 : 9, ease: "none",
        scrollTrigger: { trigger: hero, start: "top top", end: "bottom top", scrub: true },
      });
    }
    if (inner && !small) {
      gsap.to(inner, {
        yPercent: -10, opacity: 0.35, ease: "none",
        scrollTrigger: { trigger: hero, start: "35% top", end: "bottom top", scrub: true },
      });
    }

    // the quote: masked line reveal. Motion's data-split labels the element (aria-label), which a
    // blockquote may not carry; lines-only splitting keeps every word whole, so no label is needed.
    const quote = $("[data-sector-split]");
    if (quote) {
      try {
        const split = w.SplitText.create(quote, {
          type: "lines", mask: "lines", linesClass: "line", aria: "none", autoSplit: true,
          onSplit(self) {
            quote.classList.add("is-split");
            self.masks.forEach((m) => m.classList.add("line-mask"));
            return gsap.from(self.lines, {
              yPercent: 120, duration: 1.1, stagger: 0.09, ease: M.DRIFT,
              scrollTrigger: { trigger: quote, start: "top 88%", once: true },
            });
          },
        });
        offs.push(() => { split.revert(); quote.classList.remove("is-split"); });
      } catch (err) { quote.classList.add("is-split"); }
    }

    const clock = $(".sector-cta__clock");
    if (clock) {
      gsap.fromTo(clock, { yPercent: 10 }, {
        yPercent: -10, ease: "none",
        scrollTrigger: { trigger: clock.parentElement, start: "top bottom", end: "bottom top", scrub: true },
      });
    }
    return () => offs.forEach((f) => f());
  });
})(window, document);
