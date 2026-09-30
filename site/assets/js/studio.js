/*!
 * Two Squares — studio.html
 * 1. The picture frame: the letters rise from the baseline, then the workshop
 *    photograph pans and zooms inside them as you scroll (scrubbed, transform
 *    only) and drifts a touch with the pointer.
 * 2. One contract: two squares slide together until they overlap (scrubbed).
 * 3. Workshop band: a slow horizontal drift on desktop; a swipe strip elsewhere.
 * Reduced motion / no JS: the CSS default is the finished state of each.
 */
(function (w, d) {
  "use strict";
  const M = w.Motion;
  if (!M || !M.page) return;

  M.page("studio", (env) => {
    const gsap = w.gsap;
    if (!env.motion || !gsap) return;
    const offs = [];

    /* ---------------------------------------------------------- 1. picture frame */
    const frame = d.querySelector("[data-frame]");
    if (frame) {
      const fill = frame.querySelector(".frame__fill");
      const zoom = frame.querySelector("[data-frame-zoom]");
      const media = frame.querySelector(".frame__media");
      const cap = d.querySelector("[data-frame-caption]");
      // the letters rise from the baseline while the picture settles inside them
      const intro = gsap.timeline({ delay: (M.introDelay || 0) + 0.05 });
      intro.fromTo(fill, { clipPath: "inset(100% 0% 0% 0%)" },
        { clipPath: "inset(0% 0% 0% 0%)", duration: 1.35, ease: M.DRIFT,
          onComplete: () => gsap.set(fill, { clipPath: "none" }) }, 0);
      if (media) intro.fromTo(media, { scale: 1.3 }, { scale: 1.06, duration: 2.2, ease: M.EASE }, 0);
      if (cap) intro.fromTo(cap, { autoAlpha: 0, y: 12 }, { autoAlpha: 1, y: 0, duration: 0.9, ease: M.EASE, clearProps: "transform" }, 0.7);
      // as the page moves on, the picture drifts deeper into the frame
      gsap.fromTo(zoom, { scale: 1, yPercent: 0 }, {
        scale: 1.24, yPercent: 7, ease: "none",
        scrollTrigger: { trigger: frame, start: "top 25%", end: "bottom top", scrub: true },
      });
      // fine pointers: the picture sits a little behind the letters (±1.8% drift)
      if (env.fine && media) {
        const qx = gsap.quickTo(media, "xPercent", { duration: 1.1, ease: "power3.out" });
        const qy = gsap.quickTo(media, "yPercent", { duration: 1.1, ease: "power3.out" });
        const move = (e) => {
          qx((e.clientX / innerWidth - 0.5) * -3.6);
          qy((e.clientY / innerHeight - 0.5) * -3.6);
        };
        const stage = frame.closest(".studio-hero") || frame;
        stage.addEventListener("pointermove", move, { passive: true });
        offs.push(() => stage.removeEventListener("pointermove", move));
      }
    }

    /* ---------------------------------------------------------- 2. two squares, one contract */
    const duo = d.querySelector("[data-duo] .duo");
    if (duo) {
      const a = duo.querySelector(".duo__sq--a"), b = duo.querySelector(".duo__sq--b");
      const ov = duo.querySelector(".duo__overlap"), lab = duo.querySelector(".duo__label");
      // start: side by side, just touching (each square is 50% wide; the overlap is a third of a square)
      const tl = gsap.timeline({
        defaults: { ease: "none", duration: 1 },
        scrollTrigger: { trigger: duo, start: "top 82%", end: "center 42%", scrub: 0.6 },
      });
      tl.fromTo(a, { xPercent: -16.6667 }, { xPercent: 0 }, 0)
        .fromTo(b, { xPercent: 16.6667 }, { xPercent: 0 }, 0)
        .fromTo(ov, { scaleX: 0 }, { scaleX: 1 }, 0)
        .fromTo(lab, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.25 }, 0.72);
    }

    /* ---------------------------------------------------------- 3. workshop band drift (desktop) */
    const band = d.querySelector("[data-band]");
    const track = band && band.querySelector("[data-band-track]");
    if (band && track) {
      const section = band.closest(".band") || band;
      const mm = gsap.matchMedia();
      mm.add("(min-width: 901px)", () => {
        band.classList.add("is-drift");
        band.removeAttribute("tabindex");              // nothing to scroll with the keyboard while it drifts
        band.scrollLeft = 0;
        let D = 0;
        const measure = () => {
          const o = Math.max(0, track.scrollWidth - band.clientWidth);   // how much of the strip is hidden
          D = Math.min(o, (section.offsetHeight + innerHeight) * 0.5);   // drift at most half the scroll distance
        };
        // it slides in from the right, sits square to the margin as it crosses the middle of
        // the screen (the lead picture whole), then drifts on to the left as it leaves
        gsap.fromTo(track, { x: () => (measure(), D * 0.45) }, {
          x: () => (measure(), -D * 0.55), ease: "none",
          scrollTrigger: { trigger: section, start: "top bottom", end: "bottom top", scrub: 0.8, invalidateOnRefresh: true },
        });
        return () => { band.classList.remove("is-drift"); band.setAttribute("tabindex", "0"); };
      });
      offs.push(() => mm.revert());
    }

    return () => offs.forEach((f) => f());
  });
})(window, document);
